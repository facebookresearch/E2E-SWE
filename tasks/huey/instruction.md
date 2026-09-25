# Huey — Lightweight Python Task Queue

Implement **huey**, a lightweight task queue library for Python. Huey decorates functions as tasks that can be enqueued, scheduled, and executed asynchronously. It supports multiple storage backends, task pipelines, priorities, retries, locking, signals, cron-based periodic scheduling, and serialization.

## Dependencies

The environment is **offline** and every dependency below is **already installed** — do not
install anything (there is no network). The project itself is installed by a `setup.sh` that runs
offline (`pip install -e .`). `huey` itself is pure Python and needs no required runtime packages;
the following libraries back its optional integration backends and are pre-installed:

- `redis` — for the Redis storage backend (a `redis-server` service is also pre-installed and
  running on localhost:6379)
- `peewee` — for the SQL storage backend (contrib/sql_huey)
- `django` — for Django integration (contrib/djhuey)
- `gevent` — for MiniHuey (contrib/mini)

## Package Structure

```python
from huey import MemoryHuey, SqliteHuey, BlackHoleHuey, RedisHuey, FileHuey, crontab
from huey.exceptions import (CancelExecution, ConfigurationError, ResultTimeout,
                              RetryTask, TaskException, TaskLockedException,
                              HueyException)
from huey.serializer import Serializer, SignedSerializer
from huey.signals import (SIGNAL_CANCELED, SIGNAL_COMPLETE, SIGNAL_ENQUEUED,
                           SIGNAL_ERROR, SIGNAL_EXECUTING, SIGNAL_EXPIRED,
                           SIGNAL_LOCKED, SIGNAL_RETRYING, SIGNAL_REVOKED,
                           SIGNAL_SCHEDULED)
from huey.storage import (MemoryStorage, BlackHoleStorage, SqliteStorage,
                           RedisStorage, FileStorage)
from huey.constants import EmptyData
from huey.consumer import Consumer
from huey.contrib.helpers import RedisSemaphore
from huey.contrib.sql_huey import SqlHuey
```

---

## 1. Huey — Main Entry Point

`Huey` manages task registration, queue operations, scheduling, and the result store.

Constructor accepts: `name='huey'`, `immediate=False`, `utc=True`, `store_none=False`, plus `serializer`, `compression`, `use_zlib`, and `**storage_kwargs`. The `utc` flag selects Huey's internal clock: UTC when `True` (the default), local time when `False`. When `immediate=True`, tasks execute synchronously. Immediate mode only runs tasks that are ready to run now: a task scheduled for a future `eta`/`delay` (via `.schedule(...)`) is still placed in the schedule store rather than executed immediately, so its `result_count()` stays `0` and `scheduled_count()` becomes `1` — immediate mode does not bypass scheduling. `huey.immediate` can be toggled at runtime. By default, `None` results are not stored; set `store_none=True` to change this.

### Scheduling lifecycle (non-immediate mode)

In the default non-immediate mode, scheduling is two-phase and is driven by the consumer loop, NOT resolved at enqueue time:

- An **initial** `enqueue(task)` or `.schedule(args, eta=/delay=)` (the user-issued enqueue of a task) always places the task on the **main queue** — even when it carries a future `eta`/`delay`. So immediately after `.schedule(...)`, `len(huey)` and `pending_count()` count the task (it is `1`, not `0`), `scheduled_count()` is still `0`, and `dequeue()` returns that task. (This "goes to the main queue first" rule governs only the initial enqueue/`.schedule`; a **delayed retry** is routed differently — see *Retry routing* below.)
- The consumer dequeues a task and calls `execute(task, timestamp=None)`. `execute()` first checks `ready_to_run(task, timestamp)`: if the task is **not yet ready** (its `eta` is in the future relative to `timestamp`), `execute()` returns `None`, emits `SIGNAL_SCHEDULED`, and moves the task into the **schedule store** (after which `scheduled_count()` becomes `1`). This move is non-destructive — the same task can be executed again later with a `timestamp` at/after its `eta` and will then run.
- This contrasts with **immediate** mode (above), where a future-`eta` `.schedule(...)` task goes straight to the schedule store with `len(huey)==0` and `scheduled_count()==1`.

`read_schedule(timestamp)` then performs the destructive ready-at-timestamp read from the schedule store, returning the tasks whose `eta` is `<= timestamp` and removing them.

### Retry routing

When a task fails during `execute()` and a retry is due (it still has retries left, or a `RetryTask` was raised), the retry is routed by whether it carries a future execution time — and this happens **at retry time inside `execute()`**, unlike the initial enqueue above:

