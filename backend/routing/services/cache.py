"""Tiny thread-safe in-memory TTL cache (per process; enough for a demo/one dyno)."""
import threading
import time


class TTLCache:
    def __init__(self, ttl_s, max_items=512):
        self.ttl, self.max = ttl_s, max_items
        self._d, self._lock = {}, threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._d.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            self._d.pop(key, None)
            return None

    def set(self, key, value):
        with self._lock:
            if len(self._d) >= self.max:  # drop the oldest-expiring entry
                self._d.pop(min(self._d, key=lambda k: self._d[k][0]))
            self._d[key] = (time.monotonic() + self.ttl, value)
        return value

    def clear(self):
        with self._lock:
            self._d.clear()
