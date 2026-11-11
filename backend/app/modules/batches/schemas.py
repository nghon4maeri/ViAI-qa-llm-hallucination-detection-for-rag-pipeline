# backend/app/modules/batches/schemas.py
import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class BatchItemInput(BaseModel):
    context: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    response: str = Field(..., min_length=1)


class BatchUploadResponse(BaseModel):
    batch_id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    total_count: int
    status: str
    message: str


class BatchItemResult(BaseModel):
    id: uuid.UUID
    prompt: str
    response: str
    label: Optional[str] = None
    confidence: Optional[float] = None
    status: str
    latency_ms: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BatchDetailResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    hallucination_count: int
    hallucination_rate: float
    items: List[BatchItemResult] = []
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BatchSummaryResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    status: str
    total_count: int
    completed_count: int
    hallucination_count: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
