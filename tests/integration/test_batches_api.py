import io
import uuid
import pytest
from starlette.testclient import TestClient
from backend.app.modules.batches.service import BatchService


def test_batch_upload_and_process(client: TestClient, db_session, test_mock_engine):
    csv_content = (
        "context,prompt,response\n"
        "Mặt trời mọc ở hướng đông.,Mặt trời mọc ở đâu?,Mặt trời mọc ở hướng đông.\n"
        "Hà Nội là thủ đô của Việt Nam.,Thủ đô Việt Nam là gì?,Paris là thủ đô Việt Nam.\n"
    )

    files = {
        "file": ("test_batch.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
    }

    # 1. Upload Batch CSV
    response = client.post("/api/v1/batches/upload", files=files)
    assert response.status_code == 201
    data = response.json()
    assert "batch_id" in data
    assert data["total_count"] == 2
    batch_id = data["batch_id"]

    # 2. Synchronously trigger process worker
    service = BatchService(db_session, test_mock_engine)
    service.process_batch_in_background(uuid.UUID(batch_id), session=db_session)

    # 3. Check Batch Status & Detail
    detail_res = client.get(f"/api/v1/batches/{batch_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["status"] == "COMPLETED"
    assert detail["completed_count"] == 2
    assert len(detail["items"]) == 2
    assert any(item["label"] == "intrinsic" for item in detail["items"])
    assert detail["hallucination_count"] >= 1

    # 4. Check CSV Export
    export_res = client.get(f"/api/v1/batches/{batch_id}/export")
    assert export_res.status_code == 200
    assert "text/csv" in export_res.headers["content-type"]
    exported_text = export_res.text
    assert "Mặt trời mọc ở hướng đông" in exported_text
    assert "intrinsic" in exported_text

    # 5. List batches
    list_res = client.get("/api/v1/batches")
    assert list_res.status_code == 200
    assert any(b["id"] == batch_id for b in list_res.json())


def test_batch_upload_empty_csv(client: TestClient):
    csv_content = "context,prompt,response\n"
    files = {
        "file": ("empty.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
    }
    response = client.post("/api/v1/batches/upload", files=files)
    assert response.status_code == 400
