"""
Integration tests for the diskcache library.
Each test exercises user-facing behavior through realistic workflows.
Structured to follow the diskcache documentation order.
"""

import collections
import hashlib
import io
import os
import os.path as op
import threading
import time
from concurrent.futures import ProcessPoolExecutor

import pytest

import diskcache
from diskcache import (
    Cache, FanoutCache, Deque, Index,
    Disk, JSONDisk,
    ENOVAL, UNKNOWN, Timeout,
    DEFAULT_SETTINGS, EVICTION_POLICY,
)
from diskcache.recipes import (
    Averager, Lock, RLock, BoundedSemaphore,
    throttle, barrier, memoize_stampede,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cache(tmp_path):
    c = Cache(str(tmp_path / "cache"))
    yield c
    c.close()


@pytest.fixture
def fanout(tmp_path):
    fc = FanoutCache(str(tmp_path / "fanout"), shards=4)
    yield fc
    fc.close()


# ---------------------------------------------------------------------------
# Multiprocessing workers (module-level for pickling)
# ---------------------------------------------------------------------------

def _mp_cache_set_worker(args):
    directory, key, value = args
    with Cache(directory) as c:
        c.set(key, value, retry=True)
    return True


def _mp_cache_push_worker(args):
    directory, value, prefix = args
    with Cache(directory) as c:
        c.push(value, prefix=prefix, retry=True)
    return True


def _mp_locked_increment_worker(args):
    directory, n_increments = args
    with Cache(directory) as cache:
        lock = Lock(cache, "counter_lock")
        for _ in range(n_increments):
            with lock:
                val = cache["counter"]
                cache["counter"] = val + 1
    return True


def _mp_fanout_set_worker(args):
    directory, key, value = args
    with FanoutCache(directory) as fc:
        fc.set(key, value, retry=True)
    return True


def _mp_lock_acquire_worker(args):
    directory, lock_key, sleep_time = args
    with Cache(directory) as c:
        lock = Lock(c, lock_key)
        lock.acquire()
        time.sleep(sleep_time)
        lock.release()
    return time.time()


def _mp_index_set_worker(args):
    directory, key, value = args
    idx = Index(directory)
    for attempt in range(10):
        try:
            idx[key] = value
            return True
        except Exception:
            time.sleep(0.01 * (attempt + 1))
    idx[key] = value
    return True


def _mp_memoize_worker(args):
    directory, x = args
    with Cache(directory) as c:
        @c.memoize()
        def compute(val):
            return val * 2
        result = compute(x)
    return result


def _mp_cache_eviction_writer(args):
    directory, start, count = args
    with Cache(directory, timeout=10) as c:
        for i in range(start, start + count):
            c.set(f"key_{i}", b"x" * 10000, retry=True)
    return True


def _mp_atomic_incr_worker(args):
    directory, n = args
    with Cache(directory) as cache:
        for _ in range(n):
            cache.incr("counter", retry=True)
    return True


# ================================================================
# 1. CACHE
# ================================================================


class TestCacheLifecycle:

    def test_construction_persistence_close_reopen(self, tmp_path):
        """A user creates a cache, stores data, closes it, and reopens to verify persistence."""
        path = str(tmp_path / "persist_cache")

        with Cache(path, timeout=30) as c:
            assert c.directory == path
            assert c.timeout == 30
            assert isinstance(c.disk, Disk)
            c["string"] = "hello"
            c["number"] = 42
            c["nested"] = {"key": [1, 2, 3]}
            c.set("tagged", "value", tag="important")
            assert len(c) == 4

        with Cache(path) as c:
            assert c["string"] == "hello"
            assert c["number"] == 42
            assert c["nested"] == {"key": [1, 2, 3]}
            assert c.get("tagged", tag=True) == ("value", "important")
            assert len(c) == 4


class TestCacheCRUD:

    def test_full_crud_with_types_and_read_mode(self, tmp_path):
        """A user stores, retrieves, updates, and deletes various data types including file-like objects."""
        c = Cache(str(tmp_path / "crud_cache"), disk_min_file_size=0)

        values = [
            ("none_key", None, False),
            ("int_key", 1234, False),
            ("float_key", 56.78, False),
            ("str_key", "hello", False),
            ("large_str", "hello" * 2**15, False),
            ("bytes_key", b"world", False),
            ("large_bytes", b"world" * 2**15, False),
            ("tuple_key", (None,) * 100, False),
            ("file_key", io.BytesIO(b"binary" * 2**15), True),
        ]

        for key, value, file_like in values:
            assert c.set(key, value, read=file_like)
        assert len(c) == len(values)

        for key, value, file_like in values:
            if file_like:
                assert c[key] == value.getvalue()
            else:
                assert c[key] == value

        handle = c.read("large_bytes")
        assert handle.read() == b"world" * 2**15
        handle.close()

        assert c.add("new_unique", "first")
        assert not c.add("new_unique", "second")
        assert c["new_unique"] == "first"

        c.set("pop_me", 999, expire=60, tag="blue")
        val, expire_time, tag = c.pop("pop_me", expire_time=True, tag=True)
        assert val == 999
        assert isinstance(expire_time, float) and expire_time > time.time()
        assert tag == "blue"
        assert c.get("pop_me") is None

        assert c.pop("nonexistent") is None
        assert c.pop("nonexistent", "default") == "default"

        assert "str_key" in c
        assert "nonexistent" not in c

        del c["int_key"]
        with pytest.raises(KeyError):
            c["int_key"]

        assert c.delete("float_key")
        assert not c.delete("already_gone")

        c.clear()
        assert len(c) == 0
        c.close()


class TestCacheExpiration:

    def test_expiration_tags_touch_and_tag_index(self, tmp_path):
        """A user manages items with TTL and tags, creates/drops tag index, and touches items."""
        c = Cache(str(tmp_path / "exp_cache"))

        c.create_tag_index()

        for i in range(30):
            tag = ['red', 'blue', 'green'][i % 3]
            c.set(f"item_{i}", f"value_{i}", tag=tag,
                  expire=10 if tag == 'red' else None)
        assert len(c) == 30

        val, tag = c.get("item_0", tag=True)
        assert val == "value_0"
        assert tag == "red"

        # touch() updates the expire_time
        c.set("touch_me", "alive", expire=10)
        _, et_before = c.get("touch_me", expire_time=True)
        assert c.touch("touch_me", expire=100)
        _, et_after = c.get("touch_me", expire_time=True)
        assert et_after > et_before

        # expire(now=future) removes expired items without sleeping
        future = time.time() + 20
        expired = c.expire(now=future)
        assert expired == 10  # exactly 10 red items

        # Red items are gone
        assert c.get("item_0") is None

        # touch_me survives (expire=100 from touch)
        assert c.get("touch_me") == "alive"

        evicted = c.evict("blue")
        assert evicted == 10

        assert len(c) == 11  # 10 green + touch_me

        c.drop_tag_index()
        c.close()


class TestCacheCounters:

    def test_incr_decr_atomic_counters(self, cache):
        """A user uses incr/decr as atomic counters with defaults and expired keys."""
        assert cache.incr('counter', default=5) == 6
        assert cache.incr('counter', 2) == 8
        assert cache.decr('counter', 3) == 5

        assert cache.incr('new_key') == 1
        assert cache.decr('new_key') == 0

        cache.set('expiring', 100, expire=0.1)
        time.sleep(0.3)
        assert cache.incr('expiring') == 1


class TestCacheQueue:

    def test_push_pull_fifo_lifo_prefix_and_metadata(self, cache):
        """A user uses push/pull for FIFO/LIFO queues with exact key numbering."""
        # Keys start at 500 trillion
        key0 = cache.push("task_0")
        assert key0 == 500000000000000
        key1 = cache.push("task_1")
        assert key1 == 500000000000001
        key2 = cache.push("task_2")
        assert key2 == 500000000000002

        # Push to front decrements from 500 trillion
        front_key = cache.push("urgent", side="front")
        assert front_key == 499999999999999

        # Pull from front (FIFO)
        pulled_key, val = cache.pull()
        assert pulled_key == 499999999999999
        assert val == "urgent"

        pulled_key, val = cache.pull()
        assert pulled_key == 500000000000000
        assert val == "task_0"

        # Pull from back (LIFO)
        _, back_val = cache.pull(side="back")
        assert back_val == "task_2"

        # Prefix keys are strings in format "prefix-NNNNNNNNNNNNNNN"
        pkey1 = cache.push("q1_a", prefix="q1")
        assert pkey1 == "q1-500000000000000"
        pkey2 = cache.push("q1_b", prefix="q1")
        assert pkey2 == "q1-500000000000001"
        pkey3 = cache.push("q2_a", prefix="q2")
        assert pkey3 == "q2-500000000000000"

        _, val = cache.pull(prefix="q1")
        assert val == "q1_a"
        _, val = cache.pull(prefix="q2")
        assert val == "q2_a"


class TestCacheIteration:

    def test_iteration_iterkeys_and_peekitem(self, cache):
        """A user iterates keys in insertion and sorted order, and peeks first/last."""
        for ch in 'fedcba':
            cache[ch] = ord(ch)

        keys = list(cache)
        assert len(keys) == 6
        assert keys == list('fedcba')

        rev_keys = list(reversed(cache))
        assert rev_keys == list(reversed(keys))

        sorted_keys = list(cache.iterkeys())
        sorted_keys_rev = list(cache.iterkeys(reverse=True))
        assert sorted_keys_rev == list(reversed(sorted_keys))

        first_key, first_val = cache.peekitem(last=False)
        last_key, last_val = cache.peekitem(last=True)
        assert first_key == 'f'
        assert first_val == ord('f')
        assert last_key == 'a'
        assert last_val == ord('a')


class TestCacheStats:

    def test_stats_enable_track_and_reset(self, tmp_path):
        """A user enables stats, accumulates hits/misses, and resets."""
        c = Cache(str(tmp_path / "stats_cache"))
        c.stats(enable=True)

        c[0] = "value"
        for _ in range(100):
            c[0]
        for _ in range(10):
            c.get("missing")

        hits, misses = c.stats(reset=True)
        assert hits == 100
        assert misses == 10
        assert c.stats() == (0, 0)
        c.close()


class TestCacheMemoize:

    def test_memoize_typed_ignore_and_error(self, cache):
        """A user memoizes functions with typed mode, ignore params, and __cache_key__."""
        call_count = 0

        @cache.memoize(typed=True)
        def compute(x, y):
            nonlocal call_count
            call_count += 1
            return x + y

        assert compute(1, 2) == 3
        assert compute(1, 2) == 3
        assert call_count == 1

        assert compute(1.0, 2.0) == 3.0
        assert call_count == 2

        assert hasattr(compute, '__cache_key__')
        # The key returned by __cache_key__ must address the memoized entry through the
        # public cache API (documented contract: cache[fn.__cache_key__(...)] -> the result).
        assert cache[compute.__cache_key__(1, 2)] == 3

        call_count2 = 0

        @cache.memoize(ignore=('session',))
        def fetch(url, session=None):
            nonlocal call_count2
            call_count2 += 1
            return f"result_{url}"

        assert fetch("http://example.com", session="abc") == "result_http://example.com"
        assert fetch("http://example.com", session="xyz") == "result_http://example.com"
        assert call_count2 == 1

        with pytest.raises(TypeError, match="name cannot be callable"):
            @cache.memoize
            def bad_func():
                pass


class TestCacheTransactions:

    def test_transact_atomic_and_concurrent(self, tmp_path):
        """Transactions provide atomicity for grouped operations and serialization across threads."""
        c = Cache(str(tmp_path / "txn_cache"))

        # Basic atomic grouping
        c["counter"] = 0
        with c.transact():
            c["counter"] = c["counter"] + 1
            c["counter"] = c["counter"] + 1
        assert c["counter"] == 2

        # Concurrent threads using transact — no lost updates
        c["counter"] = 0
        iterations = 50

        def increment_worker():
            for _ in range(iterations):
                with c.transact(retry=True):
                    c["counter"] = c["counter"] + 1

        threads = [threading.Thread(target=increment_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c["counter"] == iterations * 4
        c.close()


class TestCacheSettings:

    def test_settings_volume_check_and_storage(self, tmp_path):
        """A user configures settings, monitors volume, checks consistency, and uses different storage modes."""
        c = Cache(str(tmp_path / "settings_cache"))

        # reset() reads and changes settings
        current = c.reset('size_limit')
        assert current == DEFAULT_SETTINGS['size_limit']
        c.reset('size_limit', 2**20)
        assert c.reset('size_limit') == 2**20
        c.reset('eviction_policy', 'least-recently-used')
        assert c.reset('eviction_policy') == 'least-recently-used'
        c.reset('cull_limit', 5)
        assert c.reset('cull_limit') == 5

        # volume() tracks size, check() verifies consistency
        initial_vol = c.volume()
        for i in range(50):
            c[i] = f"value_{i}" * 100
        assert c.volume() > initial_vol
        assert c.check() == []
        assert c.check(fix=True) == []
        c.close()

        # disk_min_file_size: both storage modes work
        large_value = b"x" * 100000
        c1 = Cache(str(tmp_path / "file_cache"), disk_min_file_size=0)
        c1.set("key", large_value)
        assert c1.get("key") == large_value
        assert c1.volume() >= 100000
        c1.close()

        c2 = Cache(str(tmp_path / "sqlite_cache"), disk_min_file_size=2**30)
        c2.set("key", large_value)
        assert c2.get("key") == large_value
        assert c2.volume() >= 100000
        c2.close()


class TestCacheEviction:

    def test_none_eviction_policy(self, tmp_path):
        """'none' eviction policy never auto-evicts; cull() does nothing."""
        c = Cache(str(tmp_path / "none_cache"), eviction_policy='none',
                  size_limit=int(5.1e6))

        million = b'x' * int(1e6)
        for i in range(10):
            c[i] = million

        assert len(c) == 10
        culled = c.cull()
        assert culled == 0
        assert len(c) == 10
        c.close()

    def test_manual_expire_and_cull_under_concurrent_writes(self, tmp_path):
        """Explicit expire()/cull() maintenance is safe and effective while other threads write.

        Distinct from the passive size_limit-driven eviction exercised by
        test_multiprocess_eviction_under_contention: here a maintenance thread calls expire()
        and cull() concurrently with writers, and we verify (a) no thread errors, (b) the cache
        stays internally consistent, (c) cull() keeps volume bounded, and (d) a final expire()
        sweep removes every short-TTL item while permanent items survive — proving manual TTL
        maintenance composes correctly with concurrent writes.
        """
        c = Cache(str(tmp_path / "manual_maint"), eviction_policy='least-recently-stored',
                  size_limit=int(5.1e6), cull_limit=5)

        million = b'x' * int(1e6)
        n_writers = 4
        per_writer = 20
        errors = []
        stop = threading.Event()

        # Each writer stores one permanent and one short-TTL item per index, so the suite can
        # later assert exactly which items the final expire() sweep must remove vs keep.
        def writer(wid):
            try:
                for i in range(per_writer):
                    c.set(f"perm_{wid}_{i}", million, retry=True)
                    c.set(f"ttl_{wid}_{i}", b"y" * 1000, expire=0.05, retry=True)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        # Maintenance thread runs expire()/cull() concurrently with the writers.
        def maintainer():
            try:
                while not stop.is_set():
                    c.expire(retry=True)
                    c.cull(retry=True)
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        writers = [threading.Thread(target=writer, args=(w,)) for w in range(n_writers)]
        maint = threading.Thread(target=maintainer)
        maint.start()
        for t in writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        maint.join()

        assert len(errors) == 0
        assert c.check() == []

        # cull() under contention must actually bound the cache, not silently no-op: volume
        # stays near size_limit (one cull batch of ~1MB-scale items of slack).
        assert c.volume() <= int(5.1e6) + int(2e6)

        # A final expire() with a future timestamp removes every remaining short-TTL item;
        # permanent items (that were not size-evicted) are never touched by expiration.
        time.sleep(0.1)
        c.expire(now=time.time() + 60, retry=True)
        for w in range(n_writers):
            for i in range(per_writer):
                assert c.get(f"ttl_{w}_{i}") is None
        # At least some permanent items survive (the most-recently-stored, under LRS culling).
        surviving_perm = sum(
            1 for w in range(n_writers) for i in range(per_writer)
            if c.get(f"perm_{w}_{i}") is not None
        )
        assert surviving_perm > 0
        c.close()


class TestCacheCrossProcess:

    def test_multiprocess_concurrent_writes(self, tmp_path):
        """Multiple processes write to the same Cache without data loss."""
        directory = str(tmp_path / "mp_cache")
        Cache(directory).close()

        tasks = [(directory, f"key_{i}", f"value_{i}") for i in range(100)]

        with ProcessPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_mp_cache_set_worker, tasks))

        assert all(results)

        with Cache(directory) as c:
            for i in range(100):
                assert c[f"key_{i}"] == f"value_{i}"

    def test_multiprocess_queue_producer_consumer(self, tmp_path):
        """Producers push from multiple processes, then all items are pulled."""
        directory = str(tmp_path / "mp_queue")
        Cache(directory).close()

        push_tasks = [(directory, f"item_{i}", "queue") for i in range(20)]

        with ProcessPoolExecutor(max_workers=4) as executor:
            list(executor.map(_mp_cache_push_worker, push_tasks))

        pulled_values = []
        with Cache(directory) as c:
            while True:
                key, val = c.pull(prefix="queue", retry=True)
                if val is None:
                    break
                pulled_values.append(val)

        assert len(pulled_values) == 20
        assert set(pulled_values) == {f"item_{i}" for i in range(20)}


# ================================================================
# 2. FANOUTCACHE
# ================================================================


class TestFanoutCacheIntegration:

    def test_full_crud_distributed(self, fanout):
        """A user stores, retrieves, and deletes items across shards."""
        for i in range(100):
            fanout.set(i, i)
        assert fanout.check() == []

        for i in range(100):
            assert fanout.get(i) == i
            assert i in fanout

        for i in range(100):
            assert fanout.delete(i)

        assert len(fanout) == 0
        assert fanout.check() == []

    def test_concurrent_add_across_shards(self, tmp_path):
        """Concurrent add() operations maintain exactly-once semantics."""
        with FanoutCache(str(tmp_path / "concurrent_fc"), shards=4) as fc:
            results = collections.deque()
            limit = 500

            def stress_add(result_list):
                total = 0
                for num in range(limit):
                    if fc.add(num, num, retry=True):
                        total += 1
                        time.sleep(0.001)
                result_list.append(total)

            threads = [
                threading.Thread(target=stress_add, args=(results,))
                for _ in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert sum(results) == limit
            assert fc.check() == []

    def test_expiration_stats_and_clear(self, tmp_path):
        """Expiration, stats, and clear work across shards."""
        fc = FanoutCache(str(tmp_path / "fanout_exp"), shards=2, statistics=True)

        fc.set("permanent", "val")
        fc.set("missing_key_for_miss", "val")
        fc.delete("missing_key_for_miss")

        # Generate hits and misses
        assert fc.get("permanent") == "val"
        assert fc.get("nonexistent") is None

        hits, misses = fc.stats()
        assert hits == 1
        assert misses == 1

        fc.clear()
        assert len(fc) == 0
        fc.close()

    def test_incr_pop_factories_transact_iter_volume(self, fanout):
        """FanoutCache incr/decr/pop, subdirectory factories, transact, iteration, and volume."""
        # incr/decr/pop
        assert fanout.incr("cnt", delta=3) == 3
        assert fanout.decr("cnt", delta=1) == 2
        assert fanout.pop("cnt") == 2
        assert fanout.get("cnt") is None

        # subdirectory factories
        sub_cache = fanout.cache("sub_cache")
        try:
            sub_cache["key"] = "value"
            assert sub_cache["key"] == "value"
        finally:
            sub_cache.close()

        sub_deque = fanout.deque("sub_deque")
        sub_deque.append("item")
        assert list(sub_deque) == ["item"]

        sub_index = fanout.index("sub_index")
        sub_index["idx_key"] = "idx_val"
        assert sub_index["idx_key"] == "idx_val"

        # transact + iteration + volume
        fanout["key"] = 0
        with fanout.transact():
            fanout["key"] = fanout["key"] + 1
        assert fanout["key"] == 1

        for i in range(50):
            fanout[i] = i
        keys = list(fanout)
        assert len(keys) == 51

        # A file-backed value (>= disk_min_file_size, default 32 KiB) contributes a
        # nonzero stored-value size, so volume() (the sum of stored value sizes) is
        # strictly positive independent of how inline scalars are sized.
        fanout["big"] = b"x" * 100000
        assert len(list(fanout)) == 52
        assert fanout.volume() > 0

    def test_memoize_across_shards(self, fanout):
        """memoize() stores the result under __cache_key__ in the routed shard, reachable
        through the public FanoutCache key lookup."""
        call_count = 0

        @fanout.memoize()
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert compute(5) == 10
        assert compute(5) == 10
        assert call_count == 1

        # FanoutCache-specific concern: the memoized entry must round-trip through the correct
        # shard, so the documented cache[fn.__cache_key__(...)] lookup resolves it via the
        # public sharded surface (not just through the decorated function).
        key = compute.__cache_key__(5)
        assert fanout[key] == 10
        assert fanout.get(key) == 10
        assert key in fanout

        # Deleting through the public key invalidates the memoized entry, forcing recompute.
        del fanout[key]
        assert compute(5) == 10
        assert call_count == 2

    def test_evict_tag_index_and_cull(self, tmp_path):
        """Tag eviction, tag index, and manual cull on FanoutCache."""
        fc = FanoutCache(str(tmp_path / "fc_evict"), shards=2)
        fc.create_tag_index()

        for i in range(6):
            fc.set(f"a_{i}", f"value_a_{i}", tag="group_a")
        for i in range(4):
            fc.set(f"b_{i}", f"value_b_{i}", tag="group_b")

        assert len(fc) == 10
        evicted = fc.evict("group_a")
        assert evicted == 6
        assert len(fc) == 4

        fc.drop_tag_index()
        fc.close()

    def test_touch_reset_read(self, tmp_path):
        """Touch, reset, and read through FanoutCache."""
        fc = FanoutCache(str(tmp_path / "fc_misc"), shards=2,
                         disk_min_file_size=0)

        fc.set("ttl_key", "val", expire=10)
        assert fc.touch("ttl_key", expire=100)
        assert fc.get("ttl_key") == "val"

        fc.reset('size_limit', 2**20)
        assert fc.reset('size_limit') == 2**20

        fc.set("file_key", b"data" * 10000)
        handle = fc.read("file_key")
        assert handle.read() == b"data" * 10000
        handle.close()

        fc.close()

    def test_fanout_cull_and_expire(self, tmp_path):
        """FanoutCache cull and expire across shards."""
        # expire: add items with short TTL, verify they get removed
        fc = FanoutCache(str(tmp_path / "fc_expire"), shards=2)
        fc.set("short1", "val", expire=0.05)
        fc.set("short2", "val", expire=0.05)
        fc.set("permanent", "val")
        time.sleep(0.1)
        expired = fc.expire()
        assert expired == 2
        assert fc.get("permanent") == "val"
        assert fc.get("short1") is None

        # cull: total volume is far below size_limit, so nothing is culled
        culled = fc.cull()
        assert culled == 0

        fc.close()

    def test_set_silent_on_timeout_vs_retry_succeeds(self, tmp_path):
        """FanoutCache.set fails silently (returns False) on a database timeout
        unless retry=True, in which case it blocks until the lock frees and succeeds."""
        # Single shard so every key contends on the same database; tiny timeout so a
        # blocked write gives up quickly.
        fc = FanoutCache(str(tmp_path / "fc_timeout"), shards=1, timeout=0.05)

        holding = threading.Event()
        release = threading.Event()

        def hold_write_lock():
            # transact() takes an exclusive write lock on the shard for the body's duration,
            # so any concurrent write must wait on it.
            with fc.transact():
                holding.set()
                release.wait(2.0)

        holder = threading.Thread(target=hold_write_lock)
        holder.start()
        try:
            assert holding.wait(2.0)
            # Lock is held by the other thread: retry=False gives up after timeout and
            # reports failure by returning False rather than raising.
            assert fc.set("k", "v1", retry=False) is False
        finally:
            release.set()
            holder.join(5.0)
        assert not holder.is_alive()

        # With the lock free, retry=True (and the default uncontended path) succeed.
        assert fc.set("k", "v2", retry=True) is True
        assert fc.get("k") == "v2"
        fc.close()

    def test_multiprocess_sharded_writes(self, tmp_path):
        """Multiple processes write concurrently through FanoutCache."""
        directory = str(tmp_path / "mp_fanout")
        FanoutCache(directory, shards=4).close()

        tasks = [(directory, f"key_{i}", f"value_{i}") for i in range(100)]

        with ProcessPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_mp_fanout_set_worker, tasks))

        assert all(results)

        with FanoutCache(directory) as fc:
            for i in range(100):
                assert fc[f"key_{i}"] == f"value_{i}"


