# backend/app/modules/api_keys/router.py
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.api_key import ApiKeyModel
from backend.app.modules.api_keys.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeySummaryResponse,
    ApiKeyListResponse
)
from backend.app.modules.api_keys.service import ApiKeyService
from backend.app.modules.api_keys.dependencies import require_api_key

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    request: ApiKeyCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Generate a new API key.
    IMPORTANT: The full secret `raw_key` is displayed ONLY ONCE in the response.
    Store it securely; it cannot be recovered afterwards.
    """
    try:
        api_key, raw_key = ApiKeyService.create_api_key(
            db=db,
            name=request.name,
            project_id=request.project_id
        )
        return ApiKeyCreatedResponse(
            id=api_key.id,
            name=api_key.name,
            key_prefix=api_key.key_prefix,
            raw_key=raw_key,
            project_id=api_key.project_id,
            is_active=api_key.is_active,
            created_at=api_key.created_at
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(val_err)
        )


@router.get("", response_model=List[ApiKeySummaryResponse])
def list_api_keys(
    project_id: Optional[uuid.UUID] = Query(None, description="Filter by project ID"),
    include_revoked: bool = Query(False, description="Include revoked/inactive keys"),
    db: Session = Depends(get_db)
):
    """
    List registered API keys. Secret hashes are strictly excluded; only prefix is visible.
    """
    keys = ApiKeyService.list_api_keys(
        db=db,
        project_id=project_id,
        include_revoked=include_revoked
    )
    return keys


@router.get("/me", response_model=ApiKeySummaryResponse)
def get_caller_identity(
    caller_key: ApiKeyModel = Depends(require_api_key)
):
    """
    Check identity and validity of the current API Key header.
    """
    return caller_key


@router.delete("/{key_id}", status_code=status.HTTP_200_OK)
def revoke_api_key(
    key_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Revoke an active API key immediately.
    """
    revoked = ApiKeyService.revoke_api_key(db=db, key_id=key_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API Key '{key_id}' not found."
        )
    return {
        "message": "API Key revoked successfully",
        "id": str(revoked.id),
        "key_prefix": revoked.key_prefix,
        "is_active": revoked.is_active,
        "revoked_at": revoked.revoked_at.isoformat() if revoked.revoked_at else None
    }
