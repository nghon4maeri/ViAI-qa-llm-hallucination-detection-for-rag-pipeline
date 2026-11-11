# backend/app/modules/api_keys/schemas.py
import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Display name / label for the API Key")
    project_id: Optional[uuid.UUID] = Field(None, description="Project ID to bind this key to. Defaults to default project.")


class ApiKeyCreatedResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    raw_key: str = Field(..., description="Full secret API key. Displayed ONLY ONCE upon creation.")
    project_id: uuid.UUID
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeySummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    project_id: uuid.UUID
    is_active: bool
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeyListResponse(BaseModel):
    data: List[ApiKeySummaryResponse]
    total: int
