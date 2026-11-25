# machine-learning/pipelines/export_feedback.py
"""
export_feedback.py
Reviewer feedback (audit_feedback) -> labelled rows in the ViHallu format, for the next training round.

  DATABASE_URL=postgresql://... python machine-learning/pipelines/export_feedback.py

RAG audits export as one row with the chunks joined as context (the same columns audit_runs stores),
labelled with the reviewer's verdict for the whole answer.
Output: data/processed/feedback/feedback-export.csv
"""

import os
import sys
from typing import Optional

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:0] = [ROOT, os.path.join(ROOT, "applications", "api")]  # repo root and the `backend` package

OUT_PATH = "data/processed/feedback/feedback-export.csv"
LABELS = {"no", "intrinsic", "extrinsic"}
# Older UI builds stored these values
LEGACY = {"no_hallucination": "no"}


def true_label(feedback_label: str, corrected_label: Optional[str], model_label: Optional[str]) -> Optional[str]:
    label = (corrected_label or feedback_label or "").strip()
    if label.upper() == "CORRECT":
        label = model_label or ""
    label = LEGACY.get(label.lower(), label.lower())
    return label if label in LABELS else None


def export(session) -> pd.DataFrame:
    from sqlalchemy import select
    from backend.app.models.audit import AuditRunModel
    from backend.app.models.feedback import AuditFeedbackModel

    stmt = (
        select(AuditRunModel, AuditFeedbackModel)
        .join(AuditFeedbackModel, AuditFeedbackModel.audit_run_id == AuditRunModel.id)
        .where(AuditRunModel.status == "COMPLETED")
    )
    rows = []
    for audit, fb in session.execute(stmt).all():
        label = true_label(fb.feedback_label, fb.corrected_label, audit.label)
        if label is None:
            continue
        rows.append({
            "id": str(audit.id), "context": audit.context, "prompt": audit.prompt, "response": audit.response,
            "label": label, "model_label": audit.label, "is_rag": bool(audit.contexts),
            "comment": fb.comment or "", "reviewed_at": fb.updated_at.isoformat() if fb.updated_at else "",
        })
    return pd.DataFrame(rows, columns=["id", "context", "prompt", "response", "label", "model_label",
                                       "is_rag", "comment", "reviewed_at"])


def main():
    from backend.app.core.database import SessionLocal

    with SessionLocal() as session:
        df = export(session)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    flipped = (df.label != df.model_label).sum() if len(df) else 0
    print(f"[INFO] {len(df)} reviewed audits -> {OUT_PATH} ({flipped} where the reviewer overruled the model)")


if __name__ == "__main__":
    main()
