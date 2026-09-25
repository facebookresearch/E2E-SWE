"""User-facing behaviour of the ObjectProxy variants:
``LazyObjectProxy`` (defers creation of the wrapped object until first use),
``AutoObjectProxy`` (adds special dunder methods to match the wrapped object)
and ``lazy_import`` (a LazyObjectProxy that imports a module on first access)."""

import asyncio

import wrapt


def test_lazy_object_proxy_and_lazy_import_defer_until_first_use():
    """``LazyObjectProxy`` does not call its factory until first use, then caches
    the result; ``lazy_import`` is a LazyObjectProxy that imports a module (or a
    named attribute of it) on first access."""

    created = []

    def factory():
        created.append(1)
        return [10, 20, 30]

    proxy = wrapt.LazyObjectProxy(factory, interface=list)
    assert created == []  # not created just by constructing
    assert len(proxy) == 3
    assert list(proxy) == [10, 20, 30]
    assert created == [1]  # created once, then cached

    json_proxy = wrapt.lazy_import("json")
    assert json_proxy.dumps({"a": 1}) == '{"a": 1}'
    dumps_proxy = wrapt.lazy_import("json", "dumps")
    assert dumps_proxy({"b": 2}) == '{"b": 2}'


def test_auto_object_proxy_adds_special_methods_matching_wrapped():
    """``AutoObjectProxy`` adds exactly the special methods appropriate to the
    wrapped object: call forwarding for callables, iteration for iterables,
    ``__next__`` for iterators, ``__length_hint__`` when present, ``__await__``
    for coroutine functions, and descriptor ``__get__`` forwarding."""

    # Callable.
    assert wrapt.AutoObjectProxy(lambda x: x + 1)(41) == 42

    # Iterable and iterator.
    assert list(wrapt.AutoObjectProxy([1, 2, 3])) == [1, 2, 3]
    iterator_proxy = wrapt.AutoObjectProxy(iter([1, 2, 3]))
    assert next(iterator_proxy) == 1
    assert list(iterator_proxy) == [2, 3]

    # length hint.
    import operator

    class Sized:
        def __length_hint__(self):
            return 42

    assert operator.length_hint(wrapt.AutoObjectProxy(Sized())) == 42

    # Awaitable (coroutine function).
    async def coro(x):
        return x + 1

    assert asyncio.run(wrapt.AutoObjectProxy(coro)(5)) == 6

    # Descriptor __get__ forwarding.
    class Descriptor:
        def __get__(self, instance, owner):
            return "descriptor-value"

    class Host:
        attr = wrapt.AutoObjectProxy(Descriptor())

    assert Host().attr == "descriptor-value"


def test_auto_object_proxy_readapts_when_wrapped_is_reassigned():
    """Reassigning ``__wrapped__`` re-derives the special methods: a proxy that
    was iterable becomes callable when pointed at a callable, and a proxy that
    was callable stops being callable when pointed at a non-callable."""

    proxy = wrapt.AutoObjectProxy([1, 2])
    assert list(proxy) == [1, 2]
    proxy.__wrapped__ = lambda z: z * 3
    assert proxy(4) == 12

    callable_proxy = wrapt.AutoObjectProxy(lambda x: x + 1)
    assert callable_proxy(1) == 2
    callable_proxy.__wrapped__ = 5
    assert callable(callable_proxy) is False
    assert int(callable_proxy) == 5
