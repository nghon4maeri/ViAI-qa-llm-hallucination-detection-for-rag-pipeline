# MVP Architectural Decisions & Assumptions
## Vietnamese AI Response QA (ViAI-QA)

- **Document Version:** 1.0.0
- **Status:** Approved Baseline
- **Author:** Principal Software Architect

---

## 1. Architectural Decision Records (ADRs)

### ADR-001: Choice of Persistence Framework (SQLAlchemy 2.0 + Alembic on PostgreSQL)
- **Status**: Accepted
- **Context**:
  The existing repository is completely stateless. The FastAPI backend has zero database connections. Meanwhile, `docker-compose.yml` runs a PostgreSQL 15 container solely for MLflow metadata. We need to introduce durable persistence for audit runs, project groupings, API keys, and human feedback.
- **Decision**:
  Adopt **SQLAlchemy 2.0** (with native type-hinted `Mapped` columns) and **Alembic** migrations, connecting to a dedicated application database `viai_qa` hosted on the existing PostgreSQL 15 instance.
- **Alternatives Considered**:
  1. *MongoDB / NoSQL*: Fast for JSON storage, but lacks ACID guarantees for audit compliance, has weak relational foreign key constraints between projects and feedback, and requires introducing a completely new database service into Docker Compose.
  2. *SQLite*: Lightweight for local development, but does not support concurrent write transactions under load, lacks native JSONB indexing, and diverges from production deployment standards.
  3. *Tortoise-ORM / SQLModel*: SQLModel has slower release cadences and subtle compatibility bugs with complex Alembic migrations; SQLAlchemy 2.0 is the enterprise Python standard.
- **Consequences**:
  - *Positive*: Zero extra database containers needed in Docker Compose; robust transactions and migration management; strong relational integrity.
  - *Negative*: Requires managing Alembic migration scripts; developers must write ORM models.

---

### ADR-002: Architecture Pattern — Modular Monolith over Microservices
- **Status**: Accepted
- **Context**:
  The system currently has small individual scripts, an unused MLflow loader, an uncalled KServe transformer adapter, and an in-process evaluation pipeline. A common architectural temptation is to split the system into multiple microservices (Auth Service, Audit Service, Inference Service, Reporting Service).
- **Decision**:
  Implement the backend as a **Modular Monolith** in FastAPI. All domains (`audits`, `projects`, `feedback`, `evaluation`, `core`) reside in one codebase and run within a single application process, cleanly separated by internal package boundaries.
- **Alternatives Considered**:
  1. *Distributed Microservices with RabbitMQ/Kafka*: Introduces immense network, serialization, deployment, and debugging overhead for a team of 1-3 developers.
  2. *Serverless Functions*: Severe cold start penalties (loading PhoBERT and DeBERTa takes 15-30 seconds), making serverless unsuitable for model serving.
- **Consequences**:
  - *Positive*: Extremely simple local debugging; zero network serialization overhead between business logic and database; fast feature iteration.
  - *Negative*: High CPU utilization during transformer inference can impact HTTP request handling if not offloaded to threadpools.

---

### ADR-003: Model Integration via In-Process Evaluation Adapter
- **Status**: Accepted
- **Context**:
  The legacy inference pipeline in [`backend/model/inference_model.py`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/backend/model/inference_model.py) is 342 lines of tightly coupled code that loads PhoBERT, DeBERTa, underthesea NER, and Qwen 1.5B directly on CPU. We need to isolate this logic without rewriting the underlying ML models.
- **Decision**:
  Implement the **Adapter Pattern** (`ExistingPipelineAdapter` implementing `EvaluationEngine` protocol). In Sprint 1, the adapter runs in-process, offloading CPU-heavy forward passes to Starlette's worker threadpool (`run_in_threadpool`). In parallel, provide a `MockEngine` for instant CI testing without model weights.
- **Alternatives Considered**:
  1. *Mandating KServe / MLServer Immediately*: Requires running Kubernetes, Knative, and Istio locally, which is prohibitive for standard developer machines (requires >16GB RAM just for infra).
  2. *Rewriting / Retraining ML Model*: Violates the core project constraint to reuse existing capabilities.
- **Consequences**:
  - *Positive*: Preserves 100% of the proven evaluation accuracy and Guardrails logic; allows unit tests to execute in milliseconds using the mock engine.
  - *Negative*: Memory footprint of backend container remains around 4.5 GB when full models are loaded on CPU.

---

### ADR-004: Ingress, Security & Gateway Routing Resolution
- **Status**: Accepted
- **Context**:
  In the current repository, `docker-compose.yml` maps port `8000:8080` directly to FastAPI. The SvelteKit frontend calls `http://localhost:8000/api/predict` directly, completely bypassing the NGINX gateway on port 80 and ignoring rate limiting and authentication checks.
- **Decision**:
  Remove the public host port mapping `8000:8080` for backend in `docker-compose.yml`. Enforce that all traffic (both frontend browser calls and external API consumers) enters through NGINX on port 80. NGINX proxies `/api/v1/` to the backend and serves the frontend on `/`.
- **Alternatives Considered**:
  1. *Running without NGINX*: Requires FastAPI to handle rate limiting, static asset caching, and SSL termination directly, increasing backend complexity.
  2. *Leaving port 8000 open*: Leaves a severe security hole where malicious callers bypass rate limits and auth guards.
