"""
Tests for huey — a lightweight Python task queue with multi-backend support.
Tests exercise the user-facing API through MemoryHuey, SqliteHuey, and
RedisHuey backends with complex integration scenarios composing multiple features.
"""
import datetime
import os
import tempfile
import threading
import time
import unittest


# ---------------------------------------------------------------------------
# Helper: manual dequeue + execute (the pattern used by huey's own tests)
# ---------------------------------------------------------------------------
def execute_next(huey, timestamp=None):
    """Dequeue the next task and execute it, returning the result value."""
    task = huey.dequeue()
    assert task is not None, "Expected a task in the queue but found none"
    return huey.execute(task, timestamp=timestamp)


# ===========================================================================
# 1. Core workflow integration — enqueue, execute, result store lifecycle
# ===========================================================================
class TestCoreWorkflow(unittest.TestCase):
    """Full enqueue -> dequeue -> execute -> result lifecycle with state tracking."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_full_task_lifecycle_with_store_none(self):
        """Enqueue a task, verify queue/result counts at each stage, execute,
        read result (which removes it), verify final state, and test store_none
        behavior for None results."""
        @self.huey.task()
        def add(a, b):
            return a + b

        # Enqueue and verify state
        result = add(3, 4)
        self.assertEqual(len(self.huey), 1)
        self.assertEqual(self.huey.result_count(), 0)

        # Dequeue and verify IDs match
        task = self.huey.dequeue()
        self.assertEqual(len(self.huey), 0)
        self.assertEqual(result.id, task.id)
        self.assertIsNone(result.get())  # Not executed yet

        # Execute and consume result
        self.assertEqual(self.huey.execute(task), 7)
        self.assertEqual(self.huey.result_count(), 1)
        self.assertEqual(result.get(), 7)
        self.assertEqual(self.huey.result_count(), 0)  # Consumed

        # None results: by default not stored
        @self.huey.task()
        def return_none():
            return None

        r_none = return_none()
        execute_next(self.huey)
        self.assertEqual(self.huey.result_count(), 0)

        # Enable store_none
        self.huey.store_none = True
        r_none2 = return_none()
        execute_next(self.huey)
        self.assertEqual(self.huey.result_count(), 1)
        self.assertIsNone(r_none2())
        self.assertEqual(self.huey.result_count(), 0)  # consumed

    def test_multiple_huey_instances_with_flush(self):
        """Two independent Huey instances have separate queues and registries.
        Also tests flush(), pending(), and queue state inspection."""
        from huey import MemoryHuey
        huey1 = self.huey
        huey2 = MemoryHuey('huey2', utc=False)

        @huey1.task()
        def task_a(n):
            return n + 1

        task_a2 = huey2.task(retries=1)(task_a)

        r = task_a(1)
        self.assertEqual(len(huey1), 1)
        self.assertEqual(len(huey2), 0)
        self.assertEqual(huey1.pending_count(), 1)

        pending = huey1.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, r.id)

        self.assertEqual(execute_next(huey1), 2)
        self.assertEqual(r.get(), 2)

        r2 = task_a2(2)
        self.assertEqual(len(huey1), 0)
        self.assertEqual(len(huey2), 1)
        self.assertEqual(huey2.execute(huey2.dequeue()), 3)
        self.assertEqual(r2.get(), 3)

        # flush clears all
        task_a(10)
        task_a(20)
        self.assertEqual(len(huey1), 2)
        huey1.flush()
        self.assertEqual(len(huey1), 0)


# ===========================================================================
# 2. Immediate mode — complex scenarios
# ===========================================================================
class TestImmediateMode(unittest.TestCase):
    """Immediate mode: sync execution, pipelines, revoke/restore, mode swapping."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(immediate=True, utc=False)

    def test_immediate_pipeline_and_map(self):
        """Pipelines and map() execute synchronously end-to-end in immediate mode."""
        @self.huey.task()
        def add(a, b):
            return a + b

        # Pipeline
        p = add.s(3, 4).then(add, 5).then(add, 6).then(add, 7)
        result_group = self.huey.enqueue(p)
        self.assertEqual(result_group(), [7, 12, 18, 25])

        # map
        @self.huey.task()
        def inc(n):
            return n + 1

        rg = inc.map(range(5))
        self.assertEqual(rg(), [1, 2, 3, 4, 5])

    def test_immediate_revoke_restore_and_swap(self):
        """Revoke/restore in immediate mode, and toggling huey.immediate
        switches between sync and async modes while preserving task registration."""
        @self.huey.task()
        def inc(n):
            return n + 1

        # Revoke
        inc.revoke()
        r = inc(3)
        self.assertEqual(len(self.huey), 0)
        self.assertIsNone(r.get())

        # Restore (the re-execution below proves restore took effect)
        inc.restore()
        r = inc(4)
        self.assertEqual(r.get(), 5)

        # Toggle to non-immediate
        self.huey.immediate = False
        r = inc(2)
        self.assertEqual(len(self.huey), 1)
        self.assertEqual(execute_next(self.huey), 3)
        self.assertEqual(r.get(), 3)

        # Toggle back to immediate
        self.huey.immediate = True
        r = inc(3)
        self.assertEqual(r.get(), 4)
        self.assertEqual(len(self.huey), 0)

    def test_immediate_scheduling_and_error(self):
        """In immediate mode, scheduled tasks go to the schedule instead of
        executing immediately. Task errors are stored as TaskException."""
        from huey.exceptions import TaskException

        @self.huey.task()
        def inc(n):
            return n + 1

        # Scheduled task goes to schedule
        r = inc.schedule((3,), delay=10)
        self.assertEqual(len(self.huey), 0)
        self.assertEqual(self.huey.result_count(), 0)
        self.assertEqual(self.huey.scheduled_count(), 1)
        self.assertIsNone(r.get())

        # Error stored as TaskException
        @self.huey.task()
        def fail(n):
            return n + "string"

        r_err = fail(1)
        with self.assertRaises(TaskException):
            r_err.get()


# ===========================================================================
# 3. Scheduling + expiration integration
# ===========================================================================
class TestSchedulingAndExpiration(unittest.TestCase):
    """Complex scheduling scenarios with delay, eta, expiration, read_schedule."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_schedule_lifecycle_and_read_schedule(self):
        """Schedule tasks with delay/eta, verify ready_to_run, read_schedule
        timestamp ordering (destructive read), and scheduled state transitions."""
        @self.huey.task()
        def task_a(n):
            return n

        # Schedule with delay — not immediately ready
        r = task_a.schedule((3,), delay=60)
        self.assertEqual(len(self.huey), 1)
        task = self.huey.dequeue()
        self.assertFalse(self.huey.ready_to_run(task))

        # Execute sends to schedule since not ready
        value = self.huey.execute(task)
        self.assertIsNone(value)
        self.assertEqual(self.huey.scheduled_count(), 1)

        # Verify scheduled list
        sched = self.huey.scheduled()
        self.assertEqual(len(sched), 1)
        self.assertEqual(sched[0].id, task.id)

        # Verify it becomes ready with future timestamp
        future = datetime.datetime.now() + datetime.timedelta(seconds=60)
        self.assertTrue(self.huey.ready_to_run(task, future))

        # Schedule with past eta runs immediately
        past = datetime.datetime(2000, 1, 1)
        r2 = task_a.schedule((4,), eta=past)
        t2 = self.huey.dequeue()
        self.assertTrue(self.huey.ready_to_run(t2))
        self.assertEqual(self.huey.execute(t2), 4)
        self.assertEqual(r2.get(), 4)

        # Test read_schedule timestamp ordering (destructive)
        server_time = datetime.datetime(2000, 1, 1)
        timestamp = datetime.datetime(2000, 1, 2, 3, 4, 5)
        second = datetime.timedelta(seconds=1)

        rn1 = task_a.schedule(-1, eta=(timestamp - second))
        r0 = task_a.schedule(0, eta=timestamp)
        rp1 = task_a.schedule(1, eta=(timestamp + second))

        for _ in range(3):
            self.huey.execute(self.huey.dequeue(), timestamp=server_time)

        # Note: first schedule from earlier is still in there too
        total_scheduled = self.huey.scheduled_count()
        self.assertEqual(total_scheduled, 4)  # 1 from earlier + 3 new

        # read_schedule at timestamp returns tasks with eta <= timestamp
        tasks = self.huey.read_schedule(timestamp)
        # Should contain rn1, r0, and the earlier scheduled task (past eta)
        ids = [t.id for t in tasks]
        self.assertIn(rn1.id, ids)
        self.assertIn(r0.id, ids)
        self.assertEqual(self.huey.read_schedule(timestamp), [])  # destructive

        # Last one readable with later timestamp
        tasks_late = self.huey.read_schedule(datetime.datetime(2010, 1, 1))
        self.assertEqual(len(tasks_late), 1)  # rp1 only

    def test_task_expiration_with_scheduling(self):
        """Tasks with relative (seconds) and absolute expiration are skipped
        when executed after their expiry window. Expiration survives schedule
        round-trips."""
        now = datetime.datetime.now()
        seconds = lambda s: now + datetime.timedelta(seconds=s)
        state = []

        @self.huey.task(context=True, expires=10)
        def task_r(task=None):
            state.append(task.id)
            return True

        # Execute within 10s window — succeeds
        r1 = task_r()
        self.assertTrue(execute_next(self.huey, timestamp=seconds(1)))
        self.assertEqual(len(state), 1)

        # Execute after 10s expiry — skipped
        r2 = task_r()
        task = self.huey.dequeue()
        self.huey.execute(task, seconds(12))
        self.assertEqual(len(state), 1)  # not executed

        # Re-execute within window — succeeds
        self.huey.execute(task, seconds(5))
        self.assertEqual(len(state), 2)

        # Override expires at call time
        state.clear()
        r3 = task_r(expires=60)
        task = self.huey.dequeue()
        self.huey.execute(task, seconds(63))  # expired
        self.assertEqual(len(state), 0)
        self.huey.execute(task, seconds(50))  # within window
        self.assertEqual(len(state), 1)

        # Expiration survives schedule round-trip
        state.clear()
        @self.huey.task()
        def task_b(n):
            state.append(n)
            return n + 1

        result = task_b.schedule((3,), eta=seconds(60), expires=300)
        self.assertEqual(len(self.huey), 1)
        execute_next(self.huey)  # goes to schedule
        self.assertEqual(self.huey.scheduled_count(), 1)
        tasks = self.huey.read_schedule(timestamp=seconds(60))
        self.assertEqual(len(tasks), 1)
        self.huey.enqueue(tasks[0])
        task = self.huey.dequeue()
        self.assertEqual(self.huey.execute(task, seconds(60)), 4)
        self.assertEqual(state, [3])


# ===========================================================================
# 4. Revocation integration — complex revoke/restore scenarios
# ===========================================================================
class TestRevocationIntegration(unittest.TestCase):
    """Complex revocation scenarios: class-level, instance-level, persistent,
    revoke_until, revoke_by_id, interaction with execution."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_class_and_instance_revocation(self):
        """Class-level revoke blocks all instances; instance-level revoke_once
        is consumed after first skip; persistent instance revocation survives
        re-enqueue."""
        state = {}

        @self.huey.task()
        def track(n):
            state[n] = n
            return n + 1

        # Class-level revoke
        track.revoke()
        self.assertTrue(track.is_revoked())
        r1, r2, r3 = track(1), track(2), track(3)
        for r in (r1, r2, r3):
            self.assertTrue(r.is_revoked())

        t1 = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(t1))
        self.assertIsNone(r1.get())
        self.assertEqual(state, {})

        # Restore, remaining tasks execute (is_revoked + re-execution prove it)
        track.restore()
        self.assertFalse(track.is_revoked())
        t2 = self.huey.dequeue()  # r2
        self.huey.execute(t2)
        t3 = self.huey.dequeue()  # r3
        self.assertEqual(self.huey.execute(t3), 4)
        self.assertEqual(r3.get(), 4)
        self.assertEqual(state, {2: 2, 3: 3})

        # Instance revoke_once consumed
        state.clear()
        r4 = track(10)
        r5 = track(20)
        r4.revoke()  # default revoke_once=True

        t4 = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(t4))
        self.assertFalse(r4.is_revoked())  # consumed

        # Drain r5
        execute_next(self.huey)

        # Re-enqueue: now executes
        self.huey.enqueue(t4)
        self.assertEqual(execute_next(self.huey), 11)

        # Persistent instance revocation
        r6 = track(30)
        r6.revoke(revoke_once=False)
        t6 = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(t6))
        self.assertTrue(r6.is_revoked())  # still revoked

        # Re-enqueue: still revoked
        self.huey.enqueue(t6)
        self.assertIsNone(execute_next(self.huey))

    def test_revoke_until_and_by_id(self):
        """revoke_until revokes tasks before a cutoff timestamp. revoke_by_id
        and restore_by_id for selective instance control."""
        @self.huey.task()
        def inc(n):
            return n + 1

        # revoke_until
        timestamp = datetime.datetime(2000, 1, 1)
        second = datetime.timedelta(seconds=1)
        inc.revoke(revoke_until=timestamp)

        r1, r2, r3 = [inc(i) for i in (1, 2, 3)]
        for delta in (-second, datetime.timedelta(0), second):
            task = self.huey.dequeue()
            self.huey.execute(task, timestamp + delta)

        self.assertIsNone(r1())
        self.assertEqual(r2(), 3)
        self.assertEqual(r3(), 4)

        # revoke_by_id
        state = []

        @self.huey.task()
        def track(n):
            state.append(n)
            return n

        r_a, r_b, r_c = [track(i) for i in (1, 2, 3)]
        for r in (r_a, r_b, r_c):
            self.huey.revoke_by_id(r.id)
            self.assertTrue(r.is_revoked())

        self.huey.restore_by_id(r_b.id)

        for _ in range(3):
            execute_next(self.huey)

        self.assertEqual(state, [2])
        self.assertEqual(r_b(), 2)
        self.assertIsNone(r_a())
        self.assertIsNone(r_c())


