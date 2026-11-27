# tests/demo/test_viai_text_parity.py
"""R1 (docs/GO_RUST_MIGRATION_PLAN.md): the Rust TF-IDF index must equal scikit-learn's char_wb TF-IDF."""
from types import SimpleNamespace as NS

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from rag_demo.retriever import TfidfRetriever

viai_text = pytest.importorskip("viai_text", reason="Rust extension not built (pip install ./machine-learning/viai_text)")

CORPUS = [
    "Theo Đông Y, Xuyên tâm liên được gọi là khổ đởm thảo, nhất kiến hỷ. Bài thuốc có vị đắng – tính hàn.",
    "Cần bảo quản thuốc Comiaryl ở nơi khô thoáng, nhiệt độ dưới 30°C. Tránh ánh sáng.",
    "Paracetamol hạ sốt cho người lớn dùng liều 500mg đến 1000mg mỗi lần, tối đa 4g mỗi ngày.",
    "Thời điểm dùng thuốc: uống ngay trước hoặc trong bữa ăn. Nên uống nguyên viên thuốc.",
    "Vitamin D3   Aquadetrim\tnên được bảo quản\nở nơi khô ráo, thoáng mát.",   # odd whitespace
    "A",                                                                            # one-char word
    "   ",                                                                          # no n-grams at all
]
QUERIES = ["Uống thuốc Comiaryl đúng cách như thế nào?", "Xuyên tâm liên theo Đông Y có vị gì?",
           "liều paracetamol tối đa", "VITAMIN d3 bảo quản", "a", "xyz không có trong kho", ""]


def sklearn_scores(query):
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
    m = vec.fit_transform(CORPUS)
    return vec, (vec.transform([query]) @ m.T).toarray()[0]


@pytest.mark.parametrize("query", QUERIES)
def test_scores_equal_scikit_learn(query):
    vec, want = sklearn_scores(query)
    idx = viai_text.CharTfidfIndex(CORPUS, 2, 4)
    assert idx.n_features == len(vec.vocabulary_)
    np.testing.assert_allclose(idx.scores(query), want, atol=1e-6)
    top = [i for i, _ in idx.search(query, 3)]
    assert set(top) == {int(i) for i in want.argsort()[::-1][:3] if want[i] > 0}


def test_retriever_backends_agree(monkeypatch):
    docs = [NS(text=t, title="", source_url="") for t in CORPUS]
    rust = TfidfRetriever(docs)
    monkeypatch.setenv("RAG_RETRIEVER", "python")
    py = TfidfRetriever(docs)
    assert (rust.backend, py.backend) == ("rust", "sklearn")
    for q in QUERIES:
        a, b = rust.search(q, k=3), py.search(q, k=3)
        assert [h.text for h in a] == [h.text for h in b] or {h.text for h in a} == {h.text for h in b}
        np.testing.assert_allclose([h.score for h in a], [h.score for h in b], atol=1e-6)


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        viai_text.CharTfidfIndex([], 2, 4)
    with pytest.raises(ValueError):
        viai_text.CharTfidfIndex(["x"], 2, 5)