- **Delayed retry → schedule store.** If the retry carries a future `eta` — whether from `RetryTask(delay=/eta=)`, a bare `RetryTask()` falling back to the task's `retry_delay`, or a **plain-exception** retry on a task configured with `retry_delay=N` (which sets the retry's `eta` to `now + N` seconds) — it is placed **directly into the schedule store** with that `eta`. So immediately after that single failed `execute()`: `len(huey)==0`, `scheduled_count()==1`, and the scheduled task carries the failed task's id and is not `ready_to_run()` now but becomes ready at its `eta`.
- **Immediate retry → main queue.** If the retry carries no future time (`retry_delay==0` / unset and no `RetryTask` eta/delay), it is re-enqueued onto the **main queue**, so `len(huey)==1` and `scheduled_count()==0`.

### Convenience subclasses

All importable from `huey` directly:

- `MemoryHuey` — uses `MemoryStorage` (priority support)
- `SqliteHuey` — uses `SqliteStorage` (accepts `filename=` kwarg)
- `BlackHoleHuey` — uses `BlackHoleStorage` (no-op, discards everything; `dequeue()` returns None)
- `RedisHuey` — uses `RedisStorage` (requires a running `redis-server` on localhost:6379). Does NOT support priority.
- `FileHuey` — uses `FileStorage` (accepts `path=` kwarg for directory)

### Core operations

- **Task decoration**: `huey.task()` and `huey.periodic_task(validate_datetime)` — return decorators wrapping functions as tasks. Parameters include `retries`, `retry_delay`, `priority`, `context` (passes task instance as `task=` kwarg), `name`, `expires`. On priority-capable backends a task with a higher `priority` value is dequeued before one with a lower value; the default priority is `0`.
- **Queue**: `enqueue(task)`, `dequeue()`, `execute(task, timestamp=None)`, `ready_to_run(task, timestamp=None)`. When `enqueue()` receives a pipeline, it returns a `ResultGroup`; for a single task, a `Result`.
- **Schedule**: `read_schedule(timestamp)` (destructive read of tasks ready at timestamp), `read_periodic(timestamp)`, `scheduled()`, `scheduled_count()`
- **Results**: `result(id, preserve=True/False)` — fetch result by task ID. `result_count()`
- **Revocation**: `revoke_by_id(task_id)`, `restore_by_id(task_id)`, `is_revoked(task)` — checks if a Task object is revoked
- **Queue state**: `len(huey)` returns the queue size. `pending()` returns a list of Task objects currently in the queue. `pending_count()` returns the count. `flush()` clears the queue, schedule, and result store for this instance. `flush_locks()` releases all held task locks.
- **Locking**: `lock_task(lock_name)` — returns a `TaskLock` (context manager AND decorator). While held, tasks with the same lock name are skipped. If the task has retries, a locked-out execution will be retried.
- **Signals**: `signal(*signals)` (decorator), `disconnect_signal(handler)`
- **Hooks**: `pre_execute()`, `post_execute()` — decorators for task lifecycle hooks. `unregister_pre_execute(name_or_fn)`, `unregister_post_execute(name_or_fn)` remove hooks.
- **Startup/Shutdown**: `on_startup()`, `on_shutdown()` — decorators for consumer lifecycle hooks. `unregister_on_startup(name)`, `unregister_on_shutdown(name)` remove them.

  The four `unregister_*` methods accept either the registered name or the function object, and return `True` when a matching hook was found and removed, `False` otherwise.
- **Context tasks**: `context_task(obj, as_argument=False)` — decorator factory; wraps task so `obj` is entered as context manager. If `as_argument=True`, the context value is passed as the first argument.

### Consumer

`from huey.consumer import Consumer` — `Consumer(huey, workers=1, worker_type='thread')` starts a background consumer that dequeues and executes tasks. `consumer.start()` begins processing, `consumer.stop()` shuts down. `worker_type` can be `'thread'`, `'process'`, or `'greenlet'`.

### Consumer CLI

`python -m huey.bin.huey_consumer path.to.huey_instance` accepts `--help` for usage info.

---

## 2. Task Decoration and TaskWrapper

`@huey.task()` returns a `TaskWrapper`. Calling the wrapper enqueues the task and returns a `Result`. Priority and expires can be overridden at call time: `my_task(arg, priority=5, expires=60)`.

`huey.task()` wraps the underlying function. Re-applying it to an existing `TaskWrapper` (e.g. `task_b = huey2.task()(task_a)` where `task_a` is already a `TaskWrapper`) is supported: the original wrapper's underlying function is unwrapped and re-registered, and the returned wrapper is bound to (and enqueues onto) the Huey instance whose `.task()` was just called — independent of the original wrapper's instance.

