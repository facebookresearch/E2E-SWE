"""
Tests for trio — structured concurrency async I/O library.

Tests exercise the complete trio API: trio.run() entry point, nurseries with
structured concurrency, CancelScope with deadlines and shielding, memory
channels with backpressure, synchronization primitives, timeouts, thread
interop, file I/O, subprocess management, MockClock for deterministic timing,
and checkpoint behavior.

All tests use trio.run() with MockClock(autojump_threshold=0) for
deterministic execution — no real sleeps or I/O waits.
"""

import math
import os
import tempfile
import time

import pytest


def _run(async_fn, *args, clock=None):
    """Helper: run async function with autojump MockClock."""
    import trio
    import trio.testing

    if clock is None:
        clock = trio.testing.MockClock(autojump_threshold=0)
    return trio.run(async_fn, *args, clock=clock)


# ============================================================
# 1. trio.run() and Basic Nurseries
# ============================================================


class TestRunAndNurseries:
    """Tests for trio.run() entry point and nursery lifecycle."""

    def test_run_returns_value(self):
        """trio.run() returns the value from the async function."""

        async def main():
            return 42

        assert _run(main) == 42

    def test_nursery_start_soon_runs_concurrent_tasks(self):
        """Nursery.start_soon() spawns concurrent tasks; nursery waits for all."""
        import trio

        results = []

        async def task(name, delay):
            await trio.sleep(delay)
            results.append(name)

        async def main():
            async with trio.open_nursery() as nursery:
                nursery.start_soon(task, "fast", 1)
                nursery.start_soon(task, "slow", 10)
            # Both should complete before nursery exits
            return sorted(results)

        assert _run(main) == ["fast", "slow"]

    def test_nursery_start_waits_for_started(self):
        """Nursery.start() blocks until child calls task_status.started()."""
        import trio

        async def service(task_status=trio.TASK_STATUS_IGNORED):
            task_status.started("ready")
            await trio.sleep_forever()

        async def main():
            async with trio.open_nursery() as nursery:
                value = await nursery.start(service)
                assert value == "ready"
                nursery.cancel_scope.cancel()

        _run(main)

    def test_nursery_exception_propagation(self):
        """Child task exceptions propagate as ExceptionGroup from nursery."""
        import trio

        async def failing_task():
            raise ValueError("boom")

        async def main():
            async with trio.open_nursery() as nursery:
                nursery.start_soon(failing_task)

        with pytest.raises(BaseExceptionGroup) as exc_info:
            _run(main)
        assert any(isinstance(e, ValueError) for e in exc_info.value.exceptions)

    def test_nursery_cancels_siblings_on_failure(self):
        """When one child fails, nursery cancels all siblings before propagating."""
        import trio

        events = []

        async def slow_task():
            try:
                await trio.sleep(1000)
            except trio.Cancelled:
                events.append("cancelled")
                raise

        async def failing_task():
            await trio.sleep(1)
            raise RuntimeError("fail")

        async def main():
            async with trio.open_nursery() as nursery:
                nursery.start_soon(slow_task)
                nursery.start_soon(failing_task)

        with pytest.raises(BaseExceptionGroup):
            _run(main)
        assert "cancelled" in events


# ============================================================
# 2. CancelScope
# ============================================================


class TestCancelScope:
    """Tests for CancelScope: deadlines, cancel(), shield, cancelled_caught."""

    def test_cancel_scope_deadline(self):
        """CancelScope with deadline cancels tasks after timeout."""
        import trio

        async def main():
            with trio.CancelScope(deadline=trio.current_time() + 5) as cs:
                await trio.sleep(100)
            assert cs.cancelled_caught is True
            assert cs.cancel_called is True

        _run(main)

    def test_cancel_scope_manual_cancel(self):
        """CancelScope.cancel() immediately cancels the scope."""
        import trio

        async def main():
            with trio.CancelScope() as cs:
                cs.cancel()
                await trio.sleep(0)
            assert cs.cancelled_caught is True

        _run(main)

    def test_cancel_scope_shield(self):
        """Shielded CancelScope blocks outer cancellation from propagating in."""
        import trio

        async def main():
            with trio.CancelScope() as outer:
                outer.cancel()
                with trio.CancelScope(shield=True) as inner:
                    await trio.sleep(0)  # should NOT be cancelled
                    inner_ok = True
                # After exiting shield, outer cancellation takes effect
                try:
                    await trio.sleep(0)
                    inner_ok = False  # shouldn't reach here
                except trio.Cancelled:
                    pass
            assert inner_ok

        _run(main)

    def test_cancel_scope_not_reusable(self):
        """CancelScope cannot be reused after exiting."""
        import trio

        async def main():
            cs = trio.CancelScope()
            with cs:
                pass
            with pytest.raises(RuntimeError):
                with cs:
                    pass

        _run(main)