# ================================================================
# 3. DJANGOCACHE
# ================================================================


def _make_django_cache(directory, **extra_options):
    from diskcache import DjangoCache
    options = {'size_limit': 2**30}
    options.update(extra_options)
    params = {
        'TIMEOUT': 300,
        'SHARDS': 4,
        'DATABASE_TIMEOUT': 0.1,
        'OPTIONS': options,
    }
    return DjangoCache(directory, params)


class TestDjangoCacheIntegration:

    def test_crud_and_has_key(self, tmp_path):
        """Django cache API: set, get, add, delete, has_key, clear."""
        dc = _make_django_cache(str(tmp_path / "django_cache"))

        dc.set("key1", "value1")
        assert dc.get("key1") == "value1"
        assert dc.has_key("key1")

        assert dc.add("key2", "value2")
        assert not dc.add("key2", "replaced")
        assert dc.get("key2") == "value2"

        dc.delete("key1")
        assert dc.get("key1") is None
        assert not dc.has_key("key1")

        assert "key2" in dc
        assert "key1" not in dc

        dc.clear()
        assert dc.get("key2") is None
        dc.close()

    def test_bulk_operations(self, tmp_path):
        """Django cache API: set_many, get_many, delete_many, get_or_set."""
        dc = _make_django_cache(str(tmp_path / "django_bulk"))

        dc.set_many({"a": 1, "b": 2, "c": 3})

        result = dc.get_many(["a", "b", "c", "missing"])
        assert result == {"a": 1, "b": 2, "c": 3}

        dc.delete_many(["a", "b"])
        assert dc.get("a") is None
        assert dc.get("c") == 3

        val = dc.get_or_set("new_key", "default_val")
        assert val == "default_val"
        val2 = dc.get_or_set("new_key", "other_val")
        assert val2 == "default_val"
        dc.close()

    def test_incr_decr_and_versioning(self, tmp_path):
        """Django cache API: incr, decr, incr_version, decr_version."""
        dc = _make_django_cache(str(tmp_path / "django_incr"))

        dc.set("counter", 10)
        assert dc.incr("counter") == 11
        assert dc.incr("counter", 5) == 16
        assert dc.decr("counter", 3) == 13

        assert dc.incr("new_counter", default=0) == 1

        dc.set("versioned", "v1", version=1)
        assert dc.get("versioned", version=1) == "v1"
        assert dc.get("versioned", version=2) is None

        new_version = dc.incr_version("versioned", version=1)
        assert new_version == 2
        assert dc.get("versioned", version=2) == "v1"
        assert dc.get("versioned", version=1) is None
        dc.close()

    def test_expiration_and_touch(self, tmp_path):
        """Django cache API: timeout and touch."""
        dc = _make_django_cache(str(tmp_path / "django_ttl"))

        dc.set("short_lived", "val", timeout=10)
        assert dc.get("short_lived") == "val"

        # touch updates the timeout
        assert dc.touch("short_lived", timeout=100)
        # Verify item still accessible
        assert dc.get("short_lived") == "val"

        # Expired items return None
        dc.set("dying", "val", timeout=0.1)
        time.sleep(0.3)
        assert dc.get("dying") is None
        dc.close()

    def test_diskcache_extensions(self, tmp_path):
        """DjangoCache supports diskcache-specific features beyond standard Django API."""
        dc = _make_django_cache(str(tmp_path / "django_ext"))

        dc.set("tagged", "val", tag="important")
        dc.create_tag_index()
        dc.set("tagged2", "val2", tag="important")
        dc.set("other", "val3", tag="other")

        evicted = dc.evict("important")
        assert evicted == 2
        assert dc.get("other") == "val3"
        dc.drop_tag_index()

        dc.stats(enable=True)
        dc.set("x", 1)
        dc.get("x")
        dc.get("missing")
        hits, misses = dc.stats()
        assert hits == 1
        assert misses == 1

        dc.set("pop_me", "val")
        assert dc.pop("pop_me") == "val"
        assert dc.get("pop_me") is None

        sub_cache = dc.cache("sub")
        sub_cache["k"] = "v"
        assert sub_cache["k"] == "v"
        sub_cache.close()

        sub_deque = dc.deque("sub_d")
        sub_deque.append("item")
        assert list(sub_deque) == ["item"]

        sub_index = dc.index("sub_i")
        sub_index["k"] = "v"
        assert sub_index["k"] == "v"

        call_count = 0

        @dc.memoize()
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert compute(5) == 10
        assert compute(5) == 10
        assert call_count == 1
        dc.close()

    def test_read_expire_cull_decr_version(self, tmp_path):
        """DjangoCache read, expire, cull, and decr_version."""
        dc = _make_django_cache(str(tmp_path / "django_misc"))

        # read
        dc.set("filedata", b"binary" * 1000)
        result = dc.read("filedata")
        if hasattr(result, 'read'):
            assert result.read() == b"binary" * 1000
            result.close()
        else:
            assert result == b"binary" * 1000

        # expire: short-lived items are removed
        dc.set("short1", "val", timeout=0.05)
        dc.set("short2", "val", timeout=0.05)
        dc.set("perm", "val2")
        time.sleep(0.1)
        expired = dc.expire()
        assert expired == 2
        assert dc.get("perm") == "val2"
        assert dc.get("short1") is None

        # cull: cache is far below size_limit, so nothing is culled
        culled = dc.cull()
        assert culled == 0

        # decr_version
        dc.set("ver_key", "data", version=5)
        assert dc.get("ver_key", version=5) == "data"
        new_ver = dc.decr_version("ver_key", version=5)
        assert new_ver == 4
        assert dc.get("ver_key", version=4) == "data"
        assert dc.get("ver_key", version=5) is None

        dc.close()