Absent an explicit `name=`, a task's name defaults to the wrapped function's bare `__name__` (e.g. a function `work` registers as `"work"`, not a module-qualified path). This is the `.name` exposed on the `TaskWrapper`, on the enqueued `Task`, and on tasks returned by `read_periodic()` / `read_schedule()` and reported to signal handlers.

`TaskWrapper` provides:
- `.s(*args, **kwargs)` — create a `Task` instance without enqueuing
- `.schedule(args, eta=, delay=, expires=)` — enqueue with a future execution time. `args` is the task's positional arguments and accepts either a tuple/list (e.g. `.schedule((3,), delay=60)`) or a single non-tuple value (e.g. `.schedule(-1, eta=...)`); a non-tuple `args` is stored as the task's argument data and round-trips through the schedule store unchanged. (When BOTH `eta=` and `delay=` are omitted, a bare numeric/`timedelta`/`datetime` first argument is instead interpreted as the delay/eta itself — the convenience form `.schedule(60)` ≡ `.schedule(delay=60)`.)
- `.map(iterable)` — enqueue one task per item, return `ResultGroup`
- `.call_local(*args, **kwargs)` — execute locally without enqueuing
- `.revoke()` / `.restore()` / `.is_revoked()` — class-level revocation
- `.unregister()` — remove from registry; subsequent calls raise `HueyException`

`@huey.periodic_task(validate_datetime)` registers a periodic task. `validate_datetime` is typically a `crontab()` instance. Periodic tasks are discovered by `read_periodic(timestamp)`.

### Task expiration

`expires` sets a deadline past which the task will not run. An integer `expires=N` means the task is skipped if it is executed more than `N` seconds after it was enqueued; passing a `datetime` instead sets an absolute deadline. Expiry is resolved at enqueue time and evaluated when the task runs, comparing the deadline against the `timestamp` passed to `execute(task, timestamp)`. An expired task is skipped: `execute()` returns `None`, the function body does not run, and `SIGNAL_EXPIRED` is emitted. Skipping is not destructive — executing the same task again with a timestamp inside the window still runs it. `expires` can be overridden at call time and via `.schedule(..., expires=)`, and the window is preserved across schedule round-trips.

---

## 3. `crontab()`

```python
crontab(minute='*', hour='*', day='*', month='*', day_of_week='*', strict=False)
```

Returns a callable `validate_datetime(dt) -> bool`. Supports: `*`, exact values (int or string), ranges (`N-M`), steps (`*/N`), comma-separated combinations. `day_of_week`: 0=Sunday, 7=Sunday alias. Step values on `day_of_week` raise `ValueError`. Out-of-range values raise `ValueError`. `strict=True` rejects non-pattern strings.

---

## 4. Result and ResultGroup

`Result` wraps a task result. `get(blocking=False, timeout=None, preserve=False)` by default removes the result from the store; `preserve=True` keeps it. `blocking=True` with `timeout` raises `ResultTimeout` if unavailable. `__call__()` is shorthand for `get()`. A `Result` caches the value the first time it is fetched: although a default (`preserve=False`) `get()` removes the entry from the result STORE, the fetched value stays cached on that same `Result` object, so subsequent `get()`/`__call__()` calls on it keep returning the same value (they do not re-read the store) until `reset()` is called. `reset()` clears that cached result. This caching also applies to the `Result` objects yielded by a `ResultGroup`, so iterating/unpacking a `ResultGroup` and reading its results more than once returns the same values. `revoke()` / `restore()` are for instance-level (by-id) revocation of this Result's task. `is_revoked()` mirrors `huey.is_revoked(task)`: it returns `True` when EITHER an instance-/by-id revocation applies to this task OR the task's class-level revocation (via its `TaskWrapper.revoke()`) is active — not only the instance-level flag. `reschedule(eta=, delay=, priority=)` revokes the current task, creates a new copy with a new ID, returns a new `Result`.

`ResultGroup` from `enqueue(pipeline)` and `map()`. `get()` / `__call__()` returns a list of results. Supports `len()`, iteration, and unpacking (e.g., `r1, r2 = huey.enqueue(pipe)`).

---

## 5. Task Pipelines

