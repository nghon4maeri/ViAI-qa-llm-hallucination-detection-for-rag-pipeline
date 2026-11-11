# backend/app/core/metrics.py
"""
Custom Prometheus metrics for Vietnamese AI Response QA.
Exposed at /metrics by Prometheus Instrumentator.
"""
from typing import Sequence
from prometheus_client import REGISTRY, Counter, Histogram, Gauge


def _get_or_create(metric_cls, name: str, documentation: str, labelnames: Sequence[str] = (), **kwargs):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return metric_cls(name, documentation, labelnames=labelnames, **kwargs)


viai_evaluations_total = _get_or_create(
    Counter,
    "viai_evaluations_total",
    "Total number of AI response evaluations performed",
    labelnames=["model_version", "label"]
)

viai_evaluation_duration_seconds = _get_or_create(
    Histogram,
    "viai_evaluation_duration_seconds",
    "Evaluation latency duration in seconds",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
)

viai_hallucination_rate_percent = _get_or_create(
    Gauge,
    "viai_hallucination_rate_percent",
    "Real-time percentage of evaluated responses classified as hallucination (intrinsic or extrinsic)"
)

viai_feedback_total = _get_or_create(
    Counter,
    "viai_feedback_total",
    "Total user feedback received (THUMBS_UP, THUMBS_DOWN, etc.)",
    labelnames=["feedback_label"]
)


def record_evaluation_metric(model_version: str, label: str, duration_sec: float) -> None:
    """Records evaluation count and latency histogram."""
    try:
        viai_evaluations_total.labels(model_version=model_version, label=label).inc()
        viai_evaluation_duration_seconds.observe(duration_sec)
    except Exception:
        pass


def record_feedback_metric(feedback_label: str) -> None:
    """Records user feedback count."""
    try:
        viai_feedback_total.labels(feedback_label=feedback_label).inc()
    except Exception:
        pass


def update_hallucination_rate_metric(hallucination_rate: float) -> None:
    """Updates real-time hallucination rate gauge (0.0 - 100.0)."""
    try:
        viai_hallucination_rate_percent.set(hallucination_rate)
    except Exception:
        pass
