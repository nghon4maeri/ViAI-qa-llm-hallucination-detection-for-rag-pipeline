# services/api/backend/app/evaluation/judge_agent.py
"""
Tier 2 judge: a Claude agent that re-examines a RAG answer with tools built on the Tier 1 detector.

Runs only on demand ("deep audit") or when Tier 1 is unsure (see needs_judge). Manual agent loop
rather than the SDK tool runner so every tool call is recorded for the UI timeline and traces,
and so the loop has no beta dependency beyond server-side refusal fallbacks.
"""
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.app.core.config import settings
from backend.app.core.logging import logger
from backend.app.evaluation.interfaces import EvaluationEngine
from backend.app.evaluation.rag import evaluate_cached
from backend.app.evaluation.schemas import (
    ClaimVerdict,
    JudgeClaim,
    JudgeVerdict,
    RagEvaluationInput,
    ToolCallTrace,
)

try:
    from opentelemetry import trace
    _tracer = trace.get_tracer(__name__)
except ImportError:  # tracing is optional, as in backend/main.py
    _tracer = None

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server-side refusal fallback exists only for these; Haiku 5.5 has none and rejects a fallback list
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You audit answers produced by a Vietnamese medical RAG chatbot. You decide, sentence by sentence, whether each claim in the answer is supported by the retrieved documents. You are not giving medical advice; the documents are the only ground truth, even when you believe a claim is true in the real world.

Labels, as in the ViHallu taxonomy:
- no: the claim is stated in or directly inferable from at least one document.
- intrinsic: the claim distorts or contradicts something a document states (wrong dose, duration, frequency, flipped "nên"/"không nên", before/after meals, wrong drug or condition taken from the documents).
- extrinsic: the claim adds information no document contains, even if it might be true elsewhere.

A first-pass detector (Tier 1) already labelled every claim; its labels can be wrong, which is why you were called. Use the tools to check the doubtful claims: detect_hallucination re-runs the detector against one chunk and returns its NLI and entity signals, check_numbers compares numbers and units between a claim and a chunk. Read the documents yourself as well; the detector is evidence, not the answer.

Only the claims listed under <to_check> need a verdict; the others are shown for context and Tier 1 keeps them. Check only what you need: one or two tool calls per claim is usually enough.

