# Refactor Plan: Main Folders, Same Stack and Architecture

**Status:** R1, R2 and R3 done (2026-11-25), folders renamed; R4–R6 not started
**Constraint:** keep the tech stack and the architecture in the README: FastAPI + NGINX, PyTorch/HF + LightGBM, MLflow + DVC + MinIO/GCS, KServe/MLServer, Docker/Helm/GKE, Terraform/Ansible, GitHub Actions + Jenkins, Prometheus/Grafana/Loki/Jaeger/Evidently, SvelteKit. Nothing is removed. Code is moved, deduplicated, or wired up to match the design.

## 1. Why

Phases 0–5 left the repo working (107 tests green) but showed structural debt:

| Finding | Evidence | Risk |
|---|---|---|
| Feature engineering written 3 times | `ml/pipelines/train.py`, `ml/pipelines/infer.py` and `backend/app/inference/inference_model.py` each build the 778-dim vector | This is how the Phase 0 train/serve skew happened. Today only `tests/integration/test_feature_parity.py` guards it |
| **KServe path can't work end to end** | `deploy/k8s/kserve/inference-service.yaml` serves the MLflow pyfunc (expects 778 features), while `backend/app/inference/kserve_adapter.py` forwards raw text. The backend runs every model in-process instead | Architecture in the README (KServe/MLServer serving) is not what runs |
| Default-project logic ×3 | `AuditRepository.get_or_create_default_project`, `BatchService.get_or_create_default_project`, `projects.router.ensure_default_project` | Drift between copies |
| Config outside `Settings` | `inference_model.py` reads `MODEL_PATH`, `LGBM_MODEL_DIR`, `DISABLE_MODEL`, `HF_TOKEN` with `os.getenv` | Two sources of truth |
| `print()` logging | 19 calls in `inference_model.py` | Invisible to Loki's structured logs |
| Dead code | `inference/mlflow_loader.py` (unused by the API), `utils/preprocessing.py` (only its own test), `utils/logger.setup_logging`, `frontend/src/lib/stores/index.ts` | Misleads readers |
| Frontend outside CI | No `svelte-check`/build in `.github/workflows/ci.yml`; `page.svelte.spec.ts` broken since before Phase 5 | UI regressions ship silently |
| Hardcoded dev API key in the browser bundle | `frontend/src/lib/api/api.ts` `X-API-Key: vihallu-dev-key-local` | Leaks into production builds |
| README drift | Tech stack says "Qwen2.5-1.5B: embedding"; the embedding is PhoBERT, Qwen feeds the 3 LLM-probability features | Wrong architecture story for reviewers |
| Root clutter (local, git-ignored) | `auth-file`, `config_flat`, `tls.crt`, `tls.key`, `mlflow.db`, `mlruns/`, `result/`, an empty `notebooks/` | Secrets next to source; easy to leak |

## 2. Target layout

```
vietnamese-llm-hallucination-detection/
├── services/                    # Everything that runs as its own container
│   ├── api/                     # FastAPI app; Python package stays `backend` (imports unchanged)
│   │   ├── backend/             #   app/{core,models,modules,evaluation,inference,utils}, main.py
│   │   ├── alembic/ alembic.ini
│   │   └── Dockerfile
│   ├── web/                     # SvelteKit UI (was frontend/)
│   ├── model-transformer/       # KServe transformer: text -> 778 features -> predictor (was kserve_adapter.py)
│   └── drift/                   # Evidently drift service (was observability/evidently)
│
├── ml/                          # Model lifecycle, run by DVC
│   ├── vihallu_features/        # NEW shared package: the ONE feature builder (train, infer, API, transformer)
│   ├── pipelines/               # embed, train, infer, promote, build_medical, generate_hard, export_feedback, evaluate
│   ├── notebooks/
│   └── params.yaml              # NEW: folds, seeds, thresholds, generator model (dvc params)
│
├── data/                        # DVC-tracked inputs (unchanged)
├── artifacts/                   # DVC outputs: models/, features/, predictions/, reports/, mlflow_data (was 4 root dirs)
│
├── sdk/python/                  # viai_qa client + MCP server (unchanged)
├── deploy/                      # docker-compose.yml, nginx/, k8s/, iac/, mlflow/, ci/ (Jenkins agent image)
├── observability/               # prometheus/, grafana/, loki/, jaeger/ configs
├── tests/
│   ├── api/                     # was unit + integration API tests
│   ├── ml/                      # feature parity, medical builder, flywheel, judge
│   └── sdk/                     # SDK + MCP end to end
├── scripts/                     # ops: pull_model, resolve_storage_uri, verify_pipeline
├── docs/
│   ├── architecture/            # PRD, technical architecture, ADRs, MEDICAL_DOMAIN
│   ├── reports/                 # sprint + phase reports
│   ├── guides/                  # deployment, GKE
│   └── images/
│
└── (root) README.md, Makefile, pyproject.toml, dvc.yaml, Jenkinsfile, render.yaml, vercel.json, .github/
```