# ============================================================
# 3. Timeouts
# ============================================================


class TestTimeouts:
    """Tests for sleep, move_on_after, fail_after."""

    def test_sleep_advances_clock(self):
        """trio.sleep() advances the MockClock time."""
        import trio

        async def main():
            t0 = trio.current_time()
            await trio.sleep(10)
            assert trio.current_time() - t0 == pytest.approx(10)

        _run(main)

    def test_move_on_after_returns_on_timeout(self):
        """move_on_after catches timeout and continues execution."""
        import trio

        async def main():
            with trio.move_on_after(5) as cs:
                await trio.sleep(100)
            assert cs.cancelled_caught is True
            return "continued"

        assert _run(main) == "continued"

    def test_fail_after_raises_too_slow(self):
        """fail_after raises TooSlowError on timeout."""
        import trio

        async def main():
            with trio.fail_after(5):
                await trio.sleep(100)

        with pytest.raises(trio.TooSlowError):
            _run(main)

    def test_move_on_after_no_timeout(self):
        """move_on_after does NOT cancel if task completes in time."""
        import trio

        async def main():
            with trio.move_on_after(100) as cs:
                await trio.sleep(1)
            assert cs.cancelled_caught is False

        _run(main)


# ============================================================
# 4. Memory Channels
# ============================================================


