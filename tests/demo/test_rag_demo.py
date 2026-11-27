# tests/demo/test_rag_demo.py
"""Medical RAG demo: retrieval, passage store, Claude request shape, and the guard loop against the real API."""
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from rag_demo.chat import FALLBACK, GuardedRagChat
from rag_demo.generator import ClaudeGenerator
from rag_demo.retriever import TfidfRetriever
from rag_demo.store import engine_from_env, ingest_vimedaqa, load_passages
from viai_qa import ViaiQA

CORPUS = [
    "Hà Nội là thủ đô của Việt Nam.",
    "Paracetamol hạ sốt cho người lớn dùng liều 500mg đến 1000mg mỗi lần.",
    "Vitamin D3 Aquadetrim nên được bảo quản ở nơi khô ráo, thoáng mát.",
]


def passages(texts):
    return [NS(text=t, title="", source_url="") for t in texts]


def test_retriever_ranks_the_matching_passage_first():
    hits = TfidfRetriever(passages(CORPUS)).search("Bảo quản vitamin D3 Aquadetrim thế nào?", k=2)
    assert hits[0].text == CORPUS[2]
    assert hits[0].score > hits[1].score


def test_retriever_needs_passages():
    with pytest.raises(ValueError):
        TfidfRetriever([])


def test_ingest_is_idempotent(tmp_path):
    p = tmp_path / "vimedaqa-test.parquet"
    pd.DataFrame([{"context": c, "title": f"t{i}", "topic": 2, "article_url": f"u{i}", "question": "q", "answer": "a"}
                  for i, c in enumerate(CORPUS + CORPUS[:1])]).to_parquet(p)
    engine = engine_from_env(f"sqlite:///{tmp_path / 'rag.db'}")
    assert ingest_vimedaqa(engine, [str(p)]) == 3
    assert ingest_vimedaqa(engine, [str(p)]) == 0
    assert [x.text for x in load_passages(engine)] == CORPUS


class FakeClaude:
    """Scripted messages.create; records each request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        a = self.answers.pop(0)
        if a is None:
            return NS(stop_reason="refusal", content=[])
        return NS(stop_reason="end_turn", content=[NS(type="thinking", thinking=""), NS(type="text", text=a)])


@pytest.fixture
def chat_factory(client):
    def make(*answers):
        claude = FakeClaude(*answers)
        chat = GuardedRagChat(TfidfRetriever(passages(CORPUS)), ClaudeGenerator(client=claude),
                              ViaiQA("http://testserver", session=client), k=1)
        return chat, claude
    return make


def test_grounded_answer_passes_first_time(chat_factory):
    chat, claude = chat_factory("Thủ đô của Việt Nam là Hà Nội.")
    out = chat.ask("Thủ đô Việt Nam là gì?")
    assert out["action"] == "pass" and out["answer"] == "Thủ đô của Việt Nam là Hà Nội."
    assert len(out["attempts"]) == 1 and out["attempts"][0]["audit_id"]
    req = claude.calls[0]
    assert req["model"] == "claude-haiku-5-5" and req["output_config"] == {"effort": "low"}
    assert "fallbacks" not in req and "<documents>" in req["messages"][0]["content"]


def test_unsupported_sentence_triggers_one_guided_retry(chat_factory):
    chat, claude = chat_factory("Thủ đô của Việt Nam là Hà Nội. Tổng thống Việt Nam sống ở đó.",
                                "Thủ đô của Việt Nam là Hà Nội.")
    out = chat.ask("Thủ đô Việt Nam là gì?")
    assert [a["action"] for a in out["attempts"]] == ["regenerate", "pass"]
    assert out["answer"] == "Thủ đô của Việt Nam là Hà Nội."
    retry = claude.calls[1]["messages"]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]  # append-only history
    assert "Tổng thống Việt Nam sống ở đó." in retry[-1]["content"]


def test_contradiction_is_blocked_without_retry(chat_factory):
    chat, claude = chat_factory("Thủ đô của Việt Nam là Paris.")
    out = chat.ask("Thủ đô Việt Nam là gì?")
    assert out["action"] == "block" and out["answer"] == FALLBACK
    assert len(claude.calls) == 1


def test_refusal_falls_back(chat_factory):
    chat, _ = chat_factory(None)
    out = chat.ask("Thủ đô Việt Nam là gì?")
    assert out["action"] == "refused" and out["answer"] == FALLBACK
