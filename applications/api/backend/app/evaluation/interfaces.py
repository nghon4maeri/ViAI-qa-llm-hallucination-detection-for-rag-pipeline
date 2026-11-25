# applications/api/backend/app/evaluation/interfaces.py
from typing import TYPE_CHECKING, List, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

from backend.app.evaluation.schemas import EvaluationInput, EvaluationResult


@runtime_checkable
class EvaluationEngine(Protocol):
    """
    Abstract evaluation boundary.
    Decouples business services from PyTorch, HuggingFace, and LightGBM model implementations.
    """

    def evaluate(self, payload: EvaluationInput) -> EvaluationResult:
        """Execute evaluation against reference context and return standardized result."""
        ...

    def is_ready(self) -> bool:
        """Check whether underlying models are loaded and ready for inference."""
        ...

    def warmup(self) -> None:
        """Trigger preloading of model weights and resources."""
        ...


@runtime_checkable
class EmbeddingEngine(Protocol):
    """Optional capability: engines that can embed text enable RAG relevance metrics."""

    def embed(self, texts: List[str]) -> "np.ndarray":
        """Return one L2-normalised vector per text."""
        ...
