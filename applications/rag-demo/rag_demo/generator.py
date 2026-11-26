# applications/rag-demo/rag_demo/generator.py
"""Answer generation with Claude. Cost-first default: claude-haiku-5-5 at low effort (RAG_MODEL / RAG_EFFORT override)."""
import os
from typing import Any, Dict, List, Optional

SYSTEM_PROMPT = """You are the answer engine of a Vietnamese medical information chatbot. Answer the user's question in Vietnamese using only the numbered documents provided with it; they were retrieved for this question and are the only facts you may use. Write two to four plain sentences, the way a pharmacist would explain it to a patient, without lists, headings or citation markers.

If the documents do not contain the answer, say in one sentence that the available documents do not cover it and suggest asking a doctor or pharmacist. Do not add doses, durations, side effects, warnings or recommendations that the documents do not state, even if you believe them to be true: a separate checker compares every sentence you write with the documents, and anything it cannot find there is treated as an error."""


class ClaudeGenerator:
    def __init__(self, client=None, model: Optional[str] = None, effort: Optional[str] = None):
        self._client = client
        self.model = model or os.getenv("RAG_MODEL", "claude-haiku-5-5")
        self.effort = effort or os.getenv("RAG_EFFORT", "low")

    @property
    def client(self):
        if self._client is None:
            import anthropic  # only needed when the demo really generates

            self._client = anthropic.Anthropic()
        return self._client

    @staticmethod
    def first_turn(question: str, contexts: List[str]) -> Dict[str, Any]:
        docs = "\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts))
        return {"role": "user", "content": f"<documents>\n{docs}\n</documents>\n\n<question>\n{question}\n</question>"}

    def generate(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Returns the answer text, or None when the model declines (stop_reason "refusal")."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={"effort": self.effort},
        )
        if response.stop_reason == "refusal":
            return None
        return "".join(b.text for b in response.content if b.type == "text").strip() or None