class TestMemoryChannels:
    """Tests for open_memory_channel: buffered/unbuffered, close semantics."""

    def test_buffered_channel_send_receive(self):
        """Buffered channel: send_nowait fills buffer, receive retrieves items."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[int](3)
            async with send, recv:
                send.send_nowait(1)
                send.send_nowait(2)
                send.send_nowait(3)
                with pytest.raises(trio.WouldBlock):
                    send.send_nowait(4)  # buffer full
                assert await recv.receive() == 1
                assert await recv.receive() == 2
                assert await recv.receive() == 3

        _run(main)

    def test_unbuffered_channel_with_nursery(self):
        """Unbuffered (0-buffer) channel: sender blocks until receiver is ready."""
        import trio

        results = []

        async def producer(send):
            for i in range(5):
                await send.send(i)
            await send.aclose()

        async def consumer(recv):
            async for item in recv:
                results.append(item)

        async def main():
            send, recv = trio.open_memory_channel[int](0)
            async with trio.open_nursery() as nursery:
                nursery.start_soon(producer, send)
                nursery.start_soon(consumer, recv)

        _run(main)
        assert results == [0, 1, 2, 3, 4]

    def test_channel_close_semantics(self):
        """Closing all senders causes EndOfChannel for receivers; closing receiver causes BrokenResourceError for senders."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[str](10)

            # Close sender → EndOfChannel for receiver
            send.close()
            with pytest.raises(trio.EndOfChannel):
                await recv.receive()

            # New channel: close receiver → BrokenResourceError for sender
            send2, recv2 = trio.open_memory_channel[str](10)
            recv2.close()
            with pytest.raises(trio.BrokenResourceError):
                send2.send_nowait("x")

        _run(main)

    def test_channel_clone(self):
        """Cloned channels: all clones must close before EndOfChannel."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[int](10)
            send2 = send.clone()
            send.close()
            # Still one sender open
            send2.send_nowait(42)
            assert await recv.receive() == 42
            send2.close()
            with pytest.raises(trio.EndOfChannel):
                await recv.receive()

        _run(main)


# ============================================================
# 5. Synchronization Primitives
# ============================================================


class TestSyncPrimitives:
    """Tests for Event, Lock, Semaphore, Condition, CapacityLimiter."""

    def test_event_set_and_wait(self):
        """Event: set wakes all waiters; wait on set event returns immediately."""
        import trio
        import trio.testing

        async def main():
            event = trio.Event()
            results = []

            async def waiter(name):
                await event.wait()
                results.append(name)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(waiter, "a")
                nursery.start_soon(waiter, "b")
                await trio.testing.wait_all_tasks_blocked()
                assert event.statistics().tasks_waiting == 2
                event.set()

            assert sorted(results) == ["a", "b"]
            assert event.is_set()

            # Wait on already-set event is immediate
            await event.wait()

        _run(main)

    def test_lock_mutual_exclusion(self):
        """Lock ensures only one task holds it at a time."""
        import trio

        async def main():
            lock = trio.Lock()
            order = []

            async def worker(name):
                async with lock:
                    order.append(f"{name}_enter")
                    await trio.sleep(1)
                    order.append(f"{name}_exit")

            async with trio.open_nursery() as nursery:
                nursery.start_soon(worker, "A")
                nursery.start_soon(worker, "B")

            # One must complete before the other enters
            assert order[0].endswith("_enter")
            assert order[1].endswith("_exit")

        _run(main)

    def test_semaphore(self):
        """Semaphore allows N concurrent acquisitions and works as async context manager."""
        import trio

        async def main():
            sem = trio.Semaphore(2, max_value=2)
            assert sem.value == 2
            sem.acquire_nowait()
            assert sem.value == 1
            sem.acquire_nowait()
            assert sem.value == 0
            with pytest.raises(trio.WouldBlock):
                sem.acquire_nowait()
            sem.release()
            assert sem.value == 1
            with pytest.raises(ValueError):
                sem.release()
                sem.release()  # exceeds max_value

            sem2 = trio.Semaphore(1)
            async with sem2:
                assert sem2.value == 0
            assert sem2.value == 1

        _run(main)

    def test_capacity_limiter(self):
        """CapacityLimiter limits concurrent resource usage and works as async context manager."""
        import trio

        async def main():
            limiter = trio.CapacityLimiter(2)
            assert limiter.total_tokens == 2
            assert limiter.available_tokens == 2

            await limiter.acquire()
            assert limiter.borrowed_tokens == 1
            assert limiter.available_tokens == 1
            limiter.release()
            assert limiter.borrowed_tokens == 0

            async with limiter:
                assert limiter.borrowed_tokens == 1
            assert limiter.borrowed_tokens == 0

        _run(main)

    def test_condition_notify(self):
        """Condition: wait releases lock, notify wakes one waiter."""
        import trio
        import trio.testing

        async def main():
            cond = trio.Condition()
            data = []

            async def waiter():
                async with cond:
                    await cond.wait()
                    data.append("woken")

            async with trio.open_nursery() as nursery:
                nursery.start_soon(waiter)
                await trio.testing.wait_all_tasks_blocked()
                async with cond:
                    cond.notify()

            assert data == ["woken"]

        _run(main)


# ============================================================
# 6. Thread Interop
# ============================================================


class TestThreadInterop:
    """Tests for trio.to_thread.run_sync and trio.from_thread."""

    def test_to_thread_run_sync(self):
        """to_thread.run_sync runs a blocking function in a worker thread."""
        import trio
        import threading

        async def main():
            trio_thread = threading.current_thread()

            def blocking_fn():
                worker_thread = threading.current_thread()
                assert worker_thread != trio_thread
                return "from_thread"

            result = await trio.to_thread.run_sync(blocking_fn)
            assert result == "from_thread"

        _run(main)

    def test_from_thread_run(self):
        """from_thread.run() calls async code from a worker thread back into trio."""
        import trio

        async def main():
            async def async_helper():
                return "async_result"

            def blocking_fn():
                return trio.from_thread.run(async_helper)

            result = await trio.to_thread.run_sync(blocking_fn)
            assert result == "async_result"

        _run(main)


# ============================================================
# 7. File I/O
# ============================================================


class TestFileIO:
    """Tests for trio.open_file() and trio.Path."""

    def test_open_file_write_read(self):
        """trio.open_file() provides async file I/O."""
        import trio

        async def main():
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
                tmp = f.name
            try:
                async with await trio.open_file(tmp, "w") as f:
                    await f.write("hello trio")
                async with await trio.open_file(tmp, "r") as f:
                    content = await f.read()
                assert content == "hello trio"
            finally:
                os.unlink(tmp)

        _run(main)

    def test_trio_path(self):
        """trio.Path provides async pathlib operations."""
        import trio

        async def main():
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
                f.write(b"path test")
                tmp = f.name
            try:
                p = trio.Path(tmp)
                assert await p.exists()
                content = await p.read_text()
                assert content == "path test"
                await p.write_text("updated")
                assert await p.read_text() == "updated"
            finally:
                os.unlink(tmp)

        _run(main)


# ============================================================
# 8. Subprocess
# ============================================================


class TestSubprocess:
    """Tests for trio.run_process()."""

    def test_run_process(self):
        """trio.run_process() runs a command and captures output."""
        import trio
        import trio.testing

        async def main():
            result = await trio.run_process(
                ["echo", "hello trio"],
                capture_stdout=True,
            )
            assert result.returncode == 0
            assert b"hello trio" in result.stdout

        _run(main, clock=trio.testing.MockClock(rate=1))

    def test_open_process(self):
        """trio.lowlevel.open_process() provides streaming access to subprocess I/O."""
        import trio
        import trio.testing
        import subprocess

        async def main():
            proc = await trio.lowlevel.open_process(
                ["cat"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            try:
                await proc.stdin.send_all(b"hello from trio\n")
                await proc.stdin.aclose()
                output = await proc.stdout.receive_some(4096)
                assert b"hello from trio" in output
            finally:
                proc.kill()
                await proc.wait()

        _run(main, clock=trio.testing.MockClock(rate=1))


# ============================================================
# 9. Testing Utilities
# ============================================================


class TestTestingUtilities:
    """Tests for trio.testing: MockClock, wait_all_tasks_blocked, Sequencer."""

    def test_mock_clock_autojump_and_manual(self):
        """MockClock: autojump advances when blocked; jump() manually advances."""
        import trio
        import trio.testing

        async def main():
            t0 = trio.current_time()
            await trio.sleep(1000)
            elapsed = trio.current_time() - t0
            assert elapsed == pytest.approx(1000)

        clock = trio.testing.MockClock(autojump_threshold=0)
        trio.run(main, clock=clock)

        clock2 = trio.testing.MockClock()
        clock2.jump(100)
        assert clock2.current_time() == pytest.approx(100)

    def test_wait_all_tasks_blocked(self):
        """wait_all_tasks_blocked() suspends until all other tasks are waiting."""
        import trio
        import trio.testing

        async def main():
            event = trio.Event()
            reached = []

            async def waiter():
                await event.wait()
                reached.append(True)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(waiter)
                await trio.testing.wait_all_tasks_blocked()
                # waiter is now blocked on event.wait()
                assert len(reached) == 0
                event.set()

            assert len(reached) == 1

        _run(main)

    def test_sequencer(self):
        """Sequencer enforces ordering between concurrent tasks."""
        import trio
        import trio.testing

        async def main():
            seq = trio.testing.Sequencer()
            order = []

            async def task_a():
                async with seq(0):
                    order.append("a0")
                async with seq(2):
                    order.append("a2")

            async def task_b():
                async with seq(1):
                    order.append("b1")
                async with seq(3):
                    order.append("b3")

            async with trio.open_nursery() as nursery:
                nursery.start_soon(task_a)
                nursery.start_soon(task_b)

            assert order == ["a0", "b1", "a2", "b3"]

        _run(main)


# ============================================================
# 10. Checkpoint Behavior
# ============================================================


class TestCheckpoints:
    """Tests for checkpoint behavior and cancellation delivery."""

    def test_sleep_zero_is_checkpoint(self):
        """trio.sleep(0) is a checkpoint that allows task switching."""
        import trio

        async def main():
            order = []

            async def task(name):
                order.append(f"{name}_start")
                await trio.sleep(0)
                order.append(f"{name}_end")

            async with trio.open_nursery() as nursery:
                nursery.start_soon(task, "A")
                nursery.start_soon(task, "B")

            # Both tasks should interleave at the checkpoint
            assert len(order) == 4

        _run(main)

    def test_cancellation_delivered_at_checkpoint(self):
        """Cancellation is delivered when the cancelled task reaches a checkpoint."""
        import trio

        async def main():
            with trio.CancelScope() as cs:
                cs.cancel()
                # No checkpoint yet — still running
                x = 1 + 1
                assert x == 2
                # Now hit a checkpoint — cancellation fires
                with pytest.raises(trio.Cancelled):
                    await trio.sleep(0)

        _run(main)


# ============================================================
# 11. Signals
# ============================================================


class TestSignals:
    """Tests for trio.open_signal_receiver."""

    def test_signal_receiver(self):
        """open_signal_receiver catches signals asynchronously."""
        import trio
        import trio.testing
        import signal

        async def main():
            received = []
            with trio.open_signal_receiver(signal.SIGUSR1) as signal_aiter:
                os.kill(os.getpid(), signal.SIGUSR1)
                # Give the signal a chance to be delivered
                await trio.testing.wait_all_tasks_blocked()
                # A timeout guards against hanging if no signal arrives; the
                # assertion below then fails because nothing was appended.
                with trio.move_on_after(1):
                    received.append(await signal_aiter.__anext__())
            # Fails (rather than passing vacuously) if the receiver delivered no signal.
            assert received == [signal.SIGUSR1]

        _run(main, clock=trio.testing.MockClock(rate=1))


# ============================================================
# 12. Complex Integration
# ============================================================


class TestComplexIntegration:
    """Complex tests combining multiple trio features."""

    def test_producer_consumer_with_backpressure(self):
        """Producer-consumer pipeline with bounded channel, timeouts, and cancellation."""
        import trio

        produced = []
        consumed = []

        async def producer(send, count):
            for i in range(count):
                await send.send(i)
                produced.append(i)
            await send.aclose()

        async def consumer(recv):
            async for item in recv:
                consumed.append(item)
                await trio.sleep(0.1)  # simulate work

        async def main():
            send, recv = trio.open_memory_channel[int](2)
            async with trio.open_nursery() as nursery:
                nursery.start_soon(producer, send, 10)
                nursery.start_soon(consumer, recv)

        _run(main)
        assert produced == list(range(10))
        assert consumed == list(range(10))

    def test_timeout_with_nested_nursery(self):
        """Nested nursery inside a timeout scope — all children cancelled on timeout."""
        import trio

        async def main():
            results = []
            with trio.move_on_after(5) as cs:
                async with trio.open_nursery() as nursery:

                    async def worker(n):
                        await trio.sleep(n)
                        results.append(n)

                    nursery.start_soon(worker, 1)
                    nursery.start_soon(worker, 3)
                    nursery.start_soon(worker, 100)  # won't complete

            assert cs.cancelled_caught is True
            assert 1 in results
            assert 3 in results
            assert 100 not in results

        _run(main)

    def test_thread_interop_with_channels(self):
        """Thread-to-trio communication via channels."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[str](10)

            def thread_fn():
                trio.from_thread.run_sync(send.send_nowait, "from_thread_1")
                trio.from_thread.run_sync(send.send_nowait, "from_thread_2")
                trio.from_thread.run_sync(send.close)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(trio.to_thread.run_sync, thread_fn)
                results = []
                async for item in recv:
                    results.append(item)

            assert results == ["from_thread_1", "from_thread_2"]

        _run(main)

    def test_sync_primitives_with_nursery(self):
        """Event + Lock + nursery: coordinate multiple tasks with sync primitives."""
        import trio

        async def main():
            lock = trio.Lock()
            event = trio.Event()
            log = []

            async def writer():
                async with lock:
                    log.append("write_start")
                    await trio.sleep(1)
                    log.append("write_end")
                event.set()

            async def reader():
                await event.wait()
                async with lock:
                    log.append("read")

            async with trio.open_nursery() as nursery:
                nursery.start_soon(writer)
                nursery.start_soon(reader)

            assert log == ["write_start", "write_end", "read"]

        _run(main)


