# Refactor Plan: Main Folders, Same Stack and Architecture

**Status:** R1–R6 done (2026-11-26). R4 is verified locally against real MLServer + kserve; it has not run on a cluster yet
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

### R4 Serving matches the architecture (KServe) ✅ (locally verified)

**Done:**
```
API (KServeEngine) --V2 {context, prompt, response}--> transformer (backend image, kserve 0.16)
   extract_signals: PhoBERT + LLM probs -> 778 features; NLI + NER signals
   --V2 FP64 [1, 778]--> predictor (MLServer 1.7.1, MLflow pyfunc, 5 LightGBM folds)
   <--prob_extrinsic / prob_no / prob_intrinsic--
   decide: guardrail v3
<--label, confidence, breakdown (JSON)--
```
- `HallucinationPipeline.predict` is split into `extract_signals` and `decide`, with the guardrail thresholds unchanged (pinned by `tests/api/test_guardrails.py`, 9 cases). The in-process engine and the transformer call the same two methods, so both paths give the same answer.
- `backend/app/inference/kserve_transformer.py` replaces `kserve_adapter.py`, which forwarded raw text to a predictor that expects 778 numbers. `predict()` is overridden, so one coroutine holds a request's signals; feature extraction runs in a thread.
- `KServeEngine` (`evaluation/adapters/kserve_engine.py`) is selected when `KSERVE_ENDPOINT` is set (`backend-prod.yaml` already sets it). Otherwise the in-process engine is used (local, Render), and `DISABLE_MODEL` selects the mock. One setting replaces the `EVALUATION_ENGINE` switch the plan proposed.
- Guardrails run in the transformer, not the API as planned. The API then needs no NLI/NER weights (its pod has 1 Gi), and the breakdown comes back as one JSON output.
- InferenceService (raw manifest + Helm chart) gains a `transformer` (backend image, `--predictor_protocol v2`, 4–6 Gi). The runtime moves to `seldonio/mlserver:1.7.1`; 1.5.0 is no longer on PyPI and bundles an old mlflow.

**Bugs found by running the real servers (fake-based tests did not catch them):**
- `train.py` logged the signature from `pd.DataFrame(X)`, which has integer column names. MLServer's MLflow runtime refuses to load such a model (`MetadataTensor name: Input should be a valid string`), so the predictor could never have started. It is now a tensor signature (`float64`, `(-1, 778)`).
- `train.py` pinned `mlflow==2.11.3` in the model's requirements while logging with mlflow 3.10. The pickle must be loaded by the version that wrote it. The pins are now the running versions of mlflow and lightgbm. The old run `3805bb2e…` (mlflow 2.11) cannot be loaded by today's stack; retrain + promote produces a servable one.
- kserve ≥ 0.15 reads `--predictor_protocol` (default v1, which MLServer does not serve), and V2 responses need an `id`.

**Checks:**
- Real MLServer 1.7.1 serving a pyfunc saved from the current folds returns exactly the probabilities of the local boosters.
- Full round trip `KServeEngine` → real kserve 0.16 transformer → MLServer: 4/4 verdicts equal the in-process `decide`, at 12–47 ms per call without model loading. `extract_signals` was stubbed there because the NLI/NER weights are not on this machine.
- `dvc repro train` with the fixed `train.py`: OOF macro F1 0.8634, and the 5 fold files are byte-identical to the previous ones. The model it logged (tensor signature, mlflow 3.10 / lightgbm 4.7 pins) loads in MLServer and returns the local boosters' probabilities.
- `tests/api/test_kserve.py` (7 tests).

**Local cluster deploy (2026-11-26):** `infrastructure/k8s/local/deploy-minikube.sh` on minikube (profile `viai-qa`) installs cert-manager 1.16 and KServe 0.16 in Standard mode, the `mlflow-runtime` ClusterServingRuntime and the `hallucination-model` chart (`values/model-minikube.yaml`: predictor only, model on a PVC). From an empty namespace it reaches InferenceService Ready in under 2 minutes, and 10/10 predictions through the KServe Service equal the local ensemble. Found on the way:
- MLServer 1.7.1's parallel workers crash with uvloop ≥ 0.22 (`There is no current event loop in thread 'MainThread'`). `Dockerfile.predictor` pins `uvloop<0.22`.
- `Dockerfile.predictor` is a 1.4 GB MLServer image pinned to the mlflow/lightgbm that `train.py` logs with. `seldonio/mlserver:1.7.1` is several GB and ships its own mlflow. Switching prod's runtime to this image is recommended but not done; it needs a Jenkins build and push.
- `machine-learning/scripts/export_serving_model.py` writes the same pyfunc as `train.py` (shared `serving_model_kwargs`) without a tracking server.
- `infrastructure/iac/ansible/setup_k8s_stack.yaml` still installs KServe v0.11.0 in Serverless mode for GKE; not changed here.