# ================================================================
# 4. DEQUE
# ================================================================


class TestDequeIntegration:

    def test_full_deque_workflow(self, tmp_path):
        """Comprehensive test of Deque as a persistent double-ended queue."""
        d = Deque(directory=str(tmp_path / "deque"))

        for i in range(10):
            d.append(i)
        assert len(d) == 10
        assert d.popleft() == 0
        assert d.popleft() == 1
        d.appendleft(-1)
        assert d[0] == -1
        assert d.pop() == 9

        d.extend([100, 200])
        d.extendleft([-200, -100])

        assert d.peekleft() == -100
        assert d.peek() == 200

        items = list(d)
        assert len(items) == len(d)
        rev_items = list(reversed(d))
        assert rev_items == list(reversed(items))

        orig = list(d)
        d.rotate(2)
        rotated = list(d)
        assert rotated == orig[-2:] + orig[:-2]

        d.reverse()
        reversed_list = list(d)
        assert reversed_list == list(reversed(rotated))

        d.clear()
        d.extend([10, 20, 30, 40, 50])
        assert d[0] == 10
        assert d[-1] == 50
        d[1] = 99
        assert d[1] == 99
        del d[1]
        assert list(d) == [10, 30, 40, 50]

        assert 30 in d
        assert 999 not in d

        d.clear()
        d.extend([1, 2, 3, 2, 1])
        assert d.count(2) == 2
        d.remove(2)
        assert d.count(2) == 1
        assert list(d) == [1, 3, 2, 1]

        assert d.index(3) == 1
        assert d.index(1) == 0
        assert d.index(1, 1) == 3

        d.clear()
        d.append(1)
        d += [2, 3, 4]
        assert list(d) == [1, 2, 3, 4]

        d2 = Deque([1, 2, 3, 4], directory=str(tmp_path / "deque2"))
        assert d == d2
        d2.append(5)
        assert d != d2
        assert d < d2
        assert d <= d2
        assert d2 > d
        assert d2 >= d

        d3 = d.copy()
        assert list(d3) == list(d)

        d4 = Deque(directory=str(tmp_path / "bounded"))
        d4.maxlen = 5
        for i in range(10):
            d4.append(i)
        assert len(d4) == 5
        assert list(d4) == [5, 6, 7, 8, 9]

        d5 = Deque([10, 20, 30], directory=str(tmp_path / "from_iter"))
        assert list(d5) == [10, 20, 30]

        d6 = Deque(directory=str(tmp_path / "txn_deque"))
        d6.append(1)
        with d6.transact():
            d6.append(2)
            d6.append(3)
        assert list(d6) == [1, 2, 3]

        c = Cache(str(tmp_path / "deque_from_cache"))
        d7 = Deque.fromcache(c, iterable=[100, 200])
        assert list(d7) == [100, 200]
        assert d7.cache is c
        c.close()

    def test_deque_concurrent_threads(self, tmp_path):
        """Multiple threads append to the same Deque concurrently."""
        d = Deque(directory=str(tmp_path / "mt_deque"))
        errors = []

        def append_worker(start, count):
            try:
                for i in range(start, start + count):
                    d.append(f"item_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=append_worker, args=(i * 10, 10))
                   for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(d) == 40
        values = set(list(d))
        assert values == {f"item_{i}" for i in range(40)}


# ================================================================
# 5. INDEX
# ================================================================


class TestIndexIntegration:

    def test_full_index_workflow(self, tmp_path):
        """Comprehensive test of Index as a persistent ordered mapping."""
        idx = Index(str(tmp_path / "index"))

        idx["alpha"] = 1
        idx["beta"] = 2
        idx["gamma"] = 3
        assert idx["alpha"] == 1
        assert len(idx) == 3

        assert list(idx) == ["alpha", "beta", "gamma"]
        assert list(reversed(idx)) == ["gamma", "beta", "alpha"]

        assert list(idx.keys()) == ["alpha", "beta", "gamma"]
        assert list(idx.values()) == [1, 2, 3]
        assert list(idx.items()) == [("alpha", 1), ("beta", 2), ("gamma", 3)]

        idx.update({"delta": 4, "epsilon": 5})
        assert len(idx) == 5

        assert idx.setdefault("alpha", 999) == 1
        assert idx.setdefault("zeta", 6) == 6

        assert idx.get("alpha") == 1
        assert idx.get("nonexistent") is None
        assert idx.get("nonexistent", "default") == "default"

        assert idx.pop("alpha") == 1
        with pytest.raises(KeyError):
            idx.pop("nonexistent")
        assert idx.pop("nonexistent", "default") == "default"

        key, val = idx.popitem(last=True)
        assert key == "zeta"
        key, val = idx.popitem(last=False)
        assert key == "beta"

        assert idx.peekitem() == ("epsilon", 5)
        assert idx.peekitem(last=False) == ("gamma", 3)

        assert "gamma" in idx
        assert "alpha" not in idx

        del idx["gamma"]
        assert "gamma" not in idx

        idx.clear()
        idx["x"] = 1
        idx["y"] = 2
        idx2 = Index(str(tmp_path / "index2"))
        idx2["x"] = 1
        idx2["y"] = 2
        assert idx == idx2
        idx2["z"] = 3
        assert idx != idx2

        idx3 = Index(str(tmp_path / "pp_index"))
        idx3.push("item1")
        idx3.push("item2")
        key, val = idx3.pull()
        assert val == "item1"

        idx4 = Index(str(tmp_path / "txn_index"))
        idx4["count"] = 0
        with idx4.transact():
            idx4["count"] = idx4["count"] + 1
        assert idx4["count"] == 1

        idx5 = Index(str(tmp_path / "dict_index"), {"a": 1, "b": 2})
        assert len(idx5) == 2
        assert idx5["a"] == 1

        idx6 = Index(str(tmp_path / "memo_index"))
        call_count = 0

        @idx6.memoize()
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 3

        assert compute(4) == 12
        assert compute(4) == 12
        assert call_count == 1

        c = Cache(str(tmp_path / "index_from_cache"))
        idx7 = Index.fromcache(c, {"p": 1, "q": 2})
        assert idx7["p"] == 1
        assert idx7.cache is c
        c.close()

    def test_index_cross_process(self, tmp_path):
        """Multiple processes write to the same Index concurrently."""
        directory = str(tmp_path / "mp_index")
        Index(directory)

        tasks = [(directory, f"key_{i}", f"value_{i}") for i in range(40)]

        with ProcessPoolExecutor(max_workers=4) as executor:
            list(executor.map(_mp_index_set_worker, tasks))

        idx = Index(directory)
        assert len(idx) == 40
        for i in range(40):
            assert idx[f"key_{i}"] == f"value_{i}"


# ================================================================
# 6. DISK / JSONDISK
# ================================================================


class TestCustomDisk:

    def test_json_disk_round_trip(self, tmp_path):
        """JSONDisk stores and retrieves JSON-serializable values with compression."""
        c = Cache(str(tmp_path / "json_cache"), disk=JSONDisk, disk_compress_level=6)
        values = [None, True, 0, 1.23, {}, [None] * 100, {"nested": {"key": [1, 2, 3]}}]
        for i, v in enumerate(values):
            c[i] = v
        for i, v in enumerate(values):
            assert c[i] == v
        c.close()

    def test_custom_filename_disk(self, tmp_path):
        """A custom Disk subclass controls the on-disk filename for file-backed values."""
        class SHA256Disk(Disk):
            def filename(self, key=UNKNOWN, value=UNKNOWN):
                filename = hashlib.sha256(key).hexdigest()[:32]
                full_path = op.join(self._directory, filename)
                return filename, full_path

        # disk_min_file_size=0 forces every value file-backed, so filename() is always
        # exercised regardless of the (unstated) default threshold — matching the sibling
        # file-backed tests rather than relying on a spec-unspecified default.
        c = Cache(str(tmp_path / "sha256_cache"), disk=SHA256Disk, disk_min_file_size=0)
        for count in range(100, 120):
            key = str(count).encode('ascii')
            c[key] = str(count) * int(1e5)

        for count in range(100, 120):
            key = str(count).encode('ascii')
            filename = hashlib.sha256(key).hexdigest()[:32]
            full_path = op.join(c.directory, filename)
            # The custom filename() controls where the blob lands on disk.
            assert op.exists(full_path)
            # The value round-trips through the public cache API regardless of on-disk format.
            assert c[key] == str(count) * int(1e5)
        c.close()


# ================================================================
# 7. RECIPES
# ================================================================


class TestRecipesLocking:

    def test_lock_serializes_threads(self, cache):
        """Lock serializes access across threads."""
        state = {'num': 0}
        lock = Lock(cache, 'demo')

        def worker():
            state['num'] += 1
            with lock:
                assert lock.locked()
                state['num'] += 1
                time.sleep(0.1)

        with lock:
            thread = threading.Thread(target=worker)
            thread.start()
            time.sleep(0.1)
            assert state['num'] == 1
        thread.join()
        assert state['num'] == 2

    def test_rlock_reentrant(self, cache):
        """RLock allows the same thread to acquire multiple times."""
        state = {'num': 0}
        rlock = RLock(cache, 'demo')

        def worker():
            state['num'] += 1
            with rlock:
                with rlock:
                    state['num'] += 1
                    time.sleep(0.1)

        with rlock:
            thread = threading.Thread(target=worker)
            thread.start()
            time.sleep(0.1)
            assert state['num'] == 1
        thread.join()
        assert state['num'] == 2

    def test_semaphore_limits_concurrent(self, cache):
        """BoundedSemaphore limits concurrent access to a resource."""
        state = {'num': 0}
        sem = BoundedSemaphore(cache, 'demo', value=3)

        def worker():
            state['num'] += 1
            with sem:
                state['num'] += 1
                time.sleep(0.1)

        sem.acquire()
        sem.acquire()
        with sem:
            thread = threading.Thread(target=worker)
            thread.start()
            time.sleep(0.1)
            assert state['num'] == 1
        thread.join()
        assert state['num'] == 2
        sem.release()
        sem.release()

    def test_lock_cross_process(self, tmp_path):
        """Lock serializes access across processes."""
        directory = str(tmp_path / "mp_lock")
        Cache(directory).close()

        tasks = [
            (directory, "shared_lock", 0.3),
            (directory, "shared_lock", 0.3),
        ]

        with ProcessPoolExecutor(max_workers=2) as executor:
            end_times = list(executor.map(_mp_lock_acquire_worker, tasks))

        diff = abs(end_times[0] - end_times[1])
        assert diff >= 0.2

    def test_lock_with_expire_auto_release(self, cache):
        """Lock with expire auto-releases after timeout."""
        lock = Lock(cache, 'expiring_lock', expire=0.2)

        lock.acquire()
        assert lock.locked()

        time.sleep(0.3)

        # Lock should have auto-expired, another acquire should succeed without blocking
        lock2 = Lock(cache, 'expiring_lock', expire=1)
        lock2.acquire()
        assert lock2.locked()
        lock2.release()


class TestRecipesComputation:

    def test_averager_running_average(self, cache):
        """Averager computes running average and resets with pop."""
        avg = Averager(cache, 'nums')
        for i in range(10):
            avg.add(i)
        assert avg.get() == pytest.approx(4.5)
        result = avg.pop()
        assert result == pytest.approx(4.5)

        for i in range(20):
            avg.add(i)
        assert avg.get() == pytest.approx(9.5)

    def test_throttle_rate_limits(self, cache):
        """throttle decorator rate-limits function calls."""
        call_count = 0

        @throttle(cache, count=2, seconds=1)
        def limited_func():
            nonlocal call_count
            call_count += 1

        start = time.time()
        for _ in range(4):
            limited_func()
        elapsed = time.time() - start

        assert call_count == 4
        assert elapsed >= 0.5

    def test_barrier_serializes_calls(self, cache):
        """barrier ensures exclusive function execution."""
        results = []
        active = {'now': 0, 'max': 0}

        @barrier(cache, Lock)
        def exclusive_work(val):
            # No extra lock here: only the barrier may serialize entry. If it does,
            # at most one thread is ever inside the body, so max concurrency stays 1.
            active['now'] += 1
            active['max'] = max(active['max'], active['now'])
            results.append(val)
            time.sleep(0.05)
            active['now'] -= 1

        threads = [threading.Thread(target=exclusive_work, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 3
        assert sorted(results) == [0, 1, 2]
        # The barrier must serialize: never more than one invocation running at once.
        assert active['max'] == 1

    def test_memoize_stampede_full(self, cache):
        """memoize_stampede caches with stampede protection, __cache_key__, and recomputation."""
        call_count = 0

        @memoize_stampede(cache, expire=0.2)
        def compute(n):
            nonlocal call_count
            call_count += 1
            return n * 2

        assert compute(5) == 10
        assert compute(5) == 10
        assert call_count == 1

        assert hasattr(compute, '__cache_key__')
        # __cache_key__ returns a tuple key (a documented attribute). We do not assert the raw
        # object stored at that key: the on-disk stored shape (a (value, timing) pair) is a
        # repo-internal detail of the stampede algorithm, not a user-facing contract. The
        # caching + recomputation behavior is exercised through the decorated function below.
        assert isinstance(compute.__cache_key__(5), tuple)

        time.sleep(0.3)
        assert compute(5) == 10
        assert call_count > 1


# ================================================================
# 8. COMPLEX INTEGRATION SCENARIOS
# ================================================================


class TestComplexWorkflows:

    def test_web_caching_workflow(self, tmp_path):
        """Simulates a web application using cache for page fragments, session data, and task queues."""
        c = Cache(str(tmp_path / "webapp"), statistics=True, tag_index=True,
                  eviction_policy='least-recently-used', size_limit=2**20)

        # Phase 1: Cache page fragments with tags
        pages = {
            "home": ("<html>Home</html>", "page"),
            "about": ("<html>About</html>", "page"),
            "contact": ("<html>Contact</html>", "page"),
        }
        for key, (html, tag) in pages.items():
            c.set(f"page:{key}", html, tag=tag, expire=300)

        # Phase 2: Store session data with short TTL
        for i in range(10):
            c.set(f"session:{i}", {"user_id": i, "cart": [f"item_{i}"]}, expire=30)

        # Phase 3: Memoize an expensive computation
        call_count = 0

        @c.memoize(tag="computed")
        def render_template(name, version):
            nonlocal call_count
            call_count += 1
            return f"rendered:{name}:v{version}"

        assert render_template("home", 1) == "rendered:home:v1"
        assert render_template("home", 1) == "rendered:home:v1"
        assert call_count == 1

        # Phase 4: Use push/pull as a task queue
        for i in range(5):
            c.push(f"email_task_{i}", prefix="tasks")

        task_key, task_val = c.pull(prefix="tasks")
        assert task_val == "email_task_0"

        # Phase 5: Check stats
        hits, misses = c.stats()
        assert hits >= 1

        # Phase 6: Invalidate all page cache
        evicted = c.evict("page")
        assert evicted == 3
        assert c.get("page:home") is None
        assert c.get(f"session:0") == {"user_id": 0, "cart": ["item_0"]}

        # Phase 7: Verify volume and consistency
        assert c.volume() > 0
        assert c.check() == []

        c.close()

    def test_data_pipeline_deque_cache_index(self, tmp_path):
        """Simulates a data pipeline: Deque as work queue, Cache for results, Index for metadata."""
        work_queue = Deque(directory=str(tmp_path / "work_queue"))
        result_cache = Cache(str(tmp_path / "results"))
        metadata = Index(str(tmp_path / "metadata"))

        # Enqueue work items
        jobs = [{"id": i, "data": f"input_{i}"} for i in range(20)]
        for job in jobs:
            work_queue.append(job)
        assert len(work_queue) == 20

        # Process jobs: dequeue, compute, store result, track metadata
        processed = 0
        while len(work_queue) > 0:
            job = work_queue.popleft()
            result = f"output_{job['id']}_{job['data']}"
            result_cache.set(f"result:{job['id']}", result, tag="batch_1")
            metadata[f"job:{job['id']}"] = {
                "status": "complete",
                "input": job["data"],
            }
            processed += 1

        assert processed == 20
        assert len(work_queue) == 0

        # Verify all results and metadata
        for i in range(20):
            assert result_cache.get(f"result:{i}") == f"output_{i}_input_{i}"
            job_meta = metadata[f"job:{i}"]
            assert job_meta["status"] == "complete"
            assert job_meta["input"] == f"input_{i}"

        # Query metadata as ordered dict
        all_keys = list(metadata.keys())
        assert len(all_keys) == 20

        # Bulk invalidate results
        result_cache.create_tag_index()
        evicted = result_cache.evict("batch_1")
        assert evicted == 20

        result_cache.close()

    def test_multiprocess_counter_with_lock(self, tmp_path):
        """Multiple processes increment a shared counter using Lock for synchronization."""
        directory = str(tmp_path / "mp_counter")
        c = Cache(directory)
        c["counter"] = 0
        c.close()

        increments_per_worker = 25
        n_workers = 4
        tasks = [(directory, increments_per_worker)] * n_workers

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            list(executor.map(_mp_locked_increment_worker, tasks))

        with Cache(directory) as c:
            assert c["counter"] == increments_per_worker * n_workers


# ================================================================
# 9. EXACT EVICTION ORDERING
# ================================================================


class TestExactEvictionOrdering:

    def test_lru_evicts_exact_items(self, tmp_path):
        """LRU eviction removes exactly the items that were accessed least recently."""
        c = Cache(str(tmp_path / "lru_exact"), eviction_policy='least-recently-used',
                  size_limit=int(10.1e6), cull_limit=5)

        million = b'x' * int(1e6)
        for i in range(10):
            c[i] = million

        time.sleep(0.01)
        for key in [0, 1, 7, 8, 9]:
            c[key]

        c[10] = million

        for key in [2, 3, 4, 5, 6]:
            assert c.get(key) is None, f"Key {key} should have been evicted (LRU)"
        for key in [0, 1, 7, 8, 9, 10]:
            assert c[key] == million, f"Key {key} should have survived with correct value (LRU)"

        assert len(c) == 6
        c.close()

    def test_lfu_evicts_exact_items(self, tmp_path):
        """LFU eviction removes exactly the items with fewest accesses."""
        c = Cache(str(tmp_path / "lfu_exact"), eviction_policy='least-frequently-used',
                  size_limit=int(10.1e6), cull_limit=5)

        million = b'x' * int(1e6)
        for i in range(10):
            c[i] = million

        for _ in range(20):
            c[0]
        for _ in range(15):
            c[1]
        for _ in range(10):
            c[2]
        for _ in range(8):
            c[3]
        for _ in range(6):
            c[4]

        c[10] = million

        for key in [5, 6, 7, 8, 9]:
            assert c.get(key) is None, f"Key {key} should have been evicted (LFU)"
        for key in [0, 1, 2, 3, 4, 10]:
            assert c[key] == million, f"Key {key} should have survived with correct value (LFU)"

        assert len(c) == 6
        c.close()

    def test_lrs_evicts_exact_items_and_cull_limit(self, tmp_path):
        """LRS eviction removes oldest-stored items; cull_limit controls how many."""
        million = b'x' * int(1e6)

        # cull_limit=5: overflow triggers removal of 5 oldest
        c = Cache(str(tmp_path / "lrs_exact"), eviction_policy='least-recently-stored',
                  size_limit=int(10.1e6), cull_limit=5)
        for i in range(10):
            c[i] = million
        c[10] = million

        for key in [0, 1, 2, 3, 4]:
            assert c.get(key) is None, f"Key {key} should have been evicted (LRS)"
        for key in [5, 6, 7, 8, 9, 10]:
            assert c[key] == million, f"Key {key} should have survived (LRS)"
        assert len(c) == 6
        c.close()

        # cull_limit=3: overflow triggers removal of only 3 oldest
        c2 = Cache(str(tmp_path / "lrs_cull3"), eviction_policy='least-recently-stored',
                   size_limit=int(10.1e6), cull_limit=3)
        for i in range(10):
            c2[i] = million
        c2[10] = million

        for key in [0, 1, 2]:
            assert c2.get(key) is None, f"Key {key} should have been evicted"
        for key in [3, 4, 5, 6, 7, 8, 9, 10]:
            assert c2[key] == million, f"Key {key} should have survived"
        assert len(c2) == 8
        c2.close()


# ================================================================
# 10. WAL MODE AND CONCURRENT READ/WRITE
# ================================================================


class TestConcurrentReadWrite:

    def test_concurrent_readers_and_writer(self, tmp_path):
        """Readers are not blocked during writes, multiple readers work concurrently, and interleaved read/write is consistent."""
        c = Cache(str(tmp_path / "wal_cache"))

        # Pre-populate
        for i in range(100):
            c[f"key_{i}"] = f"value_{i}"

        # Phase 1: Reader not blocked during writer transaction
        read_results = []
        read_done = threading.Event()

        def long_writer():
            with c.transact():
                for i in range(100, 200):
                    c[f"key_{i}"] = f"value_{i}"
                read_done.wait(timeout=5)

        def reader():
            for i in range(100):
                val = c.get(f"key_{i}")
                read_results.append(val)
            read_done.set()

        writer_thread = threading.Thread(target=long_writer)
        reader_thread = threading.Thread(target=reader)
        writer_thread.start()
        time.sleep(0.05)
        reader_thread.start()
        reader_thread.join(timeout=10)
        writer_thread.join(timeout=10)

        assert len(read_results) == 100
        assert all(r == f"value_{i}" for i, r in enumerate(read_results))

        # Phase 2: Multiple concurrent readers
        results = [[] for _ in range(4)]
        errors = []

        def multi_reader(idx, result_list):
            try:
                for i in range(100):
                    result_list.append(c[f"key_{i}"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=multi_reader, args=(i, results[i])) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        for r in results:
            assert len(r) == 100

        # Phase 3: Interleaved writer and reader
        N = 200
        interleave_errors = []

        def interleave_writer():
            try:
                for i in range(N):
                    c.set(f"w_{i}", i, retry=True)
            except Exception as e:
                interleave_errors.append(e)

        def interleave_reader():
            try:
                for i in range(N):
                    val = c.get(f"w_{i}")
                    if val is not None:
                        assert val == i
            except Exception as e:
                interleave_errors.append(e)

        w = threading.Thread(target=interleave_writer)
        r = threading.Thread(target=interleave_reader)
        w.start()
        r.start()
        w.join()
        r.join()
        assert len(interleave_errors) == 0
        for i in range(N):
            assert c[f"w_{i}"] == i

        c.close()


# ================================================================
# 11. CROSS-FEATURE CASCADING
# ================================================================


class TestCrossFeatureCascading:

    def test_memoize_survives_eviction_and_recomputes(self, tmp_path):
        """Memoized value gets evicted by size pressure, next call recomputes."""
        c = Cache(str(tmp_path / "memo_evict"), eviction_policy='least-recently-stored',
                  size_limit=int(2.1e6), cull_limit=5)

        call_count = 0

        @c.memoize()
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 10

        assert compute(42) == 420
        assert call_count == 1
        assert compute(42) == 420
        assert call_count == 1

        # Fill cache to trigger eviction of the memoized entry
        million = b'x' * int(1e6)
        for i in range(10):
            c.set(f"filler_{i}", million)

        # Memoized value should have been evicted; next call recomputes
        assert compute(42) == 420
        assert call_count == 2

        c.close()

    def test_push_pull_with_expiration(self, tmp_path):
        """Queue items expire; pull returns default for expired items."""
        c = Cache(str(tmp_path / "queue_expire"))

        c.push("ephemeral", expire=10)
        c.push("permanent")

        # Before expiration, both are available
        _, val = c.peek()
        assert val == "ephemeral"

        # Expire with future timestamp
        future = time.time() + 20
        c.expire(now=future)

        # Ephemeral is gone, permanent remains
        key, val = c.pull()
        assert val == "permanent"

        c.close()

    def test_tag_eviction_updates_stats(self, tmp_path):
        """Evicting tagged items is reflected in cache length and volume."""
        c = Cache(str(tmp_path / "tag_stats"), statistics=True, tag_index=True)

        for i in range(20):
            c.set(f"item_{i}", f"value_{i}" * 100,
                  tag="batch_a" if i < 10 else "batch_b")

        vol_before = c.volume()
        len_before = len(c)
        assert len_before == 20

        evicted = c.evict("batch_a")
        assert evicted == 10
        assert len(c) == 10
        assert c.volume() < vol_before

        # All batch_b items still accessible
        for i in range(10, 20):
            assert c.get(f"item_{i}") == f"value_{i}" * 100

        c.close()

    def test_deque_and_index_persistence_across_reopen(self, tmp_path):
        """Deque and Index data survives close and reopen."""
        # Deque persistence
        deque_dir = str(tmp_path / "deque_persist")
        d = Deque([1, 2, 3, 4, 5], directory=deque_dir)
        d.append(6)
        assert len(d) == 6
        del d
        d2 = Deque(directory=deque_dir)
        assert len(d2) == 6
        assert list(d2) == [1, 2, 3, 4, 5, 6]

        # Index persistence
        index_dir = str(tmp_path / "index_persist")
        idx = Index(index_dir, {"a": 1, "b": 2, "c": 3})
        assert len(idx) == 3
        del idx
        idx2 = Index(index_dir)
        assert len(idx2) == 3
        assert idx2["a"] == 1
        assert idx2["b"] == 2
        assert idx2["c"] == 3


# ================================================================
# 12. ADDITIONAL MULTIPROCESS TESTS
# ================================================================


class TestMultiprocessAdditional:

    def test_multiprocess_memoize_shared(self, tmp_path):
        """Multiple processes share memoized results through the same cache directory."""
        directory = str(tmp_path / "mp_memo")
        c = Cache(directory)
        c.close()

        tasks = [(directory, i) for i in range(20)]

        with ProcessPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_mp_memoize_worker, tasks))

        assert results == [i * 2 for i in range(20)]

        with Cache(directory) as c:
            assert len(c) == 20

    def test_multiprocess_eviction_under_contention(self, tmp_path):
        """Multiple processes writing past size_limit with eviction maintains consistency."""
        directory = str(tmp_path / "mp_evict")
        c = Cache(directory, eviction_policy='least-recently-stored',
                  size_limit=int(2e6), cull_limit=10)
        c.close()

        tasks = [(directory, i * 50, 50) for i in range(4)]

        with ProcessPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_mp_cache_eviction_writer, tasks))

        assert all(results)

        with Cache(directory) as c:
            assert c.check() == []
            assert c.volume() <= int(2e6) * 3

    def test_multiprocess_incr_without_lock(self, tmp_path):
        """Cache.incr() is atomic across processes without explicit locking."""
        directory = str(tmp_path / "mp_incr")
        c = Cache(directory)
        c["counter"] = 0
        c.close()

        tasks = [(directory, 50)] * 4

        with ProcessPoolExecutor(max_workers=4) as executor:
            list(executor.map(_mp_atomic_incr_worker, tasks))

        with Cache(directory) as c:
            assert c["counter"] == 200


