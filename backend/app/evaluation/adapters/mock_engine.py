# backend/app/evaluation/adapters/mock_engine.py
from typing import Optional
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.schemas import EvaluationInput, EvaluationResult, EvaluationBreakdown


class MockEngine(EvaluationEngine):
    """
    Zero-weight deterministic engine for CI unit tests and development without PyTorch/models.
    Can be configured to simulate unavailable metrics or simulated inference errors.
    """

    def __init__(self, include_breakdown: bool = True, should_fail: bool = False):
        self.include_breakdown = include_breakdown
        self.should_fail = should_fail
        self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    def warmup(self) -> None:
        self._ready = True

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        if self.should_fail:
            raise RuntimeError("Simulated inference engine failure")

        c = payload.context.lower()
        p = payload.prompt.lower()
        r = payload.response.lower()

        # Deterministic keyword logic
        if "paris" in r and "hà nội" in c:
            label = "intrinsic"
            confidence = 0.98
            guardrail = "NLI_CONTRADICTION"
        elif "200 độ" in r and "100 độ" in c:
            label = "intrinsic"
            confidence = 0.95
            guardrail = "NLI_CONTRADICTION"
        elif "tây" in r and "đông" in c:
            label = "intrinsic"
            confidence = 0.92
            guardrail = "NLI_CONTRADICTION"
        elif "ân" in c and "quảng đông" in r:
            label = "intrinsic"
            confidence = 0.94
            guardrail = "NLI_CONTRADICTION"
        elif "tổng thống" in r and "tổng thống" not in c:
            label = "extrinsic"
            confidence = 0.88
            guardrail = "NEW_ENTITY_MISMATCH"
        elif "quân đội" in r and "quân đội" not in c:
            label = "extrinsic"
            confidence = 0.86
            guardrail = "NEW_ENTITY_MISMATCH"
        elif "jeddah" in r and "jeddah" not in c:
            label = "extrinsic"
            confidence = 0.88
            guardrail = "NEW_ENTITY_MISMATCH"
        elif "châu phi" in r and "châu phi" not in c:
            label = "extrinsic"
            confidence = 0.89
            guardrail = "NEW_ENTITY_MISMATCH"
        elif "ả rập" in c and "hàng ngàn" in r:
            label = "extrinsic"
            confidence = 0.85
            guardrail = "NEW_ENTITY_MISMATCH"
        else:
            label = "no"
            confidence = 0.95
            guardrail = None

        if self.include_breakdown:
            breakdown = EvaluationBreakdown(
                p_entailment=0.95 if label == "no" else 0.05,
                p_neutral=0.88 if label == "extrinsic" else 0.05,
                p_contradiction=0.98 if label == "intrinsic" else 0.02,
                new_entity_count=1 if label == "extrinsic" else 0,
                new_entities=["tổng thống"] if label == "extrinsic" else [],
                entity_overlap_ratio=0.2 if label == "extrinsic" else 1.0,
                vistral_extrinsic_prob=0.88 if label == "extrinsic" else 0.05,
                active_guardrail=guardrail
            )
        else:
            # Honestly unavailable breakdown
            breakdown = EvaluationBreakdown()

        return EvaluationResult(
            label=label,
            confidence=confidence,
            breakdown=breakdown,
            model_version="mock-v1"
        )

    def predict(self, context: str, prompt: str, response: str) -> dict:
        """Legacy helper matching inference_model predict interface."""
        res = self.evaluate(EvaluationInput(context=context or "empty", prompt=prompt or "empty", response=response or "empty"))
        return {
            "label": res.label,
            "confidence": res.confidence
        }

