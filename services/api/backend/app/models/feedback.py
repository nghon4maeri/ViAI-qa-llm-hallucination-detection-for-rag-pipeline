# services/api/backend/app/models/feedback.py
import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, GUID, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.audit import AuditRunModel


class AuditFeedbackModel(Base, TimestampMixin):
    __tablename__ = "audit_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4
    )
    audit_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("audit_runs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True
    )

    feedback_label: Mapped[str] = mapped_column(String(30), nullable=False)
    corrected_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    audit: Mapped["AuditRunModel"] = relationship("AuditRunModel", back_populates="feedback")
