# Medical RAG demo, guarded by ViAI-QA

A small Vietnamese medical chatbot that shows the evaluation platform at work. It answers from ViMedAQA passages and lets ViAI-QA check the answer before it reaches the user:

1. **Retrieve** the top 3 passages: character n-gram TF-IDF over `rag_passages` (Postgres, or SQLite locally).
2. **Generate** with Claude: `claude-haiku-5-5`, effort `low`, told to use only the documents.
3. **Guard** through the `viai_qa` SDK (`POST /api/v1/audits/rag/guard`):
   - `pass` → the answer is returned.
   - `regenerate` → one retry with the same documents. The retry turn lists the unsupported sentences; the conversation is append-only.
   - `block` (contradicts the documents) or a refusal → a safe fallback answer plus the sources.

Every guard call stores an audit, so each turn can be inspected in the ViAI-QA trace view (history sidebar).

## Run

```bash
pip install ./client-sdk/python ./applications/rag-demo
export ANTHROPIC_API_KEY=...                      # answers
export VIAI_QA_URL=http://localhost:8080          # running ViAI-QA API
export RAG_DATABASE_URL=postgresql://user:password@localhost:5432/viai_qa   # optional; default artifacts/local/rag_demo.db

python -m rag_demo ingest                          # 17,958 ViMedAQA passages, about 1 s
python -m rag_demo ask "Uống thuốc Comiaryl đúng cách như thế nào?"
python -m rag_demo serve                           # POST /ask {"question": "..."} on :8100
```

`RAG_MODEL` and `RAG_EFFORT` override the model and effort.

## Why TF-IDF, not pgvector (yet)

Measured on ViMedAQA test (400 questions, 2,125 passages, 2026-11-26):

| Retriever | recall@1 | recall@3 | recall@5 |
|---|---|---|---|
| char n-gram TF-IDF | **0.60** | **0.80** | **0.83** |
| pgvector + LSA 512 | 0.49 | 0.67 | 0.74 |
| pgvector + mean-pooled PhoBERT | 0.19 | 0.31 | 0.36 |

Raw PhoBERT embeddings are not trained for retrieval. A Vietnamese bi-encoder (e.g. `bkai-foundation-models/vietnamese-bi-encoder`) could not be downloaded on the current network. `Retriever` is a protocol, so a `PgVectorRetriever` can replace `TfidfRetriever` by adding an `embedding vector(768)` column to `rag_passages`.

Tests: `tests/demo/test_rag_demo.py`. Claude is faked with a scripted client; the guard runs against the real API.