# ===========================================================================
# 5. Retry integration — complex retry scenarios
# ===========================================================================
class TestRetryIntegration(unittest.TestCase):
    """Retry workflows: retry-to-success, retry delays, CancelExecution
    interaction with retries, RetryTask explicit triggering."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_retry_to_success_with_delay(self):
        """Task fails twice, succeeds on third attempt. With retry_delay,
        failed retries go to the schedule rather than queue."""
        # retry to success
        state = [0]

        @self.huey.task(retries=2)
        def eventually_works():
            state[0] += 1
            if state[0] != 3:
                raise ValueError('not yet')
            return 1337

        r = eventually_works()
        self.assertIsNone(execute_next(self.huey))
        self.assertIsNone(execute_next(self.huey))
        self.assertEqual(execute_next(self.huey), 1337)
        self.assertEqual(r.get(), 1337)
        self.assertEqual(len(self.huey), 0)

        # retry_delay sends to schedule
        from huey.exceptions import TaskException

        @self.huey.task(retries=2, retry_delay=60)
        def always_fail():
            raise ValueError('try again')

        r2 = always_fail()
        self.assertIsNone(execute_next(self.huey))
        self.assertRaises(TaskException, r2.get)

        self.assertEqual(len(self.huey), 0)
        self.assertEqual(self.huey.scheduled_count(), 1)
        sched = self.huey.scheduled()
        self.assertFalse(self.huey.ready_to_run(sched[0]))
        dt = datetime.datetime.now() + datetime.timedelta(seconds=61)
        self.assertTrue(self.huey.ready_to_run(sched[0], dt))

    def test_cancel_execution_and_retry_task(self):
        """CancelExecution with retry=False suppresses retries. RetryTask
        explicitly retries without decrementing retry count. Result.reset()
        clears cached error."""
        from huey.exceptions import CancelExecution, RetryTask, TaskException

        @self.huey.task(retries=2)
        def task_cancel(retry_val=None):
            raise CancelExecution(retry=retry_val)

        # retry=False suppresses
        r = task_cancel(False)
        self.assertIsNone(execute_next(self.huey))
        self.assertRaises(TaskException, r.get)
        self.assertEqual(len(self.huey), 0)

        # retry=None uses task's retries
        r2 = task_cancel()
        for i in range(3):
            self.assertIsNone(execute_next(self.huey))
            self.assertRaises(TaskException, r2.get)
            r2.reset()
        self.assertEqual(len(self.huey), 0)

        # RetryTask without decrementing
        state = [0]

        @self.huey.task()
        def task_retry(n):
            state[0] += n
            if state[0] < 2:
                raise RetryTask('retry')
            return state[0]

        r3 = task_retry(1)
        self.assertIsNone(execute_next(self.huey))
        self.assertRaises(TaskException, r3.get)
        self.assertEqual(state, [1])
        self.assertEqual(len(self.huey), 1)

        self.assertEqual(execute_next(self.huey), 2)
        r3.reset()
        self.assertEqual(r3.get(), 2)


# ===========================================================================
# 6. Task locking integration
# ===========================================================================
class TestTaskLocking(unittest.TestCase):
    """Task locking: decorator, context manager, lock interaction with retries,
    flush_locks."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_lock_retry_and_flush(self):
        """A locked task that fails due to lock is retried when retries are
        configured, and succeeds after lock is released. flush_locks()
        releases held locks so tasks can proceed."""
        @self.huey.task(retries=1)
        @self.huey.lock_task('lock_a')
        def exclusive(n):
            return n + 1

        # Normal execution works
        exclusive(3)
        self.assertEqual(execute_next(self.huey), 4)

        # Hold the lock externally, task fails due to lock
        r = exclusive(5)
        with self.huey.lock_task('lock_a'):
            self.assertIsNone(execute_next(self.huey))

        # Lock released, retry succeeds
        self.assertEqual(execute_next(self.huey), 6)

        # flush_locks test
        @self.huey.task()
        @self.huey.lock_task("fl-lock")
        def locked_task(n):
            return n

        lock = self.huey.lock_task("fl-lock")
        lock.__enter__()

        locked_task(1)
        self.assertIsNone(execute_next(self.huey))

        self.huey.flush_locks()

        locked_task(2)
        self.assertEqual(execute_next(self.huey), 2)


