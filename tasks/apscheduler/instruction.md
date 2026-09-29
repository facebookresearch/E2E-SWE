# APScheduler v4 — Async-Native Job Scheduler

## Overview

Implement **APScheduler** (Advanced Python Scheduler) v4 — an async-first job scheduling library. The architecture: triggers determine when to fire, schedulers manage the lifecycle, data stores persist state, event brokers distribute events, and executors run jobs.

**Important**: This is v4 — a complete rewrite from v3. The API is entirely different from the v3 BackgroundScheduler. v4 is async-native, built on `anyio`. All async operations must work under both asyncio and Trio backends.

## Dependencies

The environment is **offline** and these packages are **already installed** — do not attempt to install anything:

- `anyio` — async compatibility layer (required)
- `attrs` — dataclass decorators with validators/converters
- `tenacity` — retry helper
- `tzlocal` — local timezone detection

The project must be installable offline by a `setup.sh` (the build backend is pre-installed), e.g. a `pyproject.toml` / `setup.py` installable with `pip install -e . --no-build-isolation`.

---

## 1. Triggers

All triggers are stateful iterators with a `next() -> datetime | None` method (no arguments). Each call advances internal state and returns the next fire time in chronological order.

**DateTrigger** (`apscheduler.triggers.date`): `DateTrigger(run_time)` — fires once at `run_time`, then returns None.

**IntervalTrigger** (`apscheduler.triggers.interval`): fires at regular intervals from a start time. Constructor takes keyword arguments for interval components (`weeks`, `days`, `hours`, `minutes`, `seconds`, `microseconds`) plus `start_time` and `end_time`. Multiple components compose additively. The first fire time is `start_time` itself; each subsequent call adds the composed interval (so the sequence is `start_time`, `start_time + interval`, `start_time + 2*interval`, ...). Returns None after `end_time`.

**CronTrigger** (`apscheduler.triggers.cron`): fires based on cron-like field matching. Constructor keyword arguments: `year`, `month`, `day`, `week`, `day_of_week`, `hour`, `minute`, `second`, `start_time`, `end_time`, `timezone`. Each cron field (`year`, `month`, `day`, `week`, `day_of_week`, `hour`, `minute`, `second`) accepts either an `int` (matching that single numeric value, e.g. `hour=9`) or a `str` cron expression, and defaults to `None` when omitted. Day-of-week uses Monday=0 convention and accepts lowercase English abbreviations (`mon`, `tue`, ..., `sun`). String cron fields support standard syntax: `*` (any), ranges (`1-5`), step values (`*/5`), and comma-separated lists. Class method `from_crontab(expr, *, start_time, end_time, timezone)` parses a standard 5-field crontab string (minute hour day month day_of_week). In `from_crontab`, interpret `day_of_week` using the same Monday=0 convention as the constructor.

**CalendarIntervalTrigger** (`apscheduler.triggers.calendarinterval`): calendar-aware intervals, always firing at the same wall-clock time of day. Constructor takes `years`, `months`, `weeks`, `days` keyword arguments plus `start_date`, the time-of-day fields `hour`, `minute`, `second`, and a `timezone`. The fire time of day is taken from `hour`/`minute`/`second` (each defaulting to 0, i.e. midnight `00:00:00`) interpreted in `timezone` (defaults to the local timezone). To compute the next date, `years` and `months` are added first while keeping the day-of-month constant; if the result is an invalid date (e.g. the 31st in a 30-day month, or Feb 29 in a non-leap year), that occurrence is **skipped** (advance another interval) rather than clamped to the month's last day. `weeks` and `days` are then added to the resulting date, and the date is combined with the configured time of day.

**OrTrigger** (`apscheduler.triggers.combining`): `OrTrigger(triggers)` — given a list of child triggers, fires at every fire time from any child, merging them in chronological order.

**AndTrigger** (`apscheduler.triggers.combining`): `AndTrigger(triggers, threshold, max_iterations)` — fires only when all triggers agree within `threshold` seconds (`threshold` defaults to 1). `max_iterations` is an optional keyword argument bounding the search for an agreement and defaults to 10000.

---

## 2. AsyncScheduler

`apscheduler.AsyncScheduler` — the main scheduler, used as an async context manager. Defaults to in-memory data store and local event broker.

Key methods:
- `run_job(func, *, args, kwargs, job_executor)` — execute and wait for result. Re-raises job exceptions. Sync functions run in a threadpool when `job_executor="threadpool"`.
- `add_schedule(func, trigger, *, id, args, kwargs, coalesce, conflict_policy)` → schedule_id. `conflict_policy` controls duplicate ID behavior: `ConflictPolicy.exception` (raises `ConflictingIdError`), `.replace`, or `.do_nothing`.
- `get_schedule(id)` → schedule object (raises `ScheduleLookupError` if not found)
- `get_schedules()` → list of all schedules
- `remove_schedule(id)` — silently succeeds if the ID does not exist
- `add_job(func, *, args, kwargs, result_expiration_time)` → UUID
- `subscribe(callback, event_types, *, one_shot)` → Subscription. `event_types` accepts a single event type class or an iterable of them (or None for all events). Subscriptions are forward-looking: a callback receives only events emitted *after* it is registered (past events are not replayed).
- `start_in_background()` — starts scheduler loop in background task

Entering the `async with AsyncScheduler()` context initializes the scheduler but does **not** start its loop; the loop starts only when `start_in_background()` is called. The `SchedulerStarted` event is emitted at that start transition (when `start_in_background()` brings the scheduler to the running state), so a subscriber registered after context entry but before `start_in_background()` still receives `SchedulerStarted`. Correspondingly, `SchedulerStopped` is emitted when the scheduler stops (on context exit).

**Job functions must be top-level** (importable by reference) — not lambdas or nested functions.

---

## 3. Data Stores and Event Brokers

`apscheduler.datastores.memory.MemoryDataStore` — in-memory storage, no external deps.

`apscheduler.eventbrokers.local.LocalEventBroker` — local event distribution.

---

## 4. Events

Event classes importable from `apscheduler`: `SchedulerStarted`, `SchedulerStopped`, `ScheduleAdded`, `ScheduleUpdated`, `ScheduleRemoved`, `JobAdded`, `JobReleased`, `TaskAdded`, `TaskUpdated`, `TaskRemoved`.

The schedule-lifecycle events (`ScheduleAdded`, `ScheduleUpdated`, `ScheduleRemoved`) each carry the affected schedule's id as `.schedule_id` (the same attribute name `JobReleased` uses, not the schedule object's `.id`).

`JobReleased` carries `.outcome` (a `JobOutcome` enum value — `success` or `error`), `.job_id`, `.task_id`, and `.schedule_id` (the id of the schedule that produced the job, or `None` when the job did not originate from a schedule).

---

## 5. Serialization

`apscheduler.serializers.json.JSONSerializer` — round-trips triggers and other scheduler objects through JSON. `.serialize(obj)` → bytes, `.deserialize(data)` → object. Triggers must survive serialization with their state intact (a deserialized trigger produces the same next fire time as the original).

---

## 6. Enums and Exceptions

Enums importable from `apscheduler`: `JobOutcome` (success, error, missed_start_deadline, cancelled), `CoalescePolicy` (earliest, latest, all), `ConflictPolicy` (replace, do_nothing, exception), `SchedulerRole`.

Exceptions importable from `apscheduler`: `ConflictingIdError`, `JobLookupError`, `ScheduleLookupError`, `TaskLookupError`.

---

## 7. setup.sh

```bash
pip install -e . --no-build-isolation
```
