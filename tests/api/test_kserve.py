# tests/api/test_kserve.py
"""KServe path: transformer core (V2 in/out, MLServer response shapes) and the API's KServeEngine."""
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from backend.app.evaluation.adapters.kserve_engine import KServeEngine
from backend.app.evaluation.schemas import EvaluationInput
from backend.app.inference.inference_model import HallucinationPipeline
from backend.app.inference.kserve_transformer import (TransformerCore, parse_predictor_probs, parse_text_inputs,
                                                     predictor_request)

TEXT = {"context": "Hà Nội là thủ đô của Việt Nam.", "prompt": "Thủ đô?", "response": "Thủ đô là Hà Nội."}
V2_TEXT = {"inputs": [{"name": k, "datatype": "BYTES", "shape": [1], "data": [v]} for k, v in TEXT.items()]}


class FakePipeline(HallucinationPipeline):
    """Real decide(); extract_signals replaced so no model weights are needed."""

    def extract_signals(self, context, prompt, response):
        self.seen = (context, prompt, response)
        return {"features": np.arange(778, dtype=float).reshape(1, -1), "p_entailment": 0.9, "p_neutral": 0.05,
                "p_contradiction": 0.05, "new_entity_count": 0, "entity_overlap_ratio": 1.0,
                "vistral_extrinsic_prob": 0.1}


def test_parse_text_inputs_accepts_dicts_objects_and_bytes():
    assert parse_text_inputs(V2_TEXT) == TEXT
    obj = NS(inputs=[NS(name=k, data=[v.encode()]) for k, v in TEXT.items()])  # kserve.InferRequest shape
    assert parse_text_inputs(obj) == TEXT
    with pytest.raises(ValueError, match="response"):
        parse_text_inputs({"inputs": V2_TEXT["inputs"][:2]})


def test_predictor_request_is_one_fp64_tensor():
    req = predictor_request(np.arange(778.0))
    (inp,) = req["inputs"]
    assert inp["shape"] == [1, 778] and inp["datatype"] == "FP64" and len(inp["data"]) == 778
    assert req["parameters"] == {"content_type": "np"}


@pytest.mark.parametrize("response", [
    # MLServer MLflow runtime with a DataFrame output (captured from mlserver 1.7.1, 2026-11-26)
    {"outputs": [{"name": "prob_extrinsic", "data": [0.2]}, {"name": "prob_no", "data": [0.7]},
                 {"name": "prob_intrinsic", "data": [0.1]}]},
    {"outputs": [{"name": "output-0", "data": [0.2, 0.7, 0.1]}],},
])
def test_parse_predictor_probs(response):
    assert parse_predictor_probs(response) == [0.2, 0.7, 0.1]


def test_transformer_round_trip_matches_in_process_decision():
    pipe = FakePipeline()
    core = TransformerCore(pipe)
    request, signals, request_id = core.prepare({**V2_TEXT, "id": "req-1"})
    assert pipe.seen == tuple(TEXT.values()) and request["inputs"][0]["data"][:3] == [0.0, 1.0, 2.0]

    probs = [0.1, 0.8, 0.1]
    out = core.finish({"outputs": [{"name": c, "data": [p]} for c, p in
                                   zip(["prob_extrinsic", "prob_no", "prob_intrinsic"], probs)]}, signals, request_id)
    assert out["id"] == "req-1"
    got = {o["name"]: o["data"][0] for o in out["outputs"]}
    expected = pipe.decide(probs, signals)
    assert got["label"] == expected["label"] == "no" and got["confidence"] == pytest.approx(0.8)
    assert json.loads(got["breakdown"])["p_entailment"] == 0.9


class FakeSession:
    def __init__(self, outputs=None, ok=True):
        self.outputs, self.ok, self.posted = outputs, ok, None

    def post(self, url, json, timeout):
        self.posted = (url, json)
        return NS(raise_for_status=lambda: None, json=lambda: {"outputs": self.outputs})

    def get(self, url, timeout):
        self.got = url
        return NS(ok=self.ok)


def test_kserve_engine_maps_the_transformer_response():
    url = "http://isvc/v2/models/hallucination-detector/infer"
    outputs = [{"name": "label", "data": ["extrinsic"]}, {"name": "confidence", "data": [0.85]},
               {"name": "breakdown", "data": [json.dumps({"new_entity_count": 2, "active_guardrail": "NEW_ENTITY_MISMATCH"})]}]
    session = FakeSession(outputs)
    engine = KServeEngine(url, session=session)
    res = engine.evaluate(EvaluationInput(**TEXT))
    assert (res.label, res.confidence, res.breakdown.active_guardrail) == ("extrinsic", 0.85, "NEW_ENTITY_MISMATCH")
    assert session.posted[0] == url and [i["name"] for i in session.posted[1]["inputs"]] == list(TEXT)
    assert engine.is_ready() and session.got == "http://isvc/v2/models/hallucination-detector/ready"


def test_get_engine_prefers_kserve_when_configured(monkeypatch):
    from backend.app.modules.audits import router
    monkeypatch.setattr(router.settings, "DISABLE_MODEL", False)
    monkeypatch.setattr(router.settings, "KSERVE_ENDPOINT", "http://isvc/v2/models/hallucination-detector/infer")
    monkeypatch.setattr(router, "_global_engine", None)
    assert isinstance(router.get_engine(), KServeEngine)
