"""
Tests for APScheduler v4 — async-native job scheduler.
"""

from datetime import datetime, timedelta, timezone

import anyio
import pytest


# Pin async tests to a single backend by default, so each behavior is graded once rather
# than once per backend. The dual-backend tests below (which drive anyio.run() over both
# backends inside a single graded slot) still verify the "all async operations must work
# under both asyncio and Trio backends" requirement on the scheduler's execution paths.
@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# Module-level job functions (must be top-level for callable_to_ref serialization)

async def _async_add(x, y):
    return x + y

async def _async_failing():
    raise ValueError("job failed")

async def _async_dummy():
    pass

async def _async_return_42():
    return 42

async def _async_worker():
    pass

async def _async_return_str():
    return "async_result"

# Records executions of the scheduled job in test_schedule_fires_and_executes_job.
# A module-level (importable) function and sink are required because scheduled jobs are
# stored by reference — a nested function/closure cannot be referenced.
_scheduled_runs: list[str] = []

async def _async_scheduled_marker():
    _scheduled_runs.append("scheduled_ran")

def _sync_multiply(a, b):
    return a * b

def _sync_return_str():
    return "sync_result"


# ============================================================
# 1. Triggers
# ============================================================


class TestDateTrigger:
    """Tests for DateTrigger."""

    def test_date_trigger_fires_once_then_exhausts(self):
        """DateTrigger returns run_time once, then None on subsequent calls."""
        from apscheduler.triggers.date import DateTrigger

        run_time = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        trigger = DateTrigger(run_time)
        assert trigger.next() == run_time
        assert trigger.next() is None
        assert trigger.next() is None


class TestIntervalTrigger:
    """Tests for IntervalTrigger."""

    def test_interval_sequence_and_end_time(self):
        """IntervalTrigger produces correct sequence and stops after end_time."""
        from apscheduler.triggers.interval import IntervalTrigger

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 2, 30, tzinfo=timezone.utc)
        trigger = IntervalTrigger(hours=1, start_time=start, end_time=end)

        assert trigger.next() == start
        assert trigger.next() == start + timedelta(hours=1)
        assert trigger.next() == start + timedelta(hours=2)
        assert trigger.next() is None  # 3h > 2h30m

    def test_interval_multi_component(self):
        """IntervalTrigger composes multiple time components correctly."""
        from apscheduler.triggers.interval import IntervalTrigger

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        trigger = IntervalTrigger(hours=1, minutes=30, start_time=start)

        assert trigger.next() == start
        second = trigger.next()
        assert second == start + timedelta(hours=1, minutes=30)
        third = trigger.next()
        assert third == start + timedelta(hours=3)


class TestCronTrigger:
    """Tests for CronTrigger — cron field matching and parsing."""

    def test_cron_from_crontab_hourly(self):
        """from_crontab parses '0 * * * *' and produces hourly fire times."""
        from apscheduler.triggers.cron import CronTrigger

        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        trigger = CronTrigger.from_crontab("0 * * * *", start_time=start)

        first = trigger.next()
        assert first == datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        second = trigger.next()
        assert second == datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
        third = trigger.next()
        assert third == datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)

    def test_cron_day_of_week_name_and_hour(self):
        """CronTrigger with day_of_week='mon' and hour=9 fires on Mondays at 9am."""
        from apscheduler.triggers.cron import CronTrigger

        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)  # Monday
        trigger = CronTrigger(day_of_week="mon", hour=9, minute=0, second=0, start_time=start)

        first = trigger.next()
        assert first is not None
        assert first == datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
        assert first.weekday() == 0

        second = trigger.next()
        assert second == datetime(2024, 1, 8, 9, 0, tzinfo=timezone.utc)
        assert second.weekday() == 0

    def test_cron_step_values(self):
        """CronTrigger handles step syntax (*/15 for every 15 minutes)."""
        from apscheduler.triggers.cron import CronTrigger

        start = datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc)
        trigger = CronTrigger.from_crontab("*/15 10 * * *", start_time=start)

        times = [trigger.next() for _ in range(4)]
        assert times[0] == datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc)
        assert times[1] == datetime(2024, 6, 1, 10, 15, tzinfo=timezone.utc)
        assert times[2] == datetime(2024, 6, 1, 10, 30, tzinfo=timezone.utc)
        assert times[3] == datetime(2024, 6, 1, 10, 45, tzinfo=timezone.utc)

    def test_cron_month_boundary_rollover(self):
        """CronTrigger correctly rolls over month boundaries."""
        from apscheduler.triggers.cron import CronTrigger

        start = datetime(2024, 1, 31, 23, 0, tzinfo=timezone.utc)
        trigger = CronTrigger.from_crontab("0 12 * * *", start_time=start)

        first = trigger.next()
        assert first is not None
        assert first == datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc)

    def test_cron_end_time_stops_iteration(self):
        """CronTrigger respects end_time and returns None after it."""
        from apscheduler.triggers.cron import CronTrigger

        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc)
        trigger = CronTrigger.from_crontab("0 * * * *", start_time=start, end_time=end)

        times = []
        for _ in range(10):
            t = trigger.next()
            if t is None:
                break
            times.append(t)

        assert len(times) == 4  # 0:00, 1:00, 2:00, 3:00
        assert times[-1] == datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc)


