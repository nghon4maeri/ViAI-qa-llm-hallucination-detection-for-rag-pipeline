# backend/app/modules/api_keys/dependencies.py
from typing import Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.api_key import ApiKeyModel
from backend.app.modules.api_keys.service import ApiKeyService

api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_api_key(
    api_key_header: Optional[str] = Security(api_key_header_scheme),
    bearer_token: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: Session = Depends(get_db)
) -> Optional[ApiKeyModel]:
    """
    Extracts and verifies API Key from either 'X-API-Key' or 'Authorization: Bearer <key>'.
    Returns ApiKeyModel if valid, None if not provided or invalid.
    """
    raw_key = None
    if api_key_header:
        raw_key = api_key_header.strip()
    elif bearer_token and bearer_token.credentials:
        raw_key = bearer_token.credentials.strip()

    if not raw_key:
        return None

    return ApiKeyService.verify_api_key(db, raw_key)


def require_api_key(
    key: Optional[ApiKeyModel] = Depends(get_current_api_key)
) -> ApiKeyModel:
    """
    Dependency that enforces valid API key authentication.
    Raises 401 Unauthorized if invalid or absent.
    """
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key. Provide via 'X-API-Key' header or 'Authorization: Bearer <key>'."
        )
    return key
