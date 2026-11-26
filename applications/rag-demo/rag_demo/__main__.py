# applications/rag-demo/rag_demo/__main__.py
"""
  python -m rag_demo ingest                 # ViMedAQA passages -> rag_passages (RAG_DATABASE_URL)
  python -m rag_demo ask "Uống Paracetamol tối đa bao nhiêu?"
  python -m rag_demo serve                  # POST /ask on :8100
Needs ANTHROPIC_API_KEY (answers) and a running ViAI-QA API (VIAI_QA_URL, default http://localhost:8080).
"""
import argparse
import glob
import json


def build_chat():
    from viai_qa import ViaiQA

    from rag_demo.chat import GuardedRagChat
    from rag_demo.generator import ClaudeGenerator
    from rag_demo.retriever import TfidfRetriever
    from rag_demo.store import engine_from_env, load_passages

    return GuardedRagChat(TfidfRetriever(load_passages(engine_from_env())), ClaudeGenerator(), ViaiQA())


def create_app():
    from fastapi import FastAPI
    from pydantic import BaseModel, Field

    app = FastAPI(title="ViAI-QA medical RAG demo")
    chat = build_chat()

    class Ask(BaseModel):
        question: str = Field(..., min_length=1, max_length=2000)

    @app.post("/ask")
    def ask(body: Ask):
        return chat.ask(body.question)

    return app


def main():
    ap = argparse.ArgumentParser(prog="rag_demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest")
    a = sub.add_parser("ask"); a.add_argument("question")
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8100)
    args = ap.parse_args()

    if args.cmd == "ingest":
        from rag_demo.store import engine_from_env, ingest_vimedaqa
        n = ingest_vimedaqa(engine_from_env(), sorted(glob.glob("data/raw/vimedaqa/*.parquet")))
        print(f"[INFO] {n} new passages stored")
    elif args.cmd == "ask":
        print(json.dumps(build_chat().ask(args.question), ensure_ascii=False, indent=2))
    else:
        import uvicorn
        uvicorn.run(create_app(), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