- **Consequences**:
  - *Positive*: Single point of entry on port 80; centralized rate limiting (10 req/min for audits); authenticates external callers cleanly.
  - *Negative*: Developers running frontend standalone outside Docker must point `VITE_API_URL` to `http://localhost/api/v1`.

---

### ADR-005: Tiered Docker Compose Profiles for Local Development
- **Status**: Accepted
- **Context**:
  `docker-compose.yml` currently runs 15 services simultaneously (MinIO, MinIO-init, Postgres, MLflow, Backend, Frontend, Prometheus, Loki, Promtail, Jaeger, Grafana, Evidently, CI, Jenkins, NGINX). Running all 15 services consumes over 12 GB RAM and crashes on typical developer laptops.
- **Decision**:
  Refactor `docker-compose.yml` using Docker Compose **Profiles**:
  - **Default Core Profile** (No profile flag): Runs only `db`, `backend`, `frontend`, `nginx-gateway`.
  - **`monitoring` Profile**: Runs `prometheus`, `grafana`, `loki`, `promtail`.
  - **`tracing` Profile**: Runs `jaeger`.
  - **`mlops` Profile**: Runs `minio`, `minio-init`, `mlflow`.
- **Alternatives Considered**:
  1. *Deleting unused services*: Permanently loses valuable GKE and MLOps configurations built in earlier project phases.
  2. *Keeping all services running by default*: High friction for any full-stack developer trying to run the app locally.
- **Consequences**:
  - *Positive*: Core app starts in 5 seconds with `< 1.5 GB` RAM; advanced observability remains available on demand with `--profile monitoring`.
  - *Negative*: Developers must know the `--profile` command flag to view Grafana dashboards.

---

## 2. Technical Assumptions

1. **Hardware Baseline (Local Developer)**:
   - Minimum: 4 CPU cores, 8 GB RAM (runs Core Profile with lazy model loading).
   - Recommended: 8 CPU cores, 16 GB RAM (runs full models on CPU smoothly).
2. **Evaluation Latency Expectations**:
   - Running PhoBERT + DeBERTa-v3-large + Qwen 1.5B in-process on CPU takes between **3.0s and 10.0s** per triplet. Users understand this is a thorough deep-learning audit, not a 50ms keyword search.
3. **User Concurrency**:
   - For MVP, concurrent audit requests are expected to be low (1-5 concurrent users). Uvicorn worker threadpool handles serialization safely.
4. **Data Isolation**:
   - Single-organization workspace model. Multi-tenant database schema isolation (e.g. Row-Level Security) is deferred to enterprise phases.

---

## 3. Risk Register & Mitigations

| Risk ID | Risk Description | Severity | Probability | Mitigation Strategy |
|---|---|---|---|---|
| **R-01** | **Backend OOM during Model Load** | High | Medium | Set Docker memory reservation to 4GB; configure swap; document lazy loading behavior; provide `DISABLE_MODEL=true` mock mode for UI development. |
| **R-02** | **Feature Shape Mismatch in LightGBM** | High | Low | In Sprint 1, adapter captures 783-dim features and maps them safely; document model retraining backlog task for Sprint 2 to formally align training dimensions to 783. |
| **R-03** | **Long CPU Inference Freezes Event Loop** | High | High | Strict use of `starlette.concurrency.run_in_threadpool` inside `AuditService` ensures FastAPI's async event loop remains 100% responsive for health checks and GET queries. |
| **R-04** | **Database Schema Evolution Drift** | Medium | Medium | Enforce Alembic migrations in CI pipeline. Disallow `Base.metadata.create_all()` in production code. |
| **R-05** | **Frontend Stale Cache** | Low | Low | Enforce explicit API error handling with toast notifications in SvelteKit when backend fails. |

---

## 4. Critical Questions for the Project Owner

The following 8 questions cannot be answered by source code inspection alone and materially impact product decisions:

1. **Deployment Target for MVP**: Will the initial MVP be deployed to a **single Linux VPS / Cloud VM (Docker Compose)** or straight to the **GKE Kubernetes cluster** configured in `iac/terraform`? *(Recommendation: Single VPS with Docker Compose for faster validation).*
2. **Model Serving Acceleration**: Is a **GPU (NVIDIA T4 / A10G)** available for production serving, or must the system remain optimized for **CPU-only inference**?
3. **Data Retention Policy**: How long should completed audit records (contexts, questions, responses) be retained in the database? Is there a regulatory requirement to purge or anonymize sensitive context texts after a certain retention window?
4. **User Authentication Model**: For the MVP, is a simple **API Key + Project Model** sufficient, or do you require individual **User Registration / Password Login (OAuth2 / JWT)** in Sprint 1? *(Recommendation: API Key + Projects in Sprint 1, full User Auth in Sprint 2).*
5. **Commercial Licensing of Backbone Weights**: Are there commercial restrictions on your use of `vinai/phobert-base`, `DeBERTa-v3-large`, or the `ViHallu` competition dataset that affect commercial B2B deployment?
6. **Hallucination Severity Weights**: Should intrinsic contradictions (saying "Paris" instead of "Hà Nội") be weighted more heavily in confidence scoring than extrinsic additions (mentioning true external historical facts)?
7. **Human-in-the-Loop Feedback Purpose**: Will the human feedback collected in `audit_feedback` be used solely for quality reporting, or do you plan to export it as a DPO / RLHF fine-tuning dataset for future models?
8. **Public Access vs Internal Tool**: Is the web workspace intended strictly as an **internal tool for your team**, or will it be exposed as a **public demo / SaaS endpoint**?
