"""User-facing behaviour of wrapt's synchronization and calling-convention
helpers: ``synchronized`` (thread/async mutual exclusion, context-manager and
explicit-lock forms), the ``async_to_sync`` / ``sync_to_async`` bridges, and the
``mark_as_async`` / ``mark_as_sync`` convention markers."""

import asyncio
import inspect
import threading
import time

import wrapt


def test_synchronized_serializes_concurrent_calls_thread_and_async():
    """``@synchronized`` guarantees mutual exclusion: no two threads (nor two
    awaited coroutines) execute the body at the same time, and every call
    runs."""

    def run_thread_case():
        state = {"active": 0, "violations": 0, "completed": 0}

        @wrapt.synchronized
        def critical_section():
            state["active"] += 1
            if state["active"] != 1:
                state["violations"] += 1
            time.sleep(0.002)
            state["active"] -= 1
            state["completed"] += 1

        threads = [threading.Thread(target=critical_section) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return state

    thread_state = run_thread_case()
    assert thread_state["violations"] == 0 and thread_state["completed"] == 20

    async_state = {"active": 0, "violations": 0, "completed": 0}

    @wrapt.synchronized
    async def acritical():
        async_state["active"] += 1
        if async_state["active"] != 1:
            async_state["violations"] += 1
        await asyncio.sleep(0.002)
        async_state["active"] -= 1
        async_state["completed"] += 1

    async def driver():
        await asyncio.gather(*(acritical() for _ in range(20)))

    asyncio.run(driver())
    assert async_state["violations"] == 0 and async_state["completed"] == 20


def test_synchronized_context_manager_and_explicit_lock_forms():
    """``synchronized`` supports both the auto-lock and supplied-lock forms, as
    a decorator and as a context manager, for sync and async usage."""

    # Auto-lock: the decorated function is itself a (reentrant) context manager.
    @wrapt.synchronized
    def task():
        return 1

    with task:
        assert task() == 1  # reentrant auto-lock

    # Supplied sync lock used directly, as decorator and as context manager.
    lock = threading.Lock()

    @wrapt.synchronized(lock)
    def guarded():
        assert lock.locked()
        return "done"

    assert guarded() == "done"
    assert not lock.locked()
    with wrapt.synchronized(lock) as held:
        assert held is lock and lock.locked()
    assert not lock.locked()

    # Async usage: async function as async context manager, and supplied
    # asyncio.Lock.
    @wrapt.synchronized
    async def atask():
        return 2

    alock = asyncio.Lock()

    @wrapt.synchronized(alock)
    async def aguarded():
        assert alock.locked()
        return "aok"

    async def driver():
        events = []
        async with atask:
            events.append("inside")
        result = await aguarded()
        return events, result

    assert asyncio.run(driver()) == (["inside"], "aok")


def test_synchronized_on_classmethod():
    """``@synchronized`` works when stacked on a class method, serializing calls
    and delivering the class correctly."""

    class Registry:
        created = 0

        @wrapt.synchronized
        @classmethod
        def build(cls):
            cls.created += 1
            return cls.__name__

    assert Registry.build() == "Registry"
    assert Registry.created == 1


def test_async_sync_bridges():
    """``async_to_sync`` runs a coroutine from sync code (reporting sync);
    ``sync_to_async`` makes a sync callable awaitable (reporting async)."""

    @wrapt.async_to_sync
    async def fetch(value):
        await asyncio.sleep(0)
        return value * 2

    @wrapt.sync_to_async
    def blocking(value):
        return value + 1

    assert fetch(21) == 42
    assert inspect.iscoroutinefunction(fetch) is False
    assert inspect.iscoroutinefunction(blocking) is True
    assert asyncio.run(blocking(9)) == 10


def test_calling_convention_markers_and_reporting():
    """The calling-convention markers change what introspection reports without
    changing behaviour: ``mark_as_async``/``mark_as_sync`` flip coroutine-ness,
    their ``generator=True`` forms flip async-generator/generator reporting, and
    a ``@synchronized`` async function still reports as a coroutine function."""

    def plain():
        return 1

    async def coro():
        return 2

    def gen():
        yield 1

    marked_async = wrapt.mark_as_async(plain)
    marked_sync = wrapt.mark_as_sync(coro)

    assert inspect.iscoroutinefunction(marked_async) is True
    assert inspect.iscoroutinefunction(marked_sync) is False
    assert asyncio.run(marked_async()) == 1

    assert inspect.isasyncgenfunction(wrapt.mark_as_async(gen, generator=True)) is True
    assert inspect.isgeneratorfunction(wrapt.mark_as_sync(gen, generator=True)) is True

    @wrapt.synchronized
    async def guarded():
        return 7

    assert inspect.iscoroutinefunction(guarded) is True
    assert asyncio.run(guarded()) == 7