Chain tasks with `task.then(arg, *args, **kwargs)`. `arg` may be EITHER a `TaskWrapper` (chained as `wrapper.s(*args, **kwargs)`) OR an already-constructed `Task` instance (e.g. one produced by `wrapper.s(...)`, optionally with `.error(...)` attached); when a `Task` is passed, that step — with any error handlers it already carries — is appended to the chain as-is. For example, `step1.s(5).then(step2.s().error(handler)).then(step3)` chains an error-handler-bearing step built from `.s().error()`. The result of each step is passed to the next as the first positional argument. When a task returns a tuple, it is unpacked as positional arguments to the next step. `enqueue(pipeline_head)` returns a `ResultGroup`.

Error callbacks: `task.error(handler_wrapper, *args)` — when the task fails, the error handler is enqueued with the exception as its first argument. Any extra `*args` passed to `.error(...)` follow it.

A task has at most **one** direct error handler, and chaining `.error(...)` builds a *nested* chain rather than attaching several handlers to the same task: in `task.error(h1).error(h2)`, `h1` is `task`'s error handler and `h2` is `h1`'s error handler (each further `.error(...)` attaches to the most-recently-added handler, not back to the primary task).

If a pipeline step fails, subsequent steps are not enqueued. If a step is revoked, the chain also stops.

---

## 6. Task Revocation

- **Class-level**: `task_wrapper.revoke()` / `restore()` — permanent by default
- **Instance-level**: `result.revoke()` / `restore()` — `revoke_once` defaults to `True` (consumed after first skip)
- **Persistent instance**: `result.revoke(revoke_once=False)` — survives re-enqueue
- **By ID**: `huey.revoke_by_id(task_id)` / `restore_by_id(task_id)`. `revoke_by_id` also accepts `revoke_until=` and `revoke_once=` (default `revoke_once=False`, i.e. persistent); with `revoke_once=True` the by-ID revocation skips a single execution and is then consumed, just like an instance-level `revoke_once`. A persistent (`revoke_once=False`) by-ID revocation is NOT consumed by a skipped execution — it keeps the task revoked across re-enqueues until `restore_by_id` is called. `restore_by_id(task_id)` returns a truthy value if a revocation was in fact removed, falsy otherwise.
- **Time-based**: `revoke(revoke_until=timestamp)` — revoked only before the cutoff. Like expiry (Section 2), the cutoff is compared against the `timestamp` passed to `execute(task, timestamp)` (the simulated execution time), not wall-clock `now`: the task is skipped (returns `None`, emits `SIGNAL_REVOKED`) when that execution timestamp is before `revoke_until`, and the revocation lapses for executions at or after `revoke_until`.

Revoked tasks return `None` when executed.

---

## 7. Signals

Signal constants (strings) in `huey.signals`: `SIGNAL_CANCELED`, `SIGNAL_COMPLETE`, `SIGNAL_ENQUEUED`, `SIGNAL_ERROR`, `SIGNAL_EXECUTING`, `SIGNAL_EXPIRED`, `SIGNAL_LOCKED`, `SIGNAL_RETRYING`, `SIGNAL_REVOKED`, `SIGNAL_SCHEDULED`.

Register with `@huey.signal()` (all signals) or `@huey.signal(SIGNAL_COMPLETE)` (specific). Handlers receive `(signal, task, *args)`. Disconnect with `huey.disconnect_signal(handler)`.

Per-signal payload: of these signals, only `SIGNAL_ERROR` carries an extra positional arg — the raised exception object — so its handler is invoked as `(signal, task, exc)`. Every other signal (including `SIGNAL_COMPLETE`) is emitted with NO extra positional args, i.e. the handler receives exactly `(signal, task)`. In particular the completed task's return value is NOT passed to a `SIGNAL_COMPLETE` handler (a handler declared `def h(signal, task): ...` must work for it) — use a `post_execute` hook (Section 8) if you need the return value.

---

## 8. Hooks

`@huey.pre_execute()` — called before task execution. Raising `CancelExecution` here silently cancels the task before its body runs: no error is recorded, so `result.get()` returns `None` (contrast with a `CancelExecution` raised inside the task body — see Section 11 — which is recorded as a task error).

`@huey.post_execute()` — called after execution with `(task, task_value, exc)`. `exc` is `None` on success.

---

## 9. Serializer

`Serializer(compression=False, use_zlib=False)` — pickle-based with optional gzip/zlib compression. `serialize(data) -> bytes`, `deserialize(bytes) -> data`.

`SignedSerializer(secret, salt='huey')` — extends Serializer with HMAC-SHA256 signature. Tampered data raises `ValueError`. Can be assigned to `huey.serializer` for end-to-end signed task data.

---

## 10. Storage Backends

