# client-sdk/python/viai_qa/client.py
"""Thin client over the ViAI-QA REST API. Responses are the API's JSON, returned as dicts."""
import os
import time
from typing import Any, Dict, List, Optional

import requests


class ViaiQAError(Exception):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(f"ViAI-QA API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ViaiQA:
    """
    client = ViaiQA("http://localhost:8080", api_key="...")
    verdict = client.guard(question, contexts, answer)
    if verdict["action"] != "pass": ...
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        session: Optional[Any] = None,
    ):
        self.base_url = (base_url or os.getenv("VIAI_QA_URL", "http://localhost:8080")).rstrip("/")
        self.api_key = api_key or os.getenv("VIAI_QA_API_KEY")
        self.timeout = timeout
        # Anything with requests' .request() signature works, e.g. FastAPI's TestClient in tests
        self._http = session or requests.Session()

    def _call(self, method: str, path: str, **kwargs) -> Any:
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        res = self._http.request(method, f"{self.base_url}/api/v1{path}", headers=headers, timeout=self.timeout, **kwargs)
        if res.status_code >= 400:
            try:
                detail = res.json().get("detail")
            except ValueError:
                detail = res.text
            raise ViaiQAError(res.status_code, detail)
        return res.json()

    # RAG turns
    def evaluate(self, question: str, contexts: List[str], answer: str,
                 ground_truth: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Score every answer sentence against every chunk. Returns the stored audit."""
        return self._call("POST", "/audits/rag", json=_rag_body(question, contexts, answer, ground_truth, project_id))

    def guard(self, question: str, contexts: List[str], answer: str,
              ground_truth: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Online check before showing an answer: {"action": "pass" | "regenerate" | "block", ...}."""
        return self._call("POST", "/audits/rag/guard", json=_rag_body(question, contexts, answer, ground_truth, project_id))

    def judge(self, audit_id: str, only_doubtful: bool = True) -> Dict[str, Any]:
        """Tier 2 deep audit by the Claude judge agent (paid API call on the server)."""
        return self._call("POST", f"/audits/{audit_id}/judge", params={"only_doubtful": str(only_doubtful).lower()})

    # Single triples and history
    def evaluate_single(self, context: str, prompt: str, response: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        body = {"context": context, "prompt": prompt, "response": response}
        if project_id:
            body["project_id"] = project_id
        return self._call("POST", "/audits", json=body)

    def get_audit(self, audit_id: str) -> Dict[str, Any]:
        return self._call("GET", f"/audits/{audit_id}")

    def list_audits(self, label: Optional[str] = None, page: int = 1, page_size: int = 20,
                    project_id: Optional[str] = None) -> Dict[str, Any]:
        params = {"page": page, "page_size": page_size}
        if label:
            params["label"] = label
        if project_id:
            params["project_id"] = project_id
        return self._call("GET", "/audits", params=params)

    def feedback(self, audit_id: str, label: str, comment: Optional[str] = None) -> Dict[str, Any]:
        """label: "CORRECT", or the corrected verdict "no" | "intrinsic" | "extrinsic"."""
        return self._call("POST", f"/audits/{audit_id}/feedback",
                          json={"feedback_label": label, "corrected_label": None if label == "CORRECT" else label, "comment": comment})

    # Datasets
    def upload_dataset(self, path: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        """.jsonl (one RAG turn per line) or .csv (context, prompt, response). Processing runs in the background."""
        with open(path, "rb") as f:
            data = {"project_id": project_id} if project_id else None
            return self._call("POST", "/batches/upload", files={"file": (os.path.basename(path), f)}, data=data)

    def get_batch(self, batch_id: str) -> Dict[str, Any]:
        return self._call("GET", f"/batches/{batch_id}")

    def wait_for_batch(self, batch_id: str, poll_seconds: float = 2.0, timeout: float = 3600.0) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            batch = self.get_batch(batch_id)
            if batch["status"] in ("COMPLETED", "FAILED"):
                return batch
            if time.monotonic() > deadline:
                raise TimeoutError(f"Batch {batch_id} still {batch['status']} after {timeout}s")
            time.sleep(poll_seconds)


def _rag_body(question, contexts, answer, ground_truth, project_id) -> Dict[str, Any]:
    body: Dict[str, Any] = {"question": question, "contexts": list(contexts), "answer": answer}
    if ground_truth:
        body["ground_truth"] = ground_truth
    if project_id:
        body["project_id"] = project_id
    return body
