import pytest
from starlette.testclient import TestClient


def test_create_api_key_success(client: TestClient):
    response = client.post("/api/v1/api-keys", json={"name": "Integration Test Key"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Integration Test Key"
    assert "raw_key" in data
    assert data["raw_key"].startswith("viai_live_")
    assert data["key_prefix"] == data["raw_key"][:16]
    assert data["is_active"] is True
    assert "id" in data
    assert "project_id" in data


def test_list_api_keys(client: TestClient):
    # Ensure at least one key exists
    create_res = client.post("/api/v1/api-keys", json={"name": "Listing Test Key"})
    assert create_res.status_code == 201
    created_id = create_res.json()["id"]

    response = client.get("/api/v1/api-keys")
    assert response.status_code == 200
    keys = response.json()
    assert isinstance(keys, list)
    matching = [k for k in keys if k["id"] == created_id]
    assert len(matching) == 1
    # Check that secrets are NEVER leaked in list
    assert "raw_key" not in matching[0]
    assert "key_hash" not in matching[0]
    assert matching[0]["key_prefix"].startswith("viai_live_")


def test_api_key_authentication_and_revocation(client: TestClient):
    # 1. Create a key
    create_res = client.post("/api/v1/api-keys", json={"name": "Auth Test Key"})
    assert create_res.status_code == 201
    raw_key = create_res.json()["raw_key"]
    key_id = create_res.json()["id"]

    # 2. Authenticate with X-API-Key header
    res_header = client.get("/api/v1/api-keys/me", headers={"X-API-Key": raw_key})
    assert res_header.status_code == 200
    assert res_header.json()["id"] == key_id

    # 3. Authenticate with Bearer token
    res_bearer = client.get("/api/v1/api-keys/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert res_bearer.status_code == 200
    assert res_bearer.json()["id"] == key_id

    # 4. Attempt with invalid key -> 401
    res_invalid = client.get("/api/v1/api-keys/me", headers={"X-API-Key": "viai_live_invalidkey12345"})
    assert res_invalid.status_code == 401

    # 5. Revoke the key
    del_res = client.delete(f"/api/v1/api-keys/{key_id}")
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # 6. Using revoked key must now fail with 401
    res_revoked = client.get("/api/v1/api-keys/me", headers={"X-API-Key": raw_key})
    assert res_revoked.status_code == 401

    # 7. Check listing: excluded by default, included with include_revoked=true
    active_keys = client.get("/api/v1/api-keys").json()
    assert not any(k["id"] == key_id for k in active_keys)

    all_keys = client.get("/api/v1/api-keys?include_revoked=true").json()
    assert any(k["id"] == key_id and not k["is_active"] for k in all_keys)


def test_dev_key_bypass(client: TestClient):
    res_dev = client.get("/api/v1/api-keys/me", headers={"X-API-Key": "vihallu-dev-key-local"})
    assert res_dev.status_code == 200
    assert res_dev.json()["name"] == "Development Key"