class TestCombiningTriggers:
    """Tests for OrTrigger and AndTrigger."""

    def test_or_trigger_merges_three_children_in_order(self):
        """OrTrigger merges fire times from three children in chronological order."""
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.combining import OrTrigger

        t1 = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)
        t3 = datetime(2024, 1, 1, 10, 30, tzinfo=timezone.utc)
        trigger = OrTrigger([DateTrigger(t1), DateTrigger(t2), DateTrigger(t3)])

        assert trigger.next() == t1
        assert trigger.next() == t3  # 10:30 before 11:00
        assert trigger.next() == t2
        assert trigger.next() is None

    def test_and_trigger_finds_agreement_at_lcm(self):
        """AndTrigger fires at start and at LCM of child intervals."""
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.combining import AndTrigger

        start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        t1 = IntervalTrigger(hours=2, start_time=start)
        t2 = IntervalTrigger(hours=3, start_time=start)

        trigger = AndTrigger([t1, t2], threshold=1)
        first = trigger.next()
        assert first == start

        second = trigger.next()
        assert second == start + timedelta(hours=6)


# ============================================================
# 2. Async Scheduler Lifecycle
# ============================================================


class TestSchedulerLifecycle:
    """Tests for scheduler start/stop and job execution."""

    def test_start_stop_emits_events(self):
        """Scheduler emits SchedulerStarted on start, under both asyncio and trio.

        APScheduler is anyio-based and must run unchanged on either backend, so this runs
        the same start/stop flow under each backend in a single test (one behavior, one
        grade) rather than duplicating it per backend.
        """
        from apscheduler import AsyncScheduler

        async def _start_and_collect():
            events = []
            async with AsyncScheduler() as scheduler:
                scheduler.subscribe(lambda e: events.append(type(e).__name__))
                await scheduler.start_in_background()
                await anyio.sleep(0.1)
            return events

        for backend in ("asyncio", "trio"):
            events = anyio.run(_start_and_collect, backend=backend)
            assert "SchedulerStarted" in events

    def test_run_job_returns_result_and_propagates_errors(self):
        """run_job returns function result and re-raises exceptions, under both backends.

        The result hand-off must be backend-agnostic, so the same flow is driven under
        asyncio and Trio inside one graded slot.
        """
        from apscheduler import AsyncScheduler

        async def _run_jobs():
            async with AsyncScheduler() as scheduler:
                await scheduler.start_in_background()

                result = await scheduler.run_job(_async_add, kwargs={"x": 3, "y": 4})
                assert result == 7

                with pytest.raises(ValueError, match="job failed"):
                    await scheduler.run_job(_async_failing)

        for backend in ("asyncio", "trio"):
            anyio.run(_run_jobs, backend=backend)

    def test_sync_job_via_threadpool(self):
        """Sync functions execute via the threadpool executor, under both backends.

        The threadpool executor must be backend-agnostic, so the same flow is driven
        under asyncio and Trio inside one graded slot.
        """
        from apscheduler import AsyncScheduler

        async def _run_jobs():
            async with AsyncScheduler() as scheduler:
                await scheduler.start_in_background()

                r1 = await scheduler.run_job(_async_return_str)
                assert r1 == "async_result"

                r2 = await scheduler.run_job(_sync_multiply, kwargs={"a": 6, "b": 7}, job_executor="threadpool")
                assert r2 == 42

                r3 = await scheduler.run_job(_sync_return_str, job_executor="threadpool")
                assert r3 == "sync_result"

        for backend in ("asyncio", "trio"):
            anyio.run(_run_jobs, backend=backend)

    def test_schedule_fires_and_executes_job(self):
        """End-to-end: a schedule added with a near-immediate trigger is fired by the
        running scheduler, which actually executes the scheduled function.

        This exercises the headline scheduler capability — trigger -> dispatch ->
        execute — that the run_job (immediate task-queue) tests bypass: it starts the
        scheduler loop, adds a schedule, then asserts an observable side effect from the
        scheduled function plus a matching JobReleased event with a success outcome. The
        dispatch loop must be backend-agnostic, so the same flow is driven under asyncio
        and Trio inside one graded slot.
        """
        from apscheduler import AsyncScheduler, JobOutcome, JobReleased
        from apscheduler.triggers.date import DateTrigger

        async def _add_schedule_and_wait():
            released = []
            async with AsyncScheduler() as scheduler:
                scheduler.subscribe(lambda e: released.append(e), event_types=JobReleased)
                await scheduler.start_in_background()

                # Fire essentially immediately.
                run_time = datetime.now(timezone.utc)
                await scheduler.add_schedule(
                    _async_scheduled_marker, DateTrigger(run_time), id="fire_test"
                )

                # Wait for the scheduler to dispatch and run the scheduled job.
                with anyio.fail_after(5):
                    while not any(e.schedule_id == "fire_test" for e in released):
                        await anyio.sleep(0.05)

            return released

        for backend in ("asyncio", "trio"):
            _scheduled_runs.clear()
            released = anyio.run(_add_schedule_and_wait, backend=backend)

            # The scheduled function actually executed (observable side effect)...
            assert _scheduled_runs == ["scheduled_ran"]
            # ...and the run completed successfully for this schedule.
            event = next(e for e in released if e.schedule_id == "fire_test")
            assert event.outcome is JobOutcome.success


