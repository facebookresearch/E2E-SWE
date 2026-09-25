"""
End-to-end tests for PyrateLimiter — each test exercises a meaningful
user-facing workflow that the library is designed to support.
"""

import asyncio
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, wait
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _LocalJSONServer:
    """Throwaway HTTP server on a free localhost port that answers every GET
    with ``200 {"ok": true}``.  Used to drive real requests through the httpx
    rate-limiting transports so the limiter hook is actually exercised."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *args):
            pass

    def __enter__(self):
        self._server = HTTPServer(("127.0.0.1", 0), self._Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/api"
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def _mp_acquire_task():
    """Top-level worker for MultiprocessBucket test — acquires a permit and
    returns the timestamp.  Must be module-level for ProcessPoolExecutor."""
    from pyrate_limiter import limiter_factory
    assert limiter_factory.LIMITER is not None
    limiter_factory.LIMITER.try_acquire("mp_task")
    return time.time()

# ---------------------------------------------------------------------------
# 1. Throttle a burst of operations to a fixed rate
# ---------------------------------------------------------------------------

class TestThrottleBurst:
    def test_throttle_burst_of_operations(self):
        """Throttle a burst of 10 operations to at most 5 per second, ensuring
        the limiter blocks and spaces out calls so the total wall-clock time
        reflects the enforced rate."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(5, Duration.SECOND))
        try:
            timestamps = []
            for i in range(10):
                limiter.try_acquire(f"op_{i}")
                timestamps.append(time.time())

            first_batch = timestamps[4] - timestamps[0]
            assert first_batch < 0.5, "First 5 should complete quickly"

            total = timestamps[9] - timestamps[0]
            assert total >= 0.8, "10 ops at 5/s should take ~1s"
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 2. Reject excess requests immediately (non-blocking)
# ---------------------------------------------------------------------------

class TestNonBlockingRejection:
    def test_reject_excess_requests_without_waiting(self):
        """Use the limiter in non-blocking mode to immediately reject requests
        that exceed the rate limit, simulating a server returning HTTP 429."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(3, Duration.SECOND))
        try:
            results = []
            for i in range(6):
                results.append(limiter.try_acquire(f"req_{i}", blocking=False))

            assert results[:3] == [True, True, True]
            assert results[3:] == [False, False, False]
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 3. Enforce multiple rate limits simultaneously
# ---------------------------------------------------------------------------

class TestMultipleRateLimits:
    def test_enforce_short_and_long_term_rate_limits(self):
        """Apply two rate limits (3 per 100ms and 10 per 1s) simultaneously.
        Verify the short-term limit triggers first, preventing the 4th
        request even though the long-term limit has capacity."""
        from pyrate_limiter import Limiter, Rate

        rates = [Rate(3, 100), Rate(10, 1000)]

        limiter = Limiter(rates, buffer_ms=10)
        try:
            results = [limiter.try_acquire(f"r_{i}", blocking=False) for i in range(5)]
            assert results == [True, True, True, False, False]
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 4. Rate-limit function calls via decorator
# ---------------------------------------------------------------------------

class TestSyncDecorator:
    def test_decorator_throttles_function_calls(self):
        """Wrap a sync function with as_decorator() so every call is
        automatically rate-limited.  Verify the function still executes
        correctly (forwarding positional and keyword arguments and returning
        the wrapped result transparently) and that the rate limit causes
        measurable delay."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(3, Duration.SECOND))
        try:
            call_count = 0

            @limiter.as_decorator(name="sync_fn")
            def do_work(x, *, offset=0):
                nonlocal call_count
                call_count += 1
                return x * 2 + offset

            start = time.time()
            results = [do_work(i) for i in range(6)]
            elapsed = time.time() - start

            assert results == [0, 2, 4, 6, 8, 10]
            assert call_count == 6
            assert elapsed >= 0.5, "6 calls at 3/s should take ~1s"

            # The wrapper forwards keyword arguments unchanged (not just
            # positional ones) and returns the wrapped function's value.
            assert do_work(10, offset=5) == 25
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 5. Rate-limit async coroutine calls via decorator
# ---------------------------------------------------------------------------

class TestAsyncDecorator:
    @pytest.mark.asyncio
    async def test_async_decorator_throttles_coroutine_calls(self):
        """Wrap an async function with as_decorator() and verify it is
        rate-limited while still returning correct results."""
        from pyrate_limiter import Limiter, Rate

        limiter = Limiter(Rate(3, 200), buffer_ms=10)
        try:
            call_count = 0

            @limiter.as_decorator(name="async_fn")
            async def async_work(x):
                nonlocal call_count
                call_count += 1
                return x + 1

            start = time.time()
            results = [await async_work(i) for i in range(6)]
            elapsed = time.time() - start

            assert results == [1, 2, 3, 4, 5, 6]
            assert call_count == 6
            assert elapsed >= 0.1
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 6. Throttle concurrent async tasks
# ---------------------------------------------------------------------------

