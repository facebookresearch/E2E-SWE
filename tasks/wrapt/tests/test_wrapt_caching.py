"""User-facing behaviour of ``wrapt.lru_cache``: a ``functools.lru_cache``
replacement that caches plain functions like the stdlib version but keeps a
*separate* cache per instance for instance methods, and exposes
``cache_info`` / ``cache_clear`` on the decorated callable."""

import wrapt


def test_lru_cache_memoizes_plain_function_with_cache_controls():
    """Repeated calls are served from the cache; ``cache_info`` tracks
    hits/misses, ``cache_clear`` resets, and ``maxsize`` is forwarded to
    functools so evicted entries miss again."""

    calls = []

    @wrapt.lru_cache
    def square(n):
        calls.append(n)
        return n * n

    assert square(3) == 9  # miss
    assert square(3) == 9  # hit
    assert square(4) == 16  # miss
    assert calls == [3, 4]
    info = square.cache_info()
    assert (info.hits, info.misses) == (1, 2)
    square.cache_clear()
    assert square.cache_info().misses == 0

    evictions = []

    @wrapt.lru_cache(maxsize=1)
    def identity(n):
        evictions.append(n)
        return n

    identity(1)  # caches 1
    identity(2)  # evicts 1, caches 2
    identity(1)  # miss again (1 was evicted)
    assert evictions == [1, 2, 1]
    assert identity.cache_info().maxsize == 1


def test_lru_cache_method_caching_per_instance_vs_shared():
    """Instance methods get an independent cache per instance (with independent
    ``cache_info``), while class methods and static methods share a single cache
    (matching ``functools``); ``cache_parameters`` reports the configuration."""

    class Calculator:
        def __init__(self):
            self.invocations = 0

        @wrapt.lru_cache
        def triple(self, n):
            self.invocations += 1
            return n * 3

    a = Calculator()
    b = Calculator()
    assert a.triple(2) == 6 and a.triple(2) == 6  # miss then hit on a
    assert b.triple(2) == 6  # independent cache on b
    assert a.invocations == 1 and b.invocations == 1
    assert a.triple.cache_info().hits == 1
    assert b.triple.cache_info().hits == 0

    class Registry:
        cm_calls = 0
        sm_calls = 0

        @wrapt.lru_cache(maxsize=5, typed=True)
        @classmethod
        def from_id(cls, n):
            Registry.cm_calls += 1
            return n * 10

        @wrapt.lru_cache
        @staticmethod
        def normalize(n):
            Registry.sm_calls += 1
            return n * 100

    assert Registry.from_id(2) == 20 and Registry.from_id(2) == 20
    assert Registry.cm_calls == 1
    assert Registry.from_id.cache_parameters() == {"maxsize": 5, "typed": True}
    assert Registry.normalize(3) == 300 and Registry.normalize(3) == 300
    assert Registry.sm_calls == 1
