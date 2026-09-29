# pgqueuer

Build `pgqueuer`, a Python library that turns a PostgreSQL database into a durable, concurrent job queue and cron scheduler. Producers enqueue jobs (an *entrypoint* name plus an optional binary payload) into Postgres; one or more asynchronous worker processes atomically claim jobs, run the registered handler for each entrypoint, and record the outcome. Because all coordination happens in the database, many workers across many processes can share one queue safely.

The library exposes both a Python API and a `pgqueuer` command-line tool. It also ships an in-memory backend (no database) with the same API, useful for tests and short-lived batch jobs.

## Dependencies and environment

- Targets Python 3.10+ and PostgreSQL.
- The package must be installable under the distribution name `pgqueuer` and importable as `pgqueuer`. The CLI must be runnable as `python -m pgqueuer …`.
- Two database drivers must be supported, selected by which connection object the caller passes:
  - **asyncpg** — `asyncpg.Connection` and `asyncpg.Pool`.
  - **psycopg** (psycopg 3) — `psycopg.AsyncConnection`.
- Database connection parameters are taken from the standard libpq environment variables (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`); `asyncpg.connect()`, `asyncpg.create_pool()`, and `psycopg.AsyncConnection.connect("")` all read these, so the library never needs to parse a DSN itself.
- Cron scheduling must support standard 5-field expressions (`m h dom mon dow`) and 6-field expressions with a trailing **seconds** field (e.g. `* * * * * *` fires every second). Invalid expressions must be rejected at registration time.

**The environment is offline and every dependency you need is already installed — do not install
anything (there is no network).** The following libraries are available to import directly: `asyncpg`
and `psycopg` (the two PostgreSQL drivers), `croniter` (cron-expression parsing), `pydantic` and
`pydantic-settings`, `typer` (the CLI framework), `tabulate`, `anyio`, and `uvloop`. A PostgreSQL
server is running locally and reachable through the libpq `PG*` environment variables above.

Provide a `setup.sh` script at the repository root that installs **your** package into the
(offline) environment — and nothing else: `setup.sh` must NOT start or provision PostgreSQL, create
roles or databases, or set/override the `PG*` environment variables. The grading harness already
provides a running, provisioned PostgreSQL server reachable through the `PG*` variables above. Because the dependencies and the build backend are pre-installed and the
environment has no package index, `setup.sh` must install your package without build isolation, for
example:

```bash
pip install -e . --no-build-isolation
```

## Job lifecycle and status values

A job moves through these string statuses, which are observable through the logging API below:

- `queued` — waiting to be picked.
- `picked` — claimed by a worker and currently being processed.
- `successful` — handler returned normally.
- `exception` — handler raised an unhandled exception (terminal; job removed from the queue).
- `canceled` — job was cancelled.
- `deleted` — job was removed via a targeted `clear_queue` call.
- `failed` — handler failed terminally for an entrypoint configured to *hold* failures; the job is parked for manual inspection / re-queue rather than removed.

---

## 1. `Queries` — the data layer

Importable as `from pgqueuer.queries import Queries`.

`Queries(driver)` wraps a driver object. Convenience constructors build the driver for you:

- `Queries.from_asyncpg_pool(pool)` — driver backed by an `asyncpg.Pool`.
- `Queries.from_psycopg_connection(conn)` — driver backed by a `psycopg.AsyncConnection`.

(`pgqueuer.db.AsyncpgDriver(connection)` wraps a single `asyncpg.Connection`; `Queries(AsyncpgDriver(conn))` is the explicit form.)

A driver backed by a single connection (`AsyncpgDriver` over one `asyncpg.Connection`, and likewise the psycopg driver over one `psycopg.AsyncConnection`) **serializes the operations issued through it**: concurrent calls made on the same driver are run one at a time rather than overlapping on the underlying connection. Consequently the **same** driver — and any `Queries`, `QueueManager`, or `SchedulerManager` sharing it — may be used safely from multiple concurrent coroutines without error. For example, several `QueueManager`s built over one driver may run their loops concurrently, and one worker's `run()` loop may execute alongside another caller invoking `queue_size()` or `mark_job_as_cancelled()` on the same driver.

### Schema management
- `await queries.install()` — create all the database objects the queue needs (tables, types, indexes) so that jobs can be enqueued, dequeued, and logged, and so that each `enqueue` emits a `NOTIFY` on the queue's notification channel (see §2 for the idle-worker `LISTEN`/`NOTIFY` wakeup contract).
- `await queries.uninstall()` — drop everything `install()` created.

### Enqueue
```python
await queries.enqueue(
    entrypoint,        # str, or list[str] for a batch
    payload,           # bytes | None, or list[bytes | None] for a batch
    priority=0,        # int, or list[int]
    execute_after=None,  # timedelta | None (or list); delay before the job becomes eligible
    dedupe_key=None,     # str | None (or list); see below
    headers=None,        # dict[str, str] | None (or list); arbitrary metadata stored with the job
) -> list[JobId]
```
- The scalar and list forms are interchangeable; the list form inserts a batch in one call. Returns the new job ids.
- `headers` is round-tripped verbatim: a job dequeued later exposes the exact dict that was enqueued.
- `dedupe_key`: if a job with the same dedupe key is already queued, the enqueue raises `pgqueuer.errors.DuplicateJobError` and no new job is inserted. The raised exception exposes a `dedupe_key` attribute containing the offending key.

### Dequeue
```python
await queries.dequeue(
    batch_size,             # int, max jobs to claim
    entrypoints,            # dict[str, EntrypointExecutionParameter]
    queue_manager_id,       # uuid.UUID identifying the claiming worker
    global_concurrency_limit,  # int | None
    heartbeat_timeout,      # timedelta; jobs whose heartbeat is older are reclaimable
) -> list[Job]
```
- Atomically selects eligible jobs (status `queued`, or `picked` jobs whose heartbeat is stale), sets their status to `picked`, and returns them. Concurrent workers never claim the same job.
- Ordering is **priority descending, then job id ascending** (higher `priority` first; FIFO within a priority).
- A job whose `execute_after` is in the future is **not** eligible until that time passes.
- `EntrypointExecutionParameter` (importable from `pgqueuer.queries`) is constructed as `EntrypointExecutionParameter(concurrency_limit)` where `concurrency_limit` is an int (`0` = unlimited). It is the per-entrypoint value in the `entrypoints` mapping.

### Recording outcomes and inspecting state
- `await queries.log_jobs([(job, status, traceback)])` — record terminal outcomes for a list of `(Job, status_str, TracebackRecord | None)` tuples, moving each job out of the active queue into the log.
- `await queries.queue_size() -> list[QueueStatistics]` — one row per `(entrypoint, priority, status)` still present in the queue, each with a `count`. Summing `count` over all rows gives the number of jobs currently in the queue (including `picked`).
- `await queries.queue_log() -> list[Log]` — the history of status transitions (see `Log` below).
- `await queries.log_statistics(limit=None) -> list[LogStatistics]` — aggregated transition counts; each row has a `count` and a `status`. Processing N jobs to success yields rows summing to N `queued`, N `picked`, and N `successful`.
- `await queries.next_deferred_eta(entrypoints) -> timedelta | None` — for a list of entrypoint names, the time remaining until the soonest deferred (`execute_after` in the future) job becomes eligible, or `None` when nothing is deferred (or all are already eligible).

### Clearing and cancelling
- `await queries.clear_queue(entrypoint=None)` — remove jobs. With a single entrypoint name or a list of names, the matching jobs are deleted **and each deletion is recorded in the log as a `deleted` entry**. With no argument, the entire queue is emptied.
- `await queries.mark_job_as_cancelled(ids)` — request cancellation of the given job ids. A job that is currently being processed has its handler's cancellation scope triggered (see §3), and cancelled jobs are recorded with status `canceled`.

### Holding and re-queueing failed jobs
- `await queries.list_failed_jobs() -> list[Job]` — jobs parked with status `failed` (from an entrypoint configured with `on_failure="hold"`), most recent first.
- `await queries.requeue_jobs(ids)` — move the given `failed` jobs back to `queued` so they will be processed again. After this, they no longer appear in `list_failed_jobs()`.

---

## 2. `QueueManager` and `PgQueuer` — the worker

`QueueManager` (`from pgqueuer.qm import QueueManager`) runs the processing loop. `PgQueuer` (`from pgqueuer import PgQueuer`) is a thin application wrapper around a `QueueManager` that exposes a shared `resources` mapping to its handlers.

### Constructing
- `QueueManager(queries)` — takes a `Queries` instance. Its `.queries` attribute exposes it.
- `PgQueuer(driver, resources=None)` — takes a driver (e.g. `AsyncpgDriver(conn)`) and an optional mutable `resources` mapping. Exposes:
  - `.qm` — the underlying `QueueManager`; `.qm.queries` is the `Queries`.
  - `.resources` — the shared resources mapping (the same object handlers mutate through their context).
- `PgQueuer.in_memory()` — classmethod returning a `PgQueuer` backed entirely by in-memory data structures (no PostgreSQL connection). Same API as the database-backed instance.

### Registering entrypoints
`@qm.entrypoint(name, *, concurrency_limit=0, on_failure="delete")` (and the same on `pgq`) registers an async handler for an entrypoint:

```python
@pgq.entrypoint("send_email")
async def handle(job: Job) -> None:
    ...
```
- The handler receives the `Job`. If it declares a second parameter annotated `Context` (`async def handle(job: Job, ctx: Context)`), the job's context is injected automatically (auto-detected from the signature).
- `concurrency_limit` (int, default `0` = unlimited) caps how many jobs of this entrypoint may run **simultaneously across all workers**, enforced via the database. A negative value raises `ValueError`.
- Registering a name that is already registered raises `RuntimeError`.
- `on_failure` controls terminal failure handling:
  - `"delete"` (default) — a job whose handler raises is removed from the queue and logged with status `exception` (the log entry carries the exception type, see `TracebackRecord`).
  - `"hold"` — a failing job is parked with status `failed` instead of removed, recoverable via `list_failed_jobs()` / `requeue_jobs()`.

### Running
```python
await pgq.run(
    batch_size=10,                       # jobs claimed per dequeue
    dequeue_timeout=timedelta(seconds=…),
    mode=QueueExecutionMode.drain,       # optional
)
# QueueManager.run additionally accepts max_concurrent_tasks=…
```
- `QueueExecutionMode` is importable from `pgqueuer.types`. `QueueExecutionMode.drain` runs until the queue is empty and then returns — ideal for batch processing and tests. In the default mode (`QueueExecutionMode.continuous`), the worker runs until `.shutdown` (an `asyncio.Event` on the manager) is set. Setting `.shutdown` must stop the worker **promptly** — it interrupts an in-progress idle wait rather than only taking effect at the next poll, so a worker idling with a long `dequeue_timeout` still returns within about a second of `.shutdown` being set (it does not have to wait out the remaining `dequeue_timeout`).
- `dequeue_timeout` is the **maximum** idle wait between dequeue attempts, not a fixed poll interval. A running worker also issues `LISTEN` on the queue's notification channel, and every `enqueue` emits a matching `NOTIFY`; an idle worker is therefore woken by that event and must begin processing a newly-enqueued job **promptly — well before `dequeue_timeout` elapses** — rather than only at the next poll. (Concretely: with a long `dequeue_timeout`, a job enqueued from another connection while the worker is idle should still be picked up within a second or so.)
- Each claimed job is dispatched to its handler. On success the job is logged `successful` and leaves the queue.

### Retries
A handler may raise `pgqueuer.errors.RetryRequested(delay=timedelta(...), reason="...")` to request a database-level retry instead of failing. The **same** job row is re-queued (not re-created): its id is stable, its `payload` is preserved, and `job.attempts` increments by one on each retry (it is `0` on the first execution). When the handler eventually returns normally, the job is logged `successful`. `RetryRequested(delay=…, reason=…)` — both arguments are optional (default delay `timedelta(0)`, default reason `None`).

### Per-job context and cancellation
- `qm.get_context(job_id)` returns the job's `Context` while it is being processed. The `Context` exposes:
  - `.resources` — the shared resources mapping (the same object passed to `PgQueuer(resources=...)`, mutations persist and are visible afterwards on `pgq.resources`).
  - `.cancellation` — a cancellation scope whose `.cancel_called` boolean flips to `True` when the job is cancelled via `mark_job_as_cancelled` while its handler is still running. Cancellation is **cooperative**, not a forced teardown: cancelling a running job does **not** raise into the handler or abort it at whatever `await` it happens to be suspended on. The handler keeps running, its in-progress `await`s complete normally, and it can read `.cancel_called` — now `True` — and wind down on its own before returning. Regardless of how the handler returns once its job has been cancelled, the job is recorded with status `canceled` (not `successful`).

---

## 3. `SchedulerManager` — cron scheduling

Importable as `from pgqueuer.sm import SchedulerManager`. `SchedulerManager(queries)` registers recurring tasks:

```python
@sm.schedule("nightly_cleanup", "0 0 * * *")
async def cleanup(schedule: Schedule) -> None:
    ...
```
- `sm.schedule(name, cron_expression)` returns a decorator. The handler receives a `Schedule`.
- An invalid cron expression raises `ValueError` at registration time.
- Expressions support a trailing seconds field (6 fields), so `"* * * * * *"` fires every second.
- `await sm.run()` runs the scheduler, executing each task when it is due, until `.shutdown` (an `asyncio.Event`) is set.

---

## 4. Command-line interface

Runnable as `python -m pgqueuer <command>` (entry point `pgqueuer.__main__:main`). Connection comes from the libpq `PG*` environment variables. Required commands:

- `install` — create the queue schema. Exit code 0 on success.
- `uninstall` — drop the queue schema. Exit code 0 on success (also when already absent).
- `upgrade` — apply any schema upgrades; a no-op (still exit 0) when already current.
- `verify --expect present|absent` — check whether the schema objects exist; exit code 0 when the actual state matches the expected one.

---

## 5. Exceptions

Importable from `pgqueuer.errors`:

- `RetryRequested(delay=timedelta(0), reason=None)` — raise inside a handler to request a retry (see §2).
- `DuplicateJobError` — raised by `enqueue` on a dedupe-key collision; exposes a `dedupe_key` attribute containing the conflicting key.

---

## 6. Models

Importable from `pgqueuer.models`. Only the fields/behaviour below are relied upon:

- `Job` — a queued job. Attributes used: `id`, `payload` (`bytes | None`), `status` (str), `attempts` (`int`, starts at 0, increments on each retry), and `headers` (`dict[str, str] | None`, the dict supplied at enqueue, round-tripped verbatim).
- `Context` — per-job runtime context: `resources` (mutable mapping) and `cancellation` (a scope with a `cancel_called` bool). Also usable as the type annotation that triggers context injection into a handler.
- `Schedule` — the value passed to scheduled-task handlers (type annotation).
- `QueueStatistics` — a `queue_size()` row: `count` (int) and `status` (str).
- `Log` — a `queue_log()` row: `status` (str) and `traceback` (`TracebackRecord | None`).
- `LogStatistics` — a `log_statistics()` row: `count` (int) and `status` (str).
- `TracebackRecord` — failure detail attached to an `exception` log entry; exposes `exception_type` (the raised exception's class name, e.g. `"ValueError"`).

---

## Import path summary

These symbols must be importable from exactly these locations:

- `from pgqueuer import PgQueuer`
- `from pgqueuer.db import AsyncpgDriver`
- `from pgqueuer.errors import DuplicateJobError, RetryRequested`
- `from pgqueuer.models import Context, Job, Schedule`  (and `QueueStatistics`, `Log`, `LogStatistics`, `TracebackRecord`)
- `from pgqueuer.qm import QueueManager`
- `from pgqueuer.queries import EntrypointExecutionParameter, Queries`
- `from pgqueuer.sm import SchedulerManager`
- `from pgqueuer.types import QueueExecutionMode`
