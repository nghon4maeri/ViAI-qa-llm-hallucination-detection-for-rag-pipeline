# backend/app/modules/batches/service.py
import csv
import io
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.app.models.batch import AuditBatchModel
from backend.app.models.audit import AuditRunModel
from backend.app.models.project import ProjectModel
from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.schemas import EvaluationInput
from backend.app.evaluation.cache import evaluation_cache
from backend.app.core.metrics import record_evaluation_metric
from backend.app.modules.batches.schemas import (
    BatchItemInput,
    BatchDetailResponse,
    BatchSummaryResponse,
    BatchItemResult
)
from backend.app.core.logging import logger


class BatchService:
    def __init__(self, db: Session, engine: EvaluationEngine, session_factory=None):
        self.db = db
        self.engine = engine
        self.session_factory = session_factory or SessionLocal

    def get_or_create_default_project(self) -> uuid.UUID:
        stmt = select(ProjectModel).where(ProjectModel.is_default == True).limit(1)
        project = self.db.execute(stmt).scalar_one_or_none()
        if not project:
            project = ProjectModel(
                name=settings.DEFAULT_PROJECT_NAME,
                slug=settings.DEFAULT_PROJECT_SLUG,
                description="Default workspace automatically provisioned for audits",
                is_default=True
            )
            self.db.add(project)
            self.db.commit()
            self.db.refresh(project)
        return project.id

    def create_batch(
        self,
        filename: str,
        items: List[BatchItemInput],
        project_id: Optional[uuid.UUID] = None
    ) -> AuditBatchModel:
        if not project_id:
            project_id = self.get_or_create_default_project()

        batch = AuditBatchModel(
            project_id=project_id,
            filename=filename,
            total_count=len(items),
            completed_count=0,
            failed_count=0,
            hallucination_count=0,
            status="PROCESSING" if items else "COMPLETED"
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)

        # Pre-create pending audit rows linked to this batch
        for item in items:
            audit = AuditRunModel(
                project_id=project_id,
                batch_id=batch.id,
                context=item.context,
                prompt=item.prompt,
                response=item.response,
                status="PROCESSING",
                model_version=settings.MODEL_VERSION,
            )
            self.db.add(audit)

        self.db.commit()
        return batch

    def process_batch_in_background(self, batch_id: uuid.UUID, session: Optional[Session] = None):
        """Worker executing audit runs sequentially in background thread."""
        worker_db = session or self.session_factory()
        should_close = session is None
        try:
            batch = worker_db.get(AuditBatchModel, batch_id)
            if not batch:
                return

            stmt = select(AuditRunModel).where(
                AuditRunModel.batch_id == batch_id,
                AuditRunModel.status == "PROCESSING"
            ).order_by(AuditRunModel.created_at.asc())
            audits = worker_db.execute(stmt).scalars().all()

            for audit in audits:
                start_time = time.perf_counter()
                try:
                    cached_result = evaluation_cache.get(audit.context, audit.prompt, audit.response)
                    if cached_result:
                        result = cached_result
                        latency_ms = (time.perf_counter() - start_time) * 1000.0
                    else:
                        eval_input = EvaluationInput(
                            context=audit.context,
                            prompt=audit.prompt,
                            response=audit.response
                        )
                        result = self.engine.evaluate(eval_input)
                        evaluation_cache.set(audit.context, audit.prompt, audit.response, result)
                        latency_ms = (time.perf_counter() - start_time) * 1000.0

                    audit.label = result.label
                    audit.confidence = result.confidence
                    audit.breakdown = result.breakdown.model_dump() if result.breakdown else None
                    audit.model_version = result.model_version
                    audit.latency_ms = latency_ms
                    audit.status = "COMPLETED"
                    audit.completed_at = datetime.now(timezone.utc)

                    batch.completed_count += 1
                    if result.label and ("intrinsic" in result.label.lower() or "extrinsic" in result.label.lower() or "hallucination" in result.label.lower()):
                        batch.hallucination_count += 1

                    record_evaluation_metric(
                        model_version=result.model_version,
                        label=result.label,
                        duration_sec=latency_ms / 1000.0
                    )

                except Exception as exc:
                    latency_ms = (time.perf_counter() - start_time) * 1000.0
                    audit.status = "FAILED"
                    audit.error_code = "INFERENCE_ERROR"
                    audit.error_message = str(exc)
                    audit.latency_ms = latency_ms
                    batch.failed_count += 1

                worker_db.commit()

            batch.status = "COMPLETED"
            batch.completed_at = datetime.now(timezone.utc)
            worker_db.commit()
            logger.info(f"Batch {batch_id} finished: {batch.completed_count}/{batch.total_count} processed.")
        finally:
            if should_close:
                worker_db.close()

    def get_batch_detail(self, batch_id: uuid.UUID) -> Optional[BatchDetailResponse]:
        batch = self.db.get(AuditBatchModel, batch_id)
        if not batch:
            return None

        stmt = select(AuditRunModel).where(
            AuditRunModel.batch_id == batch_id
        ).order_by(AuditRunModel.created_at.asc())
        audits = self.db.execute(stmt).scalars().all()

        rate = (batch.hallucination_count / batch.completed_count * 100.0) if batch.completed_count > 0 else 0.0

        items_resp = [
            BatchItemResult(
                id=a.id,
                prompt=a.prompt,
                response=a.response,
                label=a.label,
                confidence=a.confidence,
                status=a.status,
                latency_ms=a.latency_ms,
                created_at=a.created_at
            )
            for a in audits
        ]

        return BatchDetailResponse(
            id=batch.id,
            project_id=batch.project_id,
            filename=batch.filename,
            status=batch.status,
            total_count=batch.total_count,
            completed_count=batch.completed_count,
            failed_count=batch.failed_count,
            hallucination_count=batch.hallucination_count,
            hallucination_rate=round(rate, 1),
            items=items_resp,
            created_at=batch.created_at,
            completed_at=batch.completed_at
        )

    def list_batches(self, project_id: Optional[uuid.UUID] = None) -> List[BatchSummaryResponse]:
        stmt = select(AuditBatchModel)
        if project_id:
            stmt = stmt.where(AuditBatchModel.project_id == project_id)
        stmt = stmt.order_by(desc(AuditBatchModel.created_at))
        batches = self.db.execute(stmt).scalars().all()
        return [BatchSummaryResponse.model_validate(b) for b in batches]

    def export_batch_csv(self, batch_id: uuid.UUID) -> str:
        batch = self.db.get(AuditBatchModel, batch_id)
        if not batch:
            raise ValueError(f"Batch {batch_id} not found")

        stmt = select(AuditRunModel).where(
            AuditRunModel.batch_id == batch_id
        ).order_by(AuditRunModel.created_at.asc())
        audits = self.db.execute(stmt).scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "context", "prompt", "response", "label", "confidence", "status", "latency_ms"])

        for a in audits:
            writer.writerow([
                str(a.id),
                a.context,
                a.prompt,
                a.response,
                a.label or "",
                f"{a.confidence:.4f}" if a.confidence is not None else "",
                a.status,
                f"{a.latency_ms:.2f}" if a.latency_ms is not None else ""
            ])

        return output.getvalue()
