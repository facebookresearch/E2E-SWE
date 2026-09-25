# trio — Structured Concurrency Async I/O Library

## Overview

Implement **trio**, a Python library for async/await concurrency with structured concurrency. Unlike asyncio, trio builds its own event loop from scratch — it does not wrap the standard library's asyncio module.

The core design: every concurrent task lives inside a nursery, which ensures structured lifetimes (no orphan tasks). Cancellation propagates through a CancelScope tree. All blocking operations are explicit checkpoints where task switching and cancellation delivery occur.

## Dependencies

The environment is **offline** and all dependencies below are **already installed** — do not install
anything (there is no network). The project is installed for you by a `setup.sh` that runs offline
(`pip install -e . --no-build-isolation`); just implement the package so it imports and passes.

- `attrs` — dataclass-like decorators
- `sortedcontainers` — sorted collections for deadline heaps
- `outcome` — capturing function results (value or error)
- `sniffio` — async library detection
- `idna` — international domain names
- `exceptiongroup` — `ExceptionGroup` / `BaseExceptionGroup` backport (these are also available as
  builtins in this environment, so nursery errors can be raised as `BaseExceptionGroup` directly)

---

## 1. Entry Point

`trio.run(async_fn, *args, clock=None, instruments=(), strict_exception_groups=True)` — the synchronous entry point. Runs `async_fn` in a new trio event loop. Returns the function's return value. With `strict_exception_groups=True` (default), nursery exceptions are always wrapped in `BaseExceptionGroup`, even single exceptions.

---

## 2. Nurseries

`async with trio.open_nursery() as nursery:` — creates a child task scope.

- `nursery.start_soon(async_fn, *args, name=None)` — spawn a task (non-blocking). `name` sets the task's name.
- `nursery.start(async_fn, *args, name=None)` — spawn and wait until the task calls `task_status.started(value)`. The spawned function must accept a `task_status` keyword parameter.
- `nursery.cancel_scope` — the implicit CancelScope. Setting `nursery.cancel_scope.deadline` cancels children that exceed it.
- When a child raises, the nursery cancels all siblings, waits for them, then raises `BaseExceptionGroup`

`trio.TASK_STATUS_IGNORED` — sentinel TaskStatus with no-op `started()`.

---

## 3. CancelScope

`trio.CancelScope(deadline=math.inf, shield=False)` — cancellation scope.

Used as `with trio.CancelScope() as cs:`. Properties: `deadline` (float, read-write), `shield` (bool, read-write), `cancel_called` (bool, readonly), `cancelled_caught` (bool, readonly — True after exiting if scope caught a Cancelled). Method: `cancel()`.

`shield=True` prevents cancellation from any enclosing (outer) scope from being delivered at checkpoints inside this scope; the scope still responds to its own `cancel()`/`deadline`.

Not reusable after exiting: re-entering an already-exited CancelScope raises `RuntimeError`.

---

## 4. Timeouts and Sleep

- `await trio.sleep(seconds)` — sleep and checkpoint. `sleep(0)` is a pure checkpoint.
- `await trio.sleep_forever()` — sleep until cancelled.
- `await trio.sleep_until(deadline)` — sleep until the given absolute clock time.
- `trio.move_on_after(seconds)` / `trio.move_on_at(deadline)` — CancelScope context managers that silently catch timeout
- `trio.fail_after(seconds)` / `trio.fail_at(deadline)` — like move_on but raise `trio.TooSlowError`
- `trio.current_time()` — current clock time (float)
- `trio.current_effective_deadline()` — the nearest enclosing deadline (float, `math.inf` if none)

---

## 5. Memory Channels

`send, recv = trio.open_memory_channel[T](max_buffer_size)` — creates a paired channel. `max_buffer_size` is int >= 0 or `math.inf`.

**MemorySendChannel**: `send_nowait(value)` (raises `WouldBlock` if full), `await send(value)`, `clone()`, `close()`, `await aclose()`, `statistics()` → object with `current_buffer_used` and `max_buffer_size`. Closing all senders → receivers get `EndOfChannel`. Closing all receivers → senders get `BrokenResourceError`. Using after close raises `ClosedResourceError`. Supports `with send:` (sync context manager; exiting calls `close()`) and `async with send:` (async context manager; entering returns the channel, exiting awaits `aclose()`).

**MemoryReceiveChannel**: `receive_nowait()` (raises `WouldBlock` if empty), `await receive()`, `clone()`, `close()`, `await aclose()`. Supports `async for item in recv:`, `with recv:` (sync context manager; exiting calls `close()`), and `async with recv:` (async context manager; entering returns the channel, exiting awaits `aclose()`).

---

## 6. Synchronization Primitives

