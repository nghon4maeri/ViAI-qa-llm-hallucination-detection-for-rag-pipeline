# backend/app/modules/api_keys/service.py
import secrets
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.logging import logger
from backend.app.models.api_key import ApiKeyModel
from backend.app.models.project import ProjectModel
from backend.app.modules.projects.router import ensure_default_project


def generate_raw_api_key() -> str:
    """Generates a secure API key with standard prefix."""
    token = secrets.token_hex(20)  # 40 hex chars
    return f"viai_live_{token}"


def hash_api_key(raw_key: str) -> str:
    """Computes SHA-256 hash of raw API key for secure storage and lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class ApiKeyService:
    @staticmethod
    def create_api_key(
        db: Session,
        name: str,
        project_id: Optional[uuid.UUID] = None
    ) -> Tuple[ApiKeyModel, str]:
        """
        Creates a new API key.
        Returns tuple of (ApiKeyModel, raw_secret_key).
        """
        if not project_id:
            default_proj = ensure_default_project(db)
            project_id = default_proj.id
        else:
            # Verify project exists
            project = db.get(ProjectModel, project_id)
            if not project:
                raise ValueError(f"Project with ID '{project_id}' does not exist.")

        raw_key = generate_raw_api_key()
        key_prefix = raw_key[:16]  # e.g. 'viai_live_9a8b7c' (16 chars)
        key_hash = hash_api_key(raw_key)

        api_key = ApiKeyModel(
            project_id=project_id,
            name=name.strip(),
            key_prefix=key_prefix,
            key_hash=key_hash,
            is_active=True
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)

        logger.info(f"API key created: prefix={key_prefix}, name='{name}', project_id={project_id}")
        return api_key, raw_key

    @staticmethod
    def list_api_keys(
        db: Session,
        project_id: Optional[uuid.UUID] = None,
        include_revoked: bool = False
    ) -> List[ApiKeyModel]:
        """Lists API keys with masked representation."""
        stmt = select(ApiKeyModel)
        if project_id:
            stmt = stmt.where(ApiKeyModel.project_id == project_id)
        if not include_revoked:
            stmt = stmt.where(ApiKeyModel.is_active == True)
        stmt = stmt.order_by(ApiKeyModel.created_at.desc())

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_api_key(db: Session, key_id: uuid.UUID) -> Optional[ApiKeyModel]:
        """Gets API key by UUID."""
        return db.get(ApiKeyModel, key_id)

    @staticmethod
    def revoke_api_key(db: Session, key_id: uuid.UUID) -> Optional[ApiKeyModel]:
        """Revokes an API key, preventing any further use."""
        key = db.get(ApiKeyModel, key_id)
        if not key:
            return None

        key.is_active = False
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(key)
        logger.info(f"API key revoked: id={key_id}, prefix={key.key_prefix}")
        return key

    @staticmethod
    def verify_api_key(db: Session, raw_key: str) -> Optional[ApiKeyModel]:
        """
        Verifies a raw API key against stored SHA-256 hashes.
        Updates last_used_at on successful verification.
        Supports DEV_API_KEY in non-production environments.
        """
        if not raw_key:
            return None

        # Check for local development bypass key
        if settings.DEV_API_KEY and raw_key == settings.DEV_API_KEY:
            default_proj = ensure_default_project(db)
            now = datetime.now(timezone.utc)
            return ApiKeyModel(
                id=uuid.uuid4(),
                project_id=default_proj.id,
                name="Development Key",
                key_prefix=settings.DEV_API_KEY[:16],
                key_hash=hash_api_key(settings.DEV_API_KEY),
                is_active=True,
                created_at=now,
                last_used_at=now
            )

        hashed = hash_api_key(raw_key)
        stmt = select(ApiKeyModel).where(
            ApiKeyModel.key_hash == hashed,
            ApiKeyModel.is_active == True
        )
        key = db.execute(stmt).scalar_one_or_none()

        if key:
            key.last_used_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(key)
            return key

        return None
