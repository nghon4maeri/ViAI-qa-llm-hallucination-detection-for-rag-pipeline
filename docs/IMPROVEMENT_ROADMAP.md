# ViAI-QA Improvement Roadmap: RAG Evaluation & Guardrail Platform

**Status:** Phase 0 done (see [PHASE_0_FOUNDATION_FIX_REPORT.md](PHASE_0_FOUNDATION_FIX_REPORT.md)). Phase 1 done. Medical dataset built; the baseline is blocked on downloading the Qwen weights (see [MEDICAL_DOMAIN.md](MEDICAL_DOMAIN.md)). Phase 5 first pass done.

## Domain focus

**Healthcare (Vietnamese).** The platform stays domain-agnostic, but data, benchmarks, fine-tuning and the demo target medical RAG. See [MEDICAL_DOMAIN.md](MEDICAL_DOMAIN.md).

Revised order: **medical dataset (ViMedHallu) ✅ → baseline + fine-tune → P5 trace view → P2 agent (+ LLM-written hard split) → P3 MCP → P6 medical RAG demo.**

## Goal

Move ViAI-QA from auditing a single `(context, prompt, response)` triple to
evaluating a **whole RAG turn**: `question`, retrieved `contexts[]` and `answer`.
The platform should say *which sentence* is hallucinated, *against which chunk*,
and *why*.

The existing ViHallu detector stays the core "fast judge". An LLM agent is a
second tier that only handles hard cases.

**Constraint:** nothing built so far is removed. Every module below gets reused
or extended.

```
RAG pipeline ──SDK / REST / MCP──▶ ViAI-QA Backend (FastAPI, existing modules)
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                      ▼
      Claim splitter       Tier 1: ViHallu detector   Tier 2: Judge agent (LLM, tool calling)
      (underthesea/LLM)    (HallucinationPipeline,    tools: detect_hallucination (Tier 1),
                            KServe)                   nli_check, extract_entities,
                            per claim × chunk         find_supporting_chunk, (opt) web_search
                                    │
                                    └── escalate on low confidence / guardrail conflict
                                                   ▼
                     RAG metrics + claim-level verdicts + rationale
                     → audits / batches / feedback (Postgres)
                     → Prometheus / Grafana / Evidently / MLflow / Jaeger
```

## Reuse map

| Existing piece | New role |
|---|---|
| `HallucinationPipeline` (PhoBERT, NLI, NER, Qwen, LightGBM, guardrails) | Tier 1 claim scorer. NLI/NER become agent tools |
| `EvaluationEngine` Protocol + adapters | Add `RagEvaluationEngine` and `JudgeAgentEngine` behind the same interface |
| audits / batches / feedback / projects / api_keys | Kept. Audits gain `contexts[]` and `claims[]` |
| `/api/predict`, `/api/v1/audits` | Kept. A single context is a RAG turn with one chunk |
| Qwen judge prompt (`_get_vistral_probs`) | Local/offline LLM fallback for the agent |
| DVC + MLflow + feedback table | Flywheel: feedback and synthetic data → retrain → `auto_promote_registry.py` |
| KServe + `kserve_adapter.py` | Detector served separately from the API |
| Prometheus / Grafana / Evidently / Jaeger | RAG metrics, drift on faithfulness, one span per agent tool call |
| SvelteKit frontend | Kept and redesigned (Phase 5) |

## Phases

### Phase 0: Foundation fixes ✅
Commit the ORM models, fix the train/serve feature skew, use the 5-fold
ensemble, add a regression test. Details in the Phase 0 report.

### Phase 1: RAG evaluation core ✅

**Done:**
- `POST /api/v1/audits/rag` (`question`, `contexts[]`, `answer`). It lives under `/audits` instead of the planned `/rag/evaluate`, so RAG audits reuse history, feedback and metrics unchanged.
- `backend/app/evaluation/rag.py`: punctuation-based claim split. Each claim is scored against each chunk by the existing `EvaluationEngine` through `evaluation_cache`. A claim counts as supported if any chunk says `no`; otherwise it takes the verdict of the most related chunk (lowest NLI neutral).
- Overall label: `no` only if every claim is supported, otherwise `intrinsic` takes precedence over `extrinsic`. `faithfulness` = share of supported claims.
- Migration `003_add_rag_fields`: `audit_runs.contexts`, `claims`, `faithfulness`.
- `RagMetrics`, stored in `audit_runs.rag_metrics` (`ground_truth` gets its own column):
  - `context_utilization`: share of chunks that support at least one claim (retrieval noise). Needs no embeddings.
  - `context_recall`: share of `ground_truth` sentences that the chunks support. Same detector, used in the other direction.
  - `answer_relevance`, `context_relevance[]`: question cosines from engines that implement the optional `EmbeddingEngine.embed()`; `None` otherwise. With PhoBERT they separate related from random text (AUC 0.85 question–answer, 0.77 question–context, measured on 150 ViHallu rows) but are **not calibrated**: compare across runs, don't threshold. Upgrade: a Vietnamese bi-encoder.