# ============================================================
# 13. Trio-Specific Runtime Detection
# ============================================================


class TestTrioRuntime:
    """Tests that verify trio's own runtime is active (not an asyncio wrapper)."""

    def test_sniffio_integration(self):
        """Verify trio.run() registers with sniffio correctly."""
        import trio
        import sniffio

        async def check_library():
            lib = sniffio.current_async_library()
            assert lib == "trio", f"Expected 'trio', got '{lib}'"

        trio.run(check_library)

    def test_current_trio_token(self):
        """current_trio_token().run_sync_soon schedules a callback into the run loop."""
        import threading

        import trio
        import trio.testing

        async def main():
            token = trio.lowlevel.current_trio_token()
            assert token is not None

            ran = []
            trio_thread = threading.current_thread()

            def callback():
                ran.append(threading.current_thread())

            # From a worker thread, schedule a sync callback back into the trio loop.
            def from_worker():
                token.run_sync_soon(callback)

            await trio.to_thread.run_sync(from_worker)
            # Give the scheduled callback a chance to run in the trio thread.
            await trio.testing.wait_all_tasks_blocked()

            # The callback must have actually run, and on the trio thread.
            assert ran == [trio_thread]

        _run(main, clock=trio.testing.MockClock(rate=1))

    def test_current_task_has_parent_nursery(self):
        """A spawned task's parent_nursery is the nursery that started it."""
        import trio

        async def main():
            captured = {}

            async def child():
                captured["task"] = trio.lowlevel.current_task()

            async with trio.open_nursery() as nursery:
                nursery.start_soon(child)

            # The child's parent_nursery must be the exact nursery that spawned it.
            assert captured["task"].parent_nursery is nursery

        _run(main)


