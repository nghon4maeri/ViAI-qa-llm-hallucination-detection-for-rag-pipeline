# applications/rag-demo/rag_demo/chat.py
"""Retrieve -> generate -> ViAI-QA guard -> one guided retry -> answer or safe fallback."""
from typing import Any, Dict, List

from rag_demo.generator import ClaudeGenerator
from rag_demo.retriever import Retriever

FALLBACK = ("Xin lỗi, tôi chưa thể trả lời chắc chắn câu hỏi này dựa trên tài liệu hiện có. "
            "Bạn nên hỏi trực tiếp bác sĩ hoặc dược sĩ.")


class GuardedRagChat:
    def __init__(self, retriever: Retriever, generator: ClaudeGenerator, qa, k: int = 3, max_attempts: int = 2):
        self.retriever = retriever
        self.generator = generator
        self.qa = qa  # viai_qa.ViaiQA
        self.k = k
        self.max_attempts = max_attempts

    def ask(self, question: str) -> Dict[str, Any]:
        hits = self.retriever.search(question, k=self.k)
        sources = [{"text": h.text, "title": h.title, "url": h.source_url, "score": round(h.score, 3)} for h in hits]
        if not hits:
            return {"answer": FALLBACK, "action": "no_sources", "attempts": [], "sources": []}

        contexts = [h.text for h in hits]
        messages: List[Dict[str, Any]] = [self.generator.first_turn(question, contexts)]
        attempts = []
        for _ in range(self.max_attempts):
            draft = self.generator.generate(messages)
            if draft is None:
                attempts.append({"answer": None, "action": "refused"})
                break
            verdict = self.qa.guard(question, contexts, draft)
            attempts.append({"answer": draft, "action": verdict["action"], "faithfulness": verdict["faithfulness"],
                             "audit_id": verdict["audit_id"],
                             "failing": [c["text"] for c in verdict["failing_claims"]]})
            if verdict["action"] == "pass":
                return {"answer": draft, "action": "pass", "attempts": attempts, "sources": sources}
            if verdict["action"] == "block":
                break  # contradicts the documents: never retry into a dangerous answer
            # regenerate: same documents, told exactly which sentences had no support
            failing = "\n".join(f"- {t}" for t in attempts[-1]["failing"])
            messages += [
                {"role": "assistant", "content": draft},
                {"role": "user", "content": "Các câu sau không có trong tài liệu, hãy viết lại câu trả lời "
                                            f"chỉ dùng thông tin trong tài liệu và bỏ những câu này:\n{failing}"},
            ]
        return {"answer": FALLBACK, "action": attempts[-1]["action"] if attempts else "error",
                "attempts": attempts, "sources": sources}
