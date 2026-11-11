# backend/app/modules/batches/router.py
import csv
import io
import uuid
from typing import List, Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    Response,
    status
)
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.modules.audits.router import get_engine
from backend.app.modules.batches.service import BatchService
from backend.app.modules.batches.schemas import (
    BatchItemInput,
    BatchUploadResponse,
    BatchDetailResponse,
    BatchSummaryResponse
)

router = APIRouter(prefix="/batches", tags=["Batches"])


def get_batch_service(
    db: Session = Depends(get_db),
    engine: EvaluationEngine = Depends(get_engine)
) -> BatchService:
    return BatchService(db, engine)


@router.post("/upload", response_model=BatchUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_batch_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: Optional[uuid.UUID] = Form(None),
    service: BatchService = Depends(get_batch_service)
):
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    items: List[BatchItemInput] = []

    for row in reader:
        # Flexible column name matching
        context = row.get("context") or row.get("Context") or row.get("ngu_canh") or ""
        prompt = row.get("prompt") or row.get("Prompt") or row.get("cau_hoi") or ""
        response = row.get("response") or row.get("Response") or row.get("cau_tra_loi") or ""

        if context.strip() and prompt.strip() and response.strip():
            items.append(BatchItemInput(context=context, prompt=prompt, response=response))

    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File CSV không chứa dữ liệu hợp lệ (yêu cầu các cột: context, prompt, response)"
        )

    batch = service.create_batch(
        filename=file.filename or "batch_upload.csv",
        items=items,
        project_id=project_id
    )

    # Queue background processing
    background_tasks.add_task(service.process_batch_in_background, batch.id)

    return BatchUploadResponse(
        batch_id=batch.id,
        project_id=batch.project_id,
        filename=batch.filename,
        total_count=batch.total_count,
        status="PROCESSING",
        message=f"Đã tiếp nhận {len(items)} câu hỏi để thẩm định trong tiến trình nền."
    )


@router.get("/{batch_id}", response_model=BatchDetailResponse)
def get_batch_status(
    batch_id: uuid.UUID,
    service: BatchService = Depends(get_batch_service)
):
    detail = service.get_batch_detail(batch_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} không tồn tại"
        )
    return detail


@router.get("", response_model=List[BatchSummaryResponse])
def list_batches(
    project_id: Optional[uuid.UUID] = None,
    service: BatchService = Depends(get_batch_service)
):
    return service.list_batches(project_id)


@router.get("/{batch_id}/export")
def export_batch_csv(
    batch_id: uuid.UUID,
    service: BatchService = Depends(get_batch_service)
):
    try:
        csv_data = service.export_batch_csv(batch_id)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=viai_qa_batch_{batch_id}.csv"
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
