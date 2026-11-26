import os
import numpy as np
from typing import TYPE_CHECKING, Dict, Any, Union

import vihallu_features as vf

from backend.app.core.config import settings
from backend.app.core.logging import logger

if TYPE_CHECKING:
    import torch
    import lightgbm as lgb
    from transformers import (
        PreTrainedTokenizer, 
        PreTrainedModel,
        Pipeline as HFPipeline
    )

LGBM_DIR = settings.LGBM_MODEL_DIR or os.path.join(settings.MODELS_DIR, "lgbm")
# Written by machine-learning/pipelines/train.py next to the fold models
EMBED_CENTROID_PATH = os.path.join(LGBM_DIR, "embedding_centroid.npy")
FEATURE_SCHEMA_PATH = os.path.join(settings.MODELS_DIR, "feature_schema.json")
NLI_MODEL_NAME = settings.NLI_MODEL_NAME
NER_MODEL_NAME = settings.NER_MODEL_NAME
VISTRAL_MODEL_NAME = settings.LLM_FEATURE_MODEL


class HallucinationPipeline:
    API_LABEL_MAP = {
        "No Hallucination": "no",
        "Intrinsic Hallucination": "intrinsic",
        "Extrinsic Hallucination": "extrinsic",
    }

    def __init__(self):
        self.disabled = settings.DISABLE_MODEL
        self._is_loaded = False
        
        self.labels = {
            0: "Extrinsic Hallucination",
            1: "No Hallucination",
            2: "Intrinsic Hallucination"
        }

        self.embed_tokenizer = None
        self.embed_model = None
        self.nli_tokenizer = None
        self.nli_model = None
        self.ner_pipeline = None
        self.vistral_tokenizer = None
        self.vistral_model = None
        self.lgbm_models = []
        self.embed_centroid = None
        self.feature_dim = None
        self.device_cpu = None
        self.torch_module = None

    def _load_models(self):
        if self._is_loaded or self.disabled:
            return

        logger.info("Initializing HallucinationPipeline Resources (Lazy Loading)...")
        
        import torch
        import torch.nn.functional as F
        import lightgbm as lgb
        from transformers import (
            AutoTokenizer, 
            AutoModel, 
            AutoModelForCausalLM, 
            AutoModelForSequenceClassification, 
            pipeline
        )
        from huggingface_hub import login

        self.torch_module = torch 
        self.device_cpu = torch.device("cpu")

        if settings.HF_TOKEN:
            login(token=settings.HF_TOKEN)

        try:
            logger.info(f"- Loading PhoBERT (CPU)...")
            self.embed_tokenizer = AutoTokenizer.from_pretrained(settings.PHOBERT_TOKENIZER)
            self.embed_model = AutoModel.from_pretrained(settings.PHOBERT_MODEL).to(self.device_cpu).eval()

            logger.info(f"- Loading NLI (CPU)...")
            self.nli_tokenizer = AutoTokenizer.from_pretrained(NLI_MODEL_NAME)
            self.nli_model = AutoModelForSequenceClassification.from_pretrained(NLI_MODEL_NAME).to(self.device_cpu).eval()

            logger.info(f"- Loading NER (CPU)...")
            try:
                self.ner_pipeline = pipeline("ner", model=NER_MODEL_NAME, tokenizer=NER_MODEL_NAME, 
                                             device=-1, aggregation_strategy="simple")
            except Exception:
                fallback = settings.NER_FALLBACK_MODEL
                self.ner_pipeline = pipeline("ner", model=fallback, tokenizer=fallback, 
                                             device=-1, aggregation_strategy="simple")

            logger.info(f"- Loading Qwen 1.5B (CPU Optimized)...")
            
            self.vistral_tokenizer = AutoTokenizer.from_pretrained(VISTRAL_MODEL_NAME)
            self.vistral_model = AutoModelForCausalLM.from_pretrained(
                VISTRAL_MODEL_NAME,
                torch_dtype=torch.float32,
                device_map="cpu",
                low_cpu_mem_usage=True
            )

            logger.info(f"- Loading LightGBM fold ensemble...")
            self._load_lgbm_ensemble()

            self._is_loaded = True
            logger.info("System Ready!")

        except Exception as e:
            logger.error(f"Critical error loading models: {e}")
            raise e

    def _load_lgbm_ensemble(self):
        import glob
        import json
        import lightgbm as lgb

        fold_files = sorted(glob.glob(os.path.join(LGBM_DIR, "fold_*.txt")))
        if not fold_files:
            raise RuntimeError(f"No LightGBM fold models found in {LGBM_DIR}")
        self.lgbm_models = [lgb.Booster(model_file=f) for f in fold_files]
        self.embed_centroid = np.load(EMBED_CENTROID_PATH).reshape(1, -1)
        with open(FEATURE_SCHEMA_PATH) as f:
            self.feature_dim = json.load(f)["feature_dim"]

    def _build_model_features(self, f_embed, context, prompt, response, vistral_no_ext_int):
        """Same builder as training (vihallu_features); vistral_no_ext_int follows vf.LLM_PROB_COLUMNS."""
        x = vf.build_feature_matrix(f_embed, [context], [prompt], [response], vistral_no_ext_int, self.embed_centroid)
        # The artifact on disk must have been trained on this layout
        if x.shape[1] != self.feature_dim:
            raise ValueError(f"Feature dim mismatch: got {x.shape[1]}, expected {self.feature_dim}")
        return x

    def _predict_ensemble(self, x):
        # Mean of fold probabilities, same as LGBMEnsemble in the training script
        return np.mean([m.predict(x) for m in self.lgbm_models], axis=0)

    def _extract_embeddings(self, text_list):
        import torch 
        
        inputs = self.embed_tokenizer(text_list, padding=True, truncation=True, max_length=vf.MAX_LENGTH, return_tensors="pt").to(self.device_cpu)
        with torch.no_grad():
            outputs = self.embed_model(**inputs)
            embeddings = vf.masked_mean(outputs.last_hidden_state, inputs["attention_mask"]).cpu().numpy()
        return embeddings

    def _get_entity_set(self, text):
        if not text: return set()
        try:
            entities = self.ner_pipeline(text)
            return {e['word'].replace(" ", "").lower() for e in entities}
        except: return set()

    def _get_ner_features(self, context, response):
        c_ents = self._get_entity_set(context)
        r_ents = self._get_entity_set(response)
        new_entity_count = len(r_ents - c_ents)
        union = len(c_ents.union(r_ents))
        overlap_ratio = len(c_ents.intersection(r_ents)) / union if union > 0 else 0.0
        return np.array([[new_entity_count, overlap_ratio]])

    def _get_nli_features(self, context, response):
        import torch

        premise = context if context else "no context"
        hypothesis = response if response else "no response"

        inputs = self.nli_tokenizer(
            premise,
            hypothesis,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt"
        ).to(self.device_cpu)

        with torch.no_grad():
            outputs = self.nli_model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1).cpu().numpy()[0]

        id2label = self.nli_model.config.id2label

        p_entail = probs[[i for i, v in id2label.items() if "entail" in v.lower()][0]]
        p_neutral = probs[[i for i, v in id2label.items() if "neutral" in v.lower()][0]]
        p_contra = probs[[i for i, v in id2label.items() if "contradict" in v.lower()][0]]

        return p_entail, p_neutral, p_contra

    def _get_vistral_probs(self, context, prompt, response):
        import torch
        import torch.nn.functional as F

        sys_msg = """Bạn là chuyên gia thẩm định độ trung thực của AI (Hallucination Judge).
        Nhiệm vụ: Dựa vào 'Context', hãy phân loại 'Response' vào đúng 1 trong 3 nhãn: 0, 1, hoặc 2.
        
        === ĐỊNH NGHĨA NHÃN (HÃY TUÂN THỦ NGHIÊM NGẶT) ===
        
        1. NO Hallucination (Nhãn 1):
           Phản hồi là "no" KHI VÀ CHỈ KHI đáp ứng đủ cả 3 điều kiện:
           - Nó hoàn toàn nhất quán và đúng sự thật với thông tin được cung cấp trong context.
           - Nó không chứa bất kỳ thông tin nào sai lệch hoặc không thể suy luận trực tiếp từ context.
           - Nó trả lời đúng dựa trên context.
           
        2. EXTRINSIC Hallucination (Nhãn 0) - Lỗi Ngoại Lai:
           Phản hồi là "EXTRINSIC" khi đáp ứng tối thiểu 1 trong các điều kiện:
           - Nó bổ sung thông tin KHÔNG CÓ trong context.
           - Thông tin bổ sung không thể suy luận được từ context.
           - Thông tin bổ sung có thể đúng trong thế giới thực nhưng nó không được cung cấp trong context.
           - Phản hồi vẫn cố gắng trả lời prompt nhưng lại đưa thêm chi tiết không có nguồn gốc từ context.
           
        3. INTRINSIC Hallucination (Nhãn 2) - Lỗi Nội Tại:
           Phản hồi là "INTRINSIC" khi đáp ứng tối thiểu 1 trong các điều kiện:
           - Nó mâu thuẫn trực tiếp hoặc bóp méo thông tin đã được cung cấp rõ ràng trong context.
           - Nội dung của ảo giác vẫn dựa trên các thực thể hoặc khái niệm có trong context nhưng thông tin về chúng bị thay đổi, sai lệch.
           - LLM tạo ra một câu trả lời sai lệch nhưng nghe có vẻ khá hợp lý (plausible) trong ngữ cảnh đó.
        """

        user_msg = f"""Dựa vào các định nghĩa trên, hãy phân loại trường hợp sau:

        Context: {context}
        Prompt: {prompt}
        Response: {response}

        Chỉ trả lời duy nhất một con số đại diện cho nhãn (0, 1 hoặc 2):"""

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}
        ]
        
        input_text = self.vistral_tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.vistral_tokenizer(input_text, return_tensors="pt").to(self.vistral_model.device)

        with torch.no_grad():
            outputs = self.vistral_model(**inputs)
            next_token_logits = outputs.logits[0, -1, :]
            
            def get_id(token_str):
                ids = self.vistral_tokenizer.encode(token_str, add_special_tokens=False)
                return ids[-1] if ids else -1

            id_0 = get_id("0")
            id_1 = get_id("1")
            id_2 = get_id("2")

            score_0 = next_token_logits[id_0].item()
            score_1 = next_token_logits[id_1].item()
            score_2 = next_token_logits[id_2].item()
            
            probs = F.softmax(torch.tensor([score_0, score_1, score_2]), dim=0).numpy()
            
            return np.array([[probs[0], probs[2], probs[1]]])
        
    def _normalize_label(self, label: str) -> str:
        label = label.lower()
        if "intrinsic" in label:
            return "intrinsic"
        if "extrinsic" in label:
            return "extrinsic"
        return "no"

    def extract_signals(self, context, prompt, response) -> Dict[str, Any]:
        """
        Everything except the LightGBM vote: the 778 features plus the NLI / NER / LLM signals the
        guardrails use. The in-process engine and the KServe transformer both call this, so serving
        paths cannot diverge.
        """
        if not self._is_loaded:
            self._load_models()

        c, p, r = str(context).strip(), str(prompt).strip(), str(response).strip()
        f_embed = self._extract_embeddings([vf.embedding_text(c, p, r)])

        # NLI / NER are not LightGBM features; they drive the guardrails and the breakdown
        p_entail, p_neutral, p_contra = self._get_nli_features(c, r)
        logger.info(f"- [NLI] contra {p_contra:.4f} | neutral {p_neutral:.4f} | entail {p_entail:.4f}")
        f_ner = self._get_ner_features(c, r)
        logger.info(f"- [NER] new entities {f_ner[0][0]} | overlap {f_ner[0][1]:.2f}")
        f_vistral = self._get_vistral_probs(c, p, r)  # [ext, int, no]
        logger.info(f"- [LLM] ext {f_vistral[0][0]:.4f} | int {f_vistral[0][1]:.4f} | no {f_vistral[0][2]:.4f}")

        return {
            # training column order for the LLM probabilities is [no, ext, int]
            "features": self._build_model_features(f_embed, c, p, r, f_vistral[:, [2, 0, 1]]),
            "p_entailment": float(p_entail),
            "p_neutral": float(p_neutral),
            "p_contradiction": float(p_contra),
            "new_entity_count": int(f_ner[0][0]),
            "entity_overlap_ratio": float(f_ner[0][1]),
            "vistral_extrinsic_prob": float(f_vistral[0][0]),
        }

    def decide(self, probs, signals: Dict[str, Any]) -> Dict[str, Union[str, float, None]]:
        """LightGBM class probabilities [ext, no, int] + signals -> final verdict (guardrail v3)."""
        probs = np.asarray(probs, dtype=float).reshape(-1)
        class_id = int(np.argmax(probs))
        confidence = probs[class_id]
        original_label = self.labels.get(class_id, "Unknown")
        logger.info(f"- [LightGBM] {original_label} ({confidence:.4f})")

        p_entail = signals["p_entailment"]
        p_neutral = signals["p_neutral"]
        p_contra = signals["p_contradiction"]
        new_entity_count = signals["new_entity_count"]
        vistral_ext = signals["vistral_extrinsic_prob"]
        active_guardrail = None

        if p_contra > 0.5:
            final_label, final_conf, active_guardrail = "intrinsic", float(p_contra), "NLI_CONTRADICTION_HIGH"
        elif p_neutral > 0.45 and p_entail < 0.5:
            final_label, final_conf, active_guardrail = "extrinsic", float(p_neutral), "NLI_NEUTRAL_HIGH"
        elif new_entity_count >= 1 and class_id == 1 and p_entail < 0.9:
            final_label, final_conf, active_guardrail = "extrinsic", 0.85, "NEW_ENTITY_MISMATCH"
        elif vistral_ext > 0.6:
            final_label, final_conf, active_guardrail = "extrinsic", float(vistral_ext), "VISTRAL_EXTRINSIC_HIGH"
        elif p_contra > 0.35 and class_id == 1:
            final_label, final_conf, active_guardrail = "intrinsic", float(p_contra), "SOFT_CONTRADICTION"
        else:
            final_label, final_conf = self._normalize_label(original_label), float(confidence)
        if active_guardrail:
            logger.info(f"GUARDRAIL {active_guardrail} -> {final_label}")

        return {
            "label": final_label,
            "confidence": final_conf,
            **{k: v for k, v in signals.items() if k != "features"},
            "active_guardrail": active_guardrail,
        }

    def predict(self, context, prompt, response) -> Dict[str, Union[str, float]]:
        if self.disabled:
            return {"label": "no", "confidence": 1.0}
        signals = self.extract_signals(context, prompt, response)
        return self.decide(self._predict_ensemble(signals["features"])[0], signals)

_pipeline_instance = None

def get_hallu_model() -> HallucinationPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = HallucinationPipeline()
    return _pipeline_instance

