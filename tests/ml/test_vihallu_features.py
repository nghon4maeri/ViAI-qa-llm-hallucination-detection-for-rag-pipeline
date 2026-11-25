# tests/ml/test_vihallu_features.py
import numpy as np
import pytest

import vihallu_features as vf


def test_layout_constants():
    assert vf.FEATURE_DIM == 778
    assert list(vf.FEATURE_GROUPS) == ["phobert_embeddings", "simple_features", "cosine_similarity", "vistral_probs"]
    assert [vf.LABEL_MAP[l] for l in vf.LABELS] == [0, 1, 2]


@pytest.mark.parametrize("raw, clean", [(None, ""), (float("nan"), ""), ("  Hà Nội ", "Hà Nội"), (12, "12")])
def test_normalize(raw, clean):
    assert vf.normalize(raw) == clean


def test_build_feature_matrix_layout():
    rng = np.random.default_rng(0)
    emb = rng.normal(size=(2, 768))
    probs = np.array([[0.7, 0.2, 0.1], [0.1, 0.1, 0.8]])
    X = vf.build_feature_matrix(emb, ["ngữ cảnh một", " ab "], ["câu hỏi", "q"], ["trả lời", "r"], probs, emb.mean(axis=0))
    assert X.shape == (2, 778)
    np.testing.assert_array_equal(X[:, :768], emb)
    assert list(X[1, 768:774]) == [2, 1, 1, 1, 1, 1]  # " ab " is stripped before counting
    assert -1.0 <= X[0, 774] <= 1.0
    np.testing.assert_array_equal(X[:, 775:], probs)


def test_build_feature_matrix_rejects_wrong_shapes():
    with pytest.raises(ValueError):
        vf.build_feature_matrix(np.zeros((1, 10)), ["c"], ["p"], ["r"], np.zeros((1, 3)), np.zeros(10))
    with pytest.raises(ValueError):
        vf.build_feature_matrix(np.zeros((1, 768)), ["c"], ["p"], ["r"], np.zeros((1, 2)), np.zeros(768))


def test_masked_mean_ignores_padding():
    torch = pytest.importorskip("torch")
    hidden = torch.tensor([[[1.0, 1.0], [3.0, 3.0], [100.0, 100.0]]])  # last token is padding
    mask = torch.tensor([[1, 1, 0]])
    assert vf.masked_mean(hidden, mask).tolist() == [[2.0, 2.0]]
