# tests/api/test_rag_evaluation.py
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
    assert data["rag_metrics"]["context_utilization"] == 0.5
    assert len(data["rag_metrics"]["context_relevance"]) == 2

    detail = client.get(f"/api/v1/audits/{data['id']}").json()
    assert detail["claims"] == data["claims"]
    # RAG audits show up in the existing history list
    listed = client.get("/api/v1/audits").json()["items"]
    assert any(i["id"] == data["id"] and i["faithfulness"] == 0.5 for i in listed)


def test_context_utilization_counts_only_supporting_chunks():
    res = evaluate_rag(MockEngine(), RagEvaluationInput(
        question="Thủ đô Việt Nam là gì?",
        contexts=CONTEXTS,
        answer="Tổng thống Việt Nam sống ở Hà Nội.",
    ))
    # The only claim is unsupported, so no chunk was used
    assert res.metrics.context_utilization == 0.0


def test_context_recall_needs_ground_truth():
    payload = dict(question="Thủ đô Việt Nam là gì?", contexts=CONTEXTS, answer="Thủ đô của Việt Nam là Hà Nội.")
    assert evaluate_rag(MockEngine(), RagEvaluationInput(**payload)).metrics.context_recall is None

    res = evaluate_rag(MockEngine(), RagEvaluationInput(
        **payload, ground_truth="Hà Nội là thủ đô. Tổng thống ở Hà Nội."
    ))
    assert res.metrics.context_recall == 0.5


def test_relevance_uses_engine_embeddings():
    res = evaluate_rag(MockEngine(), RagEvaluationInput(
        question="thủ đô việt nam",
        contexts=["thủ đô việt nam là hà nội", "bóng đá ngoại hạng anh"],
        answer="thủ đô việt nam là hà nội",
    ))
    rel = res.metrics.context_relevance
    assert rel[0] > rel[1]
    assert res.metrics.answer_relevance > 0.5


def test_relevance_is_none_without_embeddings():
    class NoEmbed:
        def __init__(self):
            self._inner = MockEngine()

        def evaluate(self, payload):
            return self._inner.evaluate(payload)

    res = evaluate_rag(NoEmbed(), RagEvaluationInput(question="q", contexts=["c"], answer="a b c"))
    assert res.metrics.answer_relevance is None
    assert res.metrics.context_relevance is None


@pytest.mark.parametrize("answer, action", [
    ("Thủ đô của Việt Nam là Hà Nội.", "pass"),
    ("Thủ đô của Việt Nam là Hà Nội. Tổng thống Việt Nam sống ở đó.", "regenerate"),
    ("Thủ đô của Việt Nam là Paris. Tổng thống sống ở đó.", "block"),
])
def test_guard_endpoint_policy(client, answer, action):
    res = client.post("/api/v1/audits/rag/guard", json={
        "question": "Thủ đô Việt Nam là gì?", "contexts": [CONTEXTS[0]], "answer": answer,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == action
    assert all(c["label"] != "no" for c in data["failing_claims"])
    assert (len(data["failing_claims"]) == 0) == (action == "pass")
    # Every guard call leaves an audit for review
    assert client.get(f"/api/v1/audits/{data['audit_id']}").status_code == 200


def test_claim_chunk_grid_goes_to_the_engine_as_one_batch():
    """Batching engines get the whole claim x chunk grid (answer and reference claims) in one call."""
    from backend.app.evaluation.cache import evaluation_cache

    class BatchingMock(MockEngine):
        def __init__(self):
            super().__init__()
            self.batches = []

        def evaluate_batch(self, payloads):
            self.batches.append(len(payloads))
            return [self.evaluate(p) for p in payloads]

    payload = RagEvaluationInput(
        question="Thủ đô của Việt Nam là gì?",
        answer="Thủ đô là Hà Nội. Thủ đô là Paris. Hà Nội nằm ở miền Bắc.",
        contexts=["Hà Nội là thủ đô của Việt Nam.", "Hà Nội nằm ở miền Bắc."],
        ground_truth="Hà Nội là thủ đô.",
    )
    evaluation_cache.clear()
    sequential = evaluate_rag(MockEngine(), payload)
    evaluation_cache.clear()
    engine = BatchingMock()
    batched = evaluate_rag(engine, payload)

    assert engine.batches == [(3 + 1) * 2]           # 3 answer claims + 1 reference claim, 2 chunks each
    assert batched.model_dump() == sequential.model_dump()
    evaluate_rag(engine, payload)
    assert engine.batches == [8]                     # the second run is all cache hits