# ================================================================
# 13. FILE-BACKED VS INLINE STORAGE
# ================================================================


def _is_sqlite_db_file(name):
    """Return True for the SQLite database file or one of its journal companions.

    The base database filename is an internal implementation detail (the spec only says storage is
    "SQLite + the local filesystem"), so this matches by extension/journal pattern rather than a
    fixed name: any ``*.db`` / ``*.sqlite`` / ``*.sqlite3`` file plus the ``-wal`` / ``-shm`` /
    ``-journal`` write-ahead-log and rollback companions SQLite may create alongside it.
    """
    lower = name.lower()
    if lower.endswith((".db", ".sqlite", ".sqlite3", ".db3")):
        return True
    return any(marker in lower for marker in ("-wal", "-shm", "-journal"))


def _count_value_files(directory):
    """Count file-backed value blobs written under a cache directory.

    Counts every regular file in the directory tree except the SQLite database files. The cache
    only ever writes two kinds of files: the SQLite database (plus its journal companions) and the
    file-backed value blobs, so excluding the former leaves exactly the value blobs. The database
    filename and the value-blob suffix are both repo-internal details not pinned by the spec, so
    this neither hardcodes the database name nor assumes a fixed blob extension.
    """
    return sum(
        1
        for _root, _dirs, files in os.walk(directory)
        for name in files
        if not _is_sqlite_db_file(name)
    )


class TestStorageMode:

    def test_large_value_uses_file_below_min_file_size_else_inline(self, tmp_path):
        """disk_min_file_size routes large values to on-disk files and small ones inline to SQLite."""
        N = 20
        large_value = b"x" * (1024 * 1024)

        # A small disk_min_file_size routes large values to separate files on disk.
        file_dir = str(tmp_path / "file_storage")
        c_file = Cache(file_dir, disk_min_file_size=1024)
        for i in range(N):
            c_file.set(f"key_{i}", large_value)
        for i in range(N):
            assert c_file.get(f"key_{i}") == large_value
        assert _count_value_files(file_dir) == N
        c_file.close()

        # A huge disk_min_file_size keeps the same values inline in SQLite (no .val files).
        inline_dir = str(tmp_path / "inline_storage")
        c_inline = Cache(inline_dir, disk_min_file_size=1024 * 1024 * 10)
        for i in range(N):
            c_inline.set(f"key_{i}", large_value)
        for i in range(N):
            assert c_inline.get(f"key_{i}") == large_value
        assert _count_value_files(inline_dir) == 0
        c_inline.close()
