import threading
import time
from concurrent.futures import ThreadPoolExecutor

from src.services.response_cache import ResponseCache


def test_concurrent_callers_share_one_computation():
    cache = ResponseCache(ttl_seconds=60, max_entries=8)
    calls = 0
    calls_lock = threading.Lock()
    start = threading.Barrier(8)

    def compute():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return {"value": 42}

    def request():
        start.wait()
        return cache.get_or_compute(("same",), compute)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: request(), range(8)))

    assert calls == 1
    assert results == [{"value": 42}] * 8


def test_cache_expires_and_recomputes():
    cache = ResponseCache(ttl_seconds=0, max_entries=2)
    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        return calls

    assert cache.get_or_compute("key", compute) == 1
    assert cache.get_or_compute("key", compute) == 2
