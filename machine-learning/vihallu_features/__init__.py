# machine-learning/vihallu_features/__init__.py
"""
The one feature builder for the ViHallu LightGBM detector.

Training (pipelines/train.py), batch inference (pipelines/infer.py), the API (HallucinationPipeline)
and the evaluation scripts all import this module, so the 778-dim layout cannot drift between them
again (Phase 0 found three separate copies, two of them wrong).

Layout, in order:
  [0:768]   mean-pooled PhoBERT embedding of "context prompt response" (padding masked out)
  [768:774] char length and word count of context, prompt, response
  [774]     cosine similarity of the embedding to the training-set centroid
  [775:778] LLM probabilities prob_no, prob_extrinsic, prob_intrinsic

Install: pip install ./machine-learning  (numpy + scikit-learn only; torch is used through the tensors passed in)
"""
from typing import Any, List, Sequence

import numpy as np

# LightGBM class ids
LABEL_MAP = {"extrinsic": 0, "no": 1, "intrinsic": 2}
LABELS = ["extrinsic", "no", "intrinsic"]

EMBEDDING_DIM = 768
MAX_LENGTH = 256  # PhoBERT tokens; longer inputs are truncated
LLM_PROB_COLUMNS = ["prob_no", "prob_extrinsic", "prob_intrinsic"]
FEATURE_GROUPS = {
    "phobert_embeddings": EMBEDDING_DIM,
    "simple_features": 6,
    "cosine_similarity": 1,
    "vistral_probs": len(LLM_PROB_COLUMNS),
}
FEATURE_DIM = sum(FEATURE_GROUPS.values())  # 778


def normalize(text: Any) -> str:
    """Missing values become "", surrounding whitespace is dropped (no ViHallu training row has any)."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    return str(text).strip()


def embedding_text(context: Any, prompt: Any, response: Any) -> str:
    """The text PhoBERT embeds for one sample."""
    return f"{normalize(context)} {normalize(prompt)} {normalize(response)}"


def masked_mean(last_hidden_state, attention_mask):
    """Mean over real tokens only. Works on torch tensors (B, T, H) / (B, T); returns (B, H)."""
    mask = attention_mask.unsqueeze(-1).to(last_hidden_state.dtype)
    return (last_hidden_state * mask).sum(dim=1) / mask.sum(dim=1)


def simple_features(context: Any, prompt: Any, response: Any) -> List[int]:
    feats: List[int] = []
    for text in (context, prompt, response):
        t = normalize(text)
        feats.extend([len(t), len(t.split())])
    return feats


def centroid_cosine(embeddings: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    """(N, 1) cosine similarity of each embedding to the training-set centroid."""
    from sklearn.metrics.pairwise import cosine_similarity

    return cosine_similarity(embeddings, np.asarray(centroid).reshape(1, -1))


def build_feature_matrix(
    embeddings: np.ndarray,
    contexts: Sequence[Any],
    prompts: Sequence[Any],
    responses: Sequence[Any],
    llm_probs: np.ndarray,
    centroid: np.ndarray,
) -> np.ndarray:
    """(N, 778) matrix. llm_probs columns must follow LLM_PROB_COLUMNS."""
    embeddings = np.asarray(embeddings)
    llm_probs = np.asarray(llm_probs)
    if embeddings.shape[1] != EMBEDDING_DIM or llm_probs.shape[1] != len(LLM_PROB_COLUMNS):
        raise ValueError(f"Expected (N, {EMBEDDING_DIM}) embeddings and (N, 3) LLM probs, got {embeddings.shape} and {llm_probs.shape}")
    simple = np.array([simple_features(c, p, r) for c, p, r in zip(contexts, prompts, responses)])
    X = np.hstack([embeddings, simple, centroid_cosine(embeddings, centroid), llm_probs])
    if X.shape[1] != FEATURE_DIM:
        raise ValueError(f"Feature dim mismatch: got {X.shape[1]}, expected {FEATURE_DIM}")
    return X
