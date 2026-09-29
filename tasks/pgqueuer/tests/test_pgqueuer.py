"""Hidden test suite for the pgqueuer WRG task.

pgqueuer is a PostgreSQL-backed job queue. These tests exercise the library's
user-facing surface the way a real user would: the ``Queries`` data layer, the
``PgQueuer`` / ``QueueManager`` processing loop (entrypoints, priority, context
injection, concurrency limits, retries, hold-on-failure, cancellation), the
``SchedulerManager`` cron scheduler, the in-memory driver, the asyncpg/psycopg
drivers, and the ``pgq`` command-line interface.

Each test is a self-contained, end-to-end scenario that asserts a specific
behavioural contract. Connection settings are read from the standard libpq
environment variables (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE), which
test.sh exports. Every test runs against a freshly installed schema (autouse
``clean_schema`` fixture).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from datetime import timedelta
from typing import AsyncGenerator

import asyncpg
import psycopg
import pytest
import pytest_asyncio

# asyncio.timeout() landed in Python 3.11; fall back to the async-timeout backport on 3.10.
try:
    from asyncio import timeout as _timeout
except ImportError:
    from async_timeout import timeout as _timeout

from pgqueuer import PgQueuer
from pgqueuer.db import AsyncpgDriver
from pgqueuer.errors import DuplicateJobError, RetryRequested
from pgqueuer.models import Context, Job, Schedule
from pgqueuer.qm import QueueManager
from pgqueuer.queries import EntrypointExecutionParameter, Queries
from pgqueuer.sm import SchedulerManager
from pgqueuer.types import QueueExecutionMode

DRAIN = QueueExecutionMode.drain
HEARTBEAT = timedelta(seconds=30)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture(autouse=True)
async def clean_schema() -> AsyncGenerator[None, None]:
    """Reinstall a clean pgqueuer schema before each test and remove it after."""
    conn = await asyncpg.connect()
    q = Queries(AsyncpgDriver(conn))
    try:
        await q.uninstall()
    except Exception:
        pass
    await q.install()
    await conn.close()
    try:
        yield
    finally:
        conn = await asyncpg.connect()
        try:
            await Queries(AsyncpgDriver(conn)).uninstall()
        except Exception:
            pass
        finally:
            await conn.close()


@pytest_asyncio.fixture
async def driver() -> AsyncGenerator[AsyncpgDriver, None]:
    conn = await asyncpg.connect()
    try:
        yield AsyncpgDriver(conn)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def queries(driver: AsyncpgDriver) -> Queries:
    return Queries(driver)


def _ep(name: str, concurrency_limit: int = 0) -> dict[str, EntrypointExecutionParameter]:
    """Single-entrypoint dequeue parameter map."""
    return {name: EntrypointExecutionParameter(concurrency_limit)}


async def _total_pending(q: Queries) -> int:
    return sum(stat.count for stat in await q.queue_size())


async def _count_log(q: Queries, status: str) -> int:
    return sum(1 for log in await q.queue_log() if log.status == status)


# --------------------------------------------------------------------------- #
# CLI lifecycle
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cli_install_verify_uninstall_cycle() -> None:
    """The `pgq` CLI installs the schema, confirms presence, upgrades, then removes it again."""

    def run(*args: str) -> int:
        return subprocess.run(
            [sys.executable, "-m", "pgqueuer", *args],
            capture_output=True,
            text=True,
        ).returncode

    assert run("uninstall") == 0
    assert run("verify", "--expect", "absent") == 0
    assert run("install") == 0
    assert run("verify", "--expect", "present") == 0
    assert run("upgrade") == 0
    assert run("uninstall") == 0
    assert run("verify", "--expect", "absent") == 0


# --------------------------------------------------------------------------- #
# Enqueue / queue inspection
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_clear_queue_selectively_and_fully(queries: Queries) -> None:
    """Enqueue several entrypoints, then clear by name and by list; deletions are reflected and logged."""
    await queries.enqueue(["a", "b", "c"], [None, None, None], [0, 0, 0])
    assert await _total_pending(queries) == 3

    await queries.clear_queue("a")
    assert await _total_pending(queries) == 2

    await queries.clear_queue(["b", "c"])
    assert await _total_pending(queries) == 0
    assert await _count_log(queries, "deleted") == 3

    # The no-argument form empties whatever is left in the queue wholesale.
    await queries.enqueue(["d", "e"], [None, None], [0, 0])
    assert await _total_pending(queries) == 2
    await queries.clear_queue()
    assert await _total_pending(queries) == 0


@pytest.mark.asyncio
async def test_enqueue_headers_roundtrip(queries: Queries) -> None:
    """Custom headers and payload attached at enqueue time survive onto the dequeued job verbatim."""
    headers = {"trace": "abc", "tenant": "42"}
    await queries.enqueue("header_task", b"payload", headers=headers)

    jobs = await queries.dequeue(1, _ep("header_task"), uuid.uuid4(), 1000, HEARTBEAT)
    assert len(jobs) == 1
    assert jobs[0].headers == headers
    assert jobs[0].payload == b"payload"


@pytest.mark.asyncio
async def test_dedupe_key_rejects_duplicate(queries: Queries) -> None:
    """A second enqueue with the same dedupe_key raises DuplicateJobError and keeps a single job queued."""
    await queries.enqueue("task", None, dedupe_key="unique-1")
    assert await _total_pending(queries) == 1

    with pytest.raises(DuplicateJobError) as raised:
        await queries.enqueue("task", None, dedupe_key="unique-1")
    assert "unique-1" in raised.value.dedupe_key
    assert await _total_pending(queries) == 1


@pytest.mark.asyncio
async def test_stale_picked_job_is_reclaimed(queries: Queries) -> None:
    """A picked job whose heartbeat ages past heartbeat_timeout becomes reclaimable by another worker."""
    ids = await queries.enqueue("recover", b"data")

    # Worker A claims the job (status -> picked, heartbeat = NOW).
    first = await queries.dequeue(1, _ep("recover"), uuid.uuid4(), 1000, timedelta(seconds=30))
    assert [j.id for j in first] == ids

    # While its heartbeat is fresh, the job is held exclusively: a long-timeout
    # dequeue from another worker sees nothing.
    held = await queries.dequeue(1, _ep("recover"), uuid.uuid4(), 1000, timedelta(seconds=30))
    assert held == []

    # Once the heartbeat is older than the (zero) timeout, worker B reclaims the
    # very same row — the crash-recovery path that keeps jobs from being lost.
    await asyncio.sleep(0.05)
    reclaimed = await queries.dequeue(1, _ep("recover"), uuid.uuid4(), 1000, timedelta(seconds=0))
    assert [j.id for j in reclaimed] == ids


# --------------------------------------------------------------------------- #
# Job processing — PgQueuer / QueueManager
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_pgqueuer_processes_all_jobs_and_logs_successful(driver: AsyncpgDriver) -> None:
    """A consumer drains the queue: every job is handled exactly once, logged successful, queue empties."""
    pgq = PgQueuer(driver)
    seen: list[int] = []
    n = 8

    @pgq.entrypoint("fetch")
    async def fetch(job: Job) -> None:
        assert job.payload is not None
        seen.append(int(job.payload))

    await pgq.qm.queries.enqueue(["fetch"] * n, [f"{i}".encode() for i in range(n)], [0] * n)
    await pgq.run(dequeue_timeout=timedelta(seconds=1), mode=DRAIN)

    assert sorted(seen) == list(range(n))
    assert await _total_pending(pgq.qm.queries) == 0
    assert await _count_log(pgq.qm.queries, "successful") == n


@pytest.mark.asyncio
async def test_priority_then_fifo_ordering(driver: AsyncpgDriver) -> None:
    """One-at-a-time dispatch follows descending priority, then FIFO (id-ascending) within a priority."""
    pgq = PgQueuer(driver)
    order: list[int] = []

    @pgq.entrypoint("fetch")
    async def fetch(job: Job) -> None:
        assert job.payload is not None
        order.append(int(job.payload))

    # Two high-priority jobs (payloads 0,1) then two low-priority (2,3), enqueued in id order.
    await pgq.qm.queries.enqueue(["fetch"] * 4, [b"0", b"1", b"2", b"3"], [1, 1, 0, 0])
    await pgq.run(batch_size=1, dequeue_timeout=timedelta(seconds=1), mode=DRAIN)

    # Priority 1 group first (FIFO 0 then 1), then priority 0 group (FIFO 2 then 3).
    assert order == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_context_resources_injected_and_routed(driver: AsyncpgDriver) -> None:
    """Jobs route to the handler matching their entrypoint, and a Context handler sees shared resources."""
    pgq = PgQueuer(driver, resources={"flag": True})
    alpha_seen: list[bytes | None] = []

    @pgq.entrypoint("alpha")
    async def alpha(job: Job) -> None:
        alpha_seen.append(job.payload)

    @pgq.entrypoint("beta")
    async def beta(job: Job, ctx: Context) -> None:
        assert ctx.resources["flag"] is True
        ctx.resources["beta_runs"] = ctx.resources.get("beta_runs", 0) + 1

    await pgq.qm.queries.enqueue(
        ["alpha", "beta", "alpha"], [b"1", b"2", b"3"], [0, 0, 0]
    )
    await pgq.run(dequeue_timeout=timedelta(seconds=1), mode=DRAIN)

    assert sorted(alpha_seen) == [b"1", b"3"]
    assert pgq.resources["beta_runs"] == 1


@pytest.mark.asyncio
async def test_notify_wakes_idle_worker(driver: AsyncpgDriver) -> None:
    """A worker idling in continuous mode is woken promptly by LISTEN/NOTIFY, not by its poll timeout."""
    pgq = PgQueuer(driver)
    processed = asyncio.Event()

    @pgq.entrypoint("live")
    async def live(job: Job) -> None:
        processed.set()

    # A long dequeue_timeout: if the worker only polled, the job would not run for
    # 30s. Getting processed within seconds proves NOTIFY-driven wakeup.
    worker = asyncio.create_task(
        pgq.run(dequeue_timeout=timedelta(seconds=30), mode=QueueExecutionMode.continuous)
    )
    try:
        await asyncio.sleep(0.5)  # let the worker reach its idle LISTEN state
        # Enqueue from a separate connection (a real producer), triggering NOTIFY.
        producer = await asyncpg.connect()
        try:
            await Queries(AsyncpgDriver(producer)).enqueue("live", b"x")
        finally:
            await producer.close()
        await asyncio.wait_for(processed.wait(), timeout=5)
    finally:
        pgq.qm.shutdown.set()
        await asyncio.wait_for(worker, timeout=10)


@pytest.mark.asyncio
async def test_entrypoint_registration_validation(driver: AsyncpgDriver) -> None:
    """Registering a duplicate entrypoint name or a negative concurrency limit is rejected."""
    qm = QueueManager(Queries(driver))

    @qm.entrypoint("dup")
    async def first(job: Job) -> None: ...

    with pytest.raises(RuntimeError):
        @qm.entrypoint("dup")
        async def second(job: Job) -> None: ...

    with pytest.raises(ValueError):
        @qm.entrypoint("bad", concurrency_limit=-1)
        async def third(job: Job) -> None: ...


# --------------------------------------------------------------------------- #
# Failure handling — terminal exception, retry, hold
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_unhandled_exception_is_terminal(driver: AsyncpgDriver) -> None:
    """An unhandled exception removes the job and records one 'exception' log carrying the exception type."""
    pgq = PgQueuer(driver)

    @pgq.entrypoint("boom")
    async def boom(job: Job) -> None:
        raise ValueError("permanent failure")

    await pgq.qm.queries.enqueue("boom", b"data", priority=0)
    await pgq.run(dequeue_timeout=timedelta(seconds=1), mode=DRAIN)

    logs = [log for log in await pgq.qm.queries.queue_log() if log.status == "exception"]
    assert len(logs) == 1
    assert logs[0].traceback is not None
    assert logs[0].traceback.exception_type == "ValueError"
    assert await _total_pending(pgq.qm.queries) == 0


@pytest.mark.asyncio
async def test_retry_requested_requeues_until_success(driver: AsyncpgDriver) -> None:
    """RetryRequested re-queues the same job (attempts increment, payload preserved) until it succeeds."""
    pgq = PgQueuer(driver)
    attempts_seen: list[int] = []

    @pgq.entrypoint("retry_ep")
    async def handler(job: Job) -> None:
        attempts_seen.append(job.attempts)
        assert job.payload == b"keep-me"
        if job.attempts < 2:
            raise RetryRequested(delay=timedelta(0), reason="transient")

    await pgq.qm.queries.enqueue("retry_ep", b"keep-me", priority=0)
    await pgq.run(dequeue_timeout=timedelta(seconds=1), mode=DRAIN)

    assert attempts_seen == [0, 1, 2]
    assert await _count_log(pgq.qm.queries, "successful") == 1
    assert await _total_pending(pgq.qm.queries) == 0


@pytest.mark.asyncio
async def test_on_failure_hold_parks_and_requeue(driver: AsyncpgDriver) -> None:
    """on_failure='hold' parks the failed job as 'failed'; requeue_jobs returns it to the queue."""
    queries = Queries(driver)
    pgq = PgQueuer(driver)

    @pgq.entrypoint("held", on_failure="hold")
    async def held(job: Job) -> None:
        raise RuntimeError("nope")

    ids = await queries.enqueue("held", b"x", priority=0)
    await pgq.run(dequeue_timeout=timedelta(seconds=0.5), mode=DRAIN)

    failed = await queries.list_failed_jobs()
    assert [j.id for j in failed] == ids
    assert failed[0].status == "failed"

    await queries.requeue_jobs(ids)
    assert await queries.list_failed_jobs() == []
    assert await _total_pending(queries) == 1


# --------------------------------------------------------------------------- #
# Concurrency, deferral, statistics, cancellation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_concurrency_limit_enforced_across_workers(driver: AsyncpgDriver) -> None:
    """concurrency_limit caps simultaneous runs of an entrypoint across multiple workers sharing one queue."""
    limit = 3
    n_workers = 3
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    await Queries(driver).enqueue(["fetch"] * 500, [None] * 500, [0] * 500)

    # Several independent QueueManager instances draw from the same queue; the
    # database-enforced cap must bound the combined live count, not each worker's.
    qms = [QueueManager(Queries(driver)) for _ in range(n_workers)]

    async def run_consumer(qm: QueueManager) -> None:
        @qm.entrypoint("fetch", concurrency_limit=limit)
        async def fetch(job: Job) -> None:
            nonlocal active, max_active
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.001)
            async with lock:
                active -= 1

        await qm.run(dequeue_timeout=timedelta(seconds=0))

    async def timer() -> None:
        await asyncio.sleep(2)
        for qm in qms:
            qm.shutdown.set()

    await asyncio.gather(timer(), *(run_consumer(qm) for qm in qms))

    assert 0 < max_active <= limit


@pytest.mark.asyncio
async def test_execute_after_defers_until_eta(queries: Queries) -> None:
    """A job with a future execute_after is reported as deferred and is not eligible until its eta passes."""
    # Nothing deferred yet -> no eta.
    assert await queries.next_deferred_eta(["foo"]) is None

    await queries.enqueue("foo", None, 0, timedelta(seconds=1))

    eta = await queries.next_deferred_eta(["foo"])
    assert eta is not None and eta.total_seconds() > 0

    before = await queries.dequeue(10, _ep("foo"), uuid.uuid4(), 1000, HEARTBEAT)
    assert len(before) == 0

    await asyncio.sleep(1.1)
    after = await queries.dequeue(10, _ep("foo"), uuid.uuid4(), 1000, HEARTBEAT)
    assert len(after) == 1


@pytest.mark.asyncio
async def test_log_statistics_counts_transitions(driver: AsyncpgDriver) -> None:
    """Draining N jobs records N queued, N picked, and N successful transitions in the statistics log."""
    pgq = PgQueuer(driver)
    n = 6

    @pgq.entrypoint("placeholder")
    async def placeholder(job: Job) -> None: ...

    await pgq.qm.queries.enqueue(["placeholder"] * n, [None] * n, [0] * n)
    await pgq.run(dequeue_timeout=timedelta(seconds=1), mode=DRAIN)

    stats = await pgq.qm.queries.log_statistics(limit=None)
    assert sum(s.count for s in stats if s.status == "queued") == n
    assert sum(s.count for s in stats if s.status == "picked") == n
    assert sum(s.count for s in stats if s.status == "successful") == n


@pytest.mark.asyncio
async def test_cancellation_marks_jobs_canceled(driver: AsyncpgDriver) -> None:
    """Cancelling in-flight jobs trips each job's cancellation scope and logs them as 'canceled'."""
    n = 5
    gate = asyncio.Event()
    cancel_flags: list[bool] = []
    q = Queries(driver)
    qm = QueueManager(Queries(driver))

    @qm.entrypoint("cancelme")
    async def cancelme(job: Job) -> None:
        scope = qm.get_context(job.id).cancellation
        await gate.wait()
        # Cancellation is cooperative and observed while the handler keeps running: the flag
        # becomes visible as the handler's in-progress awaits complete, not necessarily on the
        # first resumption. Keep running (yield to the loop) until it flips, bounded so a handler
        # that is never cancelled still fails the assertion below.
        for _ in range(500):
            if scope.cancel_called:
                break
            await asyncio.sleep(0.01)
        cancel_flags.append(scope.cancel_called)

    ids = await q.enqueue(["cancelme"] * n, [None] * n, [0] * n)

    async def canceller() -> None:
        async with _timeout(10):
            while sum(s.count for s in await q.queue_size() if s.status == "picked") < n:
                await asyncio.sleep(0.01)
        await q.mark_job_as_cancelled(ids)
        gate.set()
        qm.shutdown.set()

    await asyncio.gather(qm.run(dequeue_timeout=timedelta(seconds=0)), canceller())

    assert sum(cancel_flags) == n
    assert await _count_log(q, "canceled") == n


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_scheduler_registers_runs_and_rejects_invalid(driver: AsyncpgDriver) -> None:
    """A valid cron schedule registers and fires when due; an invalid expression is rejected up front."""
    sm = SchedulerManager(Queries(driver))
    runs = 0

    async def task(schedule: Schedule) -> None:
        nonlocal runs
        runs += 1

    sm.schedule("ticker", "* * * * * *")(task)

    with pytest.raises(ValueError):
        sm.schedule("broken", "bla * * * *")(task)

    async def stop() -> None:
        await asyncio.sleep(2.5)
        sm.shutdown.set()

    await asyncio.gather(sm.run(), stop())
    assert runs >= 1


