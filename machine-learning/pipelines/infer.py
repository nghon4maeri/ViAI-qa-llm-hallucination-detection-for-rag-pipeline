# machine-learning/pipelines/infer.py
"""
infer.py
Run inference on train split, save predictions + log to MLflow.
Mirrors feature engineering from train.py exactly.
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
import mlflow
from pathlib import Path

# Shared feature builder; works installed (pip install ./machine-learning) or straight from the checkout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vihallu_features as vf  # noqa: E402


EMB_PATH            = "artifacts/features/phobert_embeddings.npy"
VISTRAL_PATH        = "data/vihallu-vistral-dataset/vistral_train_predictions_with_probs.csv"
DATA_PATH           = "data/vihallu-dataset/vihallu-train.csv"
MODEL_DIR           = Path("artifacts/models/lgbm")
FEATURE_SCHEMA_PATH = "artifacts/models/feature_schema.json"
OUT_PATH            = "artifacts/predictions/vihallu_infer_predictions.csv"

LABELS = vf.LABELS


def resolve_id_column(df: pd.DataFrame, fallback_df: pd.DataFrame) -> np.ndarray:
    if "id" in df.columns:
        return df["id"].values
    if "id" in fallback_df.columns:
        return fallback_df["id"].values
    return np.arange(len(df))


with open(FEATURE_SCHEMA_PATH) as f:
    feature_schema = json.load(f)

EXPECTED_DIM = feature_schema["feature_dim"]
print(f"[INFO] Expected feature dim: {EXPECTED_DIM}")

df         = pd.read_csv(DATA_PATH).fillna("")
embeddings = np.load(EMB_PATH)
vistral_df = pd.read_csv(VISTRAL_PATH)

assert len(df) == len(embeddings), (
    f"DataFrame rows ({len(df)}) != embeddings ({len(embeddings)})"
)
assert len(df) == len(vistral_df), (
    f"DataFrame rows ({len(df)}) != vistral rows ({len(vistral_df)})"
)

X = vf.build_feature_matrix(
    embeddings, df["context"], df["prompt"], df["response"],
    vistral_df[vf.LLM_PROB_COLUMNS].values,
    np.load(MODEL_DIR / "embedding_centroid.npy"),  # the centroid serving uses
)

assert X.shape[1] == EXPECTED_DIM, (
    f"Feature dim mismatch: got {X.shape[1]}, expected {EXPECTED_DIM}"
)
print(f"[OK] Feature matrix: {X.shape}")

model_files = sorted(MODEL_DIR.glob("fold_*.txt"))
assert len(model_files) > 0, f"No fold model files found in {MODEL_DIR}"
print(f"[INFO] Loading {len(model_files)} fold models...")

fold_probs = []
for model_path in model_files:
    booster = lgb.Booster(model_file=str(model_path))
    fold_probs.append(booster.predict(X))                   # (N, 3)

probs     = np.mean(fold_probs, axis=0)                     # (N, 3)
pred_idx  = np.argmax(probs, axis=1)
pred_label = [LABELS[i] for i in pred_idx]

id_col = resolve_id_column(df, vistral_df)

out_df = pd.DataFrame({
    "id":              id_col,
    "predict_label":   pred_label,
    "prob_extrinsic":  probs[:, 0],
    "prob_no":         probs[:, 1],
    "prob_intrinsic":  probs[:, 2],
})

Path("predictions").mkdir(parents=True, exist_ok=True)
out_df.to_csv(OUT_PATH, index=False)
print(f"[INFO] Predictions saved to {OUT_PATH}  shape={out_df.shape}")

try:
    mlflow.set_tracking_uri(
        os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    )
    mlflow.set_experiment("vihallu-pipeline")

    with mlflow.start_run(run_name="vihallu-inference"):
        mlflow.log_params({
            "num_models":  len(model_files),
            "feature_dim": X.shape[1],
            "n_samples":   len(df),
        })
        mlflow.log_artifact(OUT_PATH, artifact_path="predictions")
        mlflow.log_artifact(FEATURE_SCHEMA_PATH, artifact_path="schema")
        print("[INFO] MLflow logging done.")
except Exception as e:
    print(f"[WARN] MLflow logging skipped: {e}")

print("[DONE] Inference complete.")