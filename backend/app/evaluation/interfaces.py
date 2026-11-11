# backend/app/evaluation/interfaces.py
from typing import Protocol, runtime_checkable
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
