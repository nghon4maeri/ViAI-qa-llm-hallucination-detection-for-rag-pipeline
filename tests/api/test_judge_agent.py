# tests/api/test_judge_agent.py
"""Judge agent loop against a scripted fake Claude client; no API calls, no cost."""
from types import SimpleNamespace as NS

import pytest

from backend.app.core.config import settings
from backend.app.evaluation import judge_agent
from backend.app.evaluation.adapters.mock_engine import MockEngine
from backend.app.evaluation.judge_agent import JudgeAgent, check_numbers, needs_judge
from backend.app.evaluation.rag import evaluate_rag
from backend.app.evaluation.schemas import RagEvaluationInput

PAYLOAD = RagEvaluationInput(
    question="Thủ đô Việt Nam là gì?",
    contexts=["Hà Nội là thủ đô của Việt Nam.", "Việt Nam nằm ở Đông Nam Á."],
    answer="Thủ đô của Việt Nam là Hà Nội. Tổng thống Việt Nam sống ở đó.",
)


def tool_use(id_, name, **input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def response(*blocks, stop="tool_use", model="claude-haiku-5-5"):
    return NS(content=list(blocks), stop_reason=stop, model=model, usage=NS(input_tokens=100, output_tokens=20))


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def tier1():
    return evaluate_rag(MockEngine(), PAYLOAD).claims


def test_only_doubtful_claims_are_sent_and_judge_can_overrule(tier1):
    # Tier 1: claim 0 grounded (confident), claim 1 extrinsic with a guardrail -> doubtful
    assert needs_judge(tier1)
    client = FakeClient(
        response(
            tool_use("t1", "detect_hallucination", claim=tier1[1].text, context_index=0),
            tool_use("t2", "check_numbers", claim=tier1[1].text, context_index=0),
        ),
        response(tool_use("t3", "submit_verdict", explanation="Câu 2 thực ra có nguồn",
                          claims=[{"index": 1, "label": "no", "reason": "Tài liệu [0] nêu rõ", "evidence_index": 0}])),
    )
    verdict = JudgeAgent(MockEngine(), client=client).run(PAYLOAD, tier1, only_doubtful=True)

    assert verdict.status == "completed"
    assert "<to_check>1</to_check>" in client.calls[0]["messages"][0]["content"]
    assert [c.agrees_with_tier1 for c in verdict.claims] == [True, False]
    assert (verdict.label, verdict.faithfulness) == ("no", 1.0)
    assert [t.name for t in verdict.tool_calls] == ["detect_hallucination", "check_numbers"]
    # Both tool results go back in one user message
    results = client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert verdict.input_tokens == 200


def test_cost_settings_reach_the_request(tier1):
    client = FakeClient(response(tool_use("t", "submit_verdict", explanation="ok", claims=[])))
    JudgeAgent(MockEngine(), client=client).run(PAYLOAD, tier1)
    call = client.calls[0]
    assert call["model"] == settings.JUDGE_MODEL == "claude-haiku-5-5"
    assert call["cache_control"] == {"type": "ephemeral"}
    assert "fallbacks" not in call  # Haiku 5.5 has no server-side fallback


def test_fallback_is_requested_for_models_that_support_it(tier1, monkeypatch):
    monkeypatch.setattr(settings, "JUDGE_MODEL", "claude-opus-5-5")
    client = FakeClient(response(tool_use("t", "submit_verdict", explanation="ok", claims=[])))
    JudgeAgent(MockEngine(), client=client).run(PAYLOAD, tier1)
    assert client.calls[0]["fallbacks"] == "default"
    assert client.calls[0]["betas"] == [judge_agent.FALLBACK_BETA]


def test_refusal_leaves_tier1_standing(tier1):
    client = FakeClient(response(stop="refusal"))
    verdict = JudgeAgent(MockEngine(), client=client).run(PAYLOAD, tier1)
    assert verdict.status == "refused" and verdict.label is None and verdict.claims == []


def test_bad_tool_input_is_returned_as_error_not_raised(tier1):
    client = FakeClient(
        response(tool_use("t1", "check_numbers", claim="x", context_index=9)),
        response(tool_use("t2", "submit_verdict", explanation="ok",
                          claims=[{"index": 1, "label": "extrinsic", "reason": "r", "evidence_index": None}])),
    )
    JudgeAgent(MockEngine(), client=client).run(PAYLOAD, tier1)
    result = client.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


def test_missing_verdict_for_a_checked_claim_is_incomplete(tier1):
    client = FakeClient(response(tool_use("t", "submit_verdict", explanation="ok", claims=[])))
    verdict = JudgeAgent(MockEngine(), client=client).run(PAYLOAD, tier1, only_doubtful=True)
    assert verdict.status == "incomplete"


def test_check_numbers_flags_changed_dose_and_ignores_names():
    out = check_numbers("Uống 6000mg Vitamin D3 mỗi ngày, cách 4 giờ", "Không quá 4000mg mỗi ngày, cách nhau 4 giờ")
    assert out["not_in_chunk"] == ["6000 mg"]
    assert "3" not in " ".join(out["claim_numbers"])


def test_judge_endpoint(client, monkeypatch):
    from backend.app.modules.audits import service as audit_service

    fake = FakeClient(response(tool_use("t", "submit_verdict", explanation="Đã kiểm tra",
                                        claims=[{"index": 1, "label": "extrinsic", "reason": "Không có trong tài liệu", "evidence_index": None}])))
    monkeypatch.setattr(audit_service, "JudgeAgent", lambda engine: JudgeAgent(engine, client=fake))

    rag = client.post("/api/v1/audits/rag", json=PAYLOAD.model_dump()).json()
    res = client.post(f"/api/v1/audits/{rag['id']}/judge?only_doubtful=true")
    assert res.status_code == 200
    assert res.json()["judge"]["status"] == "completed"
    assert client.get(f"/api/v1/audits/{rag['id']}").json()["judge"]["explanation"] == "Đã kiểm tra"

    single = client.post("/api/v1/audits", json={"context": "a b c", "prompt": "q", "response": "a"}).json()
    assert client.post(f"/api/v1/audits/{single['id']}/judge").status_code == 400
    assert client.post("/api/v1/audits/00000000-0000-0000-0000-000000000000/judge").status_code == 404