# ===========================================================================
# 7. Pipeline integration — complex chaining, errors, revocations
# ===========================================================================
class TestPipelineIntegration(unittest.TestCase):
    """Complex pipeline scenarios: multi-step, error propagation, revocation
    mid-pipeline, error callbacks, tuple unpacking."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_pipeline_arithmetic_and_tuple_unpacking(self):
        """Multi-step pipeline passing results through arithmetic operations.
        Pipeline where tasks return tuples that are unpacked as args."""
        @self.huey.task()
        def add(a, b):
            return a + b

        @self.huey.task()
        def mul(a, b):
            return a * b

        pipe = add.s(1, 2).then(mul, 4).then(add, -5).then(mul, 3).then(add, 8)
        results = self.huey.enqueue(pipe)
        for _ in range(len(results)):
            self.assertEqual(len(self.huey), 1)
            execute_next(self.huey)
        self.assertEqual(len(self.huey), 0)
        self.assertEqual([r() for r in results], [3, 12, 7, 21, 29])

        # Tuple unpacking in pipeline
        @self.huey.task()
        def fib(a, b=1):
            a, b = a + b, a
            return a, b

        pipe2 = fib.s(1).then(fib).then(fib).then(fib)
        results2 = self.huey.enqueue(pipe2)
        for _ in range(4):
            execute_next(self.huey)
        self.assertEqual([r() for r in results2], [(2, 1), (3, 2), (5, 3), (8, 5)])

    def test_pipeline_error_and_revoke(self):
        """When a pipeline step errors, subsequent steps are not enqueued.
        Revoking a mid-pipeline task stops the chain at that point."""
        from huey.exceptions import TaskException

        @self.huey.task()
        def decrement(n):
            if n < 0:
                raise ValueError('below zero')
            return n - 1

        # Error stops propagation
        pipe = decrement.s(1).then(decrement).then(decrement).then(decrement)
        r1, r2, r3, r4 = self.huey.enqueue(pipe)
        self.assertEqual(execute_next(self.huey), 0)
        self.assertEqual(execute_next(self.huey), -1)
        self.assertIsNone(execute_next(self.huey))
        self.assertRaises(TaskException, r3.get)
        self.assertEqual(len(self.huey), 0)  # r4 never enqueued

        # Revoke mid-pipeline
        @self.huey.task()
        def inc(n):
            return n + 1

        pipe2 = inc.s(1).then(inc).then(inc).then(inc)
        r1, r2, r3, r4 = self.huey.enqueue(pipe2)
        r3.revoke()
        self.assertEqual(execute_next(self.huey), 2)
        self.assertEqual(execute_next(self.huey), 3)
        self.assertTrue(r3.is_revoked())
        self.assertIsNone(execute_next(self.huey))
        self.assertEqual(len(self.huey), 0)

    def test_error_callback_chains(self):
        """Error callback is enqueued when task fails, receives the exception.
        Error handler that itself fails triggers the next error handler in a
        chain: task.error(h1).error(h2)."""
        from huey.exceptions import TaskException
        state1, state2 = [], []

        @self.huey.task()
        def fail_task():
            raise ValueError('primary failure')

        @self.huey.task()
        def err_handler1(err):
            state1.append(repr(err))
            raise ValueError('handler1 also fails')

        @self.huey.task()
        def err_handler2(err):
            state2.append(repr(err))
            return 'recovered'

        task = fail_task.s().error(err_handler1).error(err_handler2)
        result = self.huey.enqueue(task)

        # Primary task fails
        self.assertIsNone(execute_next(self.huey))
        self.assertRaises(TaskException, result.get)

        # err_handler1 runs and also fails
        self.assertEqual(len(self.huey), 1)
        execute_next(self.huey)
        self.assertEqual(len(state1), 1)

        # err_handler2 runs and succeeds
        self.assertEqual(len(self.huey), 1)
        self.assertEqual(execute_next(self.huey), 'recovered')
        self.assertEqual(len(state2), 1)


# ===========================================================================
# 8. Task priority
# ===========================================================================
class TestTaskPriority(unittest.TestCase):
    """Priority ordering, runtime override, and reschedule with priority."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_priority_ordering_and_override(self):
        """Higher priority tasks are dequeued first. Priority set at call time
        overrides the task default."""
        @self.huey.task()
        def identity(n):
            return n

        identity(1, priority=1)
        identity(3, priority=3)
        identity(2, priority=2)

        results = [execute_next(self.huey) for _ in range(3)]
        self.assertEqual(results, [3, 2, 1])

        # Override at call time
        @self.huey.task(priority=10)
        def low(n):
            return n

        @self.huey.task(priority=1)
        def high(n):
            return n

        low(1)
        high(2, priority=100)
        self.assertEqual(execute_next(self.huey), 2)
        self.assertEqual(execute_next(self.huey), 1)

    def test_reschedule_with_priority(self):
        """Rescheduling can override the priority. The rescheduled task
        (priority=99) is dequeued before the original (priority=10).
        Rescheduling revokes the original and creates a new task with a new ID."""
        state = []

        @self.huey.task(context=True)
        def track(task=None):
            state.append(task.id)
            return True

        res = track(priority=10)
        res2 = res.reschedule(priority=99)
        self.assertEqual(len(self.huey), 2)
        self.assertNotEqual(res.id, res2.id)

        # Higher priority (rescheduled) dequeued first
        self.assertTrue(execute_next(self.huey))
        self.assertTrue(res.is_revoked())
        self.assertIsNone(execute_next(self.huey))  # original revoked
        self.assertEqual(state, [res2.id])


# ===========================================================================
# 9. Crontab — all patterns and edge cases
# ===========================================================================
class TestCrontab(unittest.TestCase):
    """crontab() validation of all pattern types and edge cases."""

    def test_crontab_patterns_and_validation(self):
        """Comprehensive crontab: specific date/time, day_of_week (0=Sunday,
        7=Sunday alias), ranges, steps, comma-separated values, strict mode,
        invalid values, convenience helpers."""
        from huey import crontab

        dt = datetime.datetime(2024, 3, 15, 14, 30)  # Friday

        # All fields combined
        validate = crontab(minute='30', hour='14', day='15', month='3',
                           day_of_week='5')
        self.assertTrue(validate(dt))
        self.assertFalse(validate(dt.replace(minute=31)))
        self.assertFalse(validate(dt.replace(hour=15)))

        # day_of_week: 0=Sunday, 5=Friday, 7=Sunday alias
        friday = crontab(day_of_week='5')
        self.assertTrue(friday(dt))
        sunday = datetime.datetime(2024, 3, 17, 12, 0)
        self.assertTrue(crontab(day_of_week='0')(sunday))
        self.assertTrue(crontab(day_of_week='7')(sunday))

        # Invalid crontab raises ValueError
        with self.assertRaises(ValueError):
            crontab(minute='61')
        with self.assertRaises(ValueError):
            crontab(day_of_week='*/2')

        # strict mode
        with self.assertRaises(ValueError):
            crontab(minute='bad', strict=True)

        # Comma-separated
        validate_comma = crontab(minute='0,15,30,45')
        self.assertTrue(validate_comma(datetime.datetime(2024, 1, 1, 0, 0)))
        self.assertTrue(validate_comma(datetime.datetime(2024, 1, 1, 0, 30)))
        self.assertFalse(validate_comma(datetime.datetime(2024, 1, 1, 0, 10)))

        # Range
        validate_range = crontab(hour='9-17')
        self.assertTrue(validate_range(datetime.datetime(2024, 1, 1, 9, 0)))
        self.assertTrue(validate_range(datetime.datetime(2024, 1, 1, 17, 0)))
        self.assertFalse(validate_range(datetime.datetime(2024, 1, 1, 18, 0)))

        # Step
        validate_step = crontab(minute='*/15')
        self.assertTrue(validate_step(datetime.datetime(2024, 1, 1, 0, 0)))
        self.assertTrue(validate_step(datetime.datetime(2024, 1, 1, 0, 45)))
        self.assertFalse(validate_step(datetime.datetime(2024, 1, 1, 0, 10)))

        # Integer input
        validate_int = crontab(minute=30, hour=14)
        self.assertTrue(validate_int(datetime.datetime(2024, 3, 15, 14, 30)))
        self.assertFalse(validate_int(datetime.datetime(2024, 3, 15, 14, 31)))


# ===========================================================================
# 10. Periodic tasks — registration, matching, revocation, dynamic
# ===========================================================================
class TestPeriodicTasks(unittest.TestCase):
    """Periodic task registration, read_periodic matching, revocation,
    and dynamic registration at runtime."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_periodic_lifecycle(self):
        """read_periodic returns matching tasks. Periodic tasks can be revoked
        and restored. Tasks can register periodic tasks dynamically."""
        from huey import crontab

        @self.huey.periodic_task(crontab(minute='*/15', hour='9-17'))
        def work():
            pass

        @self.huey.periodic_task(crontab(minute='0', hour='21'))
        def sleep_task():
            pass

        @self.huey.periodic_task(crontab(minute='0-30'))
        def first_half():
            pass

        def names_at(hour, minute):
            dt = datetime.datetime(2000, 1, 1, hour, minute)
            return sorted([t.name for t in self.huey.read_periodic(dt)])

        self.assertEqual(names_at(0, 0), ['first_half'])
        self.assertEqual(names_at(23, 59), [])
        self.assertEqual(names_at(9, 0), sorted(['work', 'first_half']))
        self.assertEqual(names_at(9, 45), ['work'])
        self.assertEqual(names_at(21, 0), sorted(['first_half', 'sleep_task']))

        # Revoke periodic task
        state = [0]

        @self.huey.periodic_task(crontab(minute='0'))
        def task_p():
            state[0] += 1

        task_p.revoke()
        self.assertTrue(task_p.is_revoked())
        r = task_p()
        execute_next(self.huey)
        self.assertIsNone(r())
        self.assertEqual(state, [0])

        task_p.restore()
        self.assertFalse(task_p.is_revoked())

    def test_dynamic_periodic_registration(self):
        """Tasks created at runtime via periodic_task are discovered by
        read_periodic."""
        from huey import crontab

        def ptask():
            pass

        @self.huey.task()
        def make_periodic(every_n):
            name = 'ptask_%s' % every_n
            sched = crontab('*/%s' % every_n)
            self.huey.periodic_task(sched, name=name)(ptask)

        make_periodic(5)
        make_periodic(10)

        dt = datetime.datetime(2019, 1, 1, 0, 0)
        self.assertEqual(self.huey.read_periodic(dt), [])

        execute_next(self.huey)
        execute_next(self.huey)

        tasks = self.huey.read_periodic(dt)
        self.assertEqual(sorted([t.name for t in tasks]),
                         ['ptask_10', 'ptask_5'])

        tasks5 = self.huey.read_periodic(datetime.datetime(2019, 1, 1, 0, 5))
        self.assertEqual(len(tasks5), 1)
        self.assertEqual(tasks5[0].name, 'ptask_5')


# ===========================================================================
# 11. Signal integration — lifecycle signals for complex scenarios
# ===========================================================================
class TestSignalIntegration(unittest.TestCase):
    """Signal system: lifecycle tracking for success, error, retry, lock,
    revoke, expire, disconnect, and specific signal filtering."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_signal_lifecycle_and_disconnect(self):
        """Track all signals emitted during successful execution, error+retry
        scenarios, locked tasks, revoked tasks. Disconnect removes handler.
        Specific signal handlers only receive their signals."""
        from huey.signals import (SIGNAL_ENQUEUED, SIGNAL_EXECUTING,
                                  SIGNAL_COMPLETE, SIGNAL_ERROR,
                                  SIGNAL_RETRYING, SIGNAL_LOCKED,
                                  SIGNAL_REVOKED)
        signals_log = []

        @self.huey.signal()
        def handler(signal, task, *args):
            signals_log.append(signal)

        @self.huey.task()
        def inc(n):
            return n + 1

        # Successful lifecycle
        r = inc(1)
        self.assertIn(SIGNAL_ENQUEUED, signals_log)
        execute_next(self.huey)
        self.assertIn(SIGNAL_EXECUTING, signals_log)
        self.assertIn(SIGNAL_COMPLETE, signals_log)

        # Error + retry
        @self.huey.task(retries=1)
        def fail():
            raise ValueError('oops')

        fail()
        signals_log.clear()
        execute_next(self.huey)
        self.assertIn(SIGNAL_EXECUTING, signals_log)
        self.assertIn(SIGNAL_ERROR, signals_log)
        self.assertIn(SIGNAL_RETRYING, signals_log)
        # Drain retry
        execute_next(self.huey)

        # Locked signal
        @self.huey.task()
        @self.huey.lock_task('sig-lock')
        def exclusive():
            return True

        exclusive()
        signals_log.clear()
        with self.huey.lock_task('sig-lock'):
            execute_next(self.huey)
        self.assertIn(SIGNAL_LOCKED, signals_log)

        # Revoked signal
        r2 = inc(1)
        r2.revoke()
        signals_log.clear()
        execute_next(self.huey)
        self.assertIn(SIGNAL_REVOKED, signals_log)

        # Disconnect
        count_before = len(signals_log)
        self.huey.disconnect_signal(handler)
        inc(2)
        execute_next(self.huey)
        self.assertEqual(len(signals_log), count_before)

        # Specific signal handler
        complete_log = []

        @self.huey.signal(SIGNAL_COMPLETE)
        def on_complete(signal, task):
            complete_log.append(task.id)

        r3 = inc(1)
        execute_next(self.huey)
        self.assertEqual(complete_log, [r3.id])