class TestAsyncConcurrency:
    @pytest.mark.asyncio
    async def test_throttle_concurrent_async_tasks(self):
        """Launch 10 concurrent async tasks that all try to acquire permits
        from a limiter capped at 5 per 200ms.  All tasks should eventually
        complete, and the total time should reflect the rate limit."""
        from pyrate_limiter import Limiter, Rate

        limiter = Limiter(Rate(5, 200), buffer_ms=10)
        try:
            timestamps = []

            async def task(name):
                await limiter.try_acquire_async(name)
                timestamps.append(time.time())
                return name

            results = await asyncio.gather(*[task(f"t_{i}") for i in range(10)])
            assert len(results) == 10

            total = max(timestamps) - min(timestamps)
            assert total >= 0.15, "Should take time due to rate limiting"
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 7. Use weighted requests to model variable-cost operations
# ---------------------------------------------------------------------------

class TestWeightedRequests:
    def test_heavy_request_consumes_multiple_permits(self):
        """Model a "heavy" operation that costs 5 permits while regular
        operations cost 1.  Verify that a single heavy request plus 5
        regular ones fill a bucket of capacity 10, and the next is rejected."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(10, Duration.SECOND))
        try:
            assert limiter.try_acquire("heavy", weight=5, blocking=False) is True
            for i in range(5):
                assert limiter.try_acquire(f"light_{i}", blocking=False) is True
            assert limiter.try_acquire("overflow", blocking=False) is False
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 8. Persist rate-limit state across limiter restarts with SQLite
# ---------------------------------------------------------------------------

class TestSQLitePersistence:
    def test_rate_limit_state_persists_across_limiter_instances(self):
        """Create a SQLite-backed limiter, consume some permits, close it,
        then create a new limiter pointing at the same database.  The new
        limiter should see the previously consumed permits and enforce the
        remaining capacity."""
        from pyrate_limiter import limiter_factory, Duration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "rate.db")

            limiter1 = limiter_factory.create_sqlite_limiter(
                rate_per_duration=5,
                duration=Duration.SECOND,
                db_path=db_path,
            )
            for i in range(3):
                limiter1.try_acquire(f"item_{i}")
            limiter1.close()

            limiter2 = limiter_factory.create_sqlite_limiter(
                rate_per_duration=5,
                duration=Duration.SECOND,
                db_path=db_path,
            )
            try:
                assert limiter2.try_acquire("a", blocking=False) is True
                assert limiter2.try_acquire("b", blocking=False) is True
                assert limiter2.try_acquire("c", blocking=False) is False
            finally:
                limiter2.close()


# ---------------------------------------------------------------------------
# 9. Auto-release resources using context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_context_manager_releases_buckets_on_exit(self):
        """Use the limiter as a context manager and verify that __exit__
        actually tears down resources — afterwards the limiter holds no
        active buckets, proving close() ran (not merely that a second
        close() is a safe no-op)."""
        from pyrate_limiter import Limiter, Rate, Duration

        with Limiter(Rate(5, Duration.SECOND)) as limiter:
            for i in range(5):
                limiter.try_acquire(f"item_{i}")
            # Inside the block the scheduled bucket is active.
            assert len(limiter.buckets()) == 1

        # __exit__ released the bucket(s); none remain active.
        assert limiter.buckets() == []
        # Idempotent: closing again after the context exited must not raise.
        limiter.close()

    def test_context_manager_propagates_exception_and_still_cleans_up(self):
        """An exception raised inside the block must propagate out of the
        context manager (__exit__ does not swallow it) while resources are
        still released — distinct from the normal-exit path."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(5, Duration.SECOND))
        with pytest.raises(ValueError, match="simulated error"):
            with limiter:
                limiter.try_acquire("before_error")
                raise ValueError("simulated error")

        # Even though the block raised, __exit__ still tore down the buckets.
        assert limiter.buckets() == []


# ---------------------------------------------------------------------------
# 10. Create limiters via factory convenience functions
# ---------------------------------------------------------------------------

