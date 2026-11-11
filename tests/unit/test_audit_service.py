# tests/unit/test_audit_service.py
import asyncio
from backend.app.modules.audits.repository import AuditRepository
from backend.app.modules.audits.service import AuditService
from backend.app.modules.audits.schemas import AuditCreateRequest
from backend.app.evaluation.adapters.mock_engine import MockEngine


def test_audit_service_lifecycle_success(db_session):
    async def _test():
        repo = AuditRepository(db_session)
        engine = MockEngine(include_breakdown=True)
        service = AuditService(repo, engine)

        request = AuditCreateRequest(
            context="Hà Nội là thủ đô của Việt Nam.",
            prompt="Thủ đô của Việt Nam là gì?",
            response="Thủ đô của Việt Nam là Paris."
        )

        response = await service.execute_audit(request, trace_id="trace-12345")

        assert response.status == "COMPLETED"
        assert response.label == "intrinsic"
        assert response.confidence > 0.9
        assert response.breakdown is not None
        assert response.breakdown.p_contradiction > 0.9
        assert response.trace_id == "trace-12345"
        assert response.completed_at is not None

        # Verify directly from DB
        persisted = repo.get_by_id(response.id)
        assert persisted is not None
        assert persisted.status == "COMPLETED"
        assert persisted.label == "intrinsic"

    asyncio.run(_test())


def test_audit_service_failure_state_recorded(db_session):
    async def _test():
        repo = AuditRepository(db_session)
        failing_engine = MockEngine(should_fail=True)
        service = AuditService(repo, failing_engine)

        request = AuditCreateRequest(
            context="Some context",
            prompt="Some prompt",
            response="Some response"
        )

        with pytest.raises(RuntimeError):
            await service.execute_audit(request)

        # Verify that failed audit was recorded and not left in PROCESSING
        items, total = repo.list_audits(status="FAILED")
        assert total >= 1
        failed_record = items[0]
        assert failed_record.status == "FAILED"
        assert failed_record.error_code == "INFERENCE_FAILED"
        assert "Simulated inference engine failure" in failed_record.error_message

    import pytest
    asyncio.run(_test())


def test_audit_service_unavailable_breakdown_handling(db_session):
    async def _test():
        repo = AuditRepository(db_session)
        engine_no_breakdown = MockEngine(include_breakdown=False)
        service = AuditService(repo, engine_no_breakdown)

        request = AuditCreateRequest(
            context="Some context",
            prompt="Some prompt",
            response="Some response"
        )

        response = await service.execute_audit(request)
        assert response.status == "COMPLETED"
        assert response.breakdown is not None
        # Metrics must honestly be None instead of fabricated numbers
        assert response.breakdown.p_entailment is None
        assert response.breakdown.new_entity_count is None

    asyncio.run(_test())
