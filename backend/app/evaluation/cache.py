# backend/app/evaluation/cache.py
import hashlib
import threading
from collections import OrderedDict
from typing import Optional, Dict, Any
from backend.app.evaluation.schemas import EvaluationResult


class EvaluationCache:
    """
    Thread-safe In-Memory LRU Cache for ML Evaluation Results.
    Avoids redundant inference runs for identical (context, prompt, response) tuples,
    reducing response latency from ~500ms to < 0.5ms with zero external infrastructure.
    """

    def __init__(self, capacity: int = 2048):
        self.capacity = capacity
        self._cache: OrderedDict[str, EvaluationResult] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _compute_key(context: str, prompt: str, response: str) -> str:
        raw = f"{context.strip()}|{prompt.strip()}|{response.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, context: str, prompt: str, response: str) -> Optional[EvaluationResult]:
        key = self._compute_key(context, prompt, response)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return self._cache[key]
            self._misses += 1
            return None

    def set(self, context: str, prompt: str, response: str, result: EvaluationResult) -> None:
        key = self._compute_key(context, prompt, response)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = result
            if len(self._cache) > self.capacity:
                self._cache.popitem(last=False)  # Evict least recently used

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_ratio = (self._hits / total * 100.0) if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "capacity": self.capacity,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio_percent": round(hit_ratio, 2)
            }


# Singleton evaluation cache instance
evaluation_cache = EvaluationCache(capacity=2048)
