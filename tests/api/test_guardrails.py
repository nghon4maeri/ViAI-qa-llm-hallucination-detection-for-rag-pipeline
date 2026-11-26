# tests/api/test_guardrails.py
"""Guardrail v3 decisions, shared by the in-process engine and the KServe transformer."""
import pytest

from backend.app.inference.inference_model import HallucinationPipeline

NO, EXT, INT = [0.1, 0.8, 0.1], [0.8, 0.1, 0.1], [0.1, 0.1, 0.8]  # LightGBM probs [ext, no, int]


def signals(entail=0.9, neutral=0.05, contra=0.05, new_entities=0, llm_ext=0.1):
    return {"features": None, "p_entailment": entail, "p_neutral": neutral, "p_contradiction": contra,
            "new_entity_count": new_entities, "entity_overlap_ratio": 1.0, "vistral_extrinsic_prob": llm_ext}


@pytest.mark.parametrize("probs, sig, label, guardrail, conf", [
    (NO, signals(), "no", None, 0.8),                                              # LightGBM stands
    (INT, signals(), "intrinsic", None, 0.8),
    (NO, signals(entail=0.2, contra=0.7), "intrinsic", "NLI_CONTRADICTION_HIGH", 0.7),
    (NO, signals(entail=0.3, neutral=0.6), "extrinsic", "NLI_NEUTRAL_HIGH", 0.6),
    (NO, signals(entail=0.8, new_entities=2), "extrinsic", "NEW_ENTITY_MISMATCH", 0.85),
    (EXT, signals(entail=0.8, new_entities=2), "extrinsic", None, 0.8),             # mismatch rule needs a "no" vote
    (NO, signals(llm_ext=0.7), "extrinsic", "VISTRAL_EXTRINSIC_HIGH", 0.7),
    (NO, signals(contra=0.4), "intrinsic", "SOFT_CONTRADICTION", 0.4),
    (EXT, signals(contra=0.4), "extrinsic", None, 0.8),                             # soft rule only overrides "no"
])
def test_decide(probs, sig, label, guardrail, conf):
    out = HallucinationPipeline().decide(probs, sig)
    assert (out["label"], out["active_guardrail"]) == (label, guardrail)
    assert out["confidence"] == pytest.approx(conf)
    assert "features" not in out and out["p_entailment"] == sig["p_entailment"]
