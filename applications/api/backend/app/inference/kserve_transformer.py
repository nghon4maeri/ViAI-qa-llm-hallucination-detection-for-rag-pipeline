# applications/api/backend/app/inference/kserve_transformer.py
"""
KServe transformer for the hallucination-detector InferenceService.

  API --V2 {context, prompt, response}--> transformer --V2 778 features--> MLServer/MLflow predictor
      <--{label, confidence, breakdown}--            <--[prob_extrinsic, prob_no, prob_intrinsic]--

The transformer runs HallucinationPipeline.extract_signals (PhoBERT, NLI, NER, LLM features) before the
predictor and HallucinationPipeline.decide (guardrails) after it, inside one predict() call, the same two calls the in-process
engine makes, so both serving paths give the same answer.

Runs from the backend image (kserve 0.16):
  python -m backend.app.inference.kserve_transformer --predictor_host HOST:PORT --predictor_protocol v2
"""
import asyncio
import json
import uuid
from typing import Any, Dict, List, Tuple

import numpy as np

MODEL_NAME = "hallucination-detector"
TEXT_INPUTS = ("context", "prompt", "response")
# LGBMEnsemble output columns (machine-learning/pipelines/train.py), i.e. class ids 0, 1, 2
PROB_COLUMNS = ["prob_extrinsic", "prob_no", "prob_intrinsic"]
BREAKDOWN_KEYS = ("p_entailment", "p_neutral", "p_contradiction", "new_entity_count",
                  "entity_overlap_ratio", "vistral_extrinsic_prob", "active_guardrail")

def _field(obj, name):
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


def parse_text_inputs(payload) -> Dict[str, str]:
    """V2 request (dict or kserve.InferRequest) with BYTES inputs context / prompt / response."""
    values = {}
    for inp in _field(payload, "inputs"):
        data = _field(inp, "data")
        value = data[0] if isinstance(data, (list, tuple)) and data else data
        values[_field(inp, "name")] = value.decode("utf-8") if isinstance(value, bytes) else str(value)
    missing = [k for k in TEXT_INPUTS if not values.get(k, "").strip()]
    if missing:
        raise ValueError(f"Missing or empty inputs: {', '.join(missing)}")
    return {k: values[k] for k in TEXT_INPUTS}


def predictor_request(features) -> Dict[str, Any]:
    """
    V2 request for the MLServer MLflow runtime. The request-level NumPy codec makes MLServer pass an
    ndarray to the pyfunc, which MLflow maps onto the model's column signature (columns 0..777).
    """
    x = np.asarray(features, dtype=float).reshape(1, -1)
    return {
        "parameters": {"content_type": "np"},
        "inputs": [{
            "name": "features", "shape": list(x.shape), "datatype": "FP64",
            "data": x.ravel().tolist(), "parameters": {"content_type": "np"},
        }],
    }


def parse_predictor_probs(response) -> List[float]:
    """[prob_extrinsic, prob_no, prob_intrinsic] from the predictor's V2 response."""
    outputs = _field(response, "outputs")
    by_name = {_field(o, "name"): list(_field(o, "data")) for o in outputs}
    if all(c in by_name for c in PROB_COLUMNS):  # pandas codec: one output per DataFrame column
        return [float(by_name[c][0]) for c in PROB_COLUMNS]
    if len(outputs) == 1 and len(_field(outputs[0], "data")) == len(PROB_COLUMNS):  # single tensor
        return [float(v) for v in _field(outputs[0], "data")]
    raise ValueError(f"Unexpected predictor outputs: {sorted(by_name)}")


def verdict_response(result: Dict[str, Any], model_name: str = MODEL_NAME, request_id: str = None) -> Dict[str, Any]:
    breakdown = {k: result.get(k) for k in BREAKDOWN_KEYS}
    return {
        "id": request_id or str(uuid.uuid4()),  # V2 responses require an id
        "model_name": model_name,
        "outputs": [
            {"name": "label", "datatype": "BYTES", "shape": [1], "data": [result["label"]]},
            {"name": "confidence", "datatype": "FP64", "shape": [1], "data": [float(result["confidence"])]},
            {"name": "breakdown", "datatype": "BYTES", "shape": [1], "data": [json.dumps(breakdown)]},
        ],
    }


class TransformerCore:
    """The transformer's logic without the kserve dependency (tested directly)."""

    def __init__(self, pipeline, model_name: str = MODEL_NAME):
        self.pipeline = pipeline
        self.model_name = model_name

    def prepare(self, payload) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
        """Text request -> (predictor request, signals kept for the decision, request id)."""
        signals = self.pipeline.extract_signals(**parse_text_inputs(payload))
        request_id = payload.get("id") if isinstance(payload, dict) else getattr(payload, "id", None)
        return predictor_request(signals["features"]), signals, request_id

    def finish(self, response, signals: Dict[str, Any], request_id: str = None) -> Dict[str, Any]:
        result = self.pipeline.decide(parse_predictor_probs(response), signals)
        return verdict_response(result, self.model_name, request_id)


def main():
    import kserve

    from backend.app.inference.inference_model import get_hallu_model

    class HallucinationTransformer(kserve.Model):
        def __init__(self, name: str):
            super().__init__(name)
            self.core = TransformerCore(get_hallu_model(), name)
            self.core.pipeline._load_models()  # load once at startup, not on the first request
            self.ready = True

        async def predict(self, payload, headers=None, response_headers=None):
            # one coroutine per request, so the signals stay a local variable between the two halves;
            # feature extraction (PhoBERT, NLI, NER) runs off the event loop
            request, signals, request_id = await asyncio.to_thread(self.core.prepare, payload)
            # forwards to --predictor_host over --predictor_protocol (must be v2 for MLServer)
            response = await super().predict(request, headers)
            return self.core.finish(response, signals, request_id)

    # kserve's own parser: ModelServer reads --predictor_host / --predictor_protocol from argv itself
    args, _ = kserve.model_server.parser.parse_known_args()
    name = MODEL_NAME if args.model_name == "model" else args.model_name
    kserve.ModelServer().start([HallucinationTransformer(name)])


if __name__ == "__main__":
    main()
