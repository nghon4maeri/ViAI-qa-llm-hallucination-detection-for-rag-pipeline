import os
import time
import numpy as np
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Sequence, Union

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


def _batched(items: Sequence, size: int, run: Callable[[list], np.ndarray], key: Callable = len) -> np.ndarray:
    """
    run() over chunks of at most `size` items and stack the rows back in input order. Items are grouped
    by `key` (text length) first, so each padded batch holds texts of similar length.
    """
    order = sorted(range(len(items)), key=lambda i: key(items[i]))
    rows: List[Any] = [None] * len(items)
    for start in range(0, len(order), size):
        idx = order[start:start + size]
        for i, row in zip(idx, run([items[i] for i in idx])):
            rows[i] = row
    return np.stack(rows)


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
        self.batch_size = max(1, settings.EVAL_BATCH_SIZE)
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

    def _build_model_features(self, f_embed, contexts, prompts, responses, vistral_no_ext_int):
        """Same builder as training (vihallu_features); vistral_no_ext_int follows vf.LLM_PROB_COLUMNS."""
        x = vf.build_feature_matrix(f_embed, contexts, prompts, responses, vistral_no_ext_int, self.embed_centroid)
        # The artifact on disk must have been trained on this layout
        if x.shape[1] != self.feature_dim:
            raise ValueError(f"Feature dim mismatch: got {x.shape[1]}, expected {self.feature_dim}")
        return x

    def _predict_ensemble(self, x):
        # Mean of fold probabilities, same as LGBMEnsemble in the training script
        return np.mean([m.predict(x) for m in self.lgbm_models], axis=0)

    def _extract_embeddings(self, text_list):
        """(N, 768) PhoBERT masked-mean embeddings, in batches of similar length."""
        import torch

        def run(chunk):
            inputs = self.embed_tokenizer(chunk, padding=True, truncation=True, max_length=vf.MAX_LENGTH, return_tensors="pt").to(self.device_cpu)
            with torch.no_grad():
                outputs = self.embed_model(**inputs)
                return vf.masked_mean(outputs.last_hidden_state, inputs["attention_mask"]).cpu().numpy()

        return _batched(list(text_list), self.batch_size, run, key=len)

    def _entity_sets(self, texts):
        """Entity set per text. Each distinct text goes through NER once: a RAG chunk recurs for every claim."""
        unique = list(dict.fromkeys(t for t in texts if t))
        sets = {}
        if unique:
            try:
                found = self.ner_pipeline(unique, batch_size=self.batch_size)
            except Exception:
                found = []
                for t in unique:  # one bad text must not drop the others (the old per-text behaviour)
                    try:
                        found.append(self.ner_pipeline(t))
                    except Exception:
                        found.append([])
            for t, entities in zip(unique, found):
                sets[t] = {e['word'].replace(" ", "").lower() for e in entities}
        return [sets.get(t, set()) for t in texts]

    def _ner_features(self, contexts, responses):
        """(N, 2): new entities in the response, entity overlap ratio."""
        ents = self._entity_sets(list(contexts) + list(responses))
        rows = []
        for c_ents, r_ents in zip(ents[:len(contexts)], ents[len(contexts):]):
            union = len(c_ents | r_ents)
            rows.append([len(r_ents - c_ents), len(c_ents & r_ents) / union if union > 0 else 0.0])
        return np.array(rows, dtype=float).reshape(-1, 2)

    def _nli_probs(self, pairs):
        """(N, 3) NLI probabilities [entailment, neutral, contradiction] for (premise, hypothesis) pairs."""
        import torch

        id2label = self.nli_model.config.id2label
        cols = [[i for i, v in id2label.items() if key in v.lower()][0] for key in ("entail", "neutral", "contradict")]

        def run(chunk):
            premises = [c if c else "no context" for c, _ in chunk]
            hypotheses = [r if r else "no response" for _, r in chunk]
            inputs = self.nli_tokenizer(
                premises,
                hypotheses,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt"
            ).to(self.device_cpu)
            with torch.no_grad():
                probs = torch.softmax(self.nli_model(**inputs).logits, dim=-1).cpu().numpy()
            return probs[:, cols]

        return _batched(list(pairs), self.batch_size, run, key=lambda pair: len(pair[0]) + len(pair[1]))

    def _vistral_text(self, context, prompt, response):
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
        return self.vistral_tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    def _vistral_probs(self, items):
        """
        (N, 3) LLM label probabilities [ext, int, no] for (context, prompt, response) triples: the softmax
        over the next-token logits of "0", "1", "2". Batches are left-padded so the last position is
        every row's next token; position ids skip the padding, so each row scores as it would alone.
        """
        import torch
        import torch.nn.functional as F

        tok = self.vistral_tokenizer
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token

        def get_id(token_str):
            ids = tok.encode(token_str, add_special_tokens=False)
            return ids[-1] if ids else -1

        label_ids = [get_id("0"), get_id("1"), get_id("2")]

        def run(chunk):
            side, tok.padding_side = tok.padding_side, "left"
            try:
                inputs = tok(chunk, return_tensors="pt", padding=True).to(self.vistral_model.device)
            finally:
                tok.padding_side = side
            position_ids = (inputs["attention_mask"].cumsum(-1) - 1).clamp(min=0)
            with torch.no_grad():
                # logits for the last position only: the full (batch, length, vocab) tensor is GBs
                logits = self.vistral_model(**inputs, position_ids=position_ids, logits_to_keep=1).logits[:, -1, :]
            probs = F.softmax(logits[:, label_ids].float(), dim=-1).cpu().numpy()  # [p0, p1, p2]
            return probs[:, [0, 2, 1]]

        texts = [self._vistral_text(c, p, r) for c, p, r in items]
        return _batched(texts, self.batch_size, run, key=len)

    def _get_vistral_probs(self, context, prompt, response):
        """(1, 3) [ext, int, no] for one sample (machine-learning/pipelines/evaluate_detector.py)."""
        return self._vistral_probs([(context, prompt, response)])

    def _normalize_label(self, label: str) -> str:
        label = label.lower()
        if "intrinsic" in label:
            return "intrinsic"
        if "extrinsic" in label:
            return "extrinsic"
        return "no"

    def extract_signals_batch(self, items) -> List[Dict[str, Any]]:
        """
        Everything except the LightGBM vote, for many (context, prompt, response) triples at once: the
        778 features plus the NLI / NER / LLM signals the guardrails use. Each model runs once per batch
        instead of once per triple, which is what the RAG evaluator's claim x chunk grid needs.
        """
        if not self._is_loaded:
            self._load_models()

        items = [(str(c).strip(), str(p).strip(), str(r).strip()) for c, p, r in items]
        if not items:
            return []
        contexts, prompts, responses = (list(col) for col in zip(*items))
        started = time.perf_counter()

        f_embed = self._extract_embeddings([vf.embedding_text(c, p, r) for c, p, r in items])
        # NLI / NER are not LightGBM features; they drive the guardrails and the breakdown
        nli = self._nli_probs(list(zip(contexts, responses)))       # [entail, neutral, contra]
        ner = self._ner_features(contexts, responses)               # [new entities, overlap]
        llm = self._vistral_probs(items)                            # [ext, int, no]
        # training column order for the LLM probabilities is [no, ext, int]
        features = self._build_model_features(f_embed, contexts, prompts, responses, llm[:, [2, 0, 1]])

        signals = []
        for i in range(len(items)):
            logger.debug(f"- [NLI] contra {nli[i, 2]:.4f} | neutral {nli[i, 1]:.4f} | entail {nli[i, 0]:.4f} "
                         f"| [NER] new {int(ner[i, 0])} overlap {ner[i, 1]:.2f} "
                         f"| [LLM] ext {llm[i, 0]:.4f} int {llm[i, 1]:.4f} no {llm[i, 2]:.4f}")
            signals.append({
                "features": features[i:i + 1],
                "p_entailment": float(nli[i, 0]),
                "p_neutral": float(nli[i, 1]),
                "p_contradiction": float(nli[i, 2]),
                "new_entity_count": int(ner[i, 0]),
                "entity_overlap_ratio": float(ner[i, 1]),
                "vistral_extrinsic_prob": float(llm[i, 0]),
            })
        logger.info(f"signals for {len(items)} triple(s) in {time.perf_counter() - started:.2f}s (batch size {self.batch_size})")
        return signals

    def extract_signals(self, context, prompt, response) -> Dict[str, Any]:
        """
        One triple. The in-process engine and the KServe transformer both call this (through the
        batch path), so serving paths cannot diverge.
        """
        return self.extract_signals_batch([(context, prompt, response)])[0]

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

    def predict_batch(self, items) -> List[Dict[str, Union[str, float]]]:
        """Verdicts for many (context, prompt, response) triples; one LightGBM call for all of them."""
        items = list(items)
        if self.disabled:
            return [{"label": "no", "confidence": 1.0} for _ in items]
        signals = self.extract_signals_batch(items)
        if not signals:
            return []
        probs = self._predict_ensemble(np.vstack([s["features"] for s in signals]))
        return [self.decide(p, s) for p, s in zip(probs, signals)]

    def predict(self, context, prompt, response) -> Dict[str, Union[str, float]]:
        return self.predict_batch([(context, prompt, response)])[0]

_pipeline_instance = None

def get_hallu_model() -> HallucinationPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = HallucinationPipeline()
    return _pipeline_instance