**Kept at the root on purpose**, because their tools look for them there: `Jenkinsfile`, `dvc.yaml`/`dvc.lock`, `render.yaml`, `vercel.json`, `.github/`. `docker-compose.yml` moves to `deploy/` and `make up` wraps `docker compose -f deploy/docker-compose.yml`.

## 3. Phases

Each phase is one commit (or PR). The full test suite and `svelte-check` must pass before the next phase starts, and every moved path is found with `git grep` across CI, Jenkins, Compose, Helm, Ansible, DVC and docs, as in Phase 0.

### R1 Hygiene (no moves, low risk) ✅

**Done:**
- Deleted dead code: `inference/mlflow_loader.py`, `utils/preprocessing.py` (+ 5 tests that only covered it), `utils/logger.py`, `frontend/src/lib/stores/index.ts`. Removed the empty `notebooks/`.
- Default-project logic now lives only in `projects/service.ensure_default_project`. The repository and batch methods are one-line delegates.
- Model configuration moved into `Settings`: `PHOBERT_MODEL` / `PHOBERT_TOKENIZER`, `NLI_MODEL_NAME`, `NER_MODEL_NAME` / `NER_FALLBACK_MODEL`, `LLM_FEATURE_MODEL`, `HF_TOKEN`. The unused `MODEL_PATH` was removed.
  - `backend/.env` is now loaded by explicit path. Before, it was never actually read: the current python-dotenv resolves from the working directory, so `HF_TOKEN` was silently unset.
- 18 `print()` calls in `inference_model.py` → `logger`.
- Frontend API key comes from `VITE_API_KEY`. `docker-compose.yml` sets the local gateway dev key; production builds ship none.
- `page.svelte.spec.ts` rewritten for jsdom (Svelte `mount`, offline `fetch`), with `resolve.conditions: ['browser']` under Vitest. Frontend tests: 5/5.
- README: tech-stack rows fixed, plus a "research model vs served model" note.
- `tls.crt`, `tls.key`, `auth-file`, `config_flat` → `deploy/secrets/` (git-ignored, permissions kept). Use `--from-file=deploy/secrets/auth-file` when creating the ingress basic-auth secret.
- Checks: backend 102 passed (107 − the 5 deleted preprocessing tests), `svelte-check` 0, `vite build` OK, `docker compose config` OK.

**Original scope:**
- Delete dead code: `mlflow_loader.py`, `utils/preprocessing.py` + its test, `setup_logging`, `stores/index.ts`. Fix or replace `page.svelte.spec.ts`.
- Move the default-project logic into `projects` (one function); audits and batches call it.
- Move every `os.getenv` in `inference_model.py` into `Settings`, and replace `print()` with `logger`.
- Frontend API key from `VITE_API_KEY` (empty in production builds; the NGINX gateway injects or checks keys).
- README tech-stack row fixed (PhoBERT embedding, DeBERTa NLI, Qwen LLM-probability features, Claude judge).
- Root secrets (`tls.*`, `auth-file`, `config_flat`) move to `deploy/secrets/` (git-ignored); empty `notebooks/` removed.

