# services/api/backend/app/evaluation/rag.py
import re
from typing import List, Tuple

from backend.app.evaluation.cache import evaluation_cache
from backend.app.evaluation.interfaces import EmbeddingEngine, EvaluationEngine
from backend.app.evaluation.schemas import (
    ClaimVerdict,
    EvaluationInput,
    EvaluationResult,
    RagEvaluationInput,
    RagEvaluationResult,
    RagMetrics,
)

MAX_CLAIMS = 30

# shortcut: punctuation split misses abbreviations ("TP. HCM"); swap in underthesea.sent_tokenize if that shows up in audits
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")


def split_claims(answer: str) -> List[str]:
    claims = [s.strip() for s in _SENTENCE_END.split(answer) if len(s.strip()) > 2]
    return claims[:MAX_CLAIMS] or [answer.strip()]


def evaluate_cached(engine: EvaluationEngine, context: str, prompt: str, response: str) -> EvaluationResult:
    result = evaluation_cache.get(context, prompt, response)
    if result is None:
        result = engine.evaluate(EvaluationInput(context=context, prompt=prompt, response=response))
        evaluation_cache.set(context, prompt, response, result)
    return result


def _relatedness(result: EvaluationResult) -> float:
    # A chunk the claim is about is either entailed or contradicted; NLI "neutral" means off-topic
    p_neutral = result.breakdown.p_neutral if result.breakdown else None
    return 1.0 - p_neutral if p_neutral is not None else result.confidence


def _judge_claim(engine: EvaluationEngine, claim: str, payload: RagEvaluationInput) -> Tuple[ClaimVerdict, str]:
    results = [evaluate_cached(engine, ctx, payload.question, claim) for ctx in payload.contexts]

    supported = [i for i, r in enumerate(results) if r.label == "no"]
    if supported:
        # One supporting chunk is enough for a claim to be grounded
        idx = max(supported, key=lambda i: results[i].confidence)
    else:
        # Otherwise report the verdict from the chunk the claim is most about
        idx = max(range(len(results)), key=lambda i: _relatedness(results[i]))

    r = results[idx]
    verdict = ClaimVerdict(text=claim, label=r.label, confidence=r.confidence, context_index=idx, breakdown=r.breakdown)
    return verdict, r.model_version


def _metrics(engine: EvaluationEngine, payload: RagEvaluationInput, claims: List[ClaimVerdict]) -> RagMetrics:
    used_chunks = {c.context_index for c in claims if c.label == "no"}

    context_recall = None
    if payload.ground_truth and payload.ground_truth.strip():
        # Same detector, other direction: can the retrieved chunks back up the reference answer?
        reference = [_judge_claim(engine, s, payload)[0] for s in split_claims(payload.ground_truth)]
        context_recall = sum(c.label == "no" for c in reference) / len(reference)

    answer_relevance = context_relevance = None
    if isinstance(engine, EmbeddingEngine):
        vectors = engine.embed([payload.question, payload.answer, *payload.contexts])
        q = vectors[0]
        answer_relevance = float(vectors[1] @ q)
        context_relevance = [float(v @ q) for v in vectors[2:]]

    return RagMetrics(
        answer_relevance=answer_relevance,
        context_relevance=context_relevance,
        context_utilization=len(used_chunks) / len(payload.contexts),
        context_recall=context_recall,
    )


def evaluate_rag(engine: EvaluationEngine, payload: RagEvaluationInput) -> RagEvaluationResult:
    """Tier 1 RAG evaluation: every answer sentence is scored against every retrieved chunk."""
    judged = [_judge_claim(engine, c, payload) for c in split_claims(payload.answer)]
    claims = [verdict for verdict, _ in judged]

    hallucinated = [c for c in claims if c.label != "no"]
    if not hallucinated:
        label, confidence = "no", min(c.confidence for c in claims)
    else:
        # Contradicting the sources is the more severe failure
        label = "intrinsic" if any(c.label == "intrinsic" for c in hallucinated) else "extrinsic"
        confidence = max(c.confidence for c in hallucinated if c.label == label)

    return RagEvaluationResult(
        label=label,
        confidence=confidence,
        faithfulness=(len(claims) - len(hallucinated)) / len(claims),
        claims=claims,
        metrics=_metrics(engine, payload, claims),
        model_version=judged[0][1],
    )
