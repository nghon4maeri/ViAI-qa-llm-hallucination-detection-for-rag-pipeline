# tests/integration/test_audits_api.py
import uuid


def test_create_audit_endpoint_success(client):
    payload = {
        "context": "Hà Nội là thủ đô của Việt Nam từ năm 1945.",
        "prompt": "Thủ đô của Việt Nam là gì?",
        "response": "Thủ đô của Việt Nam là Paris."
    }
    res = client.post("/api/v1/audits", json=payload)
    assert res.status_code == 201

    data = res.json()
    assert "id" in data
    assert data["status"] == "COMPLETED"
    assert data["label"] == "intrinsic"
    assert data["confidence"] > 0.9
    assert data["breakdown"] is not None
    assert data["breakdown"]["p_contradiction"] > 0.9
    assert "latency_ms" in data


def test_create_audit_endpoint_validation_error(client):
    # Missing required prompt and response
    res = client.post("/api/v1/audits", json={"context": "Hello"})
    assert res.status_code == 422


def test_create_audit_empty_payload(client):
    res = client.post("/api/v1/audits", json={"context": "", "prompt": "", "response": ""})
    assert res.status_code == 422


def test_list_audits_endpoint_pagination(client):
    # Insert 2 audits
    for resp in ["Thủ đô của Việt Nam là Hà Nội.", "Thủ đô của Việt Nam là Paris."]:
        client.post("/api/v1/audits", json={
            "context": "Hà Nội là thủ đô của Việt Nam.",
            "prompt": "Thủ đô là gì?",
            "response": resp
        })

    res = client.get("/api/v1/audits?page=1&page_size=10")
    assert res.status_code == 200

    data = res.json()
    assert "items" in data
    assert data["total"] >= 2
    assert len(data["items"]) >= 2
    assert "id" in data["items"][0]
    assert "status" in data["items"][0]


def test_get_audit_detail_endpoint(client):
    create_res = client.post("/api/v1/audits", json={
        "context": "Mặt Trời mọc ở hướng Đông.",
        "prompt": "Mặt Trời mọc ở đâu?",
        "response": "Mặt Trời mọc ở hướng Đông."
    })
    audit_id = create_res.json()["id"]

    res = client.get(f"/api/v1/audits/{audit_id}")
    assert res.status_code == 200

    data = res.json()
    assert data["id"] == audit_id
    assert data["label"] == "no"
    assert data["context"] == "Mặt Trời mọc ở hướng Đông."


def test_get_audit_detail_not_found(client):
    random_uuid = str(uuid.uuid4())
    res = client.get(f"/api/v1/audits/{random_uuid}")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_projects_crud_endpoint(client):
    # List projects (auto-creates default project)
    list_res = client.get("/api/v1/projects")
    assert list_res.status_code == 200
    projects = list_res.json()
    assert len(projects) >= 1
    assert any(p["is_default"] for p in projects)

    # Create new project
    create_res = client.post("/api/v1/projects", json={
        "name": "Customer Support QA",
        "description": "Project for auditing banking bot"
    })
    assert create_res.status_code == 201
    new_project = create_res.json()
    assert new_project["name"] == "Customer Support QA"
    assert new_project["slug"] == "customer-support-qa"
    assert new_project["is_default"] is False


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "database" in data