### R2 One feature builder (removes the skew class of bugs) ✅

**Done:**
- `machine-learning/vihallu_features/` is an installable package (`pip install ./machine-learning`, numpy + scikit-learn only). It holds `FEATURE_GROUPS`/`FEATURE_DIM`, `LABEL_MAP`/`LABELS`, `LLM_PROB_COLUMNS`, `normalize`, `embedding_text`, `masked_mean`, `simple_features`, `centroid_cosine` and `build_feature_matrix`.
- `train.py`, `infer.py`, `embed.py`, `evaluate_detector.py` and `HallucinationPipeline` all import it. The four private copies (`simple_feats`, `build_cosine_sim`, `_feat_engineer_simple`, inline pooling) are gone.
- A third skew closed at the root: serving stripped whitespace and training did not. `normalize` (strip) now lives in the package for both. No ViHallu training row changes under strip, which was checked before making the change.
- `infer.py` now uses the saved `embedding_centroid.npy`, the same one serving uses, instead of recomputing it.
- Installed in the API image (`Dockerfile.backend`), on Render (`buildCommand`) and in `make install`. Tests and CI find it through `pythonpath` / `PYTHONPATH`.
- **Verification:**
  - The feature matrix from the new `train.py` is bitwise identical (`np.array_equal`) to the matrix from the pre-R2 commit. The `infer.py` path with the saved centroid is also bitwise identical.
  - `tests/ml/test_feature_parity.py` (real PhoBERT through the serving path + OOF 0.8634) passes, plus 7 new unit tests in `tests/ml/test_vihallu_features.py`. Full suite: 111 passed.

**Original scope:**
- `ml/vihallu_features/`: `build_features(embedding, context, prompt, response, llm_probs, centroid) -> np.ndarray[778]`, the `FEATURE_ORDER` constant, and masked-mean pooling.
- `train.py`, `infer.py` and `HallucinationPipeline` all import it. The parity test then checks one function against the stored matrix.
- The API image installs it as a local package. The ML code keeps its own requirements, and the API does not import pipeline scripts.

### R3 Folder moves ✅ (done before R2, at the user's request)

> **Data split (after R2):** `data/` stays at the root because several components read it and it holds inputs, not outputs. It is split into `raw/` (downloaded, `dvc add`: `vihallu`, `vihallu-private`, `vihallu-vistral`, `vimedaqa`) and `processed/` (DVC stage outputs: `vimedhallu`, `vimedhallu-hard`, `feedback`). The `-dataset` suffixes were dropped. Every raw `.dvc` pointer reports up to date, and re-running `build_medical` from the new path reproduces the locked output hash.

