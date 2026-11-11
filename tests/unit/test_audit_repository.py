import uuid
from datetime import datetime, timezone
import pytest
from backend.app.modules.audits.repository import AuditRepository
from backend.app.modules.audits.schemas import AuditCreateRequest
from backend.app.evaluation.schemas import EvaluationResult, EvaluationBreakdown


def test_repository_lifecycle(db_session):
    repo = AuditRepository(db_session)
    
    # 1. Get or create default project
    default_proj_id = repo.get_or_create_default_project()
    assert default_proj_id is not None
    assert isinstance(default_proj_id, uuid.UUID)

    # 2. Create pending audit
    audit = repo.create_pending_audit(
        project_id=default_proj_id,
        context="Thủ đô của Việt Nam là Hà Nội.",
        prompt="Hà Nội là thủ đô nước nào?",
        response="Hà Nội là thủ đô của Việt Nam.",
    )
    assert audit.id is not None
    assert audit.status == "PROCESSING"

    # 3. Update completed audit
    breakdown_data = {
        "nli_entailment": 0.98,
        "ner_overlap_ratio": 1.0,
    }
    completed = repo.update_completed_audit(
        audit_id=audit.id,
        label="no_hallucination",
        confidence=0.98,
        breakdown=breakdown_data,
        model_version="mock-v1.0.0",
        latency_ms=45.2,
        completed_at=datetime.now(timezone.utc),
    )
    assert completed.status == "COMPLETED"
    assert completed.label == "no_hallucination"
    assert completed.confidence == 0.98
    assert completed.breakdown["nli_entailment"] == 0.98
    assert completed.latency_ms == 45.2

    # 4. Get by ID
    retrieved = repo.get_by_id(audit.id)
    assert retrieved is not None
    assert retrieved.id == audit.id

    # 5. List audits with pagination
    items, total = repo.list_audits(project_id=default_proj_id, page=1, page_size=10)
    assert total >= 1
    assert any(a.id == audit.id for a in items)


def test_repository_failed_audit(db_session):
    repo = AuditRepository(db_session)
    default_proj_id = repo.get_or_create_default_project()
    audit = repo.create_pending_audit(
        project_id=default_proj_id,
        context="C",
        prompt="P",
        response="R",
    )
    failed = repo.update_failed_audit(
        audit.id, error_code="TIMEOUT", error_message="Inference timed out"
    )
    assert failed.status == "FAILED"
    assert failed.error_code == "TIMEOUT"
    assert failed.error_message == "Inference timed out"
