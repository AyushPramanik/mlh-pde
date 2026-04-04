"""
Thread-safe sliding-window request counter used by the alert manager.
"""
from collections import deque
from threading import Lock
import time


class MetricsStore:
    def __init__(self, window_seconds: int = 120):
        self._lock = Lock()
        self._requests: deque[float] = deque()  # request timestamps
        self._errors: deque[float] = deque()    # 5xx timestamps
        self._window = window_seconds

    def record(self, status_code: int) -> None:
        now = time.time()
        with self._lock:
            self._requests.append(now)
            if status_code >= 500:
                self._errors.append(now)
            self._evict(now)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()
        while self._errors and self._errors[0] < cutoff:
            self._errors.popleft()

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            self._evict(now)
            total = len(self._requests)
            errors = len(self._errors)
        rate = errors / total if total else 0.0
        return {
            "total": total,
            "errors": errors,
            "error_rate": round(rate, 4),
            "window_seconds": self._window,
        }


# Global singleton — imported by create_app and AlertManager
store = MetricsStore(window_seconds=120)