> **Renamed afterwards (user's choice of descriptive names):** `services/` → `applications/`, `ml/` → `machine-learning/`, `sdk/` → `client-sdk/`, `deploy/` → `infrastructure/`. The paths in this plan use the names from the time each step was written. `machine-learning/` is not an importable Python name, so code loads pipeline modules by path (the tests already did); `auto_promote.py` adds `pipelines/` to `sys.path`, and the R2 shared package will be imported the same way.

**Done:**
- `backend/` + `alembic.ini` → `services/api/`; `frontend/` → `services/web/`.
- `models/`, `features/`, `predictions/`, `mlops/mlflow_data` → `artifacts/`. Local-only `mlflow.db`, `mlruns/`, `result/` → `artifacts/local/` (git-ignored).
- `observability/` → `deploy/observability/`. The Helmfile and Ansible relative paths already resolved there, so nothing changed in them. Evidently stays in it rather than moving to `services/drift`.
- `scripts/` → `ml/scripts/`; `docker-compose.yml` → `deploy/`; `requirements-*.txt` → `requirements/*.txt`.
- `docs/` split into `architecture/`, `reports/`, `guides/`; `tests/` split into `api/`, `ml/`, `sdk/`.
- Paths inside containers are unchanged (`/app/backend`, `/app/models`, `/app/predictions`). Only build sources moved, so Helm values and K8s manifests needed no edits.

**Path handling:**
- pytest `pythonpath = ["services/api", "."]`.
- `alembic.ini` uses `%(here)s`.
- `Settings.MODELS_DIR` finds the checkout root by its `dvc.yaml` (falls back to `models` under the container WORKDIR). It replaces `BASE_DIR` arithmetic that would have broken one level deeper.
- Compose pins `name: vietnamese-llm-hallucination-detection`, so moving it into `deploy/` does not create new, empty named volumes.

**Also fixed:** `Dockerfile.ci` only copied `backend` and `tests`, so the ML and SDK tests could not run in CI. It now mirrors the repo layout, and `requirements/ci.txt` adds pandas, pyarrow and mcp.

**Checks:**
- pytest 102 passed (parity reproduces OOF from the new paths)
- `alembic upgrade head` from `services/api`
- API boots and `/health` returns ok
- web: `svelte-check` 0, vitest 5/5, `vite build` OK
- `docker compose config` resolves every new path
- `dvc status`: only stale deps, no missing outputs; lock committed

**Original scope:**
- `git mv` into the layout above, one area per commit: services → artifacts → tests → docs.
- Update `Dockerfile`s (build contexts), Compose, GH Actions, Jenkins `HELM_CHART_PATH` / `dir()` paths, Ansible relative paths, `dvc.yaml` outs + `dvc.lock`, `.coveragerc`, `pyproject` testpaths, `alembic.ini` `script_location`, and the README/doc links.
- `backend` stays the package name, so imports are unchanged. Only the paths on `sys.path` and in Docker change.

### R4 Serving matches the architecture (KServe)
- `services/model-transformer`: a KServe transformer that uses `vihallu_features` (PhoBERT + LLM probs) to turn `{context, prompt, response}` into the 778-dim vector for the existing MLflow/MLServer predictor (`mlflow-runtime`).
- New `KServeEngine` adapter in the API, behind the existing `EvaluationEngine` protocol, chosen by `EVALUATION_ENGINE=kserve|inprocess|mock`. NLI/NER guardrails stay in the API, so the breakdown keeps working.
- Helm `hallucination-model` chart gains the transformer; `inference-service.yaml` references it.
- The in-process engine stays for local development and for Render.

### R5 Configuration and pipeline params
- `ml/params.yaml` (folds, seed, `JUDGE_*`, generator model, escalation threshold) is read by DVC (`params:`) and MLflow logging, so experiments are comparable.
- Requirements: keep the four `requirements-*.txt` files (CI and images depend on them), but generate them from `pyproject.toml` extras (`serving`, `ml`, `dev`, `test`) with `pip-compile` so versions stop drifting.

### R6 CI/CD
- GH Actions adds a frontend job (`npm ci`, `svelte-check`, `vitest`, `vite build`) and an SDK job (`pytest tests/sdk`). `tests/ml` stays opt-in because it needs `dvc pull`.
- Jenkins builds the transformer image and deploys the updated model chart.

## 4. What does not change
- Tech stack, the README architecture diagram, the API routes and their JSON contracts, DB schema/migrations, the MLflow model name/alias, DVC data, Helm release names.
- The Python package name `backend`, so imports stay the same.

## 5. Risks and checks
| Risk | Mitigation |
|---|---|
| A moved path is missed in CI/Jenkins/Helm/Ansible | `git grep` sweep per move (as in Phase 0), `docker compose config -q`, `helm template`, `ansible-playbook --syntax-check`, `dvc status` |
| Training/serving change after R2 | `make test-ml` must reproduce OOF 0.8634 and feature parity exactly |
| KServe transformer latency (PhoBERT + Qwen on CPU) | Measure on GKE; the in-process engine remains as a fallback switch |
| Large diff hides mistakes | One area per commit, tests green at every step, no behaviour change in R1/R3 |

## 6. Effort (rough)
R1 ½ day · R2 1 day · R3 1 day · R4 2–3 days (needs a cluster to verify) · R5 ½ day · R6 ½ day.
