import os
import csv
from pathlib import Path
import pytest
from starlette.testclient import TestClient


def test_monitoring_stats_returns_kpis(client: TestClient):
    # Ensure at least one audit run exists
    client.post(
        "/api/v1/audits",
        json={
            "context": "Thủ đô của Việt Nam là Hà Nội.",
            "prompt": "Thủ đô của Việt Nam là gì?",
            "response": "Thủ đô của Việt Nam là Hà Nội."
        }
    )

    response = client.get("/api/v1/monitoring/stats")
    assert response.status_code == 200
    data = response.json()

    assert "total_audits" in data
    assert data["total_audits"] >= 1
    assert "completed_audits" in data
    assert "hallucination_rate_percent" in data
    assert "label_breakdown" in data
    assert "cache" in data
    assert "hits" in data["cache"]
    assert "misses" in data["cache"]


def test_sync_drift_csv_generation(client: TestClient, tmp_path: Path):
    # Create an audit
    client.post(
        "/api/v1/audits",
        json={
            "context": "Sông Mê Kông chảy qua nhiều quốc gia Đông Nam Á.",
            "prompt": "Sông nào chảy qua Đông Nam Á?",
            "response": "Sông Mê Kông chảy qua nhiều nước Đông Nam Á."
        }
    )

    csv_file = tmp_path / "sync_test_predictions.csv"
    response = client.post(
        f"/api/v1/monitoring/sync-drift?output_path={csv_file}&limit=50"
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["records_synced"] >= 1
    assert os.path.exists(csv_file)

    # Validate CSV content
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ["id", "predict_label", "prob_extrinsic", "prob_no", "prob_intrinsic"]
        rows = list(reader)
        assert len(rows) >= 1
        # Check columns
        assert len(rows[0]) == 5
        assert rows[0][1] in ["no", "extrinsic", "intrinsic"]
        # Float check
        prob_ext = float(rows[0][2])
        prob_no = float(rows[0][3])
        prob_intr = float(rows[0][4])
        assert 0.0 <= prob_ext <= 1.0
        assert 0.0 <= prob_no <= 1.0
        assert 0.0 <= prob_intr <= 1.0


def test_prometheus_metrics_export(client: TestClient):
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "viai_evaluations_total" in text
    assert "viai_evaluation_duration_seconds" in text