Storage backends implement queue (with optional priority), schedule, and result store operations. On a priority-capable backend, higher-`priority` tasks are dequeued before lower-`priority` ones (default priority `0`); among tasks of equal priority, dequeue is FIFO (insertion order). Backends without priority support dequeue in FIFO order.

- **MemoryStorage**: In-memory, `priority = True`, thread-safe. `peek_data`/`pop_data` return `EmptyData` sentinel (from `huey.constants`) for missing keys. `put_if_empty(key, value)` returns `True` if set, `False` if key already exists.
- **SqliteStorage**: SQLite-backed persistent storage with priority support. Accepts `filename=` kwarg.
- **RedisStorage**: Redis-backed. `priority = False`. `put_if_empty` returns truthy on success, falsy if key exists. RedisStorage exposes the Redis client as `storage.conn`.
- **FileStorage**: File-based. Accepts `name=` and `path=` directory. `priority = False`.
- **BlackHoleStorage**: No-op storage.

All storage backends share: `enqueue(data, priority=None)`, `dequeue()`, `queue_size()`, `flush_queue()`, `add_to_schedule(data, ts)`, `read_schedule(ts)`, `schedule_size()`, `put_data(key, value)`, `peek_data(key)`, `pop_data(key)`, `has_data_for_key(key)`. Missing keys return `EmptyData`. `has_data_for_key(key)` returns `True` if a result-store value exists for `key`, else `False`.

A result-store key passed to `put_data` / `peek_data` / `pop_data` / `has_data_for_key` / `put_if_empty` may be either a `str` or `bytes`, and every backend must accept both. In particular `FileStorage` must accept both `str` and `bytes` result-store keys (as every backend must), returning the stored value on `peek_data`/`pop_data` and the `EmptyData` sentinel for a missing key.

The `ts` argument to the storage-level `add_to_schedule(data, ts)` and `read_schedule(ts)` is a `datetime.datetime` (the task's execution time). Every backend must store the scheduled `data` ordered by that timestamp, and `read_schedule(ts)` must be a destructive ready-read: it returns the data for all scheduled items whose stored timestamp is `<= ts` and removes them from the schedule.

---

## 11. Exceptions

All importable from `huey.exceptions`.

- `HueyException(Exception)` — base exception
- `ConfigurationError(HueyException)`
- `TaskLockedException(HueyException)`
- `ResultTimeout(HueyException)`
- `CancelExecution(Exception)` — cancel task execution. Constructor takes `retry=None`. `retry=False` prevents retries even if configured; `retry=None` falls back to the task's configured `retries`. When raised from within a task body, the in-flight attempt is recorded as a task error, so `result.get()` raises `TaskException`; the `retry` attribute only controls whether the task is retried. (This differs from a `CancelExecution` raised in a `pre_execute` hook — see Section 8 — which silently cancels the task before its body runs and records no error, so `result.get()` returns `None`.) Note: inherits from `Exception`, not `HueyException`.
- `RetryTask(Exception)` — trigger retry without decrementing retry count. Constructor takes optional `msg=None, eta=None, delay=None`. Attributes: `self.eta`, `self.delay`. When raised with `delay=N`, the retry goes to the schedule store with a future eta; with `eta=` it uses that eta directly. When raised with no args, falls back to the task's `retry_delay`. The in-flight attempt that raised `RetryTask` is still recorded as a task error: `result.get()` raises `TaskException` for that attempt (even though the task is re-enqueued/rescheduled and its retry count is not decremented). Inherits from `Exception`, not `HueyException`.
- `TaskException(Exception)` — wraps task errors; raised by `result.get()` for failed tasks. Constructor takes `metadata=None`. Inherits from `Exception`, not `HueyException`.

---

## 12. Contrib Modules

- `huey.contrib.sql_huey.SqlHuey` — Huey with peewee-based SQL storage. Accepts `database=` kwarg (e.g. `'sqlite:///path/to/db'`).
- `huey.contrib.helpers.RedisSemaphore(huey, name, value=1)` — distributed counting semaphore backed by Redis. `acquire()` returns an ID (or `None` if at limit), `release(id)` returns 1 on success.
- `huey.contrib.djhuey` — Django integration. When `settings.HUEY` is set to a Huey instance, exports `task` decorator that delegates to the configured instance.
- `huey.contrib.mini.MiniHuey(name, interval=1, pool_size=None)` — gevent-based single-process task queue. `start()` begins the consumer, `stop()` shuts it down. Tasks return `MiniHueyResult` (gevent `AsyncResult`) with `get(timeout=)`.
- `huey.contrib.asyncio.aget_result(result)` — async function to await a task result with exponential backoff polling.