When you are done, call submit_verdict exactly once with a verdict for every claim index in <to_check>. Write each reason in Vietnamese, in one or two sentences, quoting the decisive words from the document."""

TOOLS = [
    {
        "name": "detect_hallucination",
        "description": "Run the Tier 1 hallucination detector (PhoBERT + NLI + NER + LightGBM ensemble) on one claim against one retrieved chunk. Returns the label (no/intrinsic/extrinsic), confidence, NLI probabilities, entities in the claim that the chunk lacks, and any guardrail rule that fired. Call it for every chunk you want to test; calls are independent and can be made in parallel.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "The claim sentence, verbatim"},
                "context_index": {"type": "integer", "description": "0-based index of the chunk"},
            },
            "required": ["claim", "context_index"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_numbers",
        "description": "Compare numbers and units (doses like 500mg, durations like 6 giờ, percentages, counts) in a claim with those in one chunk. Returns both lists and the claim numbers the chunk does not contain. Use it whenever a claim has a number; a changed dose is the most dangerous error in this domain.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "context_index": {"type": "integer"},
            },
            "required": ["claim", "context_index"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_verdict",
        "description": "Submit the final verdict for every claim. Call exactly once, after checking. This ends the audit.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "label": {"type": "string", "enum": ["no", "intrinsic", "extrinsic"]},
                            "reason": {"type": "string"},
                            "evidence_index": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                        },
                        "required": ["index", "label", "reason", "evidence_index"],
                        "additionalProperties": False,
                    },
                },
                "explanation": {"type": "string", "description": "Overall summary for the reviewer, in Vietnamese"},
            },
            "required": ["claims", "explanation"],
            "additionalProperties": False,
        },
    },
]

_UNIT = r"(?:mg|mcg|µg|g|ml|l|ui|iu|%|giờ|phút|ngày|tuần|tháng|năm|lần|viên|gói|ống)"
# Same rule as the medical data builder: digits inside names ("Vitamin D3", "B12") are not quantities
_QUANTITY = re.compile(rf"(?<![\w-])(\d+(?:[.,]\d+)?)\s*({_UNIT})?(?!\w)", re.IGNORECASE)


def is_doubtful(claim: ClaimVerdict) -> bool:
    """Tier 1 is unsure: low confidence, or a guardrail rule overrode the LightGBM vote."""
    return claim.confidence < settings.JUDGE_ESCALATE_BELOW or bool(claim.breakdown and claim.breakdown.active_guardrail)


def needs_judge(claims: List[ClaimVerdict]) -> bool:
    return any(is_doubtful(c) for c in claims)


def _quantities(text: str) -> List[str]:
    return [f"{n.replace(',', '.')}{(' ' + u.lower()) if u else ''}" for n, u in _QUANTITY.findall(text)]


def check_numbers(claim: str, chunk: str) -> Dict[str, Any]:
    in_claim, in_chunk = _quantities(claim), _quantities(chunk)
    chunk_values = {q.split(" ")[0] for q in in_chunk}
    return {
        "claim_numbers": in_claim,
        "chunk_numbers": in_chunk,
        "not_in_chunk": [q for q in in_claim if q.split(" ")[0] not in chunk_values],
    }


def overall(claims: List[JudgeClaim]) -> Tuple[str, float]:
    """Same aggregation as Tier 1 (rag.evaluate_rag), so the two tiers are comparable."""
    bad = [c.label for c in claims if c.label != "no"]
    label = "no" if not bad else ("intrinsic" if "intrinsic" in bad else "extrinsic")
    return label, (len(claims) - len(bad)) / len(claims)


class JudgeAgent:
    def __init__(self, engine: EvaluationEngine, client=None):
        self.engine = engine
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic  # only needed when the agent actually runs

            self._client = anthropic.Anthropic()
        return self._client

    def _run_tool(self, name: str, args: Dict[str, Any], payload: RagEvaluationInput) -> Any:
        idx = args.get("context_index")
        if not isinstance(idx, int) or not 0 <= idx < len(payload.contexts):
            raise ValueError(f"context_index must be between 0 and {len(payload.contexts) - 1}")
        chunk = payload.contexts[idx]
        if name == "detect_hallucination":
            r = evaluate_cached(self.engine, chunk, payload.question, args["claim"])
            return {"label": r.label, "confidence": round(r.confidence, 4), **r.breakdown.model_dump(exclude_none=True)}
        if name == "check_numbers":
            return check_numbers(args["claim"], chunk)
        raise ValueError(f"Unknown tool {name}")

    def _prompt(self, payload: RagEvaluationInput, tier1: List[ClaimVerdict], to_check: List[int]) -> str:
        docs = "\n".join(f"[{i}] {c}" for i, c in enumerate(payload.contexts))
        claims = "\n".join(
            f"({i}) {c.text}\n    Tier 1: {c.label}, confidence {c.confidence:.2f}"
            + (f", guardrail {c.breakdown.active_guardrail}" if c.breakdown and c.breakdown.active_guardrail else "")
            for i, c in enumerate(tier1)
        )
        return (
            f"<question>\n{payload.question}\n</question>\n\n<documents>\n{docs}\n</documents>\n\n"
            f"<claims>\n{claims}\n</claims>\n\n<to_check>{', '.join(map(str, to_check))}</to_check>"
        )

    def run(self, payload: RagEvaluationInput, tier1: List[ClaimVerdict], only_doubtful: bool = True) -> JudgeVerdict:
        """only_doubtful: send just the claims Tier 1 is unsure of (cheapest); False re-checks every claim."""
        start = time.perf_counter()
        to_check = [i for i, c in enumerate(tier1) if not only_doubtful or is_doubtful(c)] or list(range(len(tier1)))
        messages: List[Dict[str, Any]] = [{"role": "user", "content": self._prompt(payload, tier1, to_check)}]
        traces: List[ToolCallTrace] = []
        usage = {"input": 0, "output": 0}
        model = settings.JUDGE_MODEL

        def finish(status: str, submitted: Optional[Dict[str, Any]] = None) -> JudgeVerdict:
            verdict = JudgeVerdict(
                status=status, model=model, tool_calls=traces,
                input_tokens=usage["input"], output_tokens=usage["output"],
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )
            if submitted:
                by_index = {c["index"]: c for c in submitted["claims"] if c["index"] in to_check}
                verdict.claims = [
                    JudgeClaim(**by_index[i], agrees_with_tier1=by_index[i]["label"] == t.label)
                    if i in by_index
                    # Not escalated: Tier 1 was confident, its label stands
                    else JudgeClaim(index=i, label=t.label, reason="Tier 1 đủ tin cậy, không kiểm tra lại",
                                    evidence_index=t.context_index if t.label != "extrinsic" else None,
                                    agrees_with_tier1=True)
                    for i, t in enumerate(tier1)
                ]
                verdict.explanation = submitted["explanation"]
                verdict.label, verdict.faithfulness = overall(verdict.claims)
                if any(i not in by_index for i in to_check):
                    verdict.status = "incomplete"
            return verdict

        for _ in range(settings.JUDGE_MAX_STEPS):
            fallback = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if settings.JUDGE_MODEL in FALLBACK_MODELS else {}
            response = self.client.beta.messages.create(
                model=settings.JUDGE_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": settings.JUDGE_EFFORT},
                # Each loop turn resends the whole history; caching it makes later turns ~10x cheaper on input
                cache_control={"type": "ephemeral"},
                **fallback,
            )
            usage["input"] += response.usage.input_tokens
            usage["output"] += response.usage.output_tokens
            model = response.model  # differs from JUDGE_MODEL when a fallback served the turn

            if response.stop_reason == "refusal":
                logger.warning(f"Judge refused: {getattr(response, 'stop_details', None)}")
                return finish("refused")
            if response.stop_reason == "max_tokens":
                return finish("incomplete")

            messages.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if response.stop_reason != "pause_turn":
                    messages.append({"role": "user", "content": "Call submit_verdict now with a verdict for every claim."})
                continue

            submitted, results = None, []
            for block in tool_uses:
                if block.name == "submit_verdict":
                    submitted = block.input
                    continue
                t0 = time.perf_counter()
                try:
                    if _tracer:
                        with _tracer.start_as_current_span(f"judge.tool.{block.name}"):
                            output = self._run_tool(block.name, block.input, payload)
                    else:
                        output = self._run_tool(block.name, block.input, payload)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, ensure_ascii=False)})
                except Exception as exc:
                    output = {"error": str(exc)}
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {exc}", "is_error": True})
                traces.append(ToolCallTrace(name=block.name, input=dict(block.input), output=output,
                                            latency_ms=(time.perf_counter() - t0) * 1000.0))

            if submitted is not None:
                return finish("completed", submitted)
            messages.append({"role": "user", "content": results})

        return finish("incomplete")