- `trio.Event()` — `set()`, `is_set()`, `await wait()` (returns immediately if already set), `statistics()` (returns object with `tasks_waiting`). Once set, cannot be cleared.
- `trio.Lock()` — `locked()` → bool, `acquire_nowait()` (acquires if unlocked), `await acquire()`, `release()`. Not re-entrant. `async with lock:`.
- `trio.Semaphore(initial_value, max_value=None)` — `value` property, `acquire_nowait()`, `await acquire()`, `release()` (raises ValueError if exceeds max_value). `async with sem:`.
- `trio.Condition(lock=None)` — `await wait()` (releases lock, waits, re-acquires), `notify(n=1)`, `notify_all()`. Must hold lock. `async with cond:`.
- `trio.CapacityLimiter(total_tokens)` — `total_tokens`, `borrowed_tokens`, `available_tokens`, `await acquire()`, `release()`. `async with limiter:`.

---

## 7. Thread Interop

- `await trio.to_thread.run_sync(sync_fn, *args)` — run blocking function in worker thread
- `trio.from_thread.run(async_fn, *args)` — call async code from worker thread back into trio (blocking)
- `trio.from_thread.run_sync(fn, *args)` — call sync code from worker thread in trio thread (blocking from worker thread's perspective)

---

## 8. File I/O

- `await trio.open_file(path, mode)` — async file (returns async context manager wrapping file)
- `trio.wrap_file(file)` — wraps a sync file object for async use. Returns an async file with `await read()`, `await write()`, `await aclose()`.
- `trio.Path` — async pathlib.Path wrapper: `await p.exists()`, `await p.read_text()`, `await p.write_text()`

---

## 9. Subprocess

- `await trio.run_process(command, capture_stdout=False, ...)` — run and wait, returns `CompletedProcess`
- `await trio.lowlevel.open_process(command, stdin=, stdout=, ...)` — returns `Process` with `.stdin`, `.stdout` as trio streams, `.kill()`, `await .wait()`

**Trio stream interface.** `Process.stdin` / `Process.stdout` (and trio streams generally) are not file objects — they expose trio's async byte-stream methods, not `write`/`read`:

- `await stream.send_all(data)` — send all of `data` (bytes) through the stream, blocking until done.
- `await stream.receive_some(max_bytes=None) -> bytes` — wait for data and return up to `max_bytes` bytes; returns empty bytes (`b""`) at end-of-file.
- `await stream.aclose()` — close the stream.

---

## 10. Signals

`trio.open_signal_receiver(*signals)` — context manager yielding an async iterator of received signals.

---

## 11. Testing Utilities (`trio.testing`)

- `trio.testing.MockClock(rate=0.0, autojump_threshold=math.inf)` — fake clock. `autojump_threshold=0` auto-advances when all tasks blocked. `jump(seconds)` manually advances. `current_time()` returns current time. Implements `trio.abc.Clock`. `rate` is how many seconds of virtual clock time pass per second of real (wall-clock) time: with `rate=0.0` (default) the clock advances only via `jump()` or autojump, while with `rate>0` `current_time()` additionally moves forward by `rate * (real seconds elapsed)` as real time passes.
- `await trio.testing.wait_all_tasks_blocked(cushion=0.0)` — wait until all other tasks are blocked
- `trio.testing.Sequencer()` — enforces ordering: `async with seq(0):`, `async with seq(1):`, etc.

---

## 12. Exceptions

- `trio.Cancelled` — raised at checkpoints inside cancelled scopes
- `trio.TooSlowError` — raised by `fail_after`/`fail_at`
- `trio.WouldBlock` — `_nowait` methods when they would block
- `trio.EndOfChannel` — receiving from channel with all senders closed
- `trio.ClosedResourceError` — using a closed resource (e.g., sending on a closed channel)
- `trio.BrokenResourceError` — sending when all receivers closed

---

## 13. Checkpoint Behavior

A checkpoint is where task switching and cancellation delivery occur. All `await` operations in trio contain checkpoints. `await trio.sleep(0)` is a checkpoint. Non-blocking `_nowait` methods are NOT checkpoints.

---

## 14. Runtime Detection and Low-Level APIs

`trio.run()` registers with `sniffio` so that `sniffio.current_async_library()` returns `"trio"` during `trio.run()`.

`trio.lowlevel` provides low-level APIs:
- `trio.lowlevel.current_trio_token()` — returns a `TrioToken` representing the current trio event loop. The token has a `run_sync_soon(fn, *args)` method.
- `trio.lowlevel.current_task()` — returns the current `Task` object. Each task has a `parent_nursery` attribute and a `name` attribute.

---

## 15. Utilities

- `await trio.aclose_forcefully(resource)` — closes an async resource within a short cancel scope, ensuring it doesn't block.

---

## 16. setup.sh

The environment is offline and the build backend is pre-installed, so install in editable mode
without build isolation:

```bash
pip install -e . --no-build-isolation
```