- RAG batches: `POST /api/v1/batches/upload` with a `.jsonl` file (one `{question, contexts, answer, ground_truth?}` per line; a bad line returns 400 with its line number). Batch detail adds `faithfulness` per item and `mean_faithfulness`; CSV export adds a `faithfulness` column.
- Tests: `tests/unit/test_rag_evaluation.py`, `tests/integration/test_batches_api.py`.

**Not done:** answer correctness against `ground_truth`. It needs a semantic-equivalence judge, so it is planned for the Phase 2 agent.

Original plan:
- `RagEvaluationInput`: `question`, `contexts: list[str]`, `answer`, optional `ground_truth`; Alembic migration `003`.
- Claim splitting with `underthesea` sentence split (LLM split optional).
- Score each claim against each chunk with the Tier 1 detector; keep the best supporting chunk.
- Metrics: faithfulness (share of claims labelled `no`), intrinsic/extrinsic breakdown, context relevance, answer relevance, context precision/recall when `ground_truth` exists.
- Endpoints: `POST /api/v1/rag/evaluate`, `POST /api/v1/rag/batches` (JSONL/CSV).

### Phase 2: LLM judge agent (tool calling) ✅ (built; not yet run against the live API)

**Done (2026-11-25):**
- `backend/app/evaluation/judge_agent.py` is the Tier 2 Claude agent. It is a manual tool loop (every call is recorded for the UI and traced with OpenTelemetry when available) and has three tools:
  - `detect_hallucination(claim, context_index)`: the Tier 1 detector through `evaluation_cache`
  - `check_numbers(claim, context_index)`: dose/duration/percentage comparison, digits inside names ignored
  - `submit_verdict` (strict schema): ends the loop
- Escalation:
  - `POST /api/v1/audits/{id}/judge?only_doubtful=true|false` runs a deep audit on demand; the UI button sends `only_doubtful=true`.
  - Automatic escalation runs when `JUDGE_AUTO_ESCALATE=true` **and** a claim has Tier 1 confidence below `JUDGE_ESCALATE_BELOW` (0.75) or a guardrail overrode LightGBM. It is off by default. A judge failure never fails the Tier 1 audit.
- The verdict is stored in `audit_runs.judge` (migration `004`). Overall label and faithfulness use the Tier 1 aggregation rule, so the two tiers are comparable.
- Refusals and incomplete runs leave Tier 1 standing (`status = refused | incomplete`).
- UI: `JudgePanel.svelte` in the trace view shows the agent's summary, each overruled sentence (Tier 1 label struck through, new label, reason, evidence chunk), the tool-call trail, and the token usage.
- Tests: `tests/unit/test_judge_agent.py` (8 tests) runs a scripted fake client, so it makes no API calls.

**Cost-first configuration (user decision):**

| Lever | Setting |
|---|---|
| Model | `claude-haiku-5-5` ($0.10 / $0.50 per 1M tokens, ~40x cheaper than `claude-opus-5-5` at $4 / $20) |
| Effort | `low` |
| Scope | Only the claims Tier 1 is unsure of; confident claims keep their Tier 1 label |
| Prompt caching | Top-level `cache_control`. Each loop turn resends the history, so the cached prefix makes later turns ~10x cheaper on input. Haiku 5.5's minimum cacheable prefix is 512 tokens; system + tools is ~1.2k |
| Escalation | On demand, or automatic only when `JUDGE_AUTO_ESCALATE=true` |

Haiku 5.5 has no server-side refusal fallback, so the `fallbacks` parameter is sent only for models that support it (Opus 5.5 / Opus 5 / Fable 5.1 / Sonnet 5.5).

**Estimated cost per escalation (not yet measured):** about 3 loop turns, ~8k input tokens in total (much of it cached) and ≤1.5k output tokens, gives **≈ $0.0015 on Haiku 5.5** (about $1.5 per 1,000 escalations) versus ≈ $0.06 on Opus 5.5. Verify against the `input_tokens` / `output_tokens` stored on each verdict once an API key is configured.

