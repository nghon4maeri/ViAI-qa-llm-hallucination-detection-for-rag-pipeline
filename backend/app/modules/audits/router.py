# backend/app/modules/audits/router.py
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.config import settings
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.adapters.existing_pipeline import ExistingPipelineAdapter
from backend.app.evaluation.adapters.mock_engine import MockEngine
from backend.app.modules.audits.repository import AuditRepository
from backend.app.modules.audits.service import AuditService
from backend.app.modules.audits.schemas import (
    AuditCreateRequest,
    AuditResponse,
    AuditListResponse,
    FeedbackCreateRequest,
    FeedbackResponse,
)

router = APIRouter(prefix="/audits", tags=["Audits"])

_global_engine: Optional[EvaluationEngine] = None


def get_engine() -> EvaluationEngine:
    global _global_engine
    if _global_engine is None:
        if settings.DISABLE_MODEL:
            _global_engine = MockEngine()
        else:
            _global_engine = ExistingPipelineAdapter()
    return _global_engine


def get_audit_service(
    db: Session = Depends(get_db),
    engine: EvaluationEngine = Depends(get_engine)
) -> AuditService:
    repo = AuditRepository(db)
    return AuditService(repo, engine)


@router.post("", response_model=AuditResponse, status_code=status.HTTP_201_CREATED)
async def create_audit(
    request: AuditCreateRequest,
    req: Request,
    service: AuditService = Depends(get_audit_service)
):
    trace_id = getattr(req.state, "trace_id", None) if hasattr(req, "state") else None
    try:
        return await service.execute_audit(request, trace_id=trace_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audit evaluation failed: {str(exc)}"
        )


@router.get("", response_model=AuditListResponse)
def list_audits(
    project_id: Optional[uuid.UUID] = Query(None, description="Filter by project ID"),
    label: Optional[str] = Query(None, description="Filter by verdict: no, intrinsic, extrinsic"),
    status: Optional[str] = Query(None, description="Filter by status: PROCESSING, COMPLETED, FAILED"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    service: AuditService = Depends(get_audit_service)
):
    return service.list_audits(
        project_id=project_id,
        label=label,
        status=status,
        page=page,
        page_size=page_size
    )


@router.get("/{audit_id}", response_model=AuditResponse)
def get_audit_detail(
    audit_id: uuid.UUID,
    service: AuditService = Depends(get_audit_service)
):
    audit = service.get_audit(audit_id)
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{audit_id}' was not found"
        )
    return audit


@router.post("/{audit_id}/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    audit_id: uuid.UUID,
    request: FeedbackCreateRequest,
    service: AuditService = Depends(get_audit_service)
):
    try:
        return service.submit_feedback(audit_id, request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        )


@router.get("/{audit_id}/feedback", response_model=FeedbackResponse)
def get_feedback(
    audit_id: uuid.UUID,
    service: AuditService = Depends(get_audit_service)
):
    try:
        feedback = service.get_feedback(audit_id)
        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No feedback found for audit run '{audit_id}'"
            )
        return feedback
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        )
