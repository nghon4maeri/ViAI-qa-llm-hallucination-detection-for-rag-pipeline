# machine-learning/pipelines/train.py
"""
train.py
Train PhoBERT + LightGBM ensemble for Vietnamese hallucination detection.
Outputs: artifacts/models/lgbm/, artifacts/models/metadata.yaml, artifacts/models/feature_schema.json
"""

import os
import sys
import json
import yaml
import subprocess

import mlflow
import mlflow.pyfunc
import lightgbm as lgb
import numpy as np
import pandas as pd

from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import f1_score
from mlflow.models import infer_signature

# Shared feature builder; works installed (pip install ./machine-learning) or straight from the checkout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vihallu_features as vf  # noqa: E402

import yaml  # noqa: E402

# Pipeline settings: machine-learning/params.yaml (tracked by DVC, logged to MLflow)
PARAMS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "params.yaml")
with open(PARAMS_PATH) as _f:
    PARAMS = yaml.safe_load(_f)


EXPERIMENT_NAME = "vihallu-pipeline"
MODEL_NAME      = os.getenv("MLFLOW_MODEL_NAME", "vihallu-detector")
NUM_FOLDS       = PARAMS["train"]["num_folds"]
RANDOM_STATE    = PARAMS["train"]["random_state"]

LABEL_MAP = vf.LABEL_MAP
FEAT_DIMS = vf.FEATURE_GROUPS
EXPECTED_DIM = vf.FEATURE_DIM  # 778

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

# NOTE: mlflow.set_tracking_uri / set_experiment intentionally moved inside
# main() so that importing this module doesn't crash when MLflow is offline.


def get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"]
        ).decode().strip()
    except Exception:
        return "unknown"


def load_dataset():
    df = pd.read_csv("data/raw/vihallu/vihallu-train.csv")
    df["label"] = df["label"].str.lower().str.strip()
    labels = df["label"].map(LABEL_MAP).values

    return (
        df["context"].fillna("").astype(str).tolist(),
        df["prompt"].fillna("").astype(str).tolist(),
        df["response"].fillna("").astype(str).tolist(),
        labels,
        df,
    )


def load_phobert_embeddings() -> np.ndarray:
    return np.load("artifacts/features/phobert_embeddings.npy")


def load_vistral_feats() -> np.ndarray:
    df = pd.read_csv(
        "data/raw/vihallu-vistral/vistral_train_predictions_with_probs.csv"
    )
    return df[vf.LLM_PROB_COLUMNS].values


def build_feature_matrix(
    contexts, prompts, responses, X_embed, X_vistral
) -> np.ndarray:
    # Centroid of the training embeddings; saved next to the folds so serving uses the same one
    return vf.build_feature_matrix(X_embed, contexts, prompts, responses, X_vistral, X_embed.mean(axis=0))


class LGBMEnsemble(mlflow.pyfunc.PythonModel):
    """
    Loads all fold models from artifact directory and averages predictions.
    Input:  pd.DataFrame of shape (N, 778)
    Output: pd.DataFrame with columns [prob_extrinsic, prob_no, prob_intrinsic]
    """

    def load_context(self, context):
        models_dir = context.artifacts["models_dir"]
        self.models = []
        for fname in sorted(os.listdir(models_dir)):
            if fname.endswith(".txt"):
                self.models.append(
                    lgb.Booster(model_file=os.path.join(models_dir, fname))
                )
        if not self.models:
            raise RuntimeError(f"No .txt model files found in {models_dir}")

    def predict(self, context, model_input):
        if isinstance(model_input, pd.DataFrame):
            model_input = model_input.values

        preds = np.mean([m.predict(model_input) for m in self.models], axis=0)

        return pd.DataFrame(
            preds,
            columns=["prob_extrinsic", "prob_no", "prob_intrinsic"],
        )