**Next:**
1. Run the judge on a ViMedHallu validation slice. Compare Tier 1 alone with Tier 1 + judge on F1, cost and latency, and log the results to MLflow.
2. Raise the model or effort only if the measurement shows Haiku/low misses too much.
3. A Batch API run (50% cheaper) for offline dataset benchmarks.

**Original plan:**
- Runs only when Tier 1 is unsure (low confidence, guardrail vs LightGBM conflict) or on "deep audit".
- Tools wrap existing functions: `detect_hallucination`, `nli_check`, `extract_entities`, `find_supporting_chunk`, optional `web_search` (to separate *extrinsic but true* from *fabricated*).
- Output: verdict, Vietnamese rationale, cited evidence. Every tool call is stored and traced.
- Pluggable provider: hosted API or local Qwen via vLLM/Ollama.
- Benchmark Tier 1 alone vs Tier 1 + agent (F1, cost, latency) and log to MLflow.

### Phase 3: MCP server and SDK
- MCP server `viai-qa-mcp`: `evaluate_rag_response`, `evaluate_dataset`, `get_audit`, `submit_feedback`, `list_failing_claims`.
- Thin Python SDK plus LangChain/LlamaIndex callback, on top of the REST API and API keys.
- Online guardrail `POST /api/v1/rag/guard` → `pass / block / regenerate`.

### Phase 4: Data flywheel
- Synthetic data agent: correct QA plus controlled intrinsic/extrinsic corruptions from Vietnamese documents → DVC dataset.
- Merge with `audit_feedback` → `train` stage → `auto_promote_registry.py`.

### Phase 5: UI/UX redesign ✅ (first pass)

**Done (2026-11-25):**
- **RAG trace view** (`TraceView.svelte`), the new default tab. The answer is shown as a reviewed passage: each sentence is highlighted by verdict (green = backed by a source, red solid underline = contradicts, amber dashed underline = not in the sources) and footnoted `[n]` to the chunk behind the verdict. Next to it, the retrieved chunks show "backs n sentences" or "not used", plus relevance. Clicking a sentence shows its NLI/NER/guardrail breakdown. Header figures: faithfulness, chunks used, ground-truth coverage, question relevance (an uncalibrated cosine, labelled as such).
- **Restyled existing screens** without changing features: history, single check, batch (now accepts `.jsonl` and shows faithfulness), feedback.
- **Design direction** (unslop + ui-ux-pro-max skills): a pharmacist's desk, i.e. warm paper, ink and a reviewer's highlighter. Light theme with a system dark mode, one accent (`#0e5f6b` pharmacy ink), Be Vietnam Pro + IBM Plex Mono (both cover Vietnamese; the suggested Fira Code does not). Tokens live in `frontend/src/app.css`.
- **Bugs fixed along the way:**
  - The breakdown always showed 0%: the frontend read `nli_*` / `ner_*` fields that the backend never sends.
  - The "grounded" history filter sent `no_hallucination` instead of `no`, so it was always empty.
  - A runtime dependency on an external noise image (`grainy-gradients.vercel.app`).
  - A static "Online" badge that showed nothing real.
- Feedback now stores corrected labels in the model's own vocabulary (`no`/`intrinsic`/`extrinsic`). Older rows use `no_hallucination`.
- Checks: `svelte-check` 0 errors, `vite build` OK, `src/lib/labels.spec.ts` passes. `src/routes/page.svelte.spec.ts` was already failing before this work (browser-mode test under the jsdom config).

**Original plan:**
- Keep SvelteKit. Use `unslop` and `ui-ux-pro-max` as design skills; port `animate-ui` patterns with `svelte/motion` or `motion`.
- New views: RAG trace view (sentence highlights linked to evidence chunks), agent timeline, eval-run dashboard. Existing views are restyled.

### Phase 6: End-to-end demo
- Small Vietnamese RAG on pgvector (existing Postgres) that calls ViAI-QA through the SDK.

## Order

P0 → P1 → P5 (trace view only) → P2 → P3 → P4 → P6.
P0 + P1 + the trace view already make a complete project; the rest are upgrades.

## Known risks
- Claim × chunk scoring multiplies detector calls; needs batching and cache.
- Four transformer models on CPU are slow; Tier 1 should move to KServe/GPU.
- The live server uses Qwen2.5-1.5B for the `prob_*` features, but the model was trained on precomputed Vistral probabilities (see Phase 0 report).