# --------------------------------------------------------------------------- #
# In-memory driver and alternative DB drivers
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_in_memory_pgqueuer_processes_jobs() -> None:
    """PgQueuer.in_memory() processes jobs end to end without any PostgreSQL connection."""
    pq = PgQueuer.in_memory()
    seen: list[bytes | None] = []

    @pq.entrypoint("work")
    async def work(job: Job) -> None:
        seen.append(job.payload)

    await pq.qm.queries.enqueue(["work"] * 4, [b"0", b"1", b"2", b"3"], [0] * 4)
    await pq.qm.run(
        batch_size=10, mode=DRAIN, max_concurrent_tasks=100, dequeue_timeout=timedelta(seconds=1)
    )

    assert sorted(seen) == [b"0", b"1", b"2", b"3"]


@pytest.mark.asyncio
async def test_asyncpg_pool_driver_roundtrip() -> None:
    """A pool-backed Queries enqueues and dequeues the same job through the AsyncpgPoolDriver."""
    pool = await asyncpg.create_pool(min_size=1, max_size=3)
    try:
        q = Queries.from_asyncpg_pool(pool)
        ids = await q.enqueue("pool_task", b"payload")

        jobs = await q.dequeue(10, _ep("pool_task"), uuid.uuid4(), 1000, HEARTBEAT)
        assert [j.id for j in jobs] == ids
        assert jobs[0].payload == b"payload"

        await q.log_jobs([(jobs[0], "successful", None)])
        assert await _total_pending(q) == 0
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_psycopg_driver_roundtrip() -> None:
    """A psycopg-backed Queries enqueues and dequeues the same job through the PsycopgDriver."""
    conn = await psycopg.AsyncConnection.connect("", autocommit=True)
    try:
        q = Queries.from_psycopg_connection(conn)
        ids = await q.enqueue("psycopg_task", b"payload")

        jobs = await q.dequeue(10, _ep("psycopg_task"), uuid.uuid4(), 1000, HEARTBEAT)
        assert [j.id for j in jobs] == ids
        assert jobs[0].payload == b"payload"

        await q.log_jobs([(jobs[0], "successful", None)])
        assert await _total_pending(q) == 0
    finally:
        await conn.close()