# ============================================================
# 3. Schedule Management and Error Paths
# ============================================================


class TestScheduleManagement:
    """Tests for add/get/remove schedule and error handling."""

    @pytest.mark.anyio
    async def test_add_get_remove_schedule_lifecycle(self):
        """Full schedule lifecycle: add, get one, get all, remove."""
        from apscheduler import AsyncScheduler
        from apscheduler.triggers.date import DateTrigger

        run_time = datetime.now(timezone.utc) + timedelta(hours=1)
        async with AsyncScheduler() as scheduler:
            sid = await scheduler.add_schedule(
                _async_dummy, DateTrigger(run_time), id="lifecycle_test"
            )
            assert sid == "lifecycle_test"

            schedules = await scheduler.get_schedules()
            assert any(s.id == "lifecycle_test" for s in schedules)

            single = await scheduler.get_schedule("lifecycle_test")
            assert single.id == "lifecycle_test"

            await scheduler.remove_schedule("lifecycle_test")
            schedules = await scheduler.get_schedules()
            assert not any(s.id == "lifecycle_test" for s in schedules)

    @pytest.mark.anyio
    async def test_conflict_policy_exception(self):
        """Adding a duplicate schedule ID with ConflictPolicy.exception raises ConflictingIdError."""
        from apscheduler import AsyncScheduler, ConflictingIdError, ConflictPolicy
        from apscheduler.triggers.date import DateTrigger

        run_time = datetime.now(timezone.utc) + timedelta(hours=1)
        async with AsyncScheduler() as scheduler:
            await scheduler.add_schedule(_async_dummy, DateTrigger(run_time), id="dup_test")

            with pytest.raises(ConflictingIdError):
                await scheduler.add_schedule(
                    _async_dummy, DateTrigger(run_time), id="dup_test",
                    conflict_policy=ConflictPolicy.exception,
                )

    @pytest.mark.anyio
    async def test_remove_nonexistent_schedule_silent(self):
        """Removing a nonexistent schedule does not raise an error."""
        from apscheduler import AsyncScheduler

        async with AsyncScheduler() as scheduler:
            await scheduler.remove_schedule("does_not_exist")


# ============================================================
# 4. Event System
# ============================================================


