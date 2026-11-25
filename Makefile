.PHONY: install test test-all test-ml run migrate pipeline up down frontend graph

PY ?= python

install:          ## Dev dependencies
	$(PY) -m pip install -r requirements/dev.txt

test:             ## Fast tests (no model weights needed)
	$(PY) -m pytest -m "not slow"

test-all:         ## Everything, including model-weight tests
	$(PY) -m pytest

test-ml:          ## Train/serve feature parity + OOF F1 regression (needs dvc pull)
	$(PY) -m pytest tests/ml/test_feature_parity.py -s

run:              ## API on :8080 with reload
	cd services/api && $(PY) -m uvicorn backend.main:app --reload --port 8080

migrate:          ## Apply DB migrations
	cd services/api && alembic upgrade head

pipeline:         ## DVC: embed -> train -> infer -> promote
	dvc repro

up:               ## Local stack (add --profile monitoring/tracing/mlops as needed)
	docker compose -f deploy/docker-compose.yml up -d

down:
	docker compose -f deploy/docker-compose.yml down

frontend:
	cd services/web && npm run dev

graph:            ## Refresh the graphify knowledge graph after code changes
	graphify update .
