# backend/app/modules/audits/service.py
import time
import uuid
import math
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple, List
from starlette.concurrency import run_in_threadpool

from backend.app.modules.audits.repository import AuditRepository
from backend.app.modules.audits.schemas import (
    AuditCreateRequest,
    RagAuditCreateRequest,
    AuditResponse,
    AuditSummary,
    AuditListResponse,
    FeedbackCreateRequest,
    FeedbackResponse,
)
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.schemas import EvaluationInput
from backend.app.evaluation.cache import evaluation_cache
from backend.app.evaluation.rag import evaluate_rag
from backend.app.evaluation.judge_agent import JudgeAgent, needs_judge
from backend.app.evaluation.schemas import ClaimVerdict, RagEvaluationInput
from backend.app.core.config import settings
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
        project_id = request.project_id or self.repo.get_or_create_default_project()

        # Step 2: Persist initial audit record in PROCESSING state
        audit = self.repo.create_pending_audit(
            project_id=project_id,
            context=request.context,
            prompt=request.prompt,
            response=request.response,
            trace_id=trace_id
        )
        return await self._run_audit(audit, lambda: self._evaluate_single(request))

    async def execute_rag_audit(
        self,
        request: RagAuditCreateRequest,
        trace_id: Optional[str] = None
    ) -> AuditResponse:
        project_id = request.project_id or self.repo.get_or_create_default_project()

        # context/prompt/response keep the legacy columns readable for history and batch export
        audit = self.repo.create_pending_audit(
            project_id=project_id,
            context="\n\n".join(request.contexts),
            prompt=request.question,
            response=request.answer,
            trace_id=trace_id,
            contexts=request.contexts,
            ground_truth=request.ground_truth
        )
        return await self._run_audit(audit, lambda: self._evaluate_rag(request))

    def _evaluate_single(self, request: AuditCreateRequest) -> dict:
        # Step 3: Check In-Memory LRU Cache first (< 0.5ms on hit)
        result = evaluation_cache.get(request.context, request.prompt, request.response)
        if result is None:
            eval_input = EvaluationInput(
                context=request.context,
                prompt=request.prompt,
                response=request.response
            )
            result = self.engine.evaluate(eval_input)
            evaluation_cache.set(request.context, request.prompt, request.response, result)
        return {
            "label": result.label,
            "confidence": result.confidence,
            "breakdown": result.breakdown.model_dump() if result.breakdown else None,
            "model_version": result.model_version,
        }

    def _evaluate_rag(self, request: RagAuditCreateRequest) -> dict:
        result = evaluate_rag(self.engine, request)
        return {
            "label": result.label,
            "confidence": result.confidence,
            "breakdown": None,
            "model_version": result.model_version,
            "claims": [c.model_dump() for c in result.claims],
            "faithfulness": result.faithfulness,
            "rag_metrics": result.metrics.model_dump(),
            "judge": self._auto_judge(request, result.claims),
        }

    def _auto_judge(self, request: RagEvaluationInput, claims: List[ClaimVerdict]) -> Optional[dict]:
        if not (settings.JUDGE_AUTO_ESCALATE and needs_judge(claims)):
            return None
        try:
            return JudgeAgent(self.engine).run(request, claims).model_dump()
        except Exception as exc:
            # Tier 2 is best-effort: a judge failure must not fail the Tier 1 audit
            logger.warning(f"Judge escalation skipped: {exc}")
            return None

    async def judge_audit(self, audit_id: uuid.UUID, only_doubtful: bool = False) -> AuditResponse:
        """Deep audit on demand. Raises LookupError (no audit), ValueError (not a completed RAG audit)."""
        audit = self.repo.get_by_id(audit_id)
        if not audit:
            raise LookupError(f"Audit run {audit_id} not found")
        if not audit.contexts or not audit.claims:
            raise ValueError("Chỉ thẩm định sâu được audit RAG đã chấm xong")
        payload = RagEvaluationInput(
            question=audit.prompt, contexts=audit.contexts, answer=audit.response, ground_truth=audit.ground_truth
        )
        tier1 = [ClaimVerdict(**c) for c in audit.claims]
        verdict = await run_in_threadpool(JudgeAgent(self.engine).run, payload, tier1, only_doubtful)
        return AuditResponse.model_validate(self.repo.save_judge(audit_id, verdict.model_dump()))

    async def _run_audit(self, audit, evaluate: Callable[[], dict]) -> AuditResponse:
        start_time = time.perf_counter()
        try:
            fields = await run_in_threadpool(evaluate)
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            # Step 4: Persist successful evaluation (Status: COMPLETED)
            audit = self.repo.update_completed_audit(
                audit_id=audit.id,
                latency_ms=latency_ms,
                completed_at=datetime.now(timezone.utc),
                **fields
            )
            logger.info(
                f"Audit {audit.id} COMPLETED: label={audit.label}, "
                f"confidence={audit.confidence:.4f}, latency={latency_ms:.2f}ms"
            )
            record_evaluation_metric(
                model_version=audit.model_version,
                label=audit.label,
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
                faithfulness=item.faithfulness,
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
