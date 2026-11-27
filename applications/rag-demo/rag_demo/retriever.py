# applications/rag-demo/rag_demo/retriever.py
import os
from dataclasses import dataclass
from typing import List, Protocol, Sequence, Tuple


@dataclass
class Hit:
    text: str
    score: float
    title: str = ""
    source_url: str = ""


class Retriever(Protocol):
    def search(self, query: str, k: int = 3) -> List[Hit]: ...


def _rust_index():
    """viai_text (machine-learning/viai_text, Rust) when installed, unless RAG_RETRIEVER=python."""
    if os.getenv("RAG_RETRIEVER", "auto").lower() == "python":
        return None
    try:
        import viai_text
    except ImportError:
        return None
    return viai_text.CharTfidfIndex


class TfidfRetriever:
    """
    Character n-gram TF-IDF. On ViMedAQA test it reaches recall@3 = 0.79, against 0.31 for mean-pooled
    PhoBERT and 0.67 for 512-dim LSA in pgvector (measured 2026-11-26), so it is the default.

    Two identical implementations (docs/GO_RUST_MIGRATION_PLAN.md R1): the Rust index from viai_text when
    it is installed (17,835 passages: build 0.65 s, query 0.8 ms) and scikit-learn otherwise (4.4 s,
    64 ms). Same n-grams, idf and scores (max difference 1e-8); RAG_RETRIEVER=python forces scikit-learn.
    shortcut: in-memory index rebuilt at startup; swap in a pgvector retriever with a Vietnamese
    bi-encoder once one can be downloaded.
    """

    def __init__(self, passages: Sequence):
        if not passages:
            raise ValueError("No passages to index; run `python -m rag_demo ingest` first")
        self.passages = list(passages)
        texts = [p.text for p in self.passages]
        rust = _rust_index()
        if rust is not None:
            self.backend = "rust"
            self._index = rust(texts, 2, 4)
        else:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self.backend = "sklearn"
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
            self.matrix = self.vectorizer.fit_transform(texts)

    def _top(self, query: str, k: int) -> List[Tuple[int, float]]:
        if self.backend == "rust":
            return self._index.search(query, k)
        scores = (self.vectorizer.transform([query]) @ self.matrix.T).toarray()[0]
        return [(int(i), float(scores[i])) for i in scores.argsort()[::-1][:k] if scores[i] > 0]

    def search(self, query: str, k: int = 3) -> List[Hit]:
        return [Hit(self.passages[i].text, score, self.passages[i].title or "", self.passages[i].source_url or "")
                for i, score in self._top(query, k)]
