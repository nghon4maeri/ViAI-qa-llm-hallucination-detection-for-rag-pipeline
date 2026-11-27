# Go & Rust migration plan

**Status (2026-11-27):**
- **G0, G1 done:** `infrastructure/k8s/deployctl`, dry-run verified against minikube. The real `all` run waits on image pulls.
- **R0 done:** `machine-learning/benchmarks/bench_cpu_paths.py`.
- Everything else is still a plan.

**Goal:**
- **Go** for the code that drives Kubernetes and the clusters.
- **Rust** for the CPU-heavy computation that is still written in Python.

**Constraint: the architecture does not change.** The same components, interfaces, tools and data flow remain (README architecture, `docs/images/overview.png`):
- Terraform provisions.
- Ansible bootstraps.
- Helm/helmfile releases.
- KServe serves the model.
- FastAPI stays the API.
- DVC/MLflow run the ML lifecycle.

Only the language some of the glue code and some of the hot loops are written in changes.

---

## 1. What the code does today

### Kubernetes orchestration (Go candidates)

| Where | Lines | What it does |
|---|---|---|
| `infrastructure/k8s/local/deploy-minikube.sh` | 62 | Local cluster in 8 steps: minikube profile → cert-manager + KServe (Helm) → build/load images → secrets → runtime → model on a PVC → chart → wait. |
| `Jenkinsfile`, `sh` blocks | 322 total | Deploy stages: `helm upgrade`, `kubectl apply`, `kubectl wait`, and a `curl` smoke test. |
| `infrastructure/iac/ansible/*.yaml`, shell tasks | 624 total, 44 kubectl/helm/curl calls | Polling (`kubectl wait`, waiting for the cert-manager caBundle), applying manifests, creating secrets. |
| `machine-learning/scripts/resolve_storage_uri.py` | 81 | Asks the MLflow registry for the production model's `storageUri` before `kubectl apply` / `helmfile sync`. |
| `machine-learning/scripts/pull_model_from_registry.py` | 76 | Downloads the production model for image builds. |

The glue is spread over four languages: bash, Groovy+sh, Ansible YAML+sh, and Python. The same steps, such as waiting for the KServe controller, exist in several of them. Most of the bugs found in this repo were in this layer:
- The pre-pull loop stopped after one image, because `minikube ssh` read the loop's stdin.
- `kubectl apply` followed by `patch` raced the KServe controller.
- `rollout restart` was reverted by the KServe controller.
- Helm values were silently ignored.

### Computation (Rust candidates): measured on this machine, CPU

| Path | Data | Time | Where the time goes |
|---|---|---|---|
| PhoBERT embedding (`embed.py`, `_extract_embeddings`) | ~2,500 texts | 165 s | PyTorch kernels (C++/BLAS) |
| NLI, NER, Qwen/Vistral LLM probabilities (`inference_model.py`) | per call | dominant per request | PyTorch kernels |
| LightGBM 5-fold ensemble | per call | ms | LightGBM C++ |
| Tokenisation | per call | small | HF `tokenizers`, already Rust |
| `build_feature_matrix` (vihallu_features) | 7,000 × 778 | 458 ms | sklearn cosine (BLAS); `simple_features` 99 ms |
| `split_claims` (rag.py) | 7,000 answers | 31 ms | regex in C |
| **TF-IDF index build** (`rag_demo/retriever.py`) | 17,835 passages | **4.5 s** | **Python char n-gram loops** (21 M `list.append` calls) |
| **TF-IDF query** | 1 question | **59 ms** | Python `transform` + sparse matmul |
| `build_medical_hallu.py` perturbations | ViMedAQA, one DVC run | seconds | Python regex, runs once per data change |
| Drift (`drift_service.py`) | periodic | — | pandas / Evidently |

**Finding:** almost all heavy computation already runs in native code (PyTorch, BLAS, LightGBM, and HF tokenizers, which is Rust). Rewriting those parts in Rust would not make them faster.

The real per-request cost is the RAG evaluator's claim × chunk loop. Each pair runs the full pipeline once: PhoBERT → NLI → NER → LLM → LightGBM. That is up to 30 × 20 = 600 passes per answer. The lever there is batching the pairs into one forward pass per model. That is a Python change that is independent of language and keeps the architecture, so it is listed in §4 and is not part of the Rust work.

---

## 2. Go: `deployctl`

### Scope

**Moves to Go**

