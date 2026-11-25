# services/api/backend/app/models/project.py
import uuid
from datetime import datetime, timezone
from typing import List, TYPE_CHECKING
from sqlalchemy import String, Text, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, GUID, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.audit import AuditRunModel
    from backend.app.models.api_key import ApiKeyModel


class ProjectModel(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    audits: Mapped[List["AuditRunModel"]] = relationship(
        "AuditRunModel",
        back_populates="project",
        cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["ApiKeyModel"]] = relationship(
        "ApiKeyModel",
        back_populates="project",
        cascade="all, delete-orphan"
    )
