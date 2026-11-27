# applications/api/backend/app/evaluation/adapters/existing_pipeline.py
import time
from typing import List

import numpy as np
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.schemas import EvaluationInput, EvaluationResult, EvaluationBreakdown
from backend.app.core.logging import logger


class ExistingPipelineAdapter(EvaluationEngine):
    """
    Adapter encapsulating the legacy in-process HallucinationPipeline behind the domain interface.
    Safely captures genuine NLI, NER, and Guardrail metrics when available from the model,
    and honestly leaves missing metrics as None without substituting deceptive defaults.
    """

    def __init__(self):
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            from backend.app.inference.inference_model import get_hallu_model
            self._pipeline = get_hallu_model()
        return self._pipeline

    def is_ready(self) -> bool:
        pipeline = self._get_pipeline()
        return getattr(pipeline, "_is_loaded", False)

    def warmup(self) -> None:
        pipeline = self._get_pipeline()
        if not getattr(pipeline, "_is_loaded", False):
            pipeline._load_models()

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        return self.evaluate_batch([payload])[0]

    def evaluate_batch(self, payloads: List[EvaluationInput]) -> List[EvaluationResult]:
        pipeline = self._get_pipeline()
        raw_results = pipeline.predict_batch([(p.context, p.prompt, p.response) for p in payloads])
        return [self._to_result(raw) for raw in raw_results]

    @staticmethod
    def _to_result(raw_result: dict) -> EvaluationResult:
        # Map metrics if available; if not present (e.g. model disabled), they remain None
        breakdown = EvaluationBreakdown(
            p_entailment=raw_result.get("p_entailment"),
            p_neutral=raw_result.get("p_neutral"),
            p_contradiction=raw_result.get("p_contradiction"),
            new_entity_count=raw_result.get("new_entity_count"),
            new_entities=raw_result.get("new_entities"),
            entity_overlap_ratio=raw_result.get("entity_overlap_ratio"),
            vistral_extrinsic_prob=raw_result.get("vistral_extrinsic_prob"),
            active_guardrail=raw_result.get("active_guardrail")
        )

        return EvaluationResult(
            label=raw_result["label"],
            confidence=float(raw_result["confidence"]),
            breakdown=breakdown,
            model_version="vihallu-v2-hybrid"
        )

    def embed(self, texts: List[str]) -> np.ndarray:
        pipeline = self._get_pipeline()
        if not getattr(pipeline, "_is_loaded", False):
            pipeline._load_models()
        vectors = pipeline._extract_embeddings(texts)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