# ===========================================================================
# 12. Pre/Post execute hooks integration
# ===========================================================================
class TestHooksIntegration(unittest.TestCase):
    """Pre/post execute hooks with cancellation, error propagation, and
    on_startup/on_shutdown registration."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_hooks_full_lifecycle(self):
        """Pre-execute and post-execute hooks track task IDs and results,
        including CancelExecution and error cases. on_startup and on_shutdown
        hooks are registered and can be unregistered."""
        from huey.exceptions import CancelExecution

        @self.huey.task()
        def inc(n):
            return n + 1

        allow_tasks = [True]
        pre_state = []
        post_state = []

        @self.huey.pre_execute()
        def pre_exec(task):
            if not allow_tasks[0]:
                raise CancelExecution()

        @self.huey.pre_execute()
        def pre_track(task):
            pre_state.append(task.id)

        @self.huey.post_execute()
        def post_track(task, task_value, exc):
            exc_name = type(exc).__name__ if exc else None
            post_state.append((task.id, task_value, exc_name))

        # Normal execution
        r = inc(3)
        self.assertEqual(execute_next(self.huey), 4)
        self.assertEqual(pre_state, [r.id])
        self.assertEqual(post_state, [(r.id, 4, None)])

        # Cancel via hook
        allow_tasks[0] = False
        inc(5)
        self.assertIsNone(execute_next(self.huey))
        self.assertEqual(len(pre_state), 1)

        # Error passed to post hook
        allow_tasks[0] = True
        err_r = inc(None)
        self.assertIsNone(execute_next(self.huey))
        self.assertEqual(post_state[-1], (err_r.id, None, 'TypeError'))

        # on_startup/on_shutdown registration and unregistration
        @self.huey.on_startup()
        def on_start():
            pass

        @self.huey.on_shutdown()
        def on_stop():
            pass

        # Unregister — behavioral verification via return value
        self.assertTrue(self.huey.unregister_on_startup('on_start'))
        self.assertTrue(self.huey.unregister_pre_execute(pre_exec))
        self.assertTrue(self.huey.unregister_post_execute(post_track))


# ===========================================================================
# 13. Serializer integration
# ===========================================================================
class TestSerializerIntegration(unittest.TestCase):
    """Serializer with compression (gzip and zlib) and signed serialization
    end-to-end with a Huey instance."""

    def test_compression_and_signed_serializer(self):
        """Serialize and deserialize with gzip and zlib compression.
        SignedSerializer detects tampered data via HMAC verification and
        works end-to-end with a Huey instance."""
        from huey.serializer import Serializer, SignedSerializer
        from huey import MemoryHuey

        data = {'key': 'value', 'numbers': list(range(100))}

        # gzip compression
        s_gzip = Serializer(compression=True)
        serialized_gzip = s_gzip.serialize(data)
        self.assertEqual(s_gzip.deserialize(serialized_gzip), data)

        # zlib compression
        s_zlib = Serializer(compression=True, use_zlib=True)
        serialized_zlib = s_zlib.serialize(data)
        self.assertEqual(s_zlib.deserialize(serialized_zlib), data)

        # Signed serializer with tamper detection
        ss = SignedSerializer(secret='my-secret', salt='huey')
        serialized = ss.serialize(data)
        self.assertEqual(ss.deserialize(serialized), data)
        with self.assertRaises(ValueError):
            ss.deserialize(serialized[:-1] + b'x')

        # SignedSerializer end-to-end with Huey
        huey = MemoryHuey(utc=False)
        huey.serializer = SignedSerializer(secret='test-secret')

        @huey.task()
        def add(a, b):
            return a + b

        r = add(3, 4)
        self.assertEqual(execute_next(huey), 7)
        self.assertEqual(r.get(), 7)


# ===========================================================================
# 14. Storage backend contract — shared across all backends
# ===========================================================================
class TestStorageContract(unittest.TestCase):
    """The storage protocol exercised directly against every backend
    (Memory/Sqlite/Redis/File) in one parametrized contract, mirroring
    upstream's shared StorageTests mixin. Each backend is a distinct
    implementation (in-memory heap, SQL, Redis sorted-sets, file locks) but
    must satisfy the same queue / schedule / result-store behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _backends(self):
        """Yield (label, storage, priority_capable) for each backend."""
        from huey.storage import (MemoryStorage, SqliteStorage, RedisStorage,
                                   FileStorage)

        yield 'memory', MemoryStorage(), True
        yield 'sqlite', SqliteStorage(
            filename=os.path.join(self.tmpdir, 'contract.db')), True

        redis = RedisStorage()
        redis.conn.flushdb()
        yield 'redis', redis, False

        yield 'file', FileStorage(name='contract', path=self.tmpdir), False

    def test_storage_contract_all_backends(self):
        """For every backend: queue add/dequeue/size/flush, priority ordering
        (priority-capable) or FIFO (otherwise), schedule add + destructive
        read-by-timestamp, and result store peek/pop/put_if_empty/has_data
        with the EmptyData sentinel for missing keys."""
        from huey.constants import EmptyData

        redis_to_flush = []
        try:
            for label, s, priority_capable in self._backends():
                if label == 'redis':
                    redis_to_flush.append(s)

                # --- Queue: ordering, size, flush ---
                if priority_capable:
                    s.enqueue(b'low', priority=1)
                    s.enqueue(b'high', priority=10)
                    s.enqueue(b'mid', priority=5)
                    self.assertEqual(
                        [s.dequeue() for _ in range(3)],
                        [b'high', b'mid', b'low'], label)
                else:
                    s.enqueue(b'first')
                    s.enqueue(b'second')
                    s.enqueue(b'third')
                    self.assertEqual(
                        [s.dequeue() for _ in range(3)],
                        [b'first', b'second', b'third'], label)
                self.assertIsNone(s.dequeue(), label)

                s.enqueue(b'a')
                s.enqueue(b'b')
                self.assertEqual(s.queue_size(), 2, label)
                s.flush_queue()
                self.assertEqual(s.queue_size(), 0, label)

                # --- Schedule: add + destructive read-by-timestamp ---
                now = datetime.datetime.now()
                past = now - datetime.timedelta(hours=1)
                future = now + datetime.timedelta(hours=1)
                s.add_to_schedule(b'past_task', past)
                s.add_to_schedule(b'future_task', future)
                self.assertEqual(s.schedule_size(), 2, label)
                self.assertEqual(s.read_schedule(now), [b'past_task'], label)
                self.assertEqual(s.schedule_size(), 1, label)

                # --- Result store: peek/pop/EmptyData/put_if_empty/has_data ---
                s.put_data(b'k1', b'v1')
                self.assertEqual(s.peek_data(b'k1'), b'v1', label)
                self.assertEqual(s.pop_data(b'k1'), b'v1', label)
                self.assertIs(s.pop_data(b'k1'), EmptyData, label)
                self.assertIs(s.peek_data(b'missing'), EmptyData, label)

                self.assertTrue(s.put_if_empty(b'lock', b'1'), label)
                self.assertFalse(s.put_if_empty(b'lock', b'2'), label)
                self.assertEqual(s.peek_data(b'lock'), b'1', label)

                self.assertTrue(s.has_data_for_key(b'lock'), label)
                self.assertFalse(s.has_data_for_key(b'nonexistent'), label)
        finally:
            for s in redis_to_flush:
                s.conn.flushdb()


# ===========================================================================
# 15. SqliteHuey integration
# ===========================================================================
class TestSqliteHuey(unittest.TestCase):
    """SqliteHuey end-to-end: enqueue, execute, priority, schedule, pipeline."""

    def setUp(self):
        from huey import SqliteHuey
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test_huey.db')
        self.huey = SqliteHuey(filename=self.db_path, utc=False)

    def test_sqlite_full_workflow(self):
        """Complete task lifecycle through SqliteHuey with priority, schedule,
        and pipeline. The behavioral flow below proves the correct backend is
        wired and functioning."""
        @self.huey.task()
        def add(a, b):
            return a + b

        # Priority ordering
        add(1, 1, priority=1)
        add(2, 2, priority=10)
        add(3, 3, priority=5)

        self.assertEqual(execute_next(self.huey), 4)  # priority 10
        self.assertEqual(execute_next(self.huey), 6)  # priority 5
        self.assertEqual(execute_next(self.huey), 2)  # priority 1

        # Scheduling
        r = add.schedule((10, 20), delay=60)
        self.assertEqual(len(self.huey), 1)
        task = self.huey.dequeue()
        self.assertFalse(self.huey.ready_to_run(task))
        self.huey.execute(task)
        self.assertEqual(self.huey.scheduled_count(), 1)

        # Pipeline
        pipe = add.s(1, 2).then(add, 10)
        r1, r2 = self.huey.enqueue(pipe)
        execute_next(self.huey)
        execute_next(self.huey)
        self.assertEqual(r1(), 3)
        self.assertEqual(r2(), 13)