# ============================================================
# 14. Additional Timeout APIs
# ============================================================


class TestAdditionalTimeouts:
    """Tests for sleep_forever, sleep_until, move_on_at, fail_at, current_effective_deadline."""

    def test_sleep_forever_cancelled(self):
        """sleep_forever blocks until cancelled."""
        import trio

        async def main():
            with trio.CancelScope() as cs:
                cs.cancel()
                with pytest.raises(trio.Cancelled):
                    await trio.sleep_forever()

        _run(main)

    def test_sleep_until(self):
        """sleep_until(deadline) sleeps until the given clock time."""
        import trio

        async def main():
            t0 = trio.current_time()
            await trio.sleep_until(t0 + 50)
            elapsed = trio.current_time() - t0
            assert elapsed == pytest.approx(50)

        _run(main)

    def test_move_on_at_and_fail_at(self):
        """move_on_at uses absolute deadline; fail_at raises TooSlowError."""
        import trio

        async def main():
            t0 = trio.current_time()
            with trio.move_on_at(t0 + 5) as cs:
                await trio.sleep(100)
            assert cs.cancelled_caught is True

            with pytest.raises(trio.TooSlowError):
                with trio.fail_at(trio.current_time() + 5):
                    await trio.sleep(100)

        _run(main)

    def test_current_effective_deadline(self):
        """current_effective_deadline returns the nearest enclosing deadline."""
        import trio

        async def main():
            assert trio.current_effective_deadline() == math.inf
            with trio.CancelScope(deadline=trio.current_time() + 100):
                dl = trio.current_effective_deadline()
                assert dl < math.inf
                assert dl == pytest.approx(trio.current_time() + 100, abs=1)

        _run(main)


