# backend/app/modules/audits/schemas.py
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from backend.app.evaluation.schemas import EvaluationBreakdown


class AuditCreateRequest(BaseModel):
    project_id: Optional[uuid.UUID] = Field(None, description="Target project ID; defaults to default workspace if omitted")
    context: str = Field(..., min_length=1, max_length=15000, description="Reference factual text")
    prompt: str = Field(..., min_length=1, max_length=2000, description="Question or prompt sent to LLM")
    response: str = Field(..., min_length=1, max_length=5000, description="AI-generated response to audit")


class FeedbackCreateRequest(BaseModel):
    feedback_label: str = Field(..., description="User rating or label: CORRECT, INCORRECT, no_hallucination, intrinsic, extrinsic")
    corrected_label: Optional[str] = Field(None, description="Optional corrected label")
    comment: Optional[str] = Field(None, max_length=1000, description="Optional annotation feedback")

    @field_validator("feedback_label")
    @classmethod
    def validate_feedback_label(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("feedback_label cannot be empty")
        return clean


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    audit_run_id: uuid.UUID
    feedback_label: str
    corrected_label: Optional[str] = None
    comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    label: Optional[str] = None
    confidence: Optional[float] = None
    breakdown: Optional[EvaluationBreakdown] = None
    context: str
    prompt: str
    response: str
    model_version: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[float] = None
    trace_id: Optional[str] = None
    feedback: Optional[FeedbackResponse] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AuditSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    label: Optional[str] = None
    confidence: Optional[float] = None
    prompt: str
    response: str
    has_feedback: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class AuditListResponse(BaseModel):
    items: List[AuditSummary]
    total: int
    page: int
    page_size: int
    total_pages: int
