# applications/api/backend/app/evaluation/adapters/kserve_engine.py
import json

import requests

from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.schemas import EvaluationBreakdown, EvaluationInput, EvaluationResult


class KServeEngine(EvaluationEngine):
    """
    Remote detector: the hallucination-detector InferenceService (transformer + MLServer predictor).
    Selected when KSERVE_ENDPOINT is set. No embed(), so RAG relevance metrics stay None on this path.
    """

    def __init__(self, endpoint: str, timeout: float = 60.0, session=None):
        self.endpoint = endpoint  # .../v2/models/hallucination-detector/infer
        self.timeout = timeout
        self.session = session or requests.Session()

    def _model_url(self) -> str:
        return self.endpoint.rsplit("/infer", 1)[0]

    def is_ready(self) -> bool:
        try:
            return self.session.get(f"{self._model_url()}/ready", timeout=5).ok
        except requests.RequestException:
            return False

    def warmup(self) -> None:
        pass  # the transformer loads its models at startup

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        body = {"inputs": [{"name": k, "datatype": "BYTES", "shape": [1], "data": [getattr(payload, k)]}
                           for k in ("context", "prompt", "response")]}
        r = self.session.post(self.endpoint, json=body, timeout=self.timeout)
        r.raise_for_status()
        out = {o["name"]: o["data"][0] for o in r.json()["outputs"]}
        return EvaluationResult(
            label=out["label"],
            confidence=float(out["confidence"]),
            breakdown=EvaluationBreakdown(**json.loads(out.get("breakdown") or "{}")),
            model_version="vihallu-v2-hybrid-kserve",
        )
