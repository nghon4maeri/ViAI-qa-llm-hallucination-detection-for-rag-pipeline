# tests/api/test_feature_parity.py
"""
Guards the serving feature layout against the training layout.
Before Phase 0 the backend built 783 features (with NLI/NER inline) for a model
trained on 778, hidden by predict_disable_shape_check=True, and training
embeddings averaged padding tokens (unmasked mean) while serving did not.
"""
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REQUIRED = [
    "artifacts/features/phobert_embeddings.npy",
    "data/vihallu-dataset/vihallu-train.csv",
    "data/vihallu-vistral-dataset/vistral_train_predictions_with_probs.csv",
    "artifacts/models/lgbm/embedding_centroid.npy",
    "artifacts/models/feature_schema.json",
    "artifacts/models/metadata.yaml",
    "artifacts/models/phobert/model.safetensors",
]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not all(os.path.exists(os.path.join(ROOT, p)) for p in REQUIRED),
        reason="training data / model artifacts not pulled (dvc pull)",
    ),
]


@pytest.fixture(scope="module")
def train():
    spec = importlib.util.spec_from_file_location(
        "train_vihallu", os.path.join(ROOT, "ml/pipelines/train.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        contexts, prompts, responses, y, _ = mod.load_dataset()
        X = mod.build_feature_matrix(
            contexts, prompts, responses, mod.load_phobert_embeddings(), mod.load_vistral_feats()
        )
    finally:
        os.chdir(cwd)
    return mod, X, y, contexts, prompts, responses


@pytest.fixture(scope="module")
def pipeline():
    import torch
    from transformers import AutoModel, AutoTokenizer
    from backend.app.inference.inference_model import HallucinationPipeline

    p = HallucinationPipeline()
    p.device_cpu = torch.device("cpu")
    # Only what the LightGBM path needs; NLI/NER/Qwen are not features
    p.embed_tokenizer = AutoTokenizer.from_pretrained(os.path.join(ROOT, "artifacts/models/phobert_tokenizer"))
    p.embed_model = AutoModel.from_pretrained(os.path.join(ROOT, "artifacts/models/phobert")).eval()
    p._load_lgbm_ensemble()
    return p


def test_oof_macro_f1_reproduces_training(train, pipeline):
    from sklearn.metrics import f1_score
    from sklearn.model_selection import StratifiedKFold

    mod, X, y, *_ = train
    skf = StratifiedKFold(n_splits=mod.NUM_FOLDS, shuffle=True, random_state=mod.RANDOM_STATE)
    oof = np.zeros((len(y), 3))
    for fold, (_, va_idx) in enumerate(skf.split(X, y)):
        oof[va_idx] = pipeline.lgbm_models[fold].predict(X[va_idx])
    import yaml

    f1 = f1_score(y, oof.argmax(axis=1), average="macro")
    with open(os.path.join(ROOT, "artifacts/models/metadata.yaml")) as f:
        expected = yaml.safe_load(f)["oof_macro_f1"]
    print(f"OOF macro F1 = {f1:.4f} (training reported {expected:.4f})")
    assert f1 == pytest.approx(expected, abs=1e-4)


def test_serving_features_match_training(train, pipeline):
    _, X, _, contexts, prompts, responses = train
    vistral = pd.read_csv(
        os.path.join(ROOT, "data/vihallu-vistral-dataset/vistral_train_predictions_with_probs.csv")
    )[["prob_no", "prob_extrinsic", "prob_intrinsic"]].values

    for i in range(0, len(X), 700):  # 10 rows spread over the train set
        c, p, r = contexts[i], prompts[i], responses[i]
        # Training embedded the raw (unstripped) concatenation
        f_embed = pipeline._extract_embeddings([f"{c} {p} {r}"])
        x = pipeline._build_model_features(f_embed, c, p, r, vistral[i : i + 1])
        assert x.shape == (1, pipeline.feature_dim)
        np.testing.assert_allclose(x[0], X[i], rtol=1e-3, atol=1e-3)
