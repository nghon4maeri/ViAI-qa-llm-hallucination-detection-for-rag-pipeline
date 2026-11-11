# backend/app/modules/projects/schemas.py
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Project display name")
    description: Optional[str] = Field(None, max_length=500, description="Project purpose or model description")


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
