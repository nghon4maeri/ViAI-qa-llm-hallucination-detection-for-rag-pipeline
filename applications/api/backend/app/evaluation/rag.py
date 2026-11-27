# applications/api/backend/app/evaluation/rag.py
import re
from typing import List, Tuple

from backend.app.evaluation.cache import evaluation_cache
from backend.app.evaluation.interfaces import BatchEvaluationEngine, EmbeddingEngine, EvaluationEngine
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


def evaluate_many(engine: EvaluationEngine, triples: List[Tuple[str, str, str]]) -> List[EvaluationResult]:
    """
    Cached detector results for (context, prompt, response) triples, in order. Cache misses go to the
    engine together: one evaluate_batch call when the engine batches, else one evaluate call each.
    """
    results = {t: evaluation_cache.get(*t) for t in dict.fromkeys(triples)}
    missing = [t for t, r in results.items() if r is None]
    if missing:
        payloads = [EvaluationInput(context=c, prompt=p, response=r) for c, p, r in missing]
        if isinstance(engine, BatchEvaluationEngine):
            fresh = engine.evaluate_batch(payloads)
        else:
            fresh = [engine.evaluate(x) for x in payloads]
        for t, r in zip(missing, fresh):
            evaluation_cache.set(*t, r)
            results[t] = r
    return [results[t] for t in triples]


def evaluate_cached(engine: EvaluationEngine, context: str, prompt: str, response: str) -> EvaluationResult:
    return evaluate_many(engine, [(context, prompt, response)])[0]


def _relatedness(result: EvaluationResult) -> float:
    # A chunk the claim is about is either entailed or contradicted; NLI "neutral" means off-topic
    p_neutral = result.breakdown.p_neutral if result.breakdown else None
    return 1.0 - p_neutral if p_neutral is not None else result.confidence


def _judge_claim(claim: str, results: List[EvaluationResult]) -> Tuple[ClaimVerdict, str]:
    """The claim's verdict from its results against every chunk (one per context, in order)."""
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


def _metrics(engine: EvaluationEngine, payload: RagEvaluationInput, claims: List[ClaimVerdict],
             reference: List[ClaimVerdict]) -> RagMetrics:
    used_chunks = {c.context_index for c in claims if c.label == "no"}

    # Same detector, other direction: can the retrieved chunks back up the reference answer?
    context_recall = sum(c.label == "no" for c in reference) / len(reference) if reference else None

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
    """
    Tier 1 RAG evaluation: every answer sentence is scored against every retrieved chunk. The whole
    claim x chunk grid (answer and reference claims) goes to the detector as one batch.
    """
    answer_claims = split_claims(payload.answer)
    reference_claims = split_claims(payload.ground_truth) if payload.ground_truth and payload.ground_truth.strip() else []
    all_claims = answer_claims + reference_claims
    n = len(payload.contexts)
    grid = evaluate_many(engine, [(ctx, payload.question, claim) for claim in all_claims for ctx in payload.contexts])
    judged = [_judge_claim(claim, grid[i * n:(i + 1) * n]) for i, claim in enumerate(all_claims)]
    reference = [verdict for verdict, _ in judged[len(answer_claims):]]
    judged = judged[:len(answer_claims)]
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
        metrics=_metrics(engine, payload, claims, reference),
        model_version=judged[0][1],
    )
