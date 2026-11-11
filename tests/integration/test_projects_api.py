import pytest
from starlette.testclient import TestClient


def test_list_projects(client: TestClient):
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(p["slug"] == "default-workspace" for p in data)


def test_create_project(client: TestClient):
    payload = {
        "name": "E-Commerce QA Project",
        "description": "Evaluating customer support AI answers",
    }
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "E-Commerce QA Project"
    assert data["slug"] == "e-commerce-qa-project"
    assert "id" in data


def test_create_duplicate_project_disambiguates_slug(client: TestClient):
    payload = {
        "name": "Unique QA Project",
    }
    res1 = client.post("/api/v1/projects", json=payload)
    assert res1.status_code == 201
    assert res1.json()["slug"] == "unique-qa-project"

    res2 = client.post("/api/v1/projects", json=payload)
    assert res2.status_code == 201
    assert res2.json()["slug"] == "unique-qa-project-1"
