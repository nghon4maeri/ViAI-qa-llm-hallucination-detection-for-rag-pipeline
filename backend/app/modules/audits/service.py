# backend/app/modules/audits/service.py
import time
import uuid
import math
from datetime import datetime, timezone
from typing import Optional, Tuple, List
from starlette.concurrency import run_in_threadpool

from backend.app.modules.audits.repository import AuditRepository
from backend.app.modules.audits.schemas import (
    AuditCreateRequest,
    AuditResponse,
    AuditSummary,
    AuditListResponse,
    FeedbackCreateRequest,
    FeedbackResponse,
)
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.schemas import EvaluationInput
from backend.app.evaluation.cache import evaluation_cache
from backend.app.core.logging import logger
from backend.app.core.metrics import record_evaluation_metric, record_feedback_metric


class AuditService:
    def __init__(self, repo: AuditRepository, engine: EvaluationEngine):
        self.repo = repo
        self.engine = engine

    async def execute_audit(
        self,
        request: AuditCreateRequest,
        trace_id: Optional[str] = None
    ) -> AuditResponse:
        # Step 1: Resolve project ID
        project_id = request.project_id
        if not project_id:
            project_id = self.repo.get_or_create_default_project()

        # Step 2: Persist initial audit record in PROCESSING state
        audit = self.repo.create_pending_audit(
            project_id=project_id,
            context=request.context,
            prompt=request.prompt,
            response=request.response,
            trace_id=trace_id
        )

        start_time = time.perf_counter()
        try:
            # Step 3: Check In-Memory LRU Cache first (< 0.5ms on hit)
            cached_result = evaluation_cache.get(request.context, request.prompt, request.response)
            if cached_result:
                result = cached_result
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                logger.info(f"Audit {audit.id} Cache HIT ({latency_ms:.2f}ms)")
            else:
                eval_input = EvaluationInput(
                    context=request.context,
                    prompt=request.prompt,
                    response=request.response
                )
                result = await run_in_threadpool(self.engine.evaluate, eval_input)
                evaluation_cache.set(request.context, request.prompt, request.response, result)
                latency_ms = (time.perf_counter() - start_time) * 1000.0

            # Step 4: Persist successful evaluation (Status: COMPLETED)
            breakdown_dict = result.breakdown.model_dump() if result.breakdown else None
            audit = self.repo.update_completed_audit(
                audit_id=audit.id,
                label=result.label,
                confidence=result.confidence,
                breakdown=breakdown_dict,
                model_version=result.model_version,
                latency_ms=latency_ms,
                completed_at=datetime.now(timezone.utc)
            )
            logger.info(
                f"Audit {audit.id} COMPLETED: label={audit.label}, "
                f"confidence={audit.confidence:.4f}, latency={latency_ms:.2f}ms"
            )
            record_evaluation_metric(
                model_version=result.model_version,
                label=result.label,
                duration_sec=latency_ms / 1000.0
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            # Step 5: Mark record as FAILED in database (No orphaned PROCESSING state)
            logger.error(f"Audit {audit.id} FAILED after {latency_ms:.2f}ms: {exc}")
            self.repo.update_failed_audit(
                audit_id=audit.id,
                error_code="INFERENCE_FAILED",
                error_message=str(exc),
                latency_ms=latency_ms
            )
            raise exc

        return AuditResponse.model_validate(audit)

    def get_audit(self, audit_id: uuid.UUID) -> Optional[AuditResponse]:
        audit = self.repo.get_by_id(audit_id)
        if not audit:
            return None
        return AuditResponse.model_validate(audit)

    def list_audits(
        self,
        project_id: Optional[uuid.UUID] = None,
        label: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> AuditListResponse:
        items, total = self.repo.list_audits(
            project_id=project_id,
            label=label,
            status=status,
            page=page,
            page_size=page_size
        )

        summaries = [
            AuditSummary(
                id=item.id,
                project_id=item.project_id,
                status=item.status,
                label=item.label,
                confidence=item.confidence,
                prompt=item.prompt,
                response=item.response,
                has_feedback=bool(item.feedback),
                created_at=item.created_at
            )
            for item in items
        ]

        total_pages = math.ceil(total / page_size) if total > 0 else 1

        return AuditListResponse(
            items=summaries,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )

    def submit_feedback(
        self,
        audit_id: uuid.UUID,
        request: FeedbackCreateRequest,
    ) -> FeedbackResponse:
        feedback = self.repo.create_or_update_feedback(
            audit_id=audit_id,
            feedback_label=request.feedback_label,
            corrected_label=request.corrected_label,
            comment=request.comment,
        )
        record_feedback_metric(request.feedback_label)
        return FeedbackResponse.model_validate(feedback)

    def get_feedback(
        self,
        audit_id: uuid.UUID,
    ) -> Optional[FeedbackResponse]:
        audit = self.repo.get_by_id(audit_id)
        if not audit:
            raise ValueError(f"Audit run {audit_id} not found")
        feedback = self.repo.get_feedback_for_audit(audit_id)
        if not feedback:
            return None
        return FeedbackResponse.model_validate(feedback)