# ===========================================================================
# 16. BlackHoleHuey and convenience classes
# ===========================================================================
class TestConvenienceClasses(unittest.TestCase):
    """Convenience subclasses behave per their backend. MemoryHuey round-trips
    tasks; BlackHoleHuey discards everything (queue, schedule, and result
    store all silently drop data)."""

    def test_storage_types_and_blackhole(self):
        """MemoryHuey enqueues and executes a task end-to-end with a retrievable
        result. BlackHoleHuey is a no-op sink: enqueue stores nothing, the queue
        and result store stay empty, dequeue returns None, and the result is
        never available."""
        from huey import MemoryHuey, BlackHoleHuey

        # MemoryHuey: functional round-trip only a working backend produces.
        mem = MemoryHuey(utc=False)

        @mem.task()
        def add(a, b):
            return a + b

        r = add(3, 4)
        self.assertEqual(len(mem), 1)
        self.assertEqual(execute_next(mem), 7)
        self.assertEqual(r.get(), 7)

        # BlackHoleHuey: discard semantics. Enqueue is a no-op across the queue,
        # schedule, and result store; nothing is ever readable back.
        bh = BlackHoleHuey(utc=False)

        @bh.task()
        def inc(n):
            return n + 1

        r = inc(1)
        self.assertEqual(len(bh), 0)
        self.assertEqual(bh.result_count(), 0)
        self.assertIsNone(bh.dequeue())
        self.assertIsNone(r.get())

        # Scheduling on a BlackHole is also discarded.
        inc.schedule((5,), delay=60)
        self.assertEqual(bh.scheduled_count(), 0)


# ===========================================================================
# 17. Task context parameter and call_local
# ===========================================================================
class TestTaskContextAndCallLocal(unittest.TestCase):
    """context=True passes the task instance as task= kwarg.
    call_local() executes immediately without enqueueing.
    unregister() removes a task from the registry."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_context_call_local_unregister(self):
        """context=True provides task ID, call_local bypasses queue,
        unregister removes task from registry."""
        from huey.exceptions import HueyException

        @self.huey.task(context=True)
        def inspectable(task=None):
            return task.id

        r = inspectable()
        result = execute_next(self.huey)
        self.assertEqual(result, r.id)

        # call_local
        @self.huey.task()
        def add(a, b):
            return a + b

        result = add.call_local(3, 4)
        self.assertEqual(result, 7)
        self.assertEqual(len(self.huey), 0)

        # unregister
        @self.huey.task()
        def temp_task():
            return 1

        r = temp_task()
        self.assertEqual(execute_next(self.huey), 1)
        temp_task.unregister()
        with self.assertRaises(HueyException):
            r2 = temp_task()
            execute_next(self.huey)


# ===========================================================================
# 18. ResultGroup — iteration, unpacking, len, from map and pipeline
# ===========================================================================
class TestResultGroup(unittest.TestCase):
    """ResultGroup from map() and pipeline: iteration, unpacking, len."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_result_group_operations(self):
        """ResultGroup supports len(), iteration, unpacking, and get()."""
        @self.huey.task()
        def square(n):
            return n * n

        rg = square.map([1, 2, 3, 4])
        for _ in range(4):
            execute_next(self.huey)

        self.assertEqual(len(rg), 4)
        self.assertEqual(rg(), [1, 4, 9, 16])

        # Iteration and unpacking
        @self.huey.task()
        def add(a, b):
            return a + b

        pipe = add.s(1, 2).then(add, 10).then(add, 100)
        rg2 = self.huey.enqueue(pipe)
        for _ in range(3):
            execute_next(self.huey)

        self.assertEqual(len(rg2), 3)
        results = list(rg2)  # iteration
        self.assertEqual(results[0](), 3)
        self.assertEqual(results[1](), 13)
        self.assertEqual(results[2](), 113)

        # Unpacking
        r1, r2, r3 = rg2
        self.assertEqual(r1(), 3)
        self.assertEqual(r2(), 13)
        self.assertEqual(r3(), 113)


# ===========================================================================
# 19. Result blocking, timeout, is_ready
# ===========================================================================
class TestResultBlocking(unittest.TestCase):
    """Result.get(blocking=True, timeout=...), Result.is_ready(),
    and ResultTimeout exception."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_result_blocking_timeout(self):
        """Result.get(blocking=True, timeout=...) raises ResultTimeout when
        the result is not available in time. preserve=True keeps result in
        store after reading."""
        from huey.exceptions import ResultTimeout

        @self.huey.task()
        def slow_add(a, b):
            return a + b

        r = slow_add(5, 6)

        # Blocking with very short timeout should raise
        with self.assertRaises(ResultTimeout):
            r.get(blocking=True, timeout=0.01)

        # Execute the task
        execute_next(self.huey)

        # preserve=True keeps result in store
        self.assertEqual(r.get(preserve=True), 11)
        self.assertEqual(self.huey.result_count(), 1)

        # Without preserve, result is consumed
        r.reset()
        self.assertEqual(r.get(), 11)
        self.assertEqual(self.huey.result_count(), 0)

    def test_huey_result_method(self):
        """Huey.result(id) fetches result by task ID directly."""
        @self.huey.task()
        def add(a, b):
            return a + b

        r = add(10, 20)
        task_id = r.id
        execute_next(self.huey)

        # Use huey.result() to fetch by ID
        val = self.huey.result(task_id, preserve=True)
        self.assertEqual(val, 30)


# ===========================================================================
# 20. FileHuey backend
# ===========================================================================
class TestFileHuey(unittest.TestCase):
    """FileHuey uses file-based storage for tasks and results."""

    def setUp(self):
        from huey import FileHuey
        self.tmpdir = tempfile.mkdtemp()
        self.huey = FileHuey(utc=False, path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_file_huey_lifecycle(self):
        """Full task lifecycle through FileHuey: enqueue, dequeue, execute,
        get result."""
        @self.huey.task()
        def add(a, b):
            return a + b

        r = add(3, 4)
        self.assertEqual(len(self.huey), 1)
        task = self.huey.dequeue()
        self.assertIsNotNone(task)
        self.assertEqual(self.huey.execute(task), 7)
        self.assertEqual(r.get(), 7)
        self.assertEqual(len(self.huey), 0)


# ===========================================================================
# 21. Redis backend — RedisHuey + RedisSemaphore + priority
# ===========================================================================
class TestRedisBackend(unittest.TestCase):
    """RedisHuey with a real Redis server: full lifecycle, scheduling,
    priority, and semaphore."""

    def setUp(self):
        from huey import RedisHuey
        self.huey = RedisHuey(utc=False)
        self.huey.storage.conn.flushdb()

    def tearDown(self):
        self.huey.storage.conn.flushdb()

    def test_redis_full_lifecycle_and_scheduling(self):
        """Full task lifecycle through Redis storage with scheduling."""
        @self.huey.task()
        def add(a, b):
            return a + b

        r = add(3, 4)
        self.assertEqual(len(self.huey), 1)
        task = self.huey.dequeue()
        self.assertIsNotNone(task)
        self.assertEqual(self.huey.execute(task), 7)
        self.assertEqual(r.get(), 7)

        # Scheduling
        @self.huey.task()
        def inc(n):
            return n + 1

        r2 = inc.schedule((3,), delay=60)
        self.assertEqual(len(self.huey), 1)
        task2 = self.huey.dequeue()
        self.assertFalse(self.huey.ready_to_run(task2))
        self.huey.execute(task2)
        self.assertEqual(self.huey.scheduled_count(), 1)

        # Pipeline through Redis
        pipe = add.s(1, 2).then(add, 10)
        r1, r2 = self.huey.enqueue(pipe)
        execute_next(self.huey)
        execute_next(self.huey)
        self.assertEqual(r1(), 3)
        self.assertEqual(r2(), 13)

    def test_redis_semaphore(self):
        """RedisSemaphore limits concurrent access: acquire returns an ID up to
        the capacity then None at capacity; release with an invalid ID returns
        0, with a valid ID returns 1 and frees a slot for re-acquisition."""
        from huey.contrib.helpers import RedisSemaphore

        sem = RedisSemaphore(self.huey, 'test_sem', 2)

        aid1 = sem.acquire()
        self.assertIsNotNone(aid1)
        aid2 = sem.acquire()
        self.assertIsNotNone(aid2)
        # Third acquire should fail (value=2)
        aid3 = sem.acquire()
        self.assertIsNone(aid3)

        # Release with an invalid ID is a no-op (returns 0)
        self.assertEqual(sem.release('invalid-id-12345'), 0)
        # Still at capacity, so acquire continues to fail
        self.assertIsNone(sem.acquire())

        # Release one (valid ID returns 1) and re-acquire
        self.assertEqual(sem.release(aid1), 1)
        aid4 = sem.acquire()
        self.assertIsNotNone(aid4)
        self.assertNotEqual(aid1, aid4)

        # Cleanup
        sem.release(aid2)
        sem.release(aid4)


# ===========================================================================
# 22. SqlHuey via peewee — SqlStorage backend
# ===========================================================================
class TestSqlHueyBackend(unittest.TestCase):
    """SqlHuey with peewee: full task lifecycle through SQL storage."""

    def setUp(self):
        from huey.contrib.sql_huey import SqlHuey
        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, 'test.db')
        self.huey = SqlHuey(database='sqlite:///' + db_path, utc=False)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_sql_huey_full_lifecycle(self):
        """Full task lifecycle through peewee SqlStorage including scheduling."""
        @self.huey.task()
        def multiply(a, b):
            return a * b

        r = multiply(5, 6)
        self.assertEqual(len(self.huey), 1)
        task = self.huey.dequeue()
        self.assertIsNotNone(task)
        self.assertEqual(self.huey.execute(task), 30)
        self.assertEqual(r.get(), 30)

        # Scheduling
        @self.huey.task()
        def inc(n):
            return n + 1

        r2 = inc.schedule((3,), delay=60)
        self.assertEqual(len(self.huey), 1)
        task2 = self.huey.dequeue()
        self.assertFalse(self.huey.ready_to_run(task2))
        self.huey.execute(task2)
        self.assertEqual(self.huey.scheduled_count(), 1)


# ===========================================================================
# 23. Django integration — djhuey contrib
# ===========================================================================
class TestDjangoIntegration(unittest.TestCase):
    """Django integration: djhuey task decorator with minimal Django setup."""

    def setUp(self):
        import sys
        import types
        os.environ['DJANGO_SETTINGS_MODULE'] = 'test_django_settings'

        from huey import MemoryHuey
        mod = types.ModuleType('test_django_settings')
        mod.HUEY = MemoryHuey('django-test', immediate=True)
        mod.INSTALLED_APPS = []
        mod.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                                      'NAME': ':memory:'}}
        sys.modules['test_django_settings'] = mod

        import django
        django.setup()

    def tearDown(self):
        import sys
        os.environ.pop('DJANGO_SETTINGS_MODULE', None)
        sys.modules.pop('test_django_settings', None)

    def test_djhuey_task_decorator(self):
        """djhuey @task() decorator works with minimal Django setup and
        immediate mode, executing the task synchronously."""
        from huey.contrib.djhuey import task

        @task()
        def multiply(a, b):
            return a * b

        r = multiply(3, 4)
        self.assertEqual(r.get(), 12)


# ===========================================================================
# 24. MiniHuey — gevent-based single-process
# ===========================================================================
class TestMiniHuey(unittest.TestCase):
    """MiniHuey: gevent-based single-process task execution."""

    def test_mini_huey_task_execution(self):
        """MiniHuey starts a gevent pool, executes a task, and returns result."""
        from huey.contrib.mini import MiniHuey

        h = MiniHuey('test-mini', interval=1, pool_size=2)

        @h.task()
        def add(a, b):
            return a + b

        h.start()
        try:
            r = add(10, 20)
            result = r.get(timeout=5)
            self.assertEqual(result, 30)
        finally:
            h.stop()


# ===========================================================================
# 25. Async helpers — aget_result
# ===========================================================================
class TestAsyncHelpers(unittest.TestCase):
    """Async helpers for awaiting task results."""

    def test_aget_result(self):
        """aget_result asynchronously polls for a task result."""
        import asyncio
        from huey import MemoryHuey
        from huey.contrib.asyncio import aget_result

        huey = MemoryHuey(utc=False)

        @huey.task()
        def slow_add(a, b):
            return a + b

        r = slow_add(5, 6)
        execute_next(huey)

        result = asyncio.run(aget_result(r))
        self.assertEqual(result, 11)


# ===========================================================================
# 27. context_task — context manager wrapping for tasks
# ===========================================================================
class TestContextTask(unittest.TestCase):
    """Huey.context_task() wraps a task function with a context manager."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_context_task_decorator(self):
        """context_task wraps a function so that the context manager is
        entered before the task executes."""
        entered = []

        class MyContext:
            def __enter__(self):
                entered.append('enter')
                return 'ctx_value'

            def __exit__(self, *args):
                entered.append('exit')

        @self.huey.context_task(MyContext(), as_argument=True)
        def my_task(ctx, n):
            return '%s:%d' % (ctx, n)

        r = my_task(42)
        result = execute_next(self.huey)
        self.assertEqual(result, 'ctx_value:42')
        self.assertEqual(entered, ['enter', 'exit'])
        self.assertEqual(r.get(), 'ctx_value:42')


