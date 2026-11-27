import uuid
import pytest
from starlette.testclient import TestClient


def test_submit_and_get_feedback(client: TestClient):
    # 1. Create an audit first
    audit_payload = {
        "context": "Mặt trời mọc ở hướng đông và lặn ở hướng tây.",
        "prompt": "Mặt trời mọc ở hướng nào?",
        "response": "Mặt trời mọc ở hướng đông.",
    }
    create_res = client.post("/api/v1/audits", json=audit_payload)
    assert create_res.status_code == 201
    audit_id = create_res.json()["id"]

    # 2. Submit human feedback
    feedback_payload = {
        "feedback_label": "CORRECT",
        "corrected_label": "no_hallucination",
        "comment": "Mô hình nhận định chính xác.",
    }
    fb_res = client.post(f"/api/v1/audits/{audit_id}/feedback", json=feedback_payload)
    assert fb_res.status_code == 201
    fb_data = fb_res.json()
    assert fb_data["audit_run_id"] == audit_id
    assert fb_data["feedback_label"] == "CORRECT"
    assert fb_data["corrected_label"] == "no_hallucination"
    assert fb_data["comment"] == "Mô hình nhận định chính xác."
    assert "id" in fb_data

    # 3. Retrieve feedback
    get_res = client.get(f"/api/v1/audits/{audit_id}/feedback")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == fb_data["id"]

    # 4. Check audit detail contains feedback object
    detail_res = client.get(f"/api/v1/audits/{audit_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["feedback"] is not None
    assert detail_res.json()["feedback"]["feedback_label"] == "CORRECT"


def test_submit_feedback_empty_label(client: TestClient):
    audit_res = client.post(
        "/api/v1/audits",
        json={"context": "C", "prompt": "P", "response": "R"},
    )
    audit_id = audit_res.json()["id"]

    fb_res = client.post(
        f"/api/v1/audits/{audit_id}/feedback",
        json={"feedback_label": "   "},
    )
    assert fb_res.status_code == 422


def test_submit_feedback_not_found(client: TestClient):
    fake_id = str(uuid.uuid4())
    fb_res = client.post(
        f"/api/v1/audits/{fake_id}/feedback",
        json={"feedback_label": "INCORRECT"},
    )
    assert fb_res.status_code == 404