| Today | `deployctl` command |
|---|---|
| `deploy-minikube.sh` (all of it) | `deployctl all`, split into `up`, `addons`, `images`, `preload`, `adopt`, `sync`, `status` |
| Image pre-pull (bash, stdin bug) | `deployctl preload`: reads the images from `helmfile template`, skips images already on the node, retries |
| Helm adoption of objects created by kubectl | `deployctl adopt` |
| Jenkins `sh` deploy and smoke-test blocks | Jenkins calls `deployctl sync --env prod` and `deployctl smoke`. The Jenkins stages themselves stay. |
| Ansible shell polling tasks (`kubectl wait`, caBundle loop) | `deployctl wait kserve|certmanager|isvc`, called from the same Ansible tasks. Ansible stays the bootstrap tool. |
| `resolve_storage_uri.py` | `deployctl model-uri`, which calls the MLflow REST API (`/api/2.0/mlflow/registered-models/alias`) directly |

**Stays as it is**
- Terraform (`iac/terraform`), the Ansible playbooks, the Helm charts and `helmfile.yaml.gotmpl`, the `Dockerfile`s and the GitHub Actions jobs. `deployctl` calls them; it does not replace them.
- The KServe transformer and predictor. They need PyTorch/MLServer, and that is serving, not orchestration.
- `pull_model_from_registry.py`. It downloads artifacts with the MLflow client, which is ML lifecycle work, not k8s glue.

### Design
- **Module:** `infrastructure/k8s/deployctl`. Standard library only, with no client-go. Dependencies cost time on this network, and shelling out to `helm`/`helmfile`/`kubectl` keeps their behaviour identical to today.
- **Runner interface:** every external call goes through a `Runner`. Tests use a recorder, so the command plan of each step is checked without a cluster. Subprocesses never get the terminal's stdin, which avoids the `minikube ssh` bug.
- **Safety:**
  - `deployctl` always passes `--context` / `--kube-context` and never relies on, or switches, kubectl's default context.
  - It refuses `gke_*` contexts unless `--env prod --allow-cloud` is given, so the "no cloud while there is no budget" rule is enforced in code.
  - `--dry-run` prints the plan.
- **Waits:** these are explicit and bounded. Examples are image pull timeouts per image, `helm --wait --timeout`, and InferenceService `Ready`. They replace the bash `sleep`/`until` loops.
- **Make targets:** `make deploy-local` and `make deploy-status` call it.

### Phases

| Phase | Work | Done when |
|---|---|---|
| **G0** ✅ | `deployctl` with `up`, `addons`, `images`, `preload`, `secrets`, `model`, `adopt`, `sync`, `status`, `all`. Go unit tests cover command plans, image extraction from `helmfile template`, the context guard and adoption (6 tests, 62% coverage). A `--dry-run all` against minikube found the 6 images still missing and skipped the existing secrets and adopted objects. | `deployctl all` on a fresh minikube profile brings all 12 helmfile releases up, matching what `deploy-minikube.sh` plus `helmfile -e local sync` produce |
| **G1** ✅ | `deploy-minikube.sh` removed. README, Makefile (`make deploy-local`, `make deploy-status`), the helmfile, Terraform and values comments point at `deployctl`. CI job `deployctl` (gofmt, vet, test, build) gates the image build. The first real `deployctl all` run also changed `images`: `docker build -q` hid the build log of a failing image, so the log is now streamed. | CI green; the old script has no remaining references except the history note in REFACTOR_PLAN |
| **G2** | `deployctl wait …`, used from the Ansible shell tasks | Ansible `--check` on minikube unchanged; real run passes |
| **G3** | Jenkins deploy and smoke-test stages call `deployctl`; `deployctl model-uri` replaces `resolve_storage_uri.py` | Jenkins dry run (`--dry-run`) prints the same kubectl/helm calls as today |

### Risks
- **Two orchestration styles during the transition.** Each phase removes the code it replaces in the same change.
- **Jenkins agents need a `deployctl` binary.** It is built in the CI `build` job (a static Go binary) or with `go run` in the Jenkins image.
- **Go toolchain on dev machines.** It is one binary; `make deploy-local` can fall back to a pinned release.

---

## 3. Rust: native extension for the Python hot loops

The rule is to convert only paths where Python itself is the bottleneck, behind the same Python interface. Callers do not change, and a pure-Python fallback stays.