**Not verified:** a GKE deploy (no cloud budget). The first deploy needs `hf-token` (optional) and `ghcr-secret` in the namespace, and the transformer's first start downloads the NLI/NER models (the readiness probe allows ~6 min). The backend image with kserve 0.16 has not been rebuilt here (torch download).

**Original plan:**
- `services/model-transformer`: a KServe transformer that uses `vihallu_features` (PhoBERT + LLM probs) to turn `{context, prompt, response}` into the 778-dim vector for the existing MLflow/MLServer predictor (`mlflow-runtime`).
- New `KServeEngine` adapter in the API, behind the existing `EvaluationEngine` protocol, chosen by `EVALUATION_ENGINE=kserve|inprocess|mock`. NLI/NER guardrails stay in the API, so the breakdown keeps working.
- Helm `hallucination-model` chart gains the transformer; `inference-service.yaml` references it.
- The in-process engine stays for local development and for Render.

### R5 Configuration and pipeline params ✅

**Done:**
- `machine-learning/params.yaml` holds `embed` (model, batch size), `train` (folds, seed, LightGBM hyper-parameters), `medical` (seed) and `generate_hard` (model, effort, n).
- `dvc.yaml` declares them per stage (`params:` with the non-default file path), so `dvc params diff` and `dvc status` see changes. `train.py` logs the LightGBM parameters to MLflow.
- Values are the old literals: the LightGBM estimator built from params has the same `get_params()` as before, and `build_medical` reproduces its locked output.
- Requirements: removed the unused `requirements/test.txt` (nothing referenced it; CI uses `ci.txt`), and de-duplicated `opentelemetry-api` / `opentelemetry-sdk` in `ci.txt`.

**Not done (on purpose):** generating the four requirement files from `pyproject.toml` extras with `pip-compile`. Each image needs a different, fully pinned set (torch CPU wheels, kserve, mlflow for serving vs. a light CI set), and a lock-everything step on this machine's network would take longer than it saves. The two drift bugs it was meant to prevent are fixed directly: instrumentator ≥ 8, and the CI image now has every test dependency, verified in a clean venv. Revisit with `uv pip compile` when dependency updates become routine.

**Checks:** dev venv 111 passed; clean CI venv (`requirements/ci.txt` only) 108 passed + 2 intended skips, coverage 88%; `dvc status` up to date.

**Original scope:**
- `ml/params.yaml` (folds, seed, `JUDGE_*`, generator model, escalation threshold) is read by DVC (`params:`) and MLflow logging, so experiments are comparable.
- Requirements: keep the four `requirements-*.txt` files (CI and images depend on them), but generate them from `pyproject.toml` extras (`serving`, `ml`, `dev`, `test`) with `pip-compile` so versions stop drifting.

### R6 CI/CD ✅

**Done:**
- `.github/workflows/ci.yml` gains a `web` job and a `packages` job, and `concurrency` cancels superseded runs.
  - `web` runs Node 22 with an npm cache: `npm ci`, then lint (prettier + eslint), `svelte-check`, vitest and `vite build`.
  - `packages` installs `./machine-learning` and `./client-sdk/python[mcp]` into a clean venv and imports both; `viai-qa-mcp` must be on PATH.
  - The image build now needs `test`, `web` and `packages`, and the Jenkins deploy follows the image build.
- Frontend made lint-clean instead of skipping lint: Prettier applied with the project config; 38 ESLint errors fixed.
  - Keys on every `{#each}`.
  - `catch (e: any)` replaced by `unknown` plus a shared `errorMessage()`.
  - Typed interval handle.
  - One scoped exception, for the absolute CSV download link.
- **Two real bugs found by testing in a clean CI-only venv**, which the dev venv hid:
  1. `requirements/ci.txt` pinned `prometheus-fastapi-instrumentator==7.0.0` while `fastapi>=0.111` resolves to 0.163. Instrumentator 7 crashes on every request with the new router type (`'_IncludedRouter' object has no attribute 'path'`), so 42 tests failed and coverage was 68%. The dev venv passed only because `conftest.py` mocked the missing package. This predates the refactor. Instrumentator is now `>=8.0` in ci/serving/test.
  2. `conftest.py` replaced a missing `torch` with a `MagicMock`. That broke scikit-learn's array checks, and `importorskip("torch")` silently "passed". Nothing imports torch at module load, so torch/transformers/lightgbm are no longer mocked, and the parity test skips without the ML stack.
- **Trace view fix found while re-checking the UI:** claim marks were `<button>` elements, which browsers lay out as inline-block even with `display: inline`, so each sentence broke onto its own block. They are now `<span role="button" tabindex="0">` with Enter/Space handling, and the passage flows. Breakdown rows got a gap so labels and percentages don't touch in narrow columns.
- **Checks:**
  - clean CI venv: 108 passed + 2 intended skips, coverage 88%
  - dev venv: 111 passed
  - web: lint / check / vitest / build exit 0
  - packages job simulated in a fresh venv

**Not done:** a separate Jenkins stage for the transformer image is unnecessary, because the transformer runs from the backend image the pipeline already builds.

**Original scope:**
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