# ===========================================================================
# 29. Expired signal
# ===========================================================================
class TestExpiredSignal(unittest.TestCase):
    """SIGNAL_EXPIRED is emitted when a task executes after its expiry window."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_expired_signal(self):
        """An expired task emits SIGNAL_EXPIRED."""
        from huey.signals import SIGNAL_EXPIRED
        signals_log = []

        @self.huey.signal(SIGNAL_EXPIRED)
        def handler(signal, task):
            signals_log.append(signal)

        now = datetime.datetime.now()

        @self.huey.task(expires=1)
        def inc(n):
            return n + 1

        r = inc(1)
        task = self.huey.dequeue()
        # Execute well after expiry
        far_future = now + datetime.timedelta(seconds=100)
        self.huey.execute(task, far_future)
        self.assertEqual(signals_log, [SIGNAL_EXPIRED])


# ===========================================================================
# 30. Multi-feature combo — retries + priority + expiration + locking
# ===========================================================================
class TestMultiFeatureCombo(unittest.TestCase):
    """Combines retries, priority, expiration, and locking in one workflow
    to test their interaction, not each in isolation."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_locked_retried_prioritized_expiring_task(self):
        """A task with retries=2, priority=5, expires=60 and a lock: verify
        lock contention triggers retry, retry succeeds after lock release,
        priority ordering is respected among combo tasks, and expiration
        correctly skips execution after the window."""
        now = datetime.datetime.now()
        seconds = lambda s: now + datetime.timedelta(seconds=s)

        @self.huey.task(retries=2, priority=5, expires=60)
        @self.huey.lock_task('combo-lock')
        def combo(n):
            return n * 10

        # Normal execution works
        combo(3)
        self.assertEqual(execute_next(self.huey), 30)

        # Hold lock externally: task fails due to lock, retry is enqueued
        combo(5)
        with self.huey.lock_task('combo-lock'):
            task = self.huey.dequeue()
            self.assertIsNone(self.huey.execute(task))
        # Lock released, retry in queue
        self.assertEqual(len(self.huey), 1)
        self.assertEqual(execute_next(self.huey), 50)

        # Priority ordering among combo tasks
        combo(1, priority=1)
        combo(9, priority=9)
        combo(5, priority=5)
        results = [execute_next(self.huey) for _ in range(3)]
        self.assertEqual(results, [90, 50, 10])

        # Expiration: task skipped when executed past expiry window
        combo(7)
        task = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(task, seconds(100)))
        # Re-execute within window succeeds
        self.assertEqual(self.huey.execute(task, seconds(5)), 70)


