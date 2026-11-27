.PHONY: install test test-all test-ml run migrate pipeline up down frontend graph diagrams bench deploy-local deploy-status

PY ?= python

install:          ## Dev dependencies
	$(PY) -m pip install -r requirements/dev.txt -e ./machine-learning

test:             ## Fast tests (no model weights needed)
	$(PY) -m pytest -m "not slow"

test-all:         ## Everything, including model-weight tests
	$(PY) -m pytest

test-ml:          ## Train/serve feature parity + OOF F1 regression (needs dvc pull)
	$(PY) -m pytest tests/ml/test_feature_parity.py -s

run:              ## API on :8080 with reload
	cd applications/api && $(PY) -m uvicorn backend.main:app --reload --port 8080

migrate:          ## Apply DB migrations
	cd applications/api && alembic upgrade head

pipeline:         ## DVC: embed -> train -> infer -> promote
	dvc repro

up:               ## Local stack (add --profile monitoring/tracing/mlops as needed)
	docker compose -f infrastructure/docker-compose.yml up -d

down:
	docker compose -f infrastructure/docker-compose.yml down

frontend:
	cd applications/web && npm run dev

graph:            ## Refresh the graphify knowledge graph after code changes
	graphify update .

diagrams:         ## Redraw the README pipeline diagrams (needs Graphviz `dot`)
	python docs/diagrams/architecture.py

bench:            ## CPU timings of the Rust candidates (docs/GO_RUST_MIGRATION_PLAN.md, R0)
	python machine-learning/benchmarks/bench_cpu_paths.py

DEPLOYCTL = cd infrastructure/k8s/deployctl && go run . --python $(CURDIR)/.venv/bin/python

deploy-local:     ## Local k8s deploy on minikube viai-qa (Go: infrastructure/k8s/deployctl)
	$(DEPLOYCTL) all

deploy-status:    ## Nodes, pods and InferenceService of the local cluster
	$(DEPLOYCTL) status
