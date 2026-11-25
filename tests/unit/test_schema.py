# tests/unit/test_schema.py
from backend.app.modules.legacy.schemas import HalluInput, HalluOutput


def test_hallu_input_schema():
    obj = HalluInput(
        context="a",
        prompt="b",
        response="c"
    )
    assert obj.context == "a"


def test_hallu_output_schema():
    out = HalluOutput(label="No Hallucination", confidence=0.8)
    assert out.confidence <= 1.0