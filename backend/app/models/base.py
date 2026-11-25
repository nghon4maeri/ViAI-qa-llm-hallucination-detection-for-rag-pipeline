# backend/app/models/base.py
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, TypeDecorator, CHAR, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class GUID(TypeDecorator):
    """
    Platform-independent GUID type.
    Uses PostgreSQL's native UUID type when available, otherwise CHAR(36).
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


# Dialect-adaptive JSON/JSONB type
JSONType = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
