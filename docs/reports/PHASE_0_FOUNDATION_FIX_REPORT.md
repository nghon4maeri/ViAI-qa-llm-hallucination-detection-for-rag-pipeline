# Phase 0 Report: Foundation Fixes & Repository Restructure

**Date:** 2026-11-25
**Roadmap:** [IMPROVEMENT_ROADMAP.md](../IMPROVEMENT_ROADMAP.md)
**Result:** Serving now computes exactly the features the model was trained on. The model was retrained on corrected embeddings (OOF Macro-F1 **0.8634**, previously 0.8638). The repo is reorganised into `backend/ machine-learning/ infrastructure/`.

## 1. Findings and fixes

| # | Problem | Impact | Fix |
|---|---|---|---|
| 1 | `.gitignore` rule `models/` also matched `backend/app/models/` | ORM models were never committed; a fresh clone or CI run fails on import | Rule anchored to the repo root (`/models/*`) |
| 2 | Serving built **783** features in a different order from the **778** used in training; `predict_disable_shape_check=True` hid the mismatch | LightGBM read NLI probabilities in the slots where it expects `prob_no/ext/int`. The Qwen probabilities were dropped, and the cosine feature meant something else (context vs response instead of sample vs train centroid) | `_build_model_features()` mirrors `build_feature_matrix()` from training. The dimension is checked against `feature_schema.json`. The train centroid ships as `models/lgbm/embedding_centroid.npy` |
| 3 | Only `fold_0.txt` was loaded | One fold instead of the 5-fold ensemble described in the docs | Mean of all `fold_*.txt` probabilities (same as `LGBMEnsemble`) |
| 4 | Training embeddings used an unmasked `mean(dim=1)` over batches of 8 | 2585 of 7000 training rows had padding averaged in; serving (batch of 1) had none, so short inputs drifted | Masked mean pooling in `machine-learning/pipelines/embed.py` and in serving, then embeddings and model regenerated |

NLI and NER are **still computed** at serving time. They were never model features; they drive the guardrails and the `breakdown` returned to users, as before.

### Verification

`tests/ml/test_feature_parity.py` (moved in R3) (`make test-ml`, skipped when artifacts are not pulled):
- Rebuilds the `StratifiedKFold(seed=42)` split and scores each saved fold on its own validation rows: OOF Macro-F1 = **0.8634**, identical to `models/metadata.yaml`.
- Runs the serving feature code on 10 training rows and compares against the training matrix (tolerance 1e-3): all match.

| Model | Embedding pooling | OOF Macro-F1 | Folds (0–4) |
|---|---|---|---|
| v2 (before) | unmasked mean | 0.8638 | — |
| v2.1 (now) | masked mean | 0.8634 | 0.8625 / 0.8660 / 0.8635 / 0.8723 / 0.8527 |

The v2 model is backed up in `models/_pre_phase0/` (local only, git-ignored).

## 2. Known gaps (not fixed in Phase 0)

- **LLM probability features come from different models.** Training used precomputed Vistral probabilities (`data/vihallu-vistral-dataset/`), while the live server computes them with Qwen2.5-1.5B and its own prompt, so these 3 features shift at serving time. Fix: regenerate the training probabilities with the serving model (several CPU hours) or serve Vistral.
- **Long contexts push the response out of the embedding.** Input is `context prompt response` truncated to 256 tokens, and 63% of training rows hit that limit. The embedding often never sees the response. Candidate fix: embed the response separately (Phase 1/2 experiment).
- **No labelled holdout.** `vihallu-test.csv` has no labels, so OOF is the only score available.
- **Model downloads.** Pulling DeBERTa-large and Qwen from HuggingFace is slow on the current network. Bake the weights into the image or a volume. `machine-learning/pipelines/embed.py` already accepts `PHOBERT_MODEL` / `PHOBERT_TOKENIZER` to use local copies.

## 3. Repository restructure

Package name `backend` is kept, so no import churn outside the moved legacy modules. All moves used `git mv` (history preserved).

| Before | After |
|---|---|
| `backend/model/{inference_model,mlflow_loader}.py`, `backend/kserve_adapter.py` | `backend/app/inference/` |
| `backend/routers/predict.py`, `backend/schemas/hallu_{input,output}.py` | `backend/app/modules/legacy/{router,schemas}.py` |
| `backend/utils/` | `backend/app/utils/` |
| `notebooks/{embed_phobert,train-model-vihallu,infer-model-vihallu}.py`, `scripts/auto_promote_registry.py` | `machine-learning/pipelines/{embed,train,infer,promote}.py` |
| `notebooks/*.ipynb` | `machine-learning/notebooks/` |
| `docker/`, `nginx/`, `mlops/mlflow/` | `infrastructure/docker/`, `infrastructure/nginx/`, `infrastructure/mlflow/` |
| `kubernetes/`, `mlops/kserve/` | `infrastructure/k8s/`, `infrastructure/k8s/kserve/` |
| `iac/` | `infrastructure/iac/` |
| `imgs/` | `docs/images/` |
| `tests/pytest.ini` | `[tool.pytest.ini_options]` in `pyproject.toml` |

These stay at the root because their tools look for them there: `Jenkinsfile`, `docker-compose.yml`, `dvc.yaml`, `render.yaml`, `vercel.json`, `alembic.ini`.

References updated in: `.github/workflows/ci.yml`, `Jenkinsfile`, `docker-compose.yml`, `infrastructure/docker/Dockerfile.{nginx,ci}`, Ansible playbooks (relative paths), `dvc.yaml`/`dvc.lock`, `.coveragerc`, `scripts/`, README, and the docs.

New at the root: `pyproject.toml` (metadata, pytest config) and `Makefile` (`make test`, `test-ml`, `run`, `migrate`, `pipeline`, `up`, `graph`).

### Removed from git (files kept on disk)

| Path | Why | Now |
|---|---|---|
| `mlops/mlflow_data/` (64 MB) | Local MLflow store committed by accident | `mlops/mlflow_data.dvc` |
| `models/lgbm_backup/`, `models/feature_schema_backup.json` (32 MB) | Model weights in git | `models/*.dvc` |
| `iac/terraform/.terraform/` (53 MB provider binary) | Regenerated by `terraform init` | git-ignored |
| `config-for-jenkins` | **Kubeconfig containing `client-key-data` (a private key)** | `infrastructure/ci/kubeconfig-jenkins`, git-ignored |

**Action needed:**
- Run `dvc push` once MinIO is up, so the new `.dvc` pointers can be pulled elsewhere.
- If the repo was ever pushed, treat the kubeconfig key as leaked and rotate the cluster credentials. Old git history still contains it, along with the ~150 MB of artifacts; removing them requires a history rewrite, which was not done.
- `infrastructure/k8s/secrets.yaml` and the chart's `secret.yaml` are still tracked; check that they only hold placeholders.

## 4. Reproduce

```bash
python -m venv --system-site-packages .venv && .venv/bin/pip install lightgbm "dvc[s3]"
PHOBERT_MODEL=models/phobert PHOBERT_TOKENIZER=models/phobert_tokenizer python machine-learning/pipelines/embed.py
MLFLOW_TRACKING_URI=file:./mlruns python machine-learning/pipelines/train.py
make test-ml     # parity + OOF
make test        # 52 fast tests
```
