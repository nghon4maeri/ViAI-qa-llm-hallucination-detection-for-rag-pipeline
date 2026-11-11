import sys
import os
import pytest
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# Enforce clean in-memory database and test environment for pytest runs
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DISABLE_MODEL"] = "true"
os.environ["ENABLE_TRACING"] = "false"
os.environ["ENVIRONMENT"] = "test"

# Gracefully mock optional ML or telemetry libraries if not installed in current test runner
for mod in [
    "torch", "torch.nn", "torch.nn.functional", "transformers", "lightgbm",
    "loguru", "prometheus_fastapi_instrumentator",
    "opentelemetry", "opentelemetry.trace", "opentelemetry.sdk",
    "opentelemetry.sdk.resources", "opentelemetry.sdk.trace",
    "opentelemetry.sdk.trace.export", "opentelemetry.sdk.trace.sampling",
    "opentelemetry.instrumentation", "opentelemetry.instrumentation.fastapi"
]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.app.models.base import Base
import backend.app.models  # noqa: F401 - Register all models with Base.metadata
from backend.app.core.database import get_db
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.schemas import EvaluationInput
from backend.app.evaluation.adapters.mock_engine import MockEngine
from backend.app.modules.audits.router import get_engine
from backend.main import app

# Shared test in-memory SQLite engine
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session():
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_mock_engine():
    return MockEngine(include_breakdown=True)


@pytest.fixture
def client(db_session, test_mock_engine):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_engine] = lambda: test_mock_engine

    # Backward compatibility mock for legacy /api/predict router
    mock_legacy_pipeline = MagicMock()
    mock_legacy_pipeline.predict.return_value = {
        "label": "no",
        "confidence": 0.99,
        "type": "none"
    }

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_model():
    return MockEngine(include_breakdown=True)


@pytest.fixture
def model():
    """Provides model fixture for integration tests."""
    return MockEngine(include_breakdown=True)


@pytest.fixture
def predict_fn(model):
    """Provides predict_fn fixture for legacy integration tests."""
    def _predict(context: str, prompt: str, response: str):
        res = model.evaluate(EvaluationInput(context=context, prompt=prompt, response=response))
        return {
            "label": res.label,
            "confidence": res.confidence
        }
    return _predict


@pytest.fixture
def valid_payload():
    return {
        "context": "Paris is the capital of France.",
        "prompt": "What is the capital of France?",
        "response": "Paris"
    }