class TestFactoryFunctions:
    def test_create_inmemory_limiter_via_factory(self):
        """Use the factory function to quickly spin up an in-memory limiter
        and verify it enforces the specified rate."""
        from pyrate_limiter import limiter_factory, Duration

        limiter = limiter_factory.create_inmemory_limiter(
            rate_per_duration=3, duration=Duration.SECOND
        )
        try:
            for i in range(3):
                assert limiter.try_acquire(f"i_{i}", blocking=False) is True
            assert limiter.try_acquire("excess", blocking=False) is False
        finally:
            limiter.close()

    def test_sqlite_factory_table_name_isolates_state_and_blocks(self):
        """Drive two distinct, not-otherwise-covered SQLite-factory contracts:
        (1) a non-default ``table_name`` gives each factory-built limiter its own
        independent bucket even when they share the same database file, and
        (2) a factory-built limiter actually *blocks* (spaces out) requests in
        blocking mode rather than only rejecting non-blockingly."""
        from pyrate_limiter import limiter_factory, Duration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "factory.db")

            # Two limiters on the SAME db file but DIFFERENT table names must
            # enforce their limits independently (state is partitioned by table).
            limiter_a = limiter_factory.create_sqlite_limiter(
                rate_per_duration=2,
                duration=Duration.SECOND,
                db_path=db_path,
                table_name="tenant_a",
            )
            limiter_b = limiter_factory.create_sqlite_limiter(
                rate_per_duration=2,
                duration=Duration.SECOND,
                db_path=db_path,
                table_name="tenant_b",
            )
            try:
                # Saturate tenant_a's bucket.
                assert limiter_a.try_acquire("a1", blocking=False) is True
                assert limiter_a.try_acquire("a2", blocking=False) is True
                assert limiter_a.try_acquire("a3", blocking=False) is False
                # tenant_b is a separate table, so it still has full capacity.
                assert limiter_b.try_acquire("b1", blocking=False) is True
                assert limiter_b.try_acquire("b2", blocking=False) is True
                assert limiter_b.try_acquire("b3", blocking=False) is False
            finally:
                limiter_a.close()
                limiter_b.close()

            # Blocking spacing: a factory-built limiter capped at 2 per 300ms must
            # WAIT (not reject) on the 3rd/4th acquire, so 4 blocking acquires take
            # at least roughly one window rather than completing instantly.
            blocking_limiter = limiter_factory.create_sqlite_limiter(
                rate_per_duration=2,
                duration=300,
                db_path=os.path.join(tmpdir, "blocking.db"),
                table_name="blocking_tenant",
                buffer_ms=10,
            )
            try:
                start = time.time()
                for i in range(4):
                    assert blocking_limiter.try_acquire(f"req_{i}") is True
                elapsed = time.time() - start
                assert elapsed >= 0.25, "Factory limiter should block to enforce the rate"
            finally:
                blocking_limiter.close()


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 11. Bucket recovers capacity after the time window passes
# ---------------------------------------------------------------------------

