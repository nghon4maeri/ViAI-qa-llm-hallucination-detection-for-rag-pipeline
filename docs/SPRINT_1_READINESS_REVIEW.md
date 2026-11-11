# Sprint 1 Readiness Review & Architectural Validation
## Vietnamese AI Response QA (ViAI-QA)

- **Review Date:** 2026-11-11
- **Reviewers:** Principal Software Architect & Technical Product Manager
- **Evaluation Status:** **READY WITH CONDITIONS**
- **Artifact Under Review:**
  1. [`docs/PRODUCT_REQUIREMENTS_DOCUMENT.md`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/PRODUCT_REQUIREMENTS_DOCUMENT.md)
  2. [`docs/MVP_TECHNICAL_ARCHITECTURE.md`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/MVP_TECHNICAL_ARCHITECTURE.md)
  3. [`docs/SPRINT_1_IMPLEMENTATION_PLAN.md`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/SPRINT_1_IMPLEMENTATION_PLAN.md)
  4. [`docs/SPRINT_1_BACKLOG.md`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/SPRINT_1_BACKLOG.md)
  5. [`docs/MVP_DECISIONS_AND_ASSUMPTIONS.md`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/MVP_DECISIONS_AND_ASSUMPTIONS.md)

---

## 1. Executive Summary

This readiness review evaluates whether the five planning documents for **Vietnamese AI Response QA (ViAI-QA)** provide a coherent, feasible, and implementation-ready roadmap for Sprint 1.

### Key Conclusions:
1. **Architectural Direction is Sound**: The decision to build a **Modular Monolith** using **SQLAlchemy 2.0 on PostgreSQL**, encapsulate the legacy ML code via an **Evaluation Engine Adapter**, and isolate heavy MLOps tools into **Docker Compose Profiles** is the correct strategy.
2. **High Feasibility**: The plan successfully avoids premature distributed architectures (Kafka, Celery worker clusters, microservices) and limits Sprint 1 to a verifiable core: single audit execution, PostgreSQL persistence, and paginated history retrieval.
3. **Four Critical Conditions Must Be Resolved Before Coding**:
   - **Condition 1 (ML Extraction Feasibility)**: The legacy `HallucinationPipeline.predict()` method does not return the breakdown keys (`p_entailment`, `new_entity_count`, etc.) expected by the proposed adapter.
   - **Condition 2 (Gateway Authentication Lockout)**: The current `nginx.conf` rejects all requests under `/api/` with HTTP 401 if `X-API-Key` is missing, which would lock out web UI users.
   - **Condition 3 (Existing Docker Volume Conflict)**: `init-db.sh` will not run if developers have a pre-existing `postgres_data` Docker volume.
   - **Condition 4 (OpenTelemetry Telemetry Spams Errors)**: If Jaeger is moved to an optional profile, the backend's current OTLP exporter will spam gRPC connection errors unless a clean fallback is configured.

**Final Verdict**: **`READY WITH CONDITIONS`**. Sprint 1 can proceed immediately once the four technical conditions are incorporated into the backlog.

---

## 2. Cross-Document Consistency Matrix

The table below verifies that functional requirements from the PRD map directly to architectural components and backlog implementation tasks:

| PRD Req ID | PRD Requirement | Architecture Component | Implementation Plan Section | Backlog Task ID | Consistency Status | Notes & Observations |
|---|---|---|---|---|---|---|
| **FR-001** | Single Audit Execution | `AuditRouter`, `AuditService`, `EvaluationEngine` | Section 2.4 | `S1-006`, `S1-007` | **ALIGNED** | End-to-end execution path mapped cleanly. |
| **FR-002** | Evaluation Detail Breakdown | `EvaluationBreakdown`, `ExistingPipelineAdapter` | Section 2.3 | `S1-004`, `S1-006` | **DISCREPANCY (CRITICAL)** | PRD & Arch expect NLI/NER scores, but legacy `predict()` returns only `label` and `confidence`. Requires adapter resolution. |
| **FR-003** | Persistent Audit Storage | `AuditRunModel`, PostgreSQL `audit_runs` | Section 2.2 | `S1-002`, `S1-003`, `S1-005` | **ALIGNED** | Complete schema, types, constraints, and migrations defined. |
| **FR-004** | Audit History Listing | `AuditRepository.list_audits`, `GET /api/v1/audits` | Section 2.2 | `S1-005`, `S1-007` | **ALIGNED** | Supports pagination, ordering, and project scoping. |
| **FR-005** | Audit Detail Retrieval | `AuditRepository.get_by_id`, `GET /api/v1/audits/{id}` | Section 2.2 | `S1-005`, `S1-007` | **ALIGNED** | Retrieves full context, prompt, response, and JSONB breakdown. |
| **FR-006** | Project Organization | `ProjectModel`, `ProjectsRouter` | Section 2.2 | `S1-003`, `S1-008` | **PARTIAL MISALIGNMENT** | PRD Section 6 deferred "Project Management CRUD" to Sprint 2, but Backlog `S1-008` implements basic project creation. (Resolved: Keep S1-008 for default project init). |
| **FR-007** | Search & Filter Audits | `AuditRepository` filter queries | Section 2.2 | `S1-005` | **ALIGNED** | Basic label/status filtering implemented in repository. |
| **FR-008** | Human Feedback / Annotation | `AuditFeedbackModel`, `FeedbackRouter` | File Mapping (p.2) | **MISSING IN BACKLOG** | Table exists in migration `001_initial_schema`, but no `POST /feedback` task exists in Sprint 1 backlog. (Acceptable: Deferred to Sprint 2). |
| **FR-010** | API Key Authentication | `ApiKeyModel`, NGINX Gateway | Section 10 | `S1-003`, `S1-010` | **AMBIGUOUS** | `api_keys` table created in S1-003, but auth checking in Sprint 1 is handled at NGINX layer with dev keys. |
| **FR-011** | Model Warmup & Readiness | `POST /health/warmup`, `GET /health` | Section 7.1 | `S1-004`, `S1-007` | **ALIGNED** | Supported via engine interface. |

