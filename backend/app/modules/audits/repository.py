# backend/app/modules/audits/repository.py
import uuid
import math
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session, joinedload
from backend.app.models.audit import AuditRunModel
from backend.app.models.project import ProjectModel
from backend.app.models.feedback import AuditFeedbackModel
from backend.app.core.config import settings


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_default_project(self) -> uuid.UUID:
        """Fetch or create the system default workspace project."""
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

    def create_pending_audit(
        self,
        project_id: uuid.UUID,
        context: str,
        prompt: str,
        response: str,
        trace_id: Optional[str] = None
    ) -> AuditRunModel:
        audit = AuditRunModel(
            project_id=project_id,
            context=context,
            prompt=prompt,
            response=response,
            status="PROCESSING",
            model_version=settings.MODEL_VERSION,
            trace_id=trace_id,
        )
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(audit)
        return audit

    def update_completed_audit(
        self,
        audit_id: uuid.UUID,
        label: str,
        confidence: float,
        breakdown: Optional[Dict[str, Any]],
        model_version: str,
        latency_ms: float,
        completed_at: datetime
    ) -> AuditRunModel:
        audit = self.get_by_id(audit_id)
        if not audit:
            raise ValueError(f"Audit run {audit_id} not found")

        audit.label = label
        audit.confidence = confidence
        audit.breakdown = breakdown
        audit.model_version = model_version
        audit.latency_ms = latency_ms
        audit.status = "COMPLETED"
        audit.completed_at = completed_at

        self.db.commit()
        self.db.refresh(audit)
        return audit

    def update_failed_audit(
        self,
        audit_id: uuid.UUID,
        error_code: str,
        error_message: str,
        latency_ms: Optional[float] = None
    ) -> AuditRunModel:
        audit = self.get_by_id(audit_id)
        if not audit:
            raise ValueError(f"Audit run {audit_id} not found")

        audit.status = "FAILED"
        audit.error_code = error_code
        audit.error_message = error_message
        audit.latency_ms = latency_ms
        audit.completed_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(audit)
        return audit

    def get_by_id(self, audit_id: uuid.UUID) -> Optional[AuditRunModel]:
        stmt = (
            select(AuditRunModel)
            .options(joinedload(AuditRunModel.feedback))
            .where(AuditRunModel.id == audit_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_audits(
        self,
        project_id: Optional[uuid.UUID] = None,
        label: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[AuditRunModel], int]:
        stmt = select(AuditRunModel)

        if project_id:
            stmt = stmt.where(AuditRunModel.project_id == project_id)
        if label:
            stmt = stmt.where(AuditRunModel.label == label.lower().strip())
        if status:
            stmt = stmt.where(AuditRunModel.status == status.upper().strip())

        # Count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.execute(count_stmt).scalar() or 0

        # Pagination and order
        offset = (page - 1) * page_size
        stmt = (
            stmt.options(joinedload(AuditRunModel.feedback))
            .order_by(desc(AuditRunModel.created_at))
            .offset(offset)
            .limit(page_size)
        )

        items = self.db.execute(stmt).unique().scalars().all()
        return items, total

    def create_or_update_feedback(
        self,
        audit_id: uuid.UUID,
        feedback_label: str,
        corrected_label: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> AuditFeedbackModel:
        audit = self.get_by_id(audit_id)
        if not audit:
            raise ValueError(f"Audit run {audit_id} not found")

        stmt = select(AuditFeedbackModel).where(AuditFeedbackModel.audit_run_id == audit_id)
        feedback = self.db.execute(stmt).scalar_one_or_none()

        if feedback:
            feedback.feedback_label = feedback_label
            feedback.corrected_label = corrected_label or feedback_label
            feedback.comment = comment
            feedback.updated_at = datetime.now(timezone.utc)
        else:
            feedback = AuditFeedbackModel(
                audit_run_id=audit_id,
                feedback_label=feedback_label,
                corrected_label=corrected_label or feedback_label,
                comment=comment,
            )
            self.db.add(feedback)

        self.db.commit()
        self.db.refresh(feedback)
        return feedback

    def get_feedback_for_audit(self, audit_id: uuid.UUID) -> Optional[AuditFeedbackModel]:
        stmt = (
            select(AuditFeedbackModel)
            .where(AuditFeedbackModel.audit_run_id == audit_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()
