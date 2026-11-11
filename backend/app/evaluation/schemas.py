# backend/app/evaluation/schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field


class EvaluationInput(BaseModel):
    context: str = Field(..., min_length=1, max_length=15000, description="Reference context")
    prompt: str = Field(..., min_length=1, max_length=2000, description="User question / prompt")
    response: str = Field(..., min_length=1, max_length=5000, description="AI-generated response")


class EvaluationBreakdown(BaseModel):
    """
    Detailed explainability metrics.
    Fields are Optional so that unavailable metrics are honestly represented as None
    instead of substituting deceptive default/placeholder values.
    """
    p_entailment: Optional[float] = Field(None, description="DeBERTa NLI Entailment probability")
    p_neutral: Optional[float] = Field(None, description="DeBERTa NLI Neutral probability")
    p_contradiction: Optional[float] = Field(None, description="DeBERTa NLI Contradiction probability")
    new_entity_count: Optional[int] = Field(None, description="Count of entities in response not found in context")
    new_entities: Optional[List[str]] = Field(None, description="List of novel entities extracted from response")
    entity_overlap_ratio: Optional[float] = Field(None, description="Overlap ratio between context and response entities")
    vistral_extrinsic_prob: Optional[float] = Field(None, description="Qwen/Vistral zero-shot extrinsic probability")
    active_guardrail: Optional[str] = Field(None, description="Triggered safety guardrail rule name, if any")


class EvaluationResult(BaseModel):
    label: str = Field(..., description="Verdict: 'no', 'intrinsic', or 'extrinsic'")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Prediction confidence score")
    breakdown: EvaluationBreakdown = Field(default_factory=EvaluationBreakdown)
    model_version: str = Field(default="vihallu-v2-hybrid")
