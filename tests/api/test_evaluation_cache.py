import concurrent.futures
import pytest
from backend.app.evaluation.cache import EvaluationCache
from backend.app.evaluation.schemas import EvaluationResult, EvaluationBreakdown


def test_cache_hit_and_miss():
    cache = EvaluationCache(capacity=10)
    result = EvaluationResult(
        label="no_hallucination",
        confidence=0.99,
        breakdown=EvaluationBreakdown(nli_entailment=0.99)
    )

    # 1. Miss initially
    assert cache.get("c1", "p1", "r1") is None
    stats = cache.stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0

    # 2. Store in cache
    cache.set("c1", "p1", "r1", result)
    assert cache.stats()["size"] == 1

    # 3. Hit on second lookup
    cached = cache.get("c1", "p1", "r1")
    assert cached is not None
    assert cached.label == "no_hallucination"
    assert cached.confidence == 0.99
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["hit_ratio_percent"] == 50.0


def test_cache_eviction_lru():
    cache = EvaluationCache(capacity=2)
    res = EvaluationResult(label="no", confidence=0.9)

    cache.set("c1", "p1", "r1", res)
    cache.set("c2", "p2", "r2", res)
    assert cache.stats()["size"] == 2

    # Access item 1 to make it most recently used
    assert cache.get("c1", "p1", "r1") is not None

    # Add item 3 -> should evict item 2
    cache.set("c3", "p3", "r3", res)
    assert cache.stats()["size"] == 2

    # Item 1 is retained, Item 2 was evicted, Item 3 is present
    assert cache.get("c1", "p1", "r1") is not None
    assert cache.get("c2", "p2", "r2") is None
    assert cache.get("c3", "p3", "r3") is not None


def test_cache_concurrency_thread_safe():
    cache = EvaluationCache(capacity=100)
    res = EvaluationResult(label="no", confidence=0.9)

    def worker(i: int):
        for j in range(20):
            cache.set(f"c{i}_{j}", "p", "r", res)
            _ = cache.get(f"c{i}_{j}", "p", "r")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(5)]
        for f in futures:
            f.result()

    assert cache.stats()["size"] <= 100