---

## 3. Codebase Feasibility Findings (Ground Truth vs Planning)

### 3.1 ML Pipeline Feasibility: The Breakdown Return Discrepancy
- **Claimed in Plan**:
  [`docs/SPRINT_1_IMPLEMENTATION_PLAN.md#L182-L197`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/SPRINT_1_IMPLEMENTATION_PLAN.md#L182-L197) proposes:
  ```python
  raw_result = pipeline.predict(context, prompt, response)
  breakdown = EvaluationBreakdown(
      p_entailment=raw_result.get("p_entailment", 0.0),
      new_entity_count=raw_result.get("new_entity_count", 0),
      ...
  )
  ```
- **Ground Truth in Source Code**:
  Inspection of [`backend/model/inference_model.py#L296-L333`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/backend/model/inference_model.py#L296-L333) reveals that `predict()` returns **only** two dictionary keys:
  ```python
  return {
      "label": self._normalize_label(original_label),
      "confidence": float(confidence)
  }
  ```
  The intermediate variables `p_contra`, `p_neutral`, `p_entail`, `new_entity_count`, `overlap_ratio`, and `f_vistral` are calculated as local variables and printed to stdout, but **never returned** in the output dictionary.
- **Impact**:
  If a coding agent implements `ExistingPipelineAdapter` as written, all breakdown fields will default to `0.0` or empty lists.
- **Required Fix**:
  The adapter must either:
  1. Call the pipeline's sub-methods directly (`_get_nli_features`, `_get_ner_features`, `_get_vistral_probs`), OR
  2. A minor 5-line edit to [`backend/model/inference_model.py#L296-L333`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/backend/model/inference_model.py#L296-L333) must be authorized to attach the breakdown metrics to the returned dictionary.

---

### 3.2 Gateway Feasibility: NGINX Authentication Lockout
- **Claimed in Plan**:
  In [`docs/MVP_DECISIONS_AND_ASSUMPTIONS.md#ADR-004`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/MVP_DECISIONS_AND_ASSUMPTIONS.md#ADR-004), NGINX port 80 becomes the single ingress point for both Frontend and external API calls.
- **Ground Truth in Source Code**:
  Inspection of [`nginx/nginx.conf#L38-L63`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/nginx/nginx.conf#L38-L63) reveals:
  ```nginx
  location /api/ {
      if ($api_key_valid = 0) {
          return 401 '{"error":"Invalid or missing API key. Pass key in X-API-Key header."}';
      }
      ...
  }
  ```
- **Impact**:
  Because Sprint 1 does not implement API key management in the UI, web users opening the SvelteKit frontend will have their requests to `/api/v1/audits` rejected with HTTP 401. Furthermore, `nginx.conf` currently lacks a `location /` proxy block to serve the frontend on port 80.
- **Required Fix**:
  In `Task S1-010`:
  1. Add `location / { proxy_pass http://frontend:5173; ... }` to `nginx.conf`.
  2. For Sprint 1 local development, configure `location /api/v1/` to apply rate limits without rejecting missing API keys, or configure the SvelteKit frontend API client to supply the default local key (`X-API-Key: vihallu-dev-key-local`).

---

### 3.3 Database Feasibility: Existing Docker Volumes
- **Claimed in Plan**:
  [`docs/SPRINT_1_BACKLOG.md#S1-002`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/docs/SPRINT_1_BACKLOG.md#S1-002) mounts `docker/init-db.sh` into `/docker-entrypoint-initdb.d/` to execute `CREATE DATABASE viai_qa;`.
- **Ground Truth in Docker**:
  PostgreSQL only runs scripts in `/docker-entrypoint-initdb.d/` on **initial cluster creation** when the data directory is empty. If a developer previously ran `docker compose up -d db`, the volume `postgres_data` already contains initialized data, and `init-db.sh` will **silently be ignored**.
- **Impact**:
  The backend will crash on startup with: `FATAL: database "viai_qa" does not exist`.
- **Required Fix**:
  1. Document in `docker-compose.yml` and setup guide: run `docker compose down -v` if upgrading from the legacy stack.
  2. Add database creation verification in `backend/app/core/database.py` that connects to the default `postgres` database and executes `CREATE DATABASE viai_qa` if it does not already exist.

---

### 3.4 Observability Feasibility: OpenTelemetry & Jaeger
- **Ground Truth in Source Code**:
  Inspection of [`backend/main.py#L40-L46`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/backend/main.py#L40-L46) reveals:
  ```python
  if os.getenv("DISABLE_MODEL") == "true":
      processor = BatchSpanProcessor(ConsoleSpanExporter()) 
  else:
      jaeger_url = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger-collector.observability:4317")
      processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=jaeger_url, insecure=True))
  ```
- **Impact**:
  When running the minimal Core Profile (`docker compose up -d db backend frontend nginx-gateway`), Jaeger is not running. If `DISABLE_MODEL` is false (normal execution), the backend will emit continuous gRPC connection errors trying to reach `http://jaeger:4317`.
- **Required Fix**:
  Add an environment variable `ENABLE_TRACING=false` (defaulting to false in local dev) that routes traces to `ConsoleSpanExporter` or a noop tracer when Jaeger is offline.

---

## 4. Sprint 1 Task Readiness Assessment

| Task ID | Task Title | Scope Clarity | Feasibility | Dependencies | Testability | DoD Defined | Assessment |
|---|---|---|---|---|---|---|---|
| **S1-001** | Dependencies & Config | **Clear** | **High** | None | High | Yes | **READY** |
| **S1-002** | Database Engine & Pooling | **Clear** | **Medium** | S1-001 | High | Yes | **READY WITH CONDITION** (Address existing volume gotcha). |
| **S1-003** | Models & Alembic Migration | **Clear** | **High** | S1-002 | High | Yes | **READY** |
| **S1-004** | Engine Boundary & Adapters | **Clear** | **Medium** | S1-001 | High | Yes | **READY WITH CONDITION** (Resolve breakdown extraction). |
| **S1-005** | Audit Repo & Schemas | **Clear** | **High** | S1-003 | High | Yes | **READY** |
| **S1-006** | Audit Orchestration Service | **Clear** | **High** | S1-004, S1-005 | High | Yes | **READY** |
| **S1-007** | FastAPI Audits Router | **Clear** | **High** | S1-006 | High | Yes | **READY** |
| **S1-008** | Projects Router & Default Project | **Clear** | **High** | S1-003, S1-007 | High | Yes | **READY** |
| **S1-009** | Testing Suite & CI Gate | **Clear** | **High** | S1-007 | High | Yes | **READY** |
| **S1-010** | Docker Compose & NGINX Gateway | **Clear** | **Medium** | S1-002, S1-007 | High | Yes | **READY WITH CONDITION** (Add `location /` and dev key rule). |
| **S1-011** | Frontend API Client Update | **Clear** | **High** | S1-007, S1-010 | High | Yes | **READY** |

---

## 5. Missing Decisions and Blockers

```
+-------------------------------------------------------------------------------------------------------------------+
|                                          BLOCKERS & RESOLUTION ACTIONS                                            |
+----+------------------------------------+----------+--------------------------------------------------------------+
| ID | Decision / Blocker                 | Severity | Required Action Before Coding Kickoff                        |
+----+------------------------------------+----------+--------------------------------------------------------------+
| B1 | Intermediate ML Metric Extraction  | CRITICAL | Authorize ExistingPipelineAdapter to extract sub-features     |
|    |                                    |          | (_get_nli_features, _get_ner_features) or update predict()    |
|    |                                    |          | to return full breakdown dictionary.                         |
+----+------------------------------------+----------+--------------------------------------------------------------+
| B2 | NGINX Browser Ingress Auth Policy  | HIGH     | Explicitly configure nginx.conf: allow /api/v1/audits from   |
|    |                                    |          | frontend without 401, or inject vihallu-dev-key-local.       |
+----+------------------------------------+----------+--------------------------------------------------------------+
| B3 | Postgres DB Creation Fallback      | MEDIUM   | Provide Python-level check/create for database viai_qa       |
|    |                                    |          | on backend startup in addition to init-db.sh.                |
+----+------------------------------------+----------+--------------------------------------------------------------+
| B4 | Telemetry Jaeger Decoupling        | MEDIUM   | Add ENABLE_TRACING=false flag to core config to prevent      |
|    |                                    |          | gRPC connection spam when running core profile.              |
+----+------------------------------------+----------+--------------------------------------------------------------+
```

---

## 6. Risk Register with Severity and Mitigation

| Risk ID | Category | Description | Severity | Likelihood | Impact | Actionable Mitigation Strategy |
|---|---|---|---|---|---|---|
| **RSK-01** | Architecture | Memory exhaustion (OOM) on developer machines with $\le 8\text{GB}$ RAM during model load. | **High** | Medium | High | Support `DISABLE_MODEL=true` in `backend/app/core/config.py` to route to `MockEngine` by default during local frontend development. |
| **RSK-02** | Security | Unauthenticated API abuse if NGINX bypass is not cleanly closed. | **High** | Low | High | Task `S1-010` strictly removes `ports: - "8000:8080"` from `docker-compose.yml`, exposing backend only via internal Docker network. |
| **RSK-03** | Reliability | Heavy CPU inference blocking FastAPI's async event loop. | **High** | High | High | Enforce that all synchronous `engine.evaluate()` invocations run inside `starlette.concurrency.run_in_threadpool`. |
| **RSK-04** | Data Migration | Orphaned `PROCESSING` records if server process crashes mid-evaluation. | **Medium** | Medium | Medium | Implement startup reconciliation query in `backend/main.py`: `UPDATE audit_runs SET status='FAILED', error_code='SERVER_RESTARTED' WHERE status='PROCESSING'`. |
| **RSK-05** | ML Integration | Feature dimension misalignment (783 vs 778 features in LightGBM). | **Medium** | Low | Medium | Adapter isolates `predict_disable_shape_check=True` in a single line, logging a deprecation warning until Sprint 2 retraining. |
| **RSK-06** | Scope Creep | Implementing full User Authentication / SaaS billing prematurely. | **Low** | Low | High | Strictly preserve Section 6 MVP scope boundaries: no Stripe, no multi-tenant org models in Sprint 1. |

---

## 7. Recommended Corrections to Planning Documents

To guarantee smooth execution by another coding agent, the following minor amendments should be made to the planning documents:

### 1. Amendments to `docs/SPRINT_1_IMPLEMENTATION_PLAN.md`
- **Section 2.3 (Adapter Implementation)**:  
  Update `ExistingPipelineAdapter.evaluate()` so that it directly extracts sub-features from `pipeline`:
  ```python
  p_entail, p_neutral, p_contra = pipeline._get_nli_features(c, r)
  f_ner = pipeline._get_ner_features(c, r)
  f_vistral = pipeline._get_vistral_probs(c, p, r)
  ```
  This ensures `EvaluationBreakdown` receives genuine scores rather than zeroes.

### 2. Amendments to `docs/SPRINT_1_BACKLOG.md`
- **Task S1-010 (Docker Compose & NGINX Gateway)**:  
  Explicitly append:
  1. Add `location / { proxy_pass http://frontend:5173; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }` to `nginx/nginx.conf`.
  2. For `location /api/v1/`, permit requests with missing API keys in development mode, or configure the frontend API client (`S1-011`) to send `X-API-Key: vihallu-dev-key-local`.
- **Task S1-002 (Database Setup)**:  
  Add instruction to run `docker compose down -v` if upgrading an existing environment, or add a Python-level auto-create helper.

### 3. Amendments to `docs/MVP_TECHNICAL_ARCHITECTURE.md`
- **Section 5 (Backend Modular Monolith Structure)**:  
  Add `backend/app/core/logging.py` and an explicit `ENABLE_TRACING` flag to `config.py`.

---

## 8. Final Verdict

# Verdict: **READY WITH CONDITIONS**

### Summary Justification:
The planning documentation for **Vietnamese AI Response QA** is comprehensive, architecturally disciplined, and tightly aligned with the goal of turning an experimental ML codebase into a functional product. The core technologies (FastAPI, SQLAlchemy 2.0, PostgreSQL, SvelteKit, Docker Compose) are practical and standard.

The four identified conditions (ML metric extraction, NGINX ingress routing, DB volume handling, and Jaeger decoupling) are straightforward technical fixes that do not require altering the product scope or database schema. Once the coding agent applies the specific fixes detailed in Section 7 during Sprint 1 execution, the team can proceed with implementation immediately.