### Candidates, ranked by measured gain

| # | Path | Today | Rust target | Expected | Keep the architecture by |
|---|---|---|---|---|---|
| **R1** | `TfidfRetriever` char n-gram TF-IDF (rag-demo) | build 4.5 s / 17.8 k passages, query 59 ms | crate `viai_text` (PyO3 + maturin): char_wb 2–4-gram hashing, sublinear tf, L2 norm, inverted index, top-k | build < 1 s, query < 5 ms (n-gram loops and sparse scoring in Rust) | Same `Retriever` protocol, same class name and arguments; `RAG_RETRIEVER=python` keeps sklearn |
| **R2** | Batch text features for large JSONL batches: `normalize`, `simple_features`, `split_claims` | 99 ms + 31 ms per 7 k rows | Same crate: `simple_features_batch`, `split_claims_batch` | Matters only for batches far above today's size | `vihallu_features` keeps the same functions; it calls Rust when it is installed |
| **R3** | `build_medical_hallu.py` perturbations | seconds, once per data change | — | **Not worth it** | — |
| **R4** | PhoBERT / NLI / NER inference in Rust (`ort` / `candle`) | 165 s / 2.5 k texts (PyTorch) | — | **Not recommended now.** PyTorch is already native, and the 778-feature layout must match training bit for bit (the parity test). | Revisit only with ONNX export and re-validated parity |
| — | LightGBM, HF tokenizers, numpy/BLAS, Evidently | — | — | **No change**: already C/C++/Rust | — |

### Design
- **Crate:** `machine-learning/viai_text` (Rust, PyO3 + maturin). It is a Python package with the same name, built as an abi3 wheel. It is a dependency of `vihallu_features` and `rag-demo` and is optional at import.
- **Parity tests before switching:**
  - R1: same top-k as sklearn on ViMedAQA test, and scores `allclose` (atol 1e-6), plus the measured recall@3 (0.80) unchanged.
  - R2: identical outputs on the 7 k ViHallu rows.
- **Build:**
  - The CI `packages` job gets a Rust toolchain and builds the wheel.
  - `Dockerfile.backend` and `Dockerfile.backend-lite` get a Rust builder stage; the runtime image only gets the wheel, not the toolchain.
- **Fallback:** if `viai_text` is missing, the current Python code runs. Tests run both paths.

### Phases

| Phase | Work | Done when |
|---|---|---|
| **R0** ✅ | `machine-learning/benchmarks/bench_cpu_paths.py` (`make bench`): the §1 timings, with real data or `--synthetic` (same mean lengths) for CI, and `--json` output | Reproduced locally. Real data: TF-IDF build 4.48 s, query 59 ms, feature matrix 445 ms, `simple_features` 72 ms, `split_claims` 25 ms. The first draft of this plan said 6.8 s for the build; that figure was taken under `cProfile`. |
| **R1** | `viai_text` crate + TF-IDF retriever; parity tests; wheel in CI | Parity green; build ≥ 5× faster, query ≥ 10× faster on the benchmark |
| **R2** | Batch features in the crate, only if R0 shows batches large enough to matter | Identical outputs; measured gain |

### Risks
- **A second toolchain in the Python images.** Multi-stage builds keep it out of the runtime images, and the wheel is abi3 (one build for all Python ≥ 3.10).
- **Gain on a demo path only.** R1 speeds up the RAG demo, which is the platform's showcase. The detector's own cost stays in PyTorch, see §4.

---

## 4. Outside the migration: the bigger lever (no language change)

Per request, the RAG evaluator calls the detector once per claim × chunk pair, and each call runs four transformer models. Grouping the pairs and running each model once per batch, with padding to the longest pair, cuts the per-answer cost far more than any rewrite. It is a Python change behind the same `EvaluationEngine` interface. KServe already accepts batched V2 requests, so it touches neither the architecture nor the Go/Rust plan. It is recommended as a separate item after R0 measures it.

---

## 5. Order and effort (estimate)

| Step | Effort |
|---|---|
| G0 | 1–2 days |
| G1 | ½ day |
| R0 | ½ day |
| R1 | 2 days |
| G2 | 1 day |
| G3 | 1 day |
| R2 | only if R0 justifies it |

G0, G1, R0 and R1 can start right away. G2 and G3 touch Ansible and Jenkins, which are used for GKE. They can be built and tested on minikube now and used on GKE when there is budget again.
