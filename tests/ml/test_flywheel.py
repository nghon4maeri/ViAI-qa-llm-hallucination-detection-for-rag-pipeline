# tests/api/test_flywheel.py
"""Phase 4 data flywheel: LLM hard-split generator (fake Batch API) and feedback export."""
import importlib.util
import json
import os
from types import SimpleNamespace as NS

import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, f"ml/pipelines/{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = load("generate_hard_medical")
fb = load("export_feedback")


@pytest.fixture
def vimedaqa(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    pd.DataFrame([{
        "question_idx": f"q{i}", "question": f"Câu hỏi {i}?", "answer": f"Uống {i + 1} viên sau khi ăn.",
        "context": f"Thuốc {i}: uống {i + 1} viên sau khi ăn, không dùng cho trẻ em dưới 2 tuổi.",
        "topic": 2, "article_url": f"https://example.com/{i}",
    } for i in range(6)]).to_parquet(src / "vimedaqa-test.parquet")
    monkeypatch.setattr(gen, "SRC_DIR", str(src))
    monkeypatch.setattr(gen, "OUT_DIR", str(tmp_path / "out"))
    return tmp_path


class FakeBatches:
    def __init__(self, responses):
        self.responses = responses  # custom_id -> (stop_reason, payload) | "errored"
        self.created = None

    def create(self, requests):
        self.created = requests
        return NS(id="batch_1", processing_status="in_progress")

    def retrieve(self, batch_id):
        return NS(id=batch_id, processing_status="ended")

    def results(self, batch_id):
        # Results arrive in any order
        for req in reversed(self.created):
            r = self.responses.get(req["custom_id"])
            if r == "errored":
                yield NS(custom_id=req["custom_id"], result=NS(type="errored"))
            else:
                stop, payload = r
                msg = NS(stop_reason=stop, content=[NS(type="text", text=json.dumps(payload, ensure_ascii=False))])
                yield NS(custom_id=req["custom_id"], result=NS(type="succeeded", message=msg))


def test_generator_submit_then_collect(vimedaqa):
    rows = gen.sample_rows("test", 6)
    ids = [r["custom_id"] for r in rows]
    responses = {i: ("end_turn", {"response": f"Phiên bản sai {n}.", "change": "dose"}) for n, i in enumerate(ids)}
    responses[ids[1]] = ("end_turn", {"response": rows[1]["gold"], "change": "none"})  # unchanged -> rejected
    responses[ids[2]] = "errored"
    responses[ids[3]] = ("max_tokens", {"response": "x", "change": ""})
    batches = FakeBatches(responses)
    client = NS(messages=NS(batches=batches))

    gen.submit(client, "test", 6)
    req = batches.created[0]["params"]
    assert req["model"] == "claude-haiku-5-5" and req["output_config"]["effort"] == "low"
    assert req["output_config"]["format"]["schema"]["additionalProperties"] is False

    df = gen.collect(client, "test")
    errors = df[df.label != "no"]
    assert set(errors.id) == {ids[0], ids[4], ids[5]}
    assert set(errors.label) == {"intrinsic", "extrinsic"}
    assert (df[df.label == "no"].generator == "gold").all() and not errors.reviewed.any()
    assert os.path.exists(os.path.join(gen.OUT_DIR, "vimedhallu-hard-test.csv"))


def test_generator_collect_waits_for_batch(vimedaqa):
    batches = FakeBatches({})
    batches.retrieve = lambda bid: NS(id=bid, processing_status="in_progress")
    client = NS(messages=NS(batches=batches))
    gen.submit(client, "test", 2)
    assert gen.collect(client, "test") is None


@pytest.mark.parametrize("feedback, corrected, model, expected", [
    ("CORRECT", None, "extrinsic", "extrinsic"),
    ("CORRECT", "CORRECT", "no", "no"),             # rows saved before the repository fix
    ("no_hallucination", "no_hallucination", "intrinsic", "no"),
    ("intrinsic", "intrinsic", "no", "intrinsic"),
    ("CORRECT", None, None, None),                  # failed audit has no label to confirm
    ("maybe", "maybe", "no", None),
])
def test_feedback_label_normalisation(feedback, corrected, model, expected):
    assert fb.true_label(feedback, corrected, model) == expected


def test_export_feedback_from_db(client, db_session):
    rag = client.post("/api/v1/audits/rag", json={
        "question": "Thủ đô Việt Nam là gì?", "contexts": ["Hà Nội là thủ đô của Việt Nam."],
        "answer": "Thủ đô của Việt Nam là Hà Nội. Tổng thống sống ở đó.",
    }).json()
    single = client.post("/api/v1/audits", json={
        "context": "Hà Nội là thủ đô của Việt Nam.", "prompt": "Thủ đô?", "response": "Thủ đô là Paris.",
    }).json()
    client.post("/api/v1/audits", json={"context": "a", "prompt": "b", "response": "c"})  # no feedback -> skipped
    client.post(f"/api/v1/audits/{rag['id']}/feedback", json={"feedback_label": "no"})
    client.post(f"/api/v1/audits/{single['id']}/feedback", json={"feedback_label": "CORRECT"})

    df = fb.export(db_session).set_index("id")
    assert len(df) == 2
    assert df.loc[rag["id"], "label"] == "no" and df.loc[rag["id"], "model_label"] == "extrinsic"
    assert bool(df.loc[rag["id"], "is_rag"]) is True
    assert df.loc[single["id"], "label"] == "intrinsic"