def main():
    mlflow.set_tracking_uri(
        os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    )
    mlflow.set_experiment(EXPERIMENT_NAME)

    print(f"[INFO] MLflow Tracking URI: {mlflow.get_tracking_uri()}")
    print(f"[INFO] Model registry name: {MODEL_NAME}")

    contexts, prompts, responses, y, _ = load_dataset()

    X_embed   = load_phobert_embeddings()
    X_vistral = load_vistral_feats()

    X = build_feature_matrix(contexts, prompts, responses, X_embed, X_vistral)
    print(f"[INFO] Feature matrix shape: {X.shape}")

    os.makedirs("artifacts/models", exist_ok=True)
    feature_schema = {
        "feature_dim":  int(X.shape[1]),
        "components":   FEAT_DIMS,
        "label_map":    LABEL_MAP,
        "column_order": list(vf.FEATURE_GROUPS),
    }
    with open("artifacts/models/feature_schema.json", "w") as f:
        json.dump(feature_schema, f, indent=2)
    print("[INFO] feature_schema.json saved.")

    with mlflow.start_run(run_name="vihallu-train") as run:
        print(f"[INFO] Run ID: {run.info.run_id}")

        mlflow.log_params({
            "num_folds":    NUM_FOLDS,
            "random_state": RANDOM_STATE,
            "feature_dim":  X.shape[1],
            "git_commit":   get_git_commit(),
            "model_name":   MODEL_NAME,
        })
        mlflow.log_params({f"lgbm_{k}": v for k, v in PARAMS["train"]["lgbm"].items()})

        os.makedirs("artifacts/models/lgbm", exist_ok=True)
        # Serving needs the same centroid as build_cosine_sim(); ships with the fold models
        np.save("artifacts/models/lgbm/embedding_centroid.npy", X_embed.mean(axis=0))
        oof_preds = np.zeros((len(y), 3))

        skf = StratifiedKFold(
            n_splits=NUM_FOLDS,
            shuffle=True,
            random_state=RANDOM_STATE,
        )

        for fold, (tr_idx, va_idx) in enumerate(skf.split(X, y)):
            clf = lgb.LGBMClassifier(**PARAMS["train"]["lgbm"], random_state=RANDOM_STATE)
            clf.fit(X[tr_idx], y[tr_idx])

            fold_preds          = clf.predict_proba(X[va_idx])
            oof_preds[va_idx]   = fold_preds

            fold_f1 = f1_score(
                y[va_idx],
                np.argmax(fold_preds, axis=1),
                average="macro",
            )
            mlflow.log_metric(f"fold_{fold}_macro_f1", fold_f1)
            print(f"  Fold {fold}: macro F1 = {fold_f1:.4f}")

            model_path = f"artifacts/models/lgbm/fold_{fold}.txt"
            clf.booster_.save_model(model_path)

        oof_f1 = f1_score(y, np.argmax(oof_preds, axis=1), average="macro")
        mlflow.log_metric("oof_macro_f1", oof_f1)
        print(f"[INFO] OOF macro F1: {oof_f1:.4f}")

        sample_input  = pd.DataFrame(X[:5])
        sample_output = pd.DataFrame(
            np.zeros((5, 3)),
            columns=["prob_extrinsic", "prob_no", "prob_intrinsic"],
        )
        signature = infer_signature(sample_input, sample_output)

        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=LGBMEnsemble(),
            artifacts={"models_dir": "artifacts/models/lgbm"},
            signature=signature,
            input_example=sample_input,
            pip_requirements=[
                "lightgbm",
                "mlflow==2.11.3",
                "numpy",
                "pandas",
                "scikit-learn",
            ],
        )
        print("[INFO] Model logged to MLflow.")

        metadata = {
            "label_map":    LABEL_MAP,
            "feature_dim":  int(X.shape[1]),
            "oof_macro_f1": float(oof_f1),
            "model_name":   MODEL_NAME,
        }
        with open("artifacts/models/metadata.yaml", "w") as f:
            yaml.dump(metadata, f)

        mlflow.log_artifact("artifacts/models/metadata.yaml")
        mlflow.log_artifact("artifacts/models/feature_schema.json")

        print("[INFO] Training completed successfully.")


if __name__ == "__main__":
    main()