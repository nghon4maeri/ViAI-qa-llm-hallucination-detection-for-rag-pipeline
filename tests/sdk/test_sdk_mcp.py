# tests/api/test_sdk_mcp.py
"""SDK and MCP tools end to end against the real FastAPI app (MockEngine, in-memory DB)."""
import asyncio
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "client-sdk", "python"))
from viai_qa import ViaiQA, ViaiQAError  # noqa: E402

from backend.app.modules.batches.service import BatchService  # noqa: E402

CONTEXTS = ["Hà Nội là thủ đô của Việt Nam.", "Việt Nam nằm ở khu vực Đông Nam Á."]
Q = "Thủ đô Việt Nam là gì?"


@pytest.fixture
def sdk(client):
    return ViaiQA("http://testserver", api_key="test-key", session=client)


def test_sdk_guard_evaluate_feedback(sdk):
    assert sdk.guard(Q, CONTEXTS, "Thủ đô của Việt Nam là Hà Nội.")["action"] == "pass"
    # One chunk: MockEngine only knows a contradiction when the chunk mentions "Hà Nội"
    blocked = sdk.guard(Q, CONTEXTS[:1], "Thủ đô của Việt Nam là Paris.")
    assert blocked["action"] == "block"

    audit = sdk.evaluate(Q, CONTEXTS, "Thủ đô của Việt Nam là Hà Nội. Tổng thống Việt Nam sống ở đó.")
    assert audit["faithfulness"] == 0.5
    assert sdk.get_audit(audit["id"])["claims"] == audit["claims"]
    # CORRECT stores the audit's own label, so feedback is usable for retraining
    assert sdk.feedback(audit["id"], "CORRECT")["corrected_label"] == "extrinsic"


def test_sdk_raises_api_errors(sdk):
    with pytest.raises(ViaiQAError) as err:
        sdk.get_audit(str(uuid.uuid4()))
    assert err.value.status_code == 404


def test_sdk_dataset_upload(sdk, tmp_path):
    path = tmp_path / "eval.jsonl"
    path.write_text(json.dumps({"question": Q, "contexts": CONTEXTS, "answer": "Thủ đô của Việt Nam là Hà Nội."}, ensure_ascii=False), encoding="utf-8")
    batch = sdk.upload_dataset(str(path))
    assert batch["total_count"] == 1


@pytest.fixture
def mcp(sdk, monkeypatch):
    from viai_qa import mcp_server
    monkeypatch.setattr(mcp_server, "_client", sdk)
    return mcp_server


def test_mcp_tools_are_registered_with_schemas(mcp):
    tools = {t.name: t for t in asyncio.run(mcp.server.list_tools())}
    assert set(tools) == {"guard_rag_answer", "evaluate_rag_response", "get_audit", "deep_audit",
                          "evaluate_dataset", "list_failing_claims", "submit_feedback"}
    assert tools["get_audit"].annotations.read_only_hint is True
    assert "contexts" in tools["guard_rag_answer"].input_schema["properties"]


def test_mcp_call_tool_round_trip(mcp):
    result = asyncio.run(mcp.server.call_tool("guard_rag_answer", {
        "question": Q, "contexts": CONTEXTS, "answer": "Thủ đô của Việt Nam là Hà Nội. Tổng thống sống ở đó.",
    }))
    assert not result.is_error
    # MCP SDK 2.x wraps untyped dict results as {"result": ...}; the text content carries the same JSON
    out = result.structured_content["result"]
    assert out["action"] == "regenerate"
    assert out["failing_sentences"][0]["verdict"] == "extrinsic"
    assert json.loads(result.content[0].text) == out


def test_mcp_list_failing_and_feedback(mcp):
    bad = mcp.evaluate_rag_response(Q, CONTEXTS[:1], "Thủ đô của Việt Nam là Paris.")
    assert bad["sentences"][0] == {"sentence": "Thủ đô của Việt Nam là Paris.", "verdict": "intrinsic", "confidence": 0.98, "source": 1}

    failing = mcp.list_failing_claims(limit=5)
    assert failing[0]["audit_id"] == bad["audit_id"]
    assert mcp.submit_feedback(bad["audit_id"], "no")["saved_label"] == "no"
    with pytest.raises(ValueError):
        mcp.submit_feedback(bad["audit_id"], "maybe")


def test_mcp_evaluate_dataset_waits_for_batch(mcp, sdk, db_session, test_mock_engine, tmp_path, monkeypatch):
    path = tmp_path / "eval.jsonl"
    path.write_text(json.dumps({"question": Q, "contexts": CONTEXTS[:1], "answer": "Thủ đô của Việt Nam là Paris."}, ensure_ascii=False), encoding="utf-8")
    real_get_batch = sdk.get_batch

    def get_batch(batch_id):
        # TestClient does not run the background worker against the test DB; run it on first poll
        BatchService(db_session, test_mock_engine).process_batch_in_background(uuid.UUID(batch_id), session=db_session)
        return real_get_batch(batch_id)

    monkeypatch.setattr(sdk, "get_batch", get_batch)
    out = mcp.evaluate_dataset(str(path))
    assert out["status"] == "COMPLETED"
    assert out["failing_items"][0]["verdict"] == "intrinsic"