# ============================================================
# 15. Additional Sync Primitive Features
# ============================================================


class TestAdditionalSyncFeatures:
    """Tests for Lock.locked, Lock.acquire_nowait, StrictFIFOLock, CapacityLimiter async with."""

    def test_lock_locked_and_acquire_nowait(self):
        """Lock.locked() and acquire_nowait() work correctly."""
        import trio

        async def main():
            lock = trio.Lock()
            assert not lock.locked()
            lock.acquire_nowait()
            assert lock.locked()
            lock.release()
            assert not lock.locked()

        _run(main)


# ============================================================
# 16. Channel Statistics and ClosedResourceError
# ============================================================


class TestChannelAdvanced:
    """Tests for channel statistics and ClosedResourceError."""

    def test_channel_statistics(self):
        """Memory channels provide statistics."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[int](5)
            send.send_nowait(1)
            send.send_nowait(2)
            stats = send.statistics()
            assert stats.current_buffer_used == 2
            assert stats.max_buffer_size == 5

        _run(main)

    def test_closed_resource_error(self):
        """Using a closed channel raises ClosedResourceError."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[int](5)
            send.close()
            with pytest.raises(trio.ClosedResourceError):
                send.send_nowait(1)

        _run(main)

    def test_receive_nowait(self):
        """receive_nowait returns item or raises WouldBlock."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[int](5)
            send.send_nowait(42)
            assert recv.receive_nowait() == 42
            with pytest.raises(trio.WouldBlock):
                recv.receive_nowait()

        _run(main)


# ============================================================
# 17. File I/O — wrap_file
# ============================================================


class TestFileIOAdvanced:
    """Tests for trio.wrap_file."""

    def test_wrap_file(self):
        """trio.wrap_file wraps a sync file object for async use."""
        import trio

        async def main():
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".txt", mode="w"
            ) as f:
                f.write("wrap test")
                tmp = f.name
            try:
                sync_file = open(tmp, "r")
                async_file = trio.wrap_file(sync_file)
                content = await async_file.read()
                assert content == "wrap test"
                await async_file.aclose()
            finally:
                os.unlink(tmp)

        _run(main)


# ============================================================
# 18. Nursery cancel_scope access
# ============================================================


class TestNurseryAdvanced:
    """Tests for nursery.cancel_scope and multiple exception handling."""

    def test_nursery_cancel_scope_deadline(self):
        """Nursery cancel_scope controls child lifetime via deadline."""
        import trio

        async def main():
            results = []
            async with trio.open_nursery() as nursery:
                nursery.cancel_scope.deadline = trio.current_time() + 1

                async def fast():
                    await trio.sleep(0.5)
                    results.append("fast")

                async def slow():
                    await trio.sleep(1000)
                    results.append("slow")

                nursery.start_soon(fast)
                nursery.start_soon(slow)

            assert "fast" in results
            assert "slow" not in results
            assert nursery.cancel_scope.cancelled_caught is True

        _run(main)


# ============================================================
# 19. Condition — notify_all
# ============================================================


class TestConditionAdvanced:
    """Tests for Condition.notify_all."""

    def test_condition_notify_all(self):
        """Condition.notify_all() wakes all waiting tasks."""
        import trio
        import trio.testing

        async def main():
            cond = trio.Condition()
            woken = []

            async def waiter(name):
                async with cond:
                    await cond.wait()
                    woken.append(name)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(waiter, "a")
                nursery.start_soon(waiter, "b")
                nursery.start_soon(waiter, "c")
                await trio.testing.wait_all_tasks_blocked()
                async with cond:
                    cond.notify_all()

            assert sorted(woken) == ["a", "b", "c"]

        _run(main)


# ============================================================
# 21. Async for on channel
# ============================================================


class TestChannelIteration:
    """Tests for async iteration on channels."""

    def test_async_for_channel_blocks_then_resumes(self):
        """async for blocks when the channel is temporarily empty, then resumes on send."""
        import trio
        import trio.testing

        async def main():
            send, recv = trio.open_memory_channel[int](0)
            consumed = []

            async def consumer():
                async for item in recv:
                    consumed.append(item)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(consumer)
                # Consumer parks on an empty channel until an item is available.
                await trio.testing.wait_all_tasks_blocked()
                assert consumed == []
                await send.send(1)
                # It wakes, takes the item, and parks again waiting for more.
                await trio.testing.wait_all_tasks_blocked()
                assert consumed == [1]
                await send.send(2)
                await trio.testing.wait_all_tasks_blocked()
                assert consumed == [1, 2]
                # Closing all senders ends the iteration so the consumer exits.
                await send.aclose()

            return consumed

        assert _run(main) == [1, 2]


# ============================================================
# 23. MockClock rate parameter
# ============================================================


class TestMockClockRate:
    """Tests for MockClock with rate parameter."""

    def test_mock_clock_with_rate(self):
        """MockClock with rate>0 advances time proportionally to real time."""
        import trio
        import trio.testing

        rate = 100

        async def main():
            t0 = trio.current_time()
            # Block the trio thread for a real interval so wall time provably
            # elapses; with rate>0 the virtual clock must advance by ~rate*real.
            real_slept = 0.05
            time.sleep(real_slept)
            await trio.sleep(0)
            t1 = trio.current_time()
            return t0, t1, real_slept

        clock = trio.testing.MockClock(rate=rate)
        t0, t1, real_slept = trio.run(main, clock=clock)
        # A clock that ignores `rate` (stays at 0) fails: the virtual clock must
        # advance strictly, by roughly rate * real-elapsed, never going backwards.
        assert t1 > t0
        assert (t1 - t0) >= rate * real_slept * 0.5
        assert clock.current_time() > t1


# ============================================================
# 24. Task-local storage
# ============================================================


class TestTaskLocal:
    """Tests for trio.lowlevel.current_task and task names."""

    def test_task_name(self):
        """Tasks started with name= have that name accessible."""
        import trio

        async def main():
            names = []

            async def named_task(task_status=trio.TASK_STATUS_IGNORED):
                task = trio.lowlevel.current_task()
                names.append(task.name)
                task_status.started()

            async with trio.open_nursery() as nursery:
                await nursery.start(named_task, name="my_worker")

            assert names[0] == "my_worker"

        _run(main)


# ============================================================
# 25. from_thread.run_sync
# ============================================================


class TestFromThreadRunSync:
    """Tests for trio.from_thread.run_sync."""

    def test_from_thread_run_sync(self):
        """from_thread.run_sync calls a sync function in the trio thread from a worker."""
        import trio
        import threading

        async def main():
            trio_thread = threading.current_thread()

            def worker():
                worker_thread = threading.current_thread()
                assert worker_thread != trio_thread
                result = trio.from_thread.run_sync(lambda: threading.current_thread())
                assert result == trio_thread
                return "done"

            return await trio.to_thread.run_sync(worker)

        assert _run(main) == "done"


# ============================================================
# 26. Nursery strict_exception_groups
# ============================================================


class TestStrictExceptionGroups:
    """Tests for strict_exception_groups behavior."""

    def test_single_exception_still_wrapped(self):
        """With strict_exception_groups=True, even a single child error is wrapped."""
        import trio

        async def main():
            async with trio.open_nursery() as nursery:

                async def fail():
                    raise ValueError("one")

                nursery.start_soon(fail)

        with pytest.raises(BaseExceptionGroup) as exc_info:
            trio.run(main, strict_exception_groups=True)
        assert len(exc_info.value.exceptions) == 1
        assert isinstance(exc_info.value.exceptions[0], ValueError)


# ============================================================
# 27. aclose_forcefully
# ============================================================


class TestAcloseForcefully:
    """Tests for trio.aclose_forcefully."""

    def test_aclose_forcefully_closes_resource(self):
        """aclose_forcefully closes an async resource with a short cancel scope."""
        import trio

        async def main():
            send, recv = trio.open_memory_channel[int](5)
            send.send_nowait(1)
            await trio.aclose_forcefully(send)
            with pytest.raises(trio.ClosedResourceError):
                send.send_nowait(2)

        _run(main)