# ===========================================================================
# 31. RetryTask with delay scheduling
# ===========================================================================
class TestRetryTaskDelayScheduling(unittest.TestCase):
    """RetryTask(delay=N) places the retry in the schedule store with a future
    timestamp, not back in the queue."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_retry_task_delay_goes_to_schedule(self):
        """Raising RetryTask(delay=30) inside a task causes the retry to appear
        in the schedule (not the queue) with a future eta. Verify the scheduled
        task has the correct ID, is not ready now, but becomes ready at the
        expected future timestamp. Also test that RetryTask(eta=...) uses
        the explicit eta, and that the default retry_delay is used when
        RetryTask is raised without explicit delay/eta."""
        from huey.exceptions import RetryTask, TaskException

        seconds = lambda s: (datetime.datetime.now() +
                             datetime.timedelta(seconds=s))

        # Test 1: RetryTask(delay=30) — explicit delay
        @self.huey.task(retry_delay=10)
        def task_delay(d=None, e=None):
            raise RetryTask(delay=d, eta=e)

        r1 = task_delay(d=30)
        task1 = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(task1))
        self.assertRaises(TaskException, r1.get)

        # Retry went to schedule, not queue
        self.assertEqual(len(self.huey), 0)
        self.assertEqual(self.huey.scheduled_count(), 1)

        # Scheduled task has the same ID
        sched = self.huey.scheduled()
        self.assertEqual(len(sched), 1)
        self.assertEqual(sched[0].id, r1.id)

        # Not ready now, ready at delay+1s
        self.assertFalse(self.huey.ready_to_run(sched[0]))
        self.assertTrue(self.huey.ready_to_run(sched[0], seconds(31)))

        # Verify eta is within expected range
        self.assertTrue(seconds(27) < sched[0].eta < seconds(33))

        self.huey.flush()

        # Test 2: RetryTask(eta=explicit) — uses the given eta directly
        explicit_eta = seconds(300)
        r2 = task_delay(e=explicit_eta)
        task2 = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(task2))

        sched2 = self.huey.scheduled()
        self.assertEqual(len(sched2), 1)
        self.assertEqual(sched2[0].eta, explicit_eta)
        self.assertFalse(self.huey.ready_to_run(sched2[0]))

        self.huey.flush()

        # Test 3: RetryTask() with no args — falls back to task's retry_delay=10
        r3 = task_delay()
        task3 = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(task3))

        sched3 = self.huey.scheduled()
        self.assertEqual(len(sched3), 1)
        self.assertTrue(seconds(7) < sched3[0].eta < seconds(13))


# ===========================================================================
# 32. Concurrent thread safety
# ===========================================================================
class TestConcurrentThreadSafety(unittest.TestCase):
    """Multiple threads simultaneously enqueue and execute tasks on the same
    MemoryHuey instance without data loss or duplicate execution."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_concurrent_enqueue_no_loss(self):
        """Spawn 8 threads that simultaneously enqueue 50 tasks each via a
        barrier for true concurrency. Verify all 400 tasks have unique IDs,
        the queue length matches, and all execute with correct results."""
        @self.huey.task()
        def inc(n):
            return n + 1

        num_threads = 8
        tasks_per_thread = 50
        total = num_threads * tasks_per_thread
        barrier = threading.Barrier(num_threads)
        ids_lock = threading.Lock()
        enqueued_ids = []

        def enqueue_worker(offset):
            barrier.wait()
            local_ids = []
            for i in range(tasks_per_thread):
                r = inc(offset * tasks_per_thread + i)
                local_ids.append(r.id)
            with ids_lock:
                enqueued_ids.extend(local_ids)

        threads = [threading.Thread(target=enqueue_worker, args=(t,))
                   for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All tasks enqueued with unique IDs
        self.assertEqual(len(enqueued_ids), total)
        self.assertEqual(len(set(enqueued_ids)), total)
        self.assertEqual(len(self.huey), total)

        # Execute all and collect results
        results = []
        while len(self.huey) > 0:
            task = self.huey.dequeue()
            if task is not None:
                results.append(self.huey.execute(task))

        self.assertEqual(len(results), total)
        # Each result is n+1 for some n in [0..total), so results sorted
        # should be [1, 2, ..., total]
        self.assertEqual(sorted(results), list(range(1, total + 1)))
        self.assertEqual(len(self.huey), 0)


# ===========================================================================
# 33. Periodic task + pipeline interaction
# ===========================================================================
class TestPeriodicPipelineInteraction(unittest.TestCase):
    """Register a periodic task, discover it via read_periodic, then enqueue
    it as part of a pipeline with .then(). Verify pipeline executes correctly
    through the periodic task entry point."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_periodic_task_as_pipeline_head(self):
        """A periodic task discovered via read_periodic can be chained into a
        pipeline with .then(). The pipeline executes sequentially, passing
        the periodic task's return value to the next step."""
        from huey import crontab

        @self.huey.periodic_task(crontab(minute='*/5'))
        def generate_value():
            return 42

        @self.huey.task()
        def double(n):
            return n * 2

        @self.huey.task()
        def add_hundred(n):
            return n + 100

        # Discover the periodic task
        dt = datetime.datetime(2024, 1, 1, 0, 0)
        periodic_tasks = self.huey.read_periodic(dt)
        self.assertEqual(len(periodic_tasks), 1)
        self.assertEqual(periodic_tasks[0].name, 'generate_value')

        # Chain into pipeline
        ptask = periodic_tasks[0]
        pipeline = ptask.then(double).then(add_hundred)
        result_group = self.huey.enqueue(pipeline)
        self.assertEqual(len(result_group), 3)

        # Execute all steps
        v1 = execute_next(self.huey)
        self.assertEqual(v1, 42)

        v2 = execute_next(self.huey)
        self.assertEqual(v2, 84)

        v3 = execute_next(self.huey)
        self.assertEqual(v3, 184)

        self.assertEqual(len(self.huey), 0)


# ===========================================================================
# 34. Revoke a scheduled task
# ===========================================================================
class TestRevokeScheduledTask(unittest.TestCase):
    """Schedule a task with delay, let it move to the schedule store, then
    revoke it by ID. Verify that execution after read_schedule is skipped."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_revoke_from_schedule_store(self):
        """Schedule a task with delay=60 so it enters the schedule store.
        Revoke it by ID, then read_schedule and attempt execution. The revoked
        task should return None and not execute the function body."""
        state = []

        @self.huey.task()
        def track(n):
            state.append(n)
            return n + 1

        # Schedule with delay, dequeue, execute -> goes to schedule
        r = track.schedule((10,), delay=60)
        task = self.huey.dequeue()
        self.huey.execute(task)
        self.assertEqual(self.huey.scheduled_count(), 1)
        self.assertEqual(len(self.huey), 0)
        self.assertEqual(state, [])  # Not executed yet

        # Revoke the scheduled task
        self.huey.revoke_by_id(r.id)
        self.assertTrue(r.is_revoked())

        # Read from schedule at future timestamp
        future = datetime.datetime.now() + datetime.timedelta(seconds=61)
        sched_tasks = self.huey.read_schedule(future)
        self.assertEqual(len(sched_tasks), 1)

        # Re-enqueue and try to execute at the future timestamp —
        # the task is ready to run but revoked, so it returns None
        self.huey.enqueue(sched_tasks[0])
        task2 = self.huey.dequeue()
        self.assertIsNotNone(task2)
        result = self.huey.execute(task2, timestamp=future)
        self.assertIsNone(result)
        self.assertEqual(state, [])  # Function body never ran

        # Queue and schedule are both empty
        self.assertEqual(len(self.huey), 0)


# ===========================================================================
# 35. context_task with exception
# ===========================================================================
class TestContextTaskException(unittest.TestCase):
    """context_task where the wrapped function raises an exception. Verify
    the context manager's __exit__ is still called and the exception propagates
    correctly as a TaskException."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_context_task_cleanup_on_error(self):
        """When a context_task-wrapped function raises an exception, the context
        manager's __exit__ receives the exception type and is called for cleanup.
        The exception is stored and raised as TaskException on result.get()."""
        from huey.exceptions import TaskException

        lifecycle = []

        class CleanupContext:
            def __enter__(self):
                lifecycle.append('enter')
                return 'resource'

            def __exit__(self, exc_type, exc_val, exc_tb):
                lifecycle.append(('exit', exc_type.__name__ if exc_type else None))
                return False  # Don't suppress

        # Without as_argument: function raises, cleanup still happens
        @self.huey.context_task(CleanupContext())
        def failing_task():
            raise ValueError('task failed')

        r1 = failing_task()
        result1 = execute_next(self.huey)
        self.assertIsNone(result1)
        self.assertEqual(lifecycle, ['enter', ('exit', 'ValueError')])
        with self.assertRaises(TaskException):
            r1.get()

        # With as_argument: context value is passed, exception propagates,
        # cleanup still happens
        lifecycle.clear()

        @self.huey.context_task(CleanupContext(), as_argument=True)
        def failing_with_ctx(ctx):
            raise RuntimeError('failed with %s' % ctx)

        r2 = failing_with_ctx()
        result2 = execute_next(self.huey)
        self.assertIsNone(result2)
        self.assertEqual(lifecycle, ['enter', ('exit', 'RuntimeError')])
        with self.assertRaises(TaskException):
            r2.get()


# ===========================================================================
# 36. Task custom name — name override path in TaskWrapper
# ===========================================================================
class TestTaskCustomName(unittest.TestCase):
    """Task decorated with a custom name= parameter is registered under that
    name, not the function name."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_custom_name_registration_and_execution(self):
        """@huey.task(name='custom_name') registers the task under 'custom_name'
        instead of the function name. The dequeued task carries the custom name,
        and execution produces correct results."""
        @self.huey.task(name='my_custom_adder')
        def add(a, b):
            return a + b

        # TaskWrapper exposes custom name
        self.assertEqual(add.name, 'my_custom_adder')

        # Enqueue and verify the Task message carries the custom name
        r = add(3, 4)
        task = self.huey.dequeue()
        self.assertEqual(task.name, 'my_custom_adder')

        # Execution works correctly through the custom name lookup
        self.assertEqual(self.huey.execute(task), 7)
        self.assertEqual(r.get(), 7)

        # A second task with a different custom name coexists
        @self.huey.task(name='my_custom_multiplier')
        def mul(a, b):
            return a * b

        self.assertEqual(mul.name, 'my_custom_multiplier')
        r2 = mul(5, 6)
        self.assertEqual(execute_next(self.huey), 30)
        self.assertEqual(r2.get(), 30)


# ===========================================================================
# 37. Huey.is_revoked(task) — Huey-level revocation check on Task objects
# ===========================================================================
class TestHueyIsRevoked(unittest.TestCase):
    """Huey.is_revoked() checks revocation status given a Task object,
    distinct from Result.is_revoked() and TaskWrapper.is_revoked()."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_huey_is_revoked_on_task(self):
        """huey.is_revoked(task) returns False before revocation, True after
        revoke_by_id, and False again after restore_by_id. Also verify that
        a revoked task returns None on execute."""
        @self.huey.task()
        def inc(n):
            return n + 1

        r = inc(5)
        task = self.huey.dequeue()

        # Not revoked initially
        self.assertFalse(self.huey.is_revoked(task))

        # Revoke by ID
        self.huey.revoke_by_id(r.id)
        self.assertTrue(self.huey.is_revoked(task))

        # Revoked task returns None on execute
        self.assertIsNone(self.huey.execute(task))

        # Restore and verify
        self.huey.restore_by_id(r.id)
        self.assertFalse(self.huey.is_revoked(task))

        # Re-enqueue and execute after restore succeeds
        self.huey.enqueue(task)
        self.assertEqual(execute_next(self.huey), 6)


# ===========================================================================
# 42. Consumer integration — start, enqueue, execute, stop
# ===========================================================================
class TestConsumerIntegration(unittest.TestCase):
    """Start a MemoryHuey consumer in a background thread, enqueue a task,
    wait for result, then stop. Tests the consumer main loop."""

    def test_consumer_processes_task(self):
        """Consumer(huey, workers=1, worker_type='thread') processes an
        enqueued task and the result becomes available within a timeout.
        Also smoke-checks that the consumer CLI entry point is wired."""
        import subprocess
        import sys
        from huey import MemoryHuey
        from huey.consumer import Consumer

        h = MemoryHuey('test-consumer', utc=False)

        @h.task()
        def add(a, b):
            return a + b

        consumer = Consumer(h, workers=1, worker_type='thread')
        consumer.start()
        try:
            r = add(3, 4)

            # Poll for result with timeout (up to 10 seconds)
            result = None
            for _ in range(100):
                result = r.get()
                if result is not None:
                    break
                time.sleep(0.1)

            self.assertEqual(result, 7)

            # Enqueue a second task to verify consumer stays alive
            r2 = add(10, 20)
            result2 = None
            for _ in range(100):
                result2 = r2.get()
                if result2 is not None:
                    break
                time.sleep(0.1)

            self.assertEqual(result2, 30)
        finally:
            consumer.stop()

        # CLI entry point smoke check: the consumer is also runnable via
        # `python -m huey.bin.huey_consumer <huey_instance>`. We only assert
        # the entry point is wired and `--help` succeeds; the exact wording of
        # argparse-generated help text is an incidental implementation detail.
        cli = subprocess.run(
            [sys.executable, '-m', 'huey.bin.huey_consumer', '--help'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(cli.returncode, 0)


# ===========================================================================
# 44. Serializer compression effect — output size and format distinctness
# ===========================================================================
class TestSerializerCompressionEffect(unittest.TestCase):
    """Serializer compression flags' effect on the *output bytes* (not just
    round-trip equality, which the integration serializer test already covers):
    enabling compression yields a smaller, distinct byte stream, and gzip vs
    zlib are two distinct compression formats."""

    def test_serializer_compression_output_distinct(self):
        """For a compressible payload, the gzip and zlib serializers each emit
        output bytes that are (a) smaller than the uncompressed output and (b)
        distinct from the uncompressed output and from each other.

        This owns ONLY the output-bytes contract; the gzip/zlib serialize ->
        deserialize round-trip equality is covered by
        TestSerializerIntegration.test_compression_and_signed_serializer and is
        deliberately not re-asserted here."""
        from huey.serializer import Serializer

        # A payload large/repetitive enough that compression measurably shrinks
        # it (a tiny payload would not, so the size assertions would be flaky).
        data = {
            'strings': ['hello', 'world', ''],
            'nested': {'a': [1, (2, 3)], 'b': {'c': [4, 5]}},
            'tuples': [(1, 2), (3, 4, 5)],
            'large': list(range(1000)),
            'empty': {},
            'none_val': None,
            'bool_mix': [True, False, None, 0, 1],
            'bytes': b'binary data ' * 50,
        }

        s_plain = Serializer()
        s_gzip = Serializer(compression=True)
        s_zlib = Serializer(compression=True, use_zlib=True)

        raw = s_plain.serialize(data)
        gz = s_gzip.serialize(data)
        zl = s_zlib.serialize(data)

        # Compression shrinks the output (the defining, user-observable effect).
        self.assertTrue(len(gz) < len(raw))
        self.assertTrue(len(zl) < len(raw))

        # gzip and zlib are distinct formats; both differ from the raw output.
        self.assertNotEqual(gz, raw)
        self.assertNotEqual(zl, raw)
        self.assertNotEqual(gz, zl)


# ===========================================================================
# 46. Pipeline + retry + expiration combo
# ===========================================================================
class TestPipelineRetryExpirationCombo(unittest.TestCase):
    """Pipeline where step 2 has retries=2 and step 3 has expires=10.
    Step 2 fails twice then succeeds. Verify step 3 expiration behavior."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_pipeline_retry_and_expiration(self):
        """Build a 3-step pipeline: step1 -> step2(retries=2) -> step3(expires=10).
        Step 2 fails twice then succeeds on third attempt. Step 3 executes
        within expiry window. Then repeat with step 3 executed after expiry
        to verify it is skipped."""
        now = datetime.datetime.now()
        seconds = lambda s: now + datetime.timedelta(seconds=s)
        state = {'calls': []}

        @self.huey.task()
        def step1(n):
            state['calls'].append('step1')
            return n * 2

        @self.huey.task(retries=2)
        def step2_retry(n):
            state['calls'].append('step2')
            count = len([c for c in state['calls'] if c == 'step2'])
            if count < 3:
                raise ValueError('not yet')
            return n + 10

        @self.huey.task(expires=10)
        def step3_expires(n):
            state['calls'].append('step3')
            return n + 100

        # Build pipeline
        pipe = step1.s(5).then(step2_retry).then(step3_expires)
        rg = self.huey.enqueue(pipe)

        # Execute step1: 5*2 = 10
        self.assertEqual(self.huey.execute(self.huey.dequeue(), seconds(0)), 10)

        # step2 fails twice (retries re-enqueue)
        self.assertIsNone(self.huey.execute(self.huey.dequeue(), seconds(1)))
        self.assertIsNone(self.huey.execute(self.huey.dequeue(), seconds(2)))

        # step2 succeeds on third attempt: 10+10 = 20
        self.assertEqual(
            self.huey.execute(self.huey.dequeue(), seconds(3)), 20)

        # step3 enqueued — execute within expiry window: 20+100 = 120
        task3 = self.huey.dequeue()
        self.assertIsNotNone(task3)
        self.assertEqual(self.huey.execute(task3, seconds(5)), 120)
        self.assertEqual(
            state['calls'],
            ['step1', 'step2', 'step2', 'step2', 'step3'])

        # --- Second run: step 3 expires ---
        state['calls'].clear()

        pipe2 = step1.s(5).then(step2_retry).then(step3_expires)
        rg2 = self.huey.enqueue(pipe2)

        self.huey.execute(self.huey.dequeue(), seconds(0))
        self.huey.execute(self.huey.dequeue(), seconds(1))
        self.huey.execute(self.huey.dequeue(), seconds(2))
        self.huey.execute(self.huey.dequeue(), seconds(3))

        # step3 executed AFTER expiry window (expires=10, execute at +15)
        task3b = self.huey.dequeue()
        self.assertIsNone(self.huey.execute(task3b, seconds(15)))
        self.assertNotIn('step3', state['calls'])


# ===========================================================================
# 47. persistent revoke_by_id survives until restore_by_id
# ===========================================================================
class TestPersistentRevokeById(unittest.TestCase):
    """A persistent by-ID revocation (revoke_by_id default revoke_once=False) is
    not consumed by a skipped execution: it keeps the task revoked across the
    skip and a re-enqueue until restore_by_id flips it back to runnable — the
    persistent counterpart of the consumed revoke_once path."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_persistent_revoke_by_id_survives_until_restore(self):
        """A persistent by-ID revocation (revoke_by_id default revoke_once=False)
        is NOT consumed by a skipped execution: the task stays revoked across the
        first skip and across a re-enqueue, and only restore_by_id flips it back
        to runnable. This is the persistent counterpart to the consumed
        revoke_once path (covered via Result.revoke() in
        test_class_and_instance_revocation)."""
        state = []

        @self.huey.task()
        def track(n):
            state.append(n)
            return n + 1

        # Enqueue and dequeue a task
        r = track(42)
        task = self.huey.dequeue()
        self.assertEqual(task.id, r.id)

        # Revoke the task by ID persistently (default revoke_once=False)
        self.huey.revoke_by_id(r.id)
        self.assertTrue(self.huey.is_revoked(task))

        # First execute is skipped — returns None, body never runs
        self.assertIsNone(self.huey.execute(task))
        self.assertEqual(state, [])

        # Persistent: still revoked after a skipped run (NOT consumed)
        self.assertTrue(self.huey.is_revoked(task))

        # Re-enqueue and execute again — still skipped (survives re-enqueue)
        self.huey.enqueue(task)
        self.assertIsNone(execute_next(self.huey))
        self.assertEqual(state, [])

        # restore_by_id flips it back to runnable and reports it was revoked
        self.assertTrue(self.huey.restore_by_id(r.id))
        self.assertFalse(self.huey.is_revoked(task))

        # Re-enqueue the same task — it now runs to completion
        self.huey.enqueue(task)
        self.assertEqual(execute_next(self.huey), 43)
        self.assertEqual(state, [42])
        self.assertEqual(len(self.huey), 0)


# ===========================================================================
# 48. Scheduled + periodic ready at same timestamp
# ===========================================================================
class TestScheduledAndPeriodicSameTimestamp(unittest.TestCase):
    """Register a periodic task and schedule a regular task both ready at
    the same timestamp. Verify read_schedule and read_periodic each return
    their respective tasks."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_both_ready_at_same_timestamp(self):
        """A periodic task (crontab minute=*/15) and a regular scheduled task
        with eta at a matching timestamp. read_schedule returns the scheduled
        task, read_periodic returns the periodic task, both at the same
        timestamp."""
        from huey import crontab

        @self.huey.periodic_task(crontab(minute='*/15'))
        def periodic_job():
            return 'periodic'

        @self.huey.task()
        def regular_job(n):
            return n + 1

        # Timestamp matching the periodic crontab (minute=0)
        ts = datetime.datetime(2024, 6, 1, 12, 0, 0)
        early = datetime.datetime(2000, 1, 1)

        # Schedule regular task at same timestamp
        r = regular_job.schedule((99,), eta=ts)
        task = self.huey.dequeue()
        # Execute at an early time so it goes to the schedule store
        self.huey.execute(task, timestamp=early)
        self.assertEqual(self.huey.scheduled_count(), 1)

        # read_schedule at target timestamp returns the scheduled task
        sched_tasks = self.huey.read_schedule(ts)
        self.assertEqual(len(sched_tasks), 1)
        self.assertEqual(sched_tasks[0].name, 'regular_job')

        # read_periodic at same timestamp returns the periodic task
        periodic_tasks = self.huey.read_periodic(ts)
        self.assertEqual(len(periodic_tasks), 1)
        self.assertEqual(periodic_tasks[0].name, 'periodic_job')


# ===========================================================================
# 49. Nested pipeline error + error callback interaction
# ===========================================================================
class TestNestedPipelineErrorCallback(unittest.TestCase):
    """A 4-step pipeline where step 2 has an error callback. Step 2 fails.
    Verify: error callback fires, steps 3-4 never enqueue, step 1 result
    is still available."""

    def setUp(self):
        from huey import MemoryHuey
        self.huey = MemoryHuey(utc=False)

    def test_error_callback_fires_remaining_steps_skipped(self):
        """Pipeline: step1 -> step2(error=err_handler) -> step3 -> step4.
        Step 2 fails. Error callback receives the exception, steps 3-4
        are never enqueued, and step 1 result is preserved in the result
        store."""
        from huey.exceptions import TaskException
        state = {'err_cb': [], 'steps': []}

        @self.huey.task()
        def step1(n):
            state['steps'].append(('step1', n))
            return n * 2

        @self.huey.task()
        def step2_fail(n):
            state['steps'].append(('step2', n))
            raise ValueError('step2 breaks')

        @self.huey.task()
        def step3(n):
            state['steps'].append(('step3', n))
            return n + 100

        @self.huey.task()
        def step4(n):
            state['steps'].append(('step4', n))
            return n + 1000

        @self.huey.task()
        def err_handler(err):
            state['err_cb'].append(str(err))
            return 'error caught'

        # Build pipeline with error callback on step2
        task_s2 = step2_fail.s().error(err_handler)
        pipe = step1.s(5).then(task_s2).then(step3).then(step4)
        r1, r2, r3, r4 = self.huey.enqueue(pipe)

        # Execute step1: 5*2 = 10
        self.assertEqual(self.huey.execute(self.huey.dequeue()), 10)

        # Execute step2: fails
        self.assertIsNone(self.huey.execute(self.huey.dequeue()))
        with self.assertRaises(TaskException):
            r2.get()

        # Error callback fires
        self.assertEqual(len(self.huey), 1)
        self.assertEqual(self.huey.execute(self.huey.dequeue()), 'error caught')
        self.assertEqual(state['err_cb'], ['step2 breaks'])

        # Steps 3-4 never enqueued
        self.assertEqual(len(self.huey), 0)
        self.assertFalse(
            any(s[0] in ('step3', 'step4') for s in state['steps']))

        # Step 1 result still available
        self.assertEqual(r1.get(preserve=True), 10)


if __name__ == '__main__':
    unittest.main()
