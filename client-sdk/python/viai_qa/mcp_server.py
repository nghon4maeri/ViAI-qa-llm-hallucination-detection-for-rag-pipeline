# client-sdk/python/viai_qa/mcp_server.py
"""
MCP server exposing ViAI-QA to agents (Claude Code, Cursor, any MCP client) over stdio.

    VIAI_QA_URL=http://localhost:8080 VIAI_QA_API_KEY=... viai-qa-mcp

Tool results are trimmed to what an agent needs to act on (verdicts, failing sentences, ids),
not the full audit JSON with every NLI score, to keep the caller's context small.
"""
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from viai_qa.client import ViaiQA

server = MCPServer(
    name="viai-qa",
    instructions=(
        "ViAI-QA checks answers from a Vietnamese medical RAG system against the documents that were "
        "retrieved for them. Use guard_rag_answer before showing an answer to a user, evaluate_rag_response "
        "to inspect one answer sentence by sentence, and evaluate_dataset for a whole .jsonl/.csv file. "
        "Verdicts: no = grounded, intrinsic = contradicts the documents, extrinsic = not in the documents. "
        "It judges faithfulness to the documents, not medical correctness."
    ),
)

_client: Optional[ViaiQA] = None


def client() -> ViaiQA:
    global _client
    if _client is None:
        _client = ViaiQA()  # VIAI_QA_URL / VIAI_QA_API_KEY from the environment
    return _client


def _claims(audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "sentence": c["text"],
            "verdict": c["label"],
            "confidence": round(c["confidence"], 3),
            # 1-based to match the [n] markers in the ViAI-QA UI; None when nothing in the sources backs it
            "source": c["context_index"] + 1 if c["label"] != "extrinsic" else None,
        }
        for c in audit.get("claims") or []
    ]


def _summary(audit: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "audit_id": audit["id"],
        "verdict": audit["label"],
        "faithfulness": audit.get("faithfulness"),
        "sentences": _claims(audit),
        "metrics": audit.get("rag_metrics"),
    }
    if audit.get("judge"):
        j = audit["judge"]
        out["judge"] = {
            "status": j["status"], "verdict": j.get("label"), "faithfulness": j.get("faithfulness"),
            "explanation": j.get("explanation"),
            "overruled": [{"sentence": c["index"] + 1, "verdict": c["label"], "reason": c["reason"]}
                          for c in j.get("claims", []) if not c["agrees_with_tier1"]],
        }
    return out


@server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=False))
def guard_rag_answer(question: str, contexts: List[str], answer: str) -> Dict[str, Any]:
    """Decide whether a RAG answer is safe to show: action is "pass", "regenerate" (has sentences not in the
    documents) or "block" (contradicts the documents). Lists the failing sentences. Stores an audit."""
    res = client().guard(question, contexts, answer)
    return {
        "action": res["action"],
        "reason": res["reason"],
        "faithfulness": res["faithfulness"],
        "failing_sentences": [{"sentence": c["text"], "verdict": c["label"]} for c in res["failing_claims"]],
        "audit_id": res["audit_id"],
    }


@server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=False))
def evaluate_rag_response(question: str, contexts: List[str], answer: str,
                          ground_truth: Optional[str] = None) -> Dict[str, Any]:
    """Check every sentence of a RAG answer against the retrieved chunks (contexts, in retrieval order).
    Returns the overall verdict, faithfulness (share of grounded sentences), per-sentence verdicts with the
    supporting chunk number, and retrieval metrics. Pass ground_truth to get context_recall."""
    return _summary(client().evaluate(question, contexts, answer, ground_truth))


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def get_audit(audit_id: str) -> Dict[str, Any]:
    """Fetch a stored audit by id, including the judge agent's verdict if one was run."""
    return _summary(client().get_audit(audit_id))


@server.tool(annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True))
def deep_audit(audit_id: str, only_doubtful: bool = True) -> Dict[str, Any]:
    """Ask the Claude judge agent to re-check an audit's sentences with tools. Costs a paid API call on the
    ViAI-QA server; only_doubtful=True (cheapest) re-checks just the sentences the detector was unsure of."""
    return _summary(client().judge(audit_id, only_doubtful=only_doubtful))


@server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=False))
def evaluate_dataset(path: str, wait: bool = True) -> Dict[str, Any]:
    """Evaluate a dataset file on the machine running this server: .jsonl with one
    {"question", "contexts", "answer", "ground_truth"?} per line, or .csv with context,prompt,response.
    With wait=True, blocks until scoring finishes (up to 30 minutes) and returns the summary."""
    batch = client().upload_dataset(path)
    if not wait:
        return {"batch_id": batch["batch_id"], "status": batch["status"], "total": batch["total_count"]}
    done = client().wait_for_batch(batch["batch_id"], timeout=1800)
    return {
        "batch_id": done["id"],
        "status": done["status"],
        "scored": done["completed_count"],
        "failed": done["failed_count"],
        "hallucination_rate_percent": done["hallucination_rate"],
        "mean_faithfulness": done.get("mean_faithfulness"),
        "failing_items": [
            {"audit_id": i["id"], "question": i["prompt"], "verdict": i["label"], "faithfulness": i.get("faithfulness")}
            for i in done["items"] if i.get("label") not in (None, "no")
        ][:50],
    }


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def list_failing_claims(limit: int = 10, verdict: Optional[str] = None) -> List[Dict[str, Any]]:
    """Recent audits whose answer was not grounded, with the failing sentences. verdict filters to
    "intrinsic" or "extrinsic"; default returns both. limit caps the number of audits (max 50)."""
    limit = max(1, min(limit, 50))
    labels = [verdict] if verdict else ["intrinsic", "extrinsic"]
    items = [i for label in labels for i in client().list_audits(label=label, page_size=limit)["items"]]
    items.sort(key=lambda i: i["created_at"], reverse=True)
    out = []
    for item in items[:limit]:
        audit = client().get_audit(item["id"])
        out.append({
            "audit_id": audit["id"],
            "question": audit["prompt"],
            "verdict": audit["label"],
            "failing_sentences": [c for c in _claims(audit) if c["verdict"] != "no"] or [{"sentence": audit["response"], "verdict": audit["label"]}],
        })
    return out


@server.tool(annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
def submit_feedback(audit_id: str, verdict: str, comment: Optional[str] = None) -> Dict[str, Any]:
    """Record a human review of an audit for retraining. verdict: "CORRECT" (the audit was right), or the
    true label "no", "intrinsic" or "extrinsic"."""
    if verdict not in ("CORRECT", "no", "intrinsic", "extrinsic"):
        raise ValueError('verdict must be "CORRECT", "no", "intrinsic" or "extrinsic"')
    fb = client().feedback(audit_id, verdict, comment)
    return {"audit_id": audit_id, "saved_label": fb["corrected_label"]}


def main():
    server.run()  # stdio


if __name__ == "__main__":
    main()