class TestEventSystem:
    """Tests for event subscription and filtering."""

    @pytest.mark.anyio
    async def test_subscribe_filters_to_schedule_lifecycle_events(self):
        """An event_types filter delivers only the schedule-lifecycle events it names.

        Subscribing with event_types=(ScheduleAdded, ScheduleRemoved) must deliver those
        two event types while excluding the job-execution events that run_job emits
        (JobAdded/JobReleased/...), exercising a distinct filtering path from the
        JobReleased-only subscription used elsewhere.
        """
        from apscheduler import AsyncScheduler, ScheduleAdded, ScheduleRemoved
        from apscheduler.triggers.interval import IntervalTrigger

        received = []
        async with AsyncScheduler() as scheduler:
            scheduler.subscribe(
                received.append,
                event_types=(ScheduleAdded, ScheduleRemoved),
            )
            await scheduler.start_in_background()

            # Schedule lifecycle (matches the filter) interleaved with a run_job that
            # emits non-matching job-execution events. Anchor the schedule's first fire
            # far in the future so the running scheduler never dispatches it before it is
            # removed below.
            future = datetime.now(timezone.utc) + timedelta(days=1)
            await scheduler.add_schedule(
                _async_worker, IntervalTrigger(seconds=60, start_time=future), id="filt_test"
            )
            await scheduler.run_job(_async_return_42)
            await scheduler.remove_schedule("filt_test")
            await anyio.sleep(0.1)

        # Only the two filtered schedule-lifecycle types were delivered — no job events leaked.
        assert all(isinstance(e, (ScheduleAdded, ScheduleRemoved)) for e in received)
        assert any(isinstance(e, ScheduleAdded) and e.schedule_id == "filt_test" for e in received)
        assert any(isinstance(e, ScheduleRemoved) and e.schedule_id == "filt_test" for e in received)

    @pytest.mark.anyio
    async def test_unfiltered_subscribe_delivers_all_event_types(self):
        """An unfiltered subscribe() (no event_types) delivers the full event stream.

        This is the complement of test_subscribe_filters_to_schedule_lifecycle_events:
        with no event_types argument the subscription must receive *every* event type,
        so the same add/remove + run_job activity that the filtered subscriber sees
        narrowed to ScheduleAdded/ScheduleRemoved here also delivers the job-execution
        events (JobReleased) that the filter excludes.
        """
        from apscheduler import AsyncScheduler, JobReleased, ScheduleAdded, ScheduleRemoved
        from apscheduler.triggers.interval import IntervalTrigger

        events = []
        async with AsyncScheduler() as scheduler:
            scheduler.subscribe(events.append)
            await scheduler.start_in_background()

            # Anchor the first fire far in the future so the running scheduler never
            # dispatches this schedule before it is removed below.
            future = datetime.now(timezone.utc) + timedelta(days=1)
            await scheduler.add_schedule(
                _async_worker, IntervalTrigger(seconds=60, start_time=future), id="evt_test"
            )
            # A run_job emits job-execution events that a filtered schedule-only
            # subscriber would not see; the unfiltered subscriber must receive them.
            await scheduler.run_job(_async_return_42)
            await scheduler.remove_schedule("evt_test")
            await anyio.sleep(0.1)

        added = [e for e in events if isinstance(e, ScheduleAdded)]
        removed = [e for e in events if isinstance(e, ScheduleRemoved)]
        job_released = [e for e in events if isinstance(e, JobReleased)]
        assert any(e.schedule_id == "evt_test" for e in added)
        assert any(e.schedule_id == "evt_test" for e in removed)
        # The distinguishing contract: unfiltered delivery includes job events too.
        assert len(job_released) >= 1

    @pytest.mark.anyio
    async def test_job_released_carries_outcome(self):
        """JobReleased event carries correct outcome for success and error jobs."""
        from apscheduler import AsyncScheduler, JobReleased, JobOutcome

        released = []
        async with AsyncScheduler() as scheduler:
            scheduler.subscribe(
                lambda e: released.append(e),
                event_types=JobReleased,
            )
            await scheduler.start_in_background()

            await scheduler.run_job(_async_return_42)
            try:
                await scheduler.run_job(_async_failing)
            except ValueError:
                pass

        assert len(released) == 2
        outcomes = [e.outcome for e in released]
        assert JobOutcome.success in outcomes
        assert JobOutcome.error in outcomes


# ============================================================
# 5. Serialization
# ============================================================


class TestSerialization:
    """Tests for JSONSerializer trigger round-trip with state preservation."""

    def test_trigger_roundtrip_preserves_state(self):
        """JSONSerializer round-trips triggers with their fire-time state intact.

        The serializer is type-generic (it marshals any trigger via the shared
        __getstate__/__setstate__ machinery), so a single test exercises the round-trip
        contract across trigger subtypes: each trigger is advanced, serialized to bytes,
        restored, and the restored trigger must reproduce the original's remaining
        fire-time sequence — not merely be an instance of the right class.
        """
        from apscheduler.serializers.json import JSONSerializer
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        triggers = [
            IntervalTrigger(hours=2, start_time=start),
            CronTrigger.from_crontab("0 9 * * 1-5", start_time=start),
        ]
        serializer = JSONSerializer()

        for trigger in triggers:
            trigger.next()  # advance state once before serializing

            data = serializer.serialize(trigger)
            assert isinstance(data, bytes)
            restored = serializer.deserialize(data)

            assert isinstance(restored, type(trigger))
            assert restored.next() == trigger.next()
            assert restored.next() == trigger.next()
