# backend/app/modules/monitoring/router.py
import os
import csv
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.logging import logger
from backend.app.core.metrics import update_hallucination_rate_metric
from backend.app.models.audit import AuditRunModel
from backend.app.models.feedback import AuditFeedbackModel
from backend.app.evaluation.cache import evaluation_cache

router = APIRouter(prefix="/monitoring", tags=["Monitoring & Observability"])

DEFAULT_PREDICTIONS_PATH = os.getenv("CURRENT_DATA_PATH", "predictions/current_predictions.csv")


@router.post("/sync-drift")
def sync_evidently_drift_data(
    limit: int = Query(1000, ge=1, le=10000, description="Max recent records to export"),
    output_path: Optional[str] = Query(None, description="Custom CSV file path"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Exports latest completed audit runs from the database to CSV for Evidently AI drift monitoring.
    Format adheres to: id, predict_label, prob_extrinsic, prob_no, prob_intrinsic.
    """
    target_path = output_path or DEFAULT_PREDICTIONS_PATH
    path_obj = Path(target_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    # Query latest completed audits
    stmt = (
        select(AuditRunModel)
        .where(AuditRunModel.status == "COMPLETED")
        .order_by(AuditRunModel.completed_at.desc())
        .limit(limit)
    )
    audits = list(db.execute(stmt).scalars().all())

    exported_count = 0
    with open(path_obj, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["id", "predict_label", "prob_extrinsic", "prob_no", "prob_intrinsic"])

        for audit in audits:
            label = (audit.label or "no").lower()
            conf = audit.confidence if audit.confidence is not None else 0.8
            rem = max(0.0, (1.0 - conf) / 2.0)

            if "extrinsic" in label:
                prob_ext = conf
                prob_no = rem
                prob_intr = rem
                pred_label = "extrinsic"
            elif "intrinsic" in label:
                prob_ext = rem
                prob_no = rem
                prob_intr = conf
                pred_label = "intrinsic"
            else:
                prob_ext = rem
                prob_no = conf
                prob_intr = rem
                pred_label = "no"

            writer.writerow([
                str(audit.id),
                pred_label,
                f"{prob_ext:.6f}",
                f"{prob_no:.6f}",
                f"{prob_intr:.6f}"
            ])
            exported_count += 1

    logger.info(f"Evidently drift dataset synced: {exported_count} records exported to '{target_path}'")
    return {
        "status": "success",
        "records_synced": exported_count,
        "file_path": str(target_path),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/stats")
def get_monitoring_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Returns real-time aggregated operational statistics and KPI metrics.
    """
    # 1. Total counts by status
    status_counts_stmt = select(AuditRunModel.status, func.count(AuditRunModel.id)).group_by(AuditRunModel.status)
    status_counts = dict(db.execute(status_counts_stmt).all())

    total_audits = sum(status_counts.values())
    completed_audits = status_counts.get("COMPLETED", 0)
    failed_audits = status_counts.get("FAILED", 0)
    processing_audits = status_counts.get("PROCESSING", 0)

    # 2. Breakdown by label
    label_counts_stmt = (
        select(AuditRunModel.label, func.count(AuditRunModel.id))
        .where(AuditRunModel.status == "COMPLETED")
        .group_by(AuditRunModel.label)
    )
    label_counts = {str(k or "unknown"): v for k, v in db.execute(label_counts_stmt).all()}

    hallucination_count = sum(
        count for lbl, count in label_counts.items()
        if "extrinsic" in lbl.lower() or "intrinsic" in lbl.lower()
    )

    hallucination_rate_percent = (
        round((hallucination_count / completed_audits) * 100.0, 2)
        if completed_audits > 0 else 0.0
    )

    # Update gauge in Prometheus
    update_hallucination_rate_metric(hallucination_rate_percent)

    # 3. User feedback breakdown
    fb_counts_stmt = select(AuditFeedbackModel.feedback_label, func.count(AuditFeedbackModel.id)).group_by(AuditFeedbackModel.feedback_label)
    feedback_counts = dict(db.execute(fb_counts_stmt).all())
    total_feedbacks = sum(feedback_counts.values())

    # 4. In-memory LRU Cache stats
    cache_metrics = evaluation_cache.stats()

    return {
        "total_audits": total_audits,
        "completed_audits": completed_audits,
        "failed_audits": failed_audits,
        "processing_audits": processing_audits,
        "hallucination_count": hallucination_count,
        "hallucination_rate_percent": hallucination_rate_percent,
        "label_breakdown": label_counts,
        "total_feedbacks": total_feedbacks,
        "feedback_breakdown": feedback_counts,
        "cache": cache_metrics,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