class TestBucketRecovery:
    def test_bucket_recovers_capacity_after_window_expires(self):
        """Fill the bucket to capacity, wait for the rate window to expire,
        then verify new requests succeed — demonstrating the leaky-bucket
        algorithm correctly frees up capacity over time."""
        from pyrate_limiter import Limiter, Rate

        limiter = Limiter(Rate(3, 200), buffer_ms=10)
        try:
            for i in range(3):
                assert limiter.try_acquire(f"fill_{i}", blocking=False) is True
            assert limiter.try_acquire("rejected", blocking=False) is False

            time.sleep(0.3)

            assert limiter.try_acquire("recovered", blocking=False) is True
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 12. Thread-safe rate limiting across multiple threads
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_rate_limit_is_enforced_across_threads(self):
        """Share a single limiter across 10 threads that each try to acquire
        a permit non-blockingly.  Exactly 5 should succeed (matching the
        rate limit), proving thread-safety of the acquisition logic."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(5, Duration.SECOND))
        try:
            def acquire(name):
                return limiter.try_acquire(name, blocking=False)

            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = [pool.submit(acquire, f"t_{i}") for i in range(10)]
                results = [f.result() for f in futures]

            assert sum(results) == 5
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 13. Async rate limiting with timeout
# ---------------------------------------------------------------------------

class TestAsyncTimeout:
    @pytest.mark.asyncio
    async def test_async_acquire_returns_false_on_timeout(self):
        """Attempt to acquire a permit asynchronously with a short timeout
        after the bucket is already full.  The call should return False
        rather than blocking indefinitely, allowing the caller to handle
        the timeout gracefully."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(2, Duration.SECOND))
        try:
            assert await limiter.try_acquire_async("a") is True
            assert await limiter.try_acquire_async("b") is True

            result = await limiter.try_acquire_async("c", timeout=0.2)
            assert result is False
        finally:
            limiter.close()

    @pytest.mark.asyncio
    async def test_async_nonblocking_immediate_rejection(self):
        """Use non-blocking async acquisition to get an immediate rejection
        when the bucket is full, without waiting at all."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(2, Duration.SECOND))
        try:
            assert await limiter.try_acquire_async("a") is True
            assert await limiter.try_acquire_async("b") is True
            assert await limiter.try_acquire_async("c", blocking=False) is False
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 14. Duration arithmetic for composing time intervals
# ---------------------------------------------------------------------------

class TestDurationArithmetic:
    def test_compose_custom_intervals_with_duration_arithmetic(self):
        """Use Duration arithmetic (multiply, add) to compose custom time
        intervals for rate definitions, enabling expressions like
        '2 * Duration.SECOND' or 'Duration.SECOND + Duration.MINUTE'."""
        from pyrate_limiter import Duration, Rate

        assert Duration.SECOND * 2 == 2000
        assert 3 * Duration.SECOND == 3000
        assert Duration.SECOND + Duration.MINUTE == 61000
        assert int(Duration.HOUR) == 3600000

        rate = Rate(10, Duration.SECOND * 5)
        assert rate.limit == 10
        assert rate.interval == 5000


# ---------------------------------------------------------------------------
# 15. Bypass rate limiting for zero-cost operations (health checks)
# ---------------------------------------------------------------------------

class TestWeightZeroPassthrough:
    def test_zero_weight_bypasses_full_bucket(self):
        """Send health-check or metadata requests with weight=0 so they always
        succeed even when the bucket is completely full, without consuming
        any capacity."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(2, Duration.SECOND))
        try:
            # Fill bucket to capacity
            assert limiter.try_acquire("a", blocking=False) is True
            assert limiter.try_acquire("b", blocking=False) is True
            # Bucket is full — normal request rejected
            assert limiter.try_acquire("c", blocking=False) is False
            # weight=0 always passes
            assert limiter.try_acquire("healthcheck", weight=0) is True
            # Bucket is still full for normal requests
            assert limiter.try_acquire("d", blocking=False) is False
        finally:
            limiter.close()

    @pytest.mark.asyncio
    async def test_zero_weight_bypasses_full_bucket_async(self):
        """Verify weight=0 passthrough works in async context too, so async
        health checks are never rate-limited."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(2, Duration.SECOND))
        try:
            assert await limiter.try_acquire_async("a") is True
            assert await limiter.try_acquire_async("b") is True
            assert await limiter.try_acquire_async("healthcheck", weight=0) is True
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 16. Direct bucket management: add items, check count, leak, and flush
# ---------------------------------------------------------------------------

class TestDirectBucketManagement:
    def test_fill_inspect_leak_and_flush_bucket(self):
        """Manage an InMemoryBucket directly: add timestamped items, verify
        the count reflects weights, leak expired items to reclaim capacity,
        and flush to completely reset the bucket."""
        from pyrate_limiter import InMemoryBucket, Rate, RateItem, Duration

        bucket = InMemoryBucket([Rate(20, Duration.SECOND)])

        # Put items and verify count
        ts = int(time.monotonic() * 1000)
        for i in range(5):
            assert bucket.put(RateItem(f"item_{i}", ts + i)) is True
        assert bucket.count() == 5

        # Weighted item counts as its weight
        assert bucket.put(RateItem("heavy", ts + 10, weight=3)) is True
        assert bucket.count() == 8

        # Leak with a far-future timestamp removes all items
        leaked = bucket.leak(ts + Duration.SECOND + 100)
        assert leaked == 8
        assert bucket.count() == 0

        # Refill and flush
        for i in range(4):
            bucket.put(RateItem(f"refill_{i}", ts + Duration.SECOND + 200 + i))
        assert bucket.count() == 4
        bucket.flush()
        assert bucket.count() == 0


# ---------------------------------------------------------------------------
# 17. Query retry delay from a full bucket (Retry-After)
# ---------------------------------------------------------------------------

class TestWaitingRetryAfter:
    def test_query_wait_time_for_retry_after_header(self):
        """After a bucket rejects a request, query waiting() to find out
        exactly how many milliseconds until a slot opens — useful for setting
        HTTP Retry-After headers or scheduling retries."""
        from pyrate_limiter import InMemoryBucket, Rate, RateItem

        bucket = InMemoryBucket([Rate(3, 1000)])  # 3 per second

        ts = int(time.monotonic() * 1000)
        for i in range(3):
            bucket.put(RateItem(f"r_{i}", ts))

        # Bucket is full — put fails
        overflow = RateItem("overflow", ts)
        assert bucket.put(overflow) is False

        # All items (and the overflow) were put at the same fixed timestamp with no
        # leak in between, so waiting() has one exact correct result: the full rate
        # interval of 1000 ms until the oldest item expires.
        wait_ms = bucket.waiting(overflow)
        assert isinstance(wait_ms, int)
        assert wait_ms == 1000


# ---------------------------------------------------------------------------
# 18. Inspect bucket contents for monitoring
# ---------------------------------------------------------------------------

class TestBucketPeek:
    def test_peek_at_bucket_items_for_monitoring(self):
        """Use peek() to inspect the most recent and oldest items in a bucket
        without modifying it — useful for monitoring dashboards or debugging
        rate-limit state."""
        from pyrate_limiter import InMemoryBucket, Rate, RateItem, Duration

        bucket = InMemoryBucket([Rate(10, Duration.SECOND)])

        ts = int(time.monotonic() * 1000)
        for i in range(5):
            bucket.put(RateItem(f"item_{i}", ts + i * 10))

        # peek(0) returns the most recent item
        latest = bucket.peek(0)
        assert latest is not None
        assert latest.name == "item_4"

        # peek(4) returns the oldest item
        oldest = bucket.peek(4)
        assert oldest is not None
        assert oldest.name == "item_0"

        # Out of bounds returns None
        assert bucket.peek(100) is None


# ---------------------------------------------------------------------------
# 19. Sync try_acquire with timeout
# ---------------------------------------------------------------------------

class TestSyncTimeout:
    def test_sync_acquire_with_timeout_returns_false(self):
        """Enforce a maximum wait time for a blocking sync acquisition so
        the caller is not stuck indefinitely when the bucket is full."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(1, Duration.SECOND))
        try:
            assert limiter.try_acquire("first") is True

            start = time.time()
            result = limiter.try_acquire("second", timeout=0.15)
            elapsed = time.time() - start

            assert result is False
            assert elapsed < 0.5, "Should return after timeout, not full rate window"
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 20. Gracefully handle impossibly heavy requests
# ---------------------------------------------------------------------------

