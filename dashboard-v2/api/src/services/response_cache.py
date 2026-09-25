from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, TypeVar


T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    value: T
    expires_at: float


class ResponseCache:
    """Bounded TTL cache that coalesces concurrent work for the same key."""

    def __init__(self, ttl_seconds: int = 900, max_entries: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[Hashable, CacheEntry] = OrderedDict()
        self._inflight: dict[Hashable, Future] = {}
        self._lock = threading.Lock()

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        now = time.monotonic()

        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now:
                self._entries.move_to_end(key)
                return entry.value
            if entry is not None:
                del self._entries[key]

            future = self._inflight.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._inflight[key] = future

        if not owner:
            return future.result()

        try:
            value = compute()
        except BaseException as exc:
            future.set_exception(exc)
            with self._lock:
                self._inflight.pop(key, None)
            raise

        with self._lock:
            self._entries[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + self.ttl_seconds,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            self._inflight.pop(key, None)

        future.set_result(value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

