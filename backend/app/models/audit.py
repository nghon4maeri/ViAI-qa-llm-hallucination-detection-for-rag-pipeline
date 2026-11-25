# backend/app/models/audit.py
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from sqlalchemy import String, Text, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, GUID, JSONType, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.project import ProjectModel
    from backend.app.models.feedback import AuditFeedbackModel
    from backend.app.models.batch import AuditBatchModel


class AuditRunModel(Base, TimestampMixin):
    __tablename__ = "audit_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    context: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)

    label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROCESSING")

    breakdown: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)

    # RAG audits only: retrieved chunks, per-claim verdicts, share of supported claims
    contexts: Mapped[Optional[List[str]]] = mapped_column(JSONType, nullable=True)
    claims: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONType, nullable=True)
    faithfulness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, default="vihallu-v2-hybrid")

    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["ProjectModel"] = relationship("ProjectModel", back_populates="audits")
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(),
        ForeignKey("audit_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    batch: Mapped[Optional["AuditBatchModel"]] = relationship(
        "AuditBatchModel",
        back_populates="audits"
    )
    feedback: Mapped[Optional["AuditFeedbackModel"]] = relationship(
        "AuditFeedbackModel",
        uselist=False,
        back_populates="audit",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_audit_runs_project_created", "project_id", "created_at"),
        Index("ix_audit_runs_label", "label"),
        Index("ix_audit_runs_status", "status"),
    )