class TestUnacquirableWeight:
    def test_weight_exceeding_capacity_returns_false_immediately(self):
        """When a request's weight exceeds the bucket's maximum capacity,
        return False immediately rather than blocking forever, so the
        application can reject or split the request."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(5, Duration.SECOND))
        try:
            result = limiter.try_acquire("impossible", weight=10, blocking=False)
            assert result is False
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 21. Invalid parameter combinations raise clear errors
# ---------------------------------------------------------------------------

class TestParameterValidation:
    def test_nonblocking_with_timeout_raises_error(self):
        """Detect the invalid combination of blocking=False with a timeout
        value, raising RuntimeError so the user knows to pick one mode."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(5, Duration.SECOND))
        try:
            with pytest.raises(RuntimeError, match="Can't set timeout with non-blocking"):
                limiter.try_acquire("x", blocking=False, timeout=1)
        finally:
            limiter.close()

    def test_negative_timeout_raises_error(self):
        """Detect an invalid negative timeout (other than -1 which means
        indefinite), raising ValueError to prevent silent misconfiguration."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(5, Duration.SECOND))
        try:
            with pytest.raises(ValueError, match="timeout must be -1 or >= 0"):
                limiter.try_acquire("x", timeout=-2)
        finally:
            limiter.close()

    @pytest.mark.asyncio
    async def test_async_nonblocking_with_timeout_raises_error(self):
        """Same validation applies to the async path: blocking=False with
        a timeout raises RuntimeError."""
        from pyrate_limiter import Limiter, Rate, Duration

        limiter = Limiter(Rate(5, Duration.SECOND))
        try:
            with pytest.raises(RuntimeError, match="Can't set timeout with non-blocking"):
                await limiter.try_acquire_async("x", blocking=False, timeout=1)
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 22. Use BucketAsyncWrapper for async rate limiting with sync buckets
# ---------------------------------------------------------------------------

class TestBucketAsyncWrapper:
    @pytest.mark.asyncio
    async def test_wrap_sync_bucket_for_async_limiter(self):
        """Wrap a sync InMemoryBucket with BucketAsyncWrapper so the limiter
        uses asyncio.sleep instead of time.sleep, preventing event-loop
        blocking in async applications."""
        from pyrate_limiter import (
            BucketAsyncWrapper, InMemoryBucket, Rate, Duration, Limiter,
        )

        sync_bucket = InMemoryBucket([Rate(3, 200)])
        async_bucket = BucketAsyncWrapper(sync_bucket)
        limiter = Limiter(async_bucket, buffer_ms=10)
        try:
            # First 3 should succeed
            for i in range(3):
                result = await limiter.try_acquire_async(f"item_{i}")
                assert result is True

            # 4th should fail non-blocking
            result = await limiter.try_acquire_async("overflow", blocking=False)
            assert result is False

            # Blocking acquire should succeed after waiting
            start = time.time()
            result = await limiter.try_acquire_async("waited")
            elapsed = time.time() - start
            assert result is True
            assert elapsed >= 0.1, "Should have waited for a slot"
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 23. Rate-limit operations across multiple worker processes
# ---------------------------------------------------------------------------

class TestMultiprocessBucket:
    def test_multiprocess_bucket_enforces_rate_across_processes(self):
        """Share a MultiprocessBucket across worker processes via
        ProcessPoolExecutor and verify the rate limit is enforced globally
        — not per-process — by checking that request timestamps respect
        the configured rate across all workers."""
        from pyrate_limiter import MultiprocessBucket, Rate, Duration, limiter_factory

        bucket = MultiprocessBucket.init([Rate(5, Duration.SECOND)])

        start = time.time()
        with ProcessPoolExecutor(
            max_workers=3,
            initializer=limiter_factory.init_global_limiter,
            initargs=(bucket,),
        ) as executor:
            futures = [executor.submit(_mp_acquire_task) for _ in range(10)]
            wait(futures)

        times = [f.result() for f in futures]
        elapsed = max(times) - start

        # 10 requests at 5/s across 3 workers should take ~1s
        assert elapsed >= 0.8, f"Expected >= 0.8s, got {elapsed:.2f}s"
        assert len(times) == 10


# ---------------------------------------------------------------------------
# 24. Format durations as human-readable strings for user-facing messages
# ---------------------------------------------------------------------------

class TestDurationReadable:
    def test_format_durations_as_human_readable_strings(self):
        """Convert millisecond durations to human-readable strings suitable
        for log messages, Retry-After headers, or user-facing rate limit
        descriptions (e.g., '1.0s', '5.0m', '2.5h')."""
        from pyrate_limiter import Duration

        assert Duration.readable(300) == "300ms"
        assert Duration.readable(1000) == "1.0s"
        assert Duration.readable(1500) == "1.5s"
        assert Duration.readable(int(Duration.MINUTE)) == "1.0m"
        assert Duration.readable(int(Duration.HOUR)) == "1.0h"
        assert Duration.readable(int(Duration.DAY)) == "1.0d"
        assert Duration.readable(int(Duration.WEEK)) == "1.0w"
        assert Duration.readable(5 * Duration.MINUTE + 30 * Duration.SECOND) == "5.5m"


# ---------------------------------------------------------------------------
# 25. Rate string representation for logging
# ---------------------------------------------------------------------------

class TestRateDisplay:
    def test_rate_string_representation_for_logging(self):
        """Convert Rate objects to readable strings for log messages and
        diagnostics, showing the limit and human-readable interval."""
        from pyrate_limiter import Rate, Duration

        # Pin the full format: "limit={limit}/{Duration.readable(interval)}"
        assert str(Rate(5, Duration.SECOND)) == "limit=5/1.0s"
        assert str(Rate(100, Duration.MINUTE)) == "limit=100/1.0m"


# ---------------------------------------------------------------------------
# 26. Multi-rate blocking waits for both rates to have capacity
# ---------------------------------------------------------------------------

class TestMultiRateBlocking:
    def test_blocking_respects_all_rate_tiers(self):
        """With two rate tiers (a fast short-term limit and a small long-term
        limit), a blocking acquire must wait for *every* tier to have capacity,
        so a later request is gated by the long-term tier even after the
        short-term tier has already recovered — distinct from single-rate
        blocking and from non-blocking multi-rate rejection."""
        from pyrate_limiter import Limiter, Rate

        # Short tier: 2 per 300ms. Long tier: 3 per 5000ms.
        # Rates are passed smallest-interval-first per the ordering precondition.
        limiter = Limiter([Rate(2, 300), Rate(3, 5000)], buffer_ms=10)
        try:
            # Consume the long tier's full capacity (3); the short tier paces
            # these out (the 3rd blocks ~300ms waiting on the short window).
            for i in range(3):
                assert limiter.try_acquire(f"item_{i}") is True

            # A 4th acquire: the short tier (2/300ms) would admit it within
            # ~300ms, but the long tier (3/5s) is now full, so a blocking
            # acquire with a 1s timeout must FAIL — it would need ~5s. This
            # proves blocking coordinates the wait across both tiers, gating on
            # the long tier rather than only the short one.
            start = time.time()
            gated = limiter.try_acquire("item_3", timeout=1.0)
            waited = time.time() - start

            assert gated is False, "long-term tier must gate the 4th blocking acquire"
            # Whether the limiter burns the full timeout (poll-until-timeout) or returns early
            # once the required wait is known to exceed the budget (fail-fast) is left to the
            # implementation; both must honor the 1.0s timeout budget rather than wait the ~5s
            # the long tier would actually need.
            assert waited <= 1.2, "must honor the timeout budget, not wait the full long-tier window"
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 27. SQLite bucket with direct bucket operations
# ---------------------------------------------------------------------------

class TestSQLiteBucketDirect:
    def test_sqlite_bucket_put_count_flush_close(self):
        """Use SQLiteBucket directly for persistent rate limiting: add items,
        verify count, flush to reset, and close to release the database
        connection."""
        from pyrate_limiter import SQLiteBucket, Rate, RateItem, Duration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "direct.db")
            bucket = SQLiteBucket.init_from_file(
                [Rate(10, Duration.SECOND)],
                db_path=db_path,
                table="test_bucket",
            )
            try:
                ts = int(time.monotonic() * 1000)
                for i in range(5):
                    assert bucket.put(RateItem(f"item_{i}", ts + i)) is True
                assert bucket.count() == 5

                # Exceeding rate returns False
                for i in range(5):
                    bucket.put(RateItem(f"fill_{i}", ts + 10 + i))
                assert bucket.put(RateItem("overflow", ts + 20)) is False

                # Flush resets
                bucket.flush()
                assert bucket.count() == 0
            finally:
                bucket.close()


# ---------------------------------------------------------------------------
# 28. Rate-limit operations using RedisBucket with a real Redis server
# ---------------------------------------------------------------------------

class TestRedisBucket:
    def test_redis_bucket_enforces_rate_limit(self):
        """Use RedisBucket backed by a real Redis server to enforce rate
        limits with atomic Lua-script-based check-and-insert, suitable for
        distributed rate limiting across multiple application instances."""
        import redis as redis_lib
        from pyrate_limiter import RedisBucket, Rate, Duration, Limiter

        r = redis_lib.Redis(host="localhost", port=6379)
        r.ping()

        bucket_key = f"test_ratelimit_{int(time.time() * 1000)}"
        bucket = RedisBucket.init([Rate(3, Duration.SECOND)], r, bucket_key)
        limiter = Limiter(bucket)
        try:
            for i in range(3):
                assert limiter.try_acquire(f"req_{i}", blocking=False) is True
            assert limiter.try_acquire("excess", blocking=False) is False

            # Verify count
            assert bucket.count() == 3
        finally:
            limiter.close()
            r.delete(bucket_key)
            r.close()

    @pytest.mark.asyncio
    async def test_redis_bucket_async(self):
        """Use RedisBucket with an async Redis client to rate-limit
        operations in async applications without blocking the event loop."""
        import redis.asyncio as aioredis
        from pyrate_limiter import RedisBucket, Rate, Duration, Limiter

        r = aioredis.Redis(host="localhost", port=6379)
        await r.ping()

        bucket_key = f"test_ratelimit_async_{int(time.time() * 1000)}"
        bucket = await RedisBucket.init([Rate(3, Duration.SECOND)], r, bucket_key)
        limiter = Limiter(bucket)
        try:
            for i in range(3):
                assert await limiter.try_acquire_async(f"req_{i}", blocking=False) is True
            assert await limiter.try_acquire_async("excess", blocking=False) is False
        finally:
            limiter.close()
            await r.delete(bucket_key)
            await r.aclose()


# ---------------------------------------------------------------------------
# 29. Rate-limit HTTP requests with httpx transport integration
# ---------------------------------------------------------------------------

class TestHttpxIntegration:
    def test_httpx_sync_transport_rate_limits_requests(self):
        """Wrap httpx's HTTP transport with RateLimiterTransport so every
        outgoing request is automatically rate-limited, useful for
        respecting third-party API rate limits.  Drive real requests through
        an httpx.Client so the test fails if the transport never invokes the
        limiter."""
        import httpx
        from pyrate_limiter import Limiter, Rate, Duration
        from pyrate_limiter.extras.httpx_limiter import RateLimiterTransport

        limiter = Limiter(Rate(3, Duration.SECOND))
        transport = RateLimiterTransport(limiter=limiter)
        try:
            with _LocalJSONServer() as server, httpx.Client(transport=transport) as client:
                start = time.time()
                responses = [client.get(server.url) for _ in range(6)]
                elapsed = time.time() - start

            # Requests must succeed through the wrapped transport...
            assert all(r.status_code == 200 for r in responses)
            assert all(r.json() == {"ok": True} for r in responses)
            # ...and 6 requests at 3/s are only this slow if the transport
            # actually called the limiter on each request.
            assert elapsed >= 0.5, "Should be rate-limited by the transport"
        finally:
            limiter.close()

    @pytest.mark.asyncio
    async def test_httpx_async_transport_rate_limits_requests(self):
        """Wrap httpx's async transport with AsyncRateLimiterTransport for
        rate-limiting in async HTTP clients.  Drive real requests through an
        httpx.AsyncClient so the test fails if the transport never invokes the
        limiter."""
        import httpx
        from pyrate_limiter import Limiter, Rate, Duration
        from pyrate_limiter.extras.httpx_limiter import AsyncRateLimiterTransport

        limiter = Limiter(Rate(3, Duration.SECOND))
        transport = AsyncRateLimiterTransport(limiter=limiter)
        try:
            with _LocalJSONServer() as server:
                async with httpx.AsyncClient(transport=transport) as client:
                    start = time.time()
                    responses = []
                    for _ in range(6):
                        responses.append(await client.get(server.url))
                    elapsed = time.time() - start

            assert all(r.status_code == 200 for r in responses)
            assert all(r.json() == {"ok": True} for r in responses)
            assert elapsed >= 0.5, "Should be rate-limited by the transport"
        finally:
            limiter.close()


# ---------------------------------------------------------------------------
# 30. Rate-limit HTTP requests with requests session integration
# ---------------------------------------------------------------------------

class TestRequestsIntegration:
    def test_requests_session_rate_limits_http_calls(self):
        """Wrap Python requests.Session with RateLimitedRequestsSession so
        every HTTP call is automatically throttled, useful for web scraping
        or API client libraries."""
        import responses as responses_mock
        from pyrate_limiter import Limiter, Rate, Duration
        from pyrate_limiter.extras.requests_limiter import RateLimitedRequestsSession

        limiter = Limiter(Rate(3, Duration.SECOND))

        responses_mock.start()
        responses_mock.add(responses_mock.GET, "http://example.com/api", json={"ok": True})
        try:
            session = RateLimitedRequestsSession(limiter)
            start = time.time()
            results = [session.get("http://example.com/api") for _ in range(6)]
            elapsed = time.time() - start

            assert all(r.status_code == 200 for r in results)
            assert elapsed >= 0.5, "Should be rate-limited"
            session.close()
        finally:
            responses_mock.stop()
            responses_mock.reset()
            limiter.close()


# ---------------------------------------------------------------------------
# 31. Rate-limit operations using PostgresBucket with concurrent threads
# ---------------------------------------------------------------------------

class TestPostgresBucket:
    def _get_pool(self):
        from psycopg_pool import ConnectionPool
        pool = ConnectionPool(
            "postgresql://postgres:postgres@localhost:5432",
            min_size=2, max_size=5, open=True,
        )
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return pool

    def test_postgres_bucket_enforces_rate_under_concurrency(self):
        """Use multiple independent Limiters backed by PostgresBucket on the
        same table to enforce rate limits across concurrent threads —
        simulating separate application instances sharing a database for
        distributed rate limiting."""
        import threading
        from pyrate_limiter import PostgresBucket, Rate, Duration, Limiter

        pool = self._get_pool()
        table = f"test_pg_{int(time.time() * 1000)}"
        rates = [Rate(5, Duration.SECOND)]

        # Pre-create the table with a single bucket to avoid concurrent
        # CREATE TABLE races (table creation is a setup step, not the
        # behavior under test)
        setup_bucket = PostgresBucket(pool, table, rates)

        results = []
        lock = threading.Lock()

        def worker(tid):
            # Each thread creates its own Limiter + PostgresBucket —
            # simulating independent application instances
            bucket = PostgresBucket(pool, table, rates)
            limiter = Limiter(bucket)
            for _ in range(5):
                ok = limiter.try_acquire(f"thread_{tid}", blocking=False)
                with lock:
                    results.append(ok)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = sum(1 for r in results if r)
        rejections = sum(1 for r in results if not r)

        # Some should succeed, some should be rejected
        assert successes > 0
        assert rejections > 0
        # All 20 attempts happen with no sleeps, so they share a single 1s window.
        # The NOWAIT exclusive table lock serializes check-and-insert and only ever
        # rejects on contention, so successes can never exceed one window's capacity.
        assert successes <= 5  # Rate limit = one window's capacity

        # Clean up
        try:
            with pool.connection() as conn:
                conn.execute(f"DROP TABLE IF EXISTS ratelimit___{table}")
        finally:
            pool.close()


# ---------------------------------------------------------------------------
# 32. Rate-limit HTTP requests with aiohttp session integration
# ---------------------------------------------------------------------------

class TestAiohttpIntegration:
    @pytest.mark.asyncio
    async def test_aiohttp_session_rate_limits_requests(self):
        """Wrap aiohttp.ClientSession with RateLimitedSession so every
        async HTTP request is automatically rate-limited, useful for
        async web scrapers and API clients."""
        from aioresponses import aioresponses
        from pyrate_limiter import Limiter, Rate, Duration
        from pyrate_limiter.extras.aiohttp_limiter import RateLimitedSession

        limiter = Limiter(Rate(3, Duration.SECOND))

        with aioresponses() as m:
            for _ in range(10):
                m.get("http://example.com/api", payload={"ok": True})

            async with RateLimitedSession(limiter) as session:
                start = time.time()
                responses = []
                for _ in range(6):
                    resp = await session.get("http://example.com/api")
                    responses.append(resp)
                elapsed = time.time() - start

            assert len(responses) == 6
            assert elapsed >= 0.5, "Should be rate-limited"
        limiter.close()
