# viai-qa: Python SDK and MCP server

Client for the ViAI-QA API, which checks Vietnamese medical RAG answers sentence by sentence against the retrieved documents. The package also ships an MCP server so agents can call it directly.

```bash
pip install ./sdk/python            # SDK only (depends on requests)
pip install "./sdk/python[mcp]"     # + MCP server (mcp>=1.2, tested on 2.3)
```

Configuration comes from the environment, or from the constructor arguments:

| Variable | Meaning | Default |
|---|---|---|
| `VIAI_QA_URL` | API base URL | `http://localhost:8080` |
| `VIAI_QA_API_KEY` | Sent as `X-API-Key` (the NGINX gateway checks it) | unset |

## SDK

```python
from viai_qa import ViaiQA

qa = ViaiQA()  # or ViaiQA("https://api.example.com", api_key="...")

# Online guardrail inside your RAG pipeline, before the answer reaches the user
verdict = qa.guard(question, contexts, answer)
if verdict["action"] == "block":          # contradicts the documents (e.g. wrong dose)
    answer = "Xin lỗi, tôi chưa thể trả lời chắc chắn câu này."
elif verdict["action"] == "regenerate":   # has sentences the documents don't support
    answer = regenerate(question, contexts, avoid=[c["text"] for c in verdict["failing_claims"]])

# Full per-sentence audit, optionally with a reference answer for context_recall
audit = qa.evaluate(question, contexts, answer, ground_truth=reference)
audit["faithfulness"], audit["claims"], audit["rag_metrics"]

qa.judge(audit["id"])                     # Tier 2 Claude agent (paid call on the server)
qa.feedback(audit["id"], "intrinsic")     # or "CORRECT"; feeds retraining

batch = qa.upload_dataset("eval.jsonl")   # {"question", "contexts", "answer", "ground_truth"?} per line
done = qa.wait_for_batch(batch["batch_id"])
done["mean_faithfulness"]
```

API errors raise `ViaiQAError`, with `status_code` and `detail`.

## MCP server

`viai-qa-mcp` serves MCP over stdio. Add it to Claude Code:

```bash
claude mcp add viai-qa -e VIAI_QA_URL=http://localhost:8080 -e VIAI_QA_API_KEY=... -- viai-qa-mcp
```

Or add it to any MCP client config:

```json
{ "mcpServers": { "viai-qa": { "command": "viai-qa-mcp", "env": { "VIAI_QA_URL": "http://localhost:8080" } } } }
```

| Tool | What it does |
|---|---|
| `guard_rag_answer` | `pass` / `regenerate` / `block` plus the failing sentences |
| `evaluate_rag_response` | Per-sentence verdicts with the supporting chunk number, faithfulness and retrieval metrics |
| `get_audit` | A stored audit (read-only) |
| `deep_audit` | Runs the Claude judge agent on an audit (paid on the server; `only_doubtful` by default) |
| `evaluate_dataset` | Uploads a local `.jsonl`/`.csv` file and waits for the summary and failing items |
| `list_failing_claims` | Recent ungrounded answers with their failing sentences (read-only) |
| `submit_feedback` | Records a human verdict for retraining |

Results are trimmed to what an agent needs to act on (verdicts, failing sentences, ids), so they don't fill the caller's context with every NLI score. `get_audit` returns the full detail through the SDK.

Tests: `tests/integration/test_sdk_mcp.py` drives the SDK and the MCP tools against the real FastAPI app.
