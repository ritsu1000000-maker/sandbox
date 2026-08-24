from collections import defaultdict, deque
from threading import Lock
import time


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 3600):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._events = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str):
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            queue = self._events[key]
            while queue and queue[0] < cutoff:
                queue.popleft()
            if len(queue) >= self.limit:
                retry_after = max(1, int(queue[0] + self.window_seconds - now))
                return False, retry_after
            queue.append(now)
            return True, 0
