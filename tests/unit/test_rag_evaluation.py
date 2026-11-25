# tests/unit/test_rag_evaluation.py
import pytest
from pydantic import ValidationError

from backend.app.evaluation.adapters.mock_engine import MockEngine
from backend.app.evaluation.rag import evaluate_rag, split_claims
from backend.app.evaluation.schemas import RagEvaluationInput

CONTEXTS = ["Hà Nội là thủ đô của Việt Nam.", "Việt Nam nằm ở khu vực Đông Nam Á."]


def test_split_claims_on_sentence_punctuation_and_newlines():
    assert split_claims("Câu một. Câu hai!\nCâu ba? ") == ["Câu một.", "Câu hai!", "Câu ba?"]
    assert split_claims("Không có dấu câu") == ["Không có dấu câu"]


def test_all_claims_supported():
    res = evaluate_rag(MockEngine(), RagEvaluationInput(
        question="Thủ đô Việt Nam là gì?",
        contexts=CONTEXTS,
        answer="Thủ đô của Việt Nam là Hà Nội. Việt Nam nằm ở Đông Nam Á.",
    ))
    assert res.label == "no"
    assert res.faithfulness == 1.0
    assert len(res.claims) == 2


def test_one_unsupported_claim_lowers_faithfulness():
    res = evaluate_rag(MockEngine(), RagEvaluationInput(
        question="Thủ đô Việt Nam là gì?",
        contexts=CONTEXTS,
        answer="Thủ đô của Việt Nam là Hà Nội. Tổng thống Việt Nam sống ở đó.",
    ))
    assert res.label == "extrinsic"
    assert res.faithfulness == 0.5
    assert [c.label for c in res.claims] == ["no", "extrinsic"]


def test_intrinsic_outranks_extrinsic_in_overall_label():
    res = evaluate_rag(MockEngine(), RagEvaluationInput(
        question="Thủ đô Việt Nam là gì?",
        contexts=[CONTEXTS[0]],
        answer="Thủ đô của Việt Nam là Paris. Tổng thống sống ở đó.",
    ))
    assert res.label == "intrinsic"
    assert res.faithfulness == 0.0


def test_blank_contexts_rejected():
    with pytest.raises(ValidationError):
        RagEvaluationInput(question="q", contexts=["  ", ""], answer="a")


def test_rag_audit_endpoint_persists_claims(client):
    res = client.post("/api/v1/audits/rag", json={
        "question": "Thủ đô Việt Nam là gì?",
        "contexts": CONTEXTS,
        "answer": "Thủ đô của Việt Nam là Hà Nội. Tổng thống Việt Nam sống ở đó.",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "COMPLETED"
    assert data["label"] == "extrinsic"
    assert data["faithfulness"] == 0.5
    assert data["contexts"] == CONTEXTS
    assert data["claims"][1]["text"] == "Tổng thống Việt Nam sống ở đó."

    detail = client.get(f"/api/v1/audits/{data['id']}").json()
    assert detail["claims"] == data["claims"]
    # RAG audits show up in the existing history list
    listed = client.get("/api/v1/audits").json()["items"]
    assert any(i["id"] == data["id"] and i["faithfulness"] == 0.5 for i in listed)
