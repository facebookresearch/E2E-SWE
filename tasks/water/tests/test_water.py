"""Behavioral test suite for the `water` workflow-orchestration engine.

Every test drives the public Python API (``import water``; build a Flow with
``create_task`` + builder methods; ``await flow.run(...)``). Async flows are
driven via ``asyncio.run`` inside synchronous test functions so the suite needs
no async-test plugin (only pytest + pytest-timeout).

LLM providers are mocked with the built-in ``MockProvider`` — no network.

Round-3 hardening note: the individually-trivial guard/happy-path checks have
been CONSOLIDATED into a smaller number of bundled tests (one grouped contract
each, multiple asserts), and a larger set of cross-cutting interaction tests has
been added. Behavior coverage is preserved; the test-mix now emphasises genuine
multi-feature interaction difficulty.
"""

import asyncio
import time

import pytest
from pydantic import BaseModel

from water import (
    Flow,
    Task,
    create_task,
    InMemoryStorage,
    SQLiteStorage,
    FlowStatus,
    FlowPausedError,
    FlowStoppedError,
    CircuitBreaker,
    CircuitBreakerOpen,
    InMemoryCache,
    InMemoryCheckpoint,
    InMemoryDLQ,
    FallbackChain,
    MockProvider,
    ExecutionContext,
)
from water.agents.llm import LLMProvider
from water.agents.tools import Tool


# ---------------------------------------------------------------------------
# Shared schemas + task factory helpers
# ---------------------------------------------------------------------------

class AnyData(BaseModel):
    """Permissive schema that accepts arbitrary extra keys."""
    model_config = {"extra": "allow"}


def run(coro):
    """Drive a coroutine to completion on a fresh event loop."""
    return asyncio.run(coro)


def make_task(task_id, fn, **kwargs):
    """Build a Task whose execute returns fn(input_data)."""
    def _execute(params, context):
        return fn(params["input_data"])
    return create_task(
        id=task_id,
        input_schema=AnyData,
        output_schema=AnyData,
        execute=_execute,
        **kwargs,
    )


def make_async_task(task_id, async_fn, **kwargs):
    async def _execute(params, context):
        return await async_fn(params["input_data"])
    return create_task(
        id=task_id,
        input_schema=AnyData,
        output_schema=AnyData,
        execute=_execute,
        **kwargs,
    )


# ===========================================================================
# CONSOLIDATED bundles — individually-trivial guards & happy paths grouped
# into single contract tests with multiple asserts. (Round-3 consolidation.)
# ===========================================================================

def test_flow_construction_and_builder_state_guards():
    """Flow id auto-gen, .then(None), post-register mutation, and empty-register all enforced.

    Bundles: auto id shape; .then(None) -> ValueError; builder methods after
    register() -> RuntimeError; register() with no tasks -> ValueError;
    run() before register() -> RuntimeError.
    """
    f = Flow()
    assert f.id.startswith("flow_")
    assert len(f.id) == len("flow_") + 8

    with pytest.raises(ValueError):
        Flow().then(None)

    registered = Flow().then(make_task("t", lambda d: d)).register()
    with pytest.raises(RuntimeError):
        registered.then(make_task("t2", lambda d: d))

    with pytest.raises(ValueError):
        Flow().register()

    unregistered = Flow().then(make_task("t", lambda d: d))
    with pytest.raises(RuntimeError):
        run(unregistered.run({"x": 1}))


def test_builder_empty_argument_and_async_condition_guards():
    """Empty .dag/.parallel/.branch/.map(over='') and async branch conditions all rejected.

    Bundles every collection-shape build-time ValueError plus the async-condition guard.
    """
    with pytest.raises(ValueError):
        Flow().dag([])
    with pytest.raises(ValueError):
        Flow().parallel([])
    with pytest.raises(ValueError):
        Flow().branch([])
    with pytest.raises(ValueError):
        Flow().map(make_task("t", lambda d: d), over="")

    async def cond(data):
        return True
    with pytest.raises(ValueError):
        Flow().branch([(cond, make_task("t", lambda d: d))])


def test_task_constructor_validation_bundle():
    """Task/create_task constructor validation: schema type, retry, timeout, agentic/on_error guards.

    Bundles: non-BaseModel schema -> WaterError; retry_count<0 -> ValueError;
    timeout<=0 -> ValueError; agentic_loop(max_iterations=0) -> ValueError;
    on_error() with no prior tasks -> ValueError.
    """
    from water.core.exceptions import WaterError

    with pytest.raises(WaterError):
        Task(input_schema=dict, output_schema=AnyData, execute=lambda p, c: {})

    with pytest.raises(ValueError):
        create_task(id="t", input_schema=AnyData, output_schema=AnyData,
                    execute=lambda p, c: {}, retry_count=-1)
    with pytest.raises(ValueError):
        create_task(id="t", input_schema=AnyData, output_schema=AnyData,
                    execute=lambda p, c: {}, timeout=0)

    with pytest.raises(ValueError):
        Flow().agentic_loop(MockProvider(), max_iterations=0)
    with pytest.raises(ValueError):
        Flow().on_error(lambda err, ctx: {})


def test_sequential_conditional_and_fallback_bundle():
    """Sequential threading, when-skip, fallback-on-failure, and no-fallback-on-success.

    Bundles the four core .then behaviours into one contract.
    """
    f = (
        Flow()
        .then(make_task("a", lambda d: {"n": d["n"] + 1}))
        .then(make_task("b", lambda d: {"n": d["n"] * 10}))
        .register()
    )
    assert run(f.run({"n": 1})) == {"n": 20}

    skip = (
        Flow()
        .then(make_task("a", lambda d: {"n": 999}), when=lambda d: d["n"] > 100)
        .register()
    )
    assert run(skip.run({"n": 5})) == {"n": 5}

    def boom(d):
        raise RuntimeError("primary failed")
    fb = (
        Flow()
        .then(make_task("p", boom),
              fallback=make_task("fb", lambda d: {"via": "fallback", "n": d["n"]}))
        .register()
    )
    assert run(fb.run({"n": 7})) == {"via": "fallback", "n": 7}

    fb_ran = {"v": False}
    def fbrec(d):
        fb_ran["v"] = True
        return d
    nofb = (
        Flow()
        .then(make_task("p", lambda d: {"ok": True}), fallback=make_task("fb", fbrec))
        .register()
    )
    assert run(nofb.run({})) == {"ok": True}
    assert fb_ran["v"] is False


def test_branch_first_match_and_passthrough_bundle():
    """Branch executes the FIRST matching condition; passes through when none match."""
    first = (
        Flow()
        .branch([
            (lambda d: d["n"] > 0, make_task("pos", lambda d: {"label": "positive"})),
            (lambda d: True, make_task("any", lambda d: {"label": "any"})),
        ])
        .register()
    )
    assert run(first.run({"n": 5})) == {"label": "positive"}

    nomatch = (
        Flow()
        .branch([(lambda d: d["n"] > 100, make_task("big", lambda d: {"label": "big"}))])
        .register()
    )
    assert run(nomatch.run({"n": 1})) == {"n": 1}


def test_parallel_and_map_basics_bundle():
    """Parallel returns {task_id: result}; map returns ordered {'results': [...]} and validates 'over'.

    Bundles: parallel dict-keying; map list-in-order; map empty list; map over
    non-list -> ValueError; map replaces only the 'over' key per item.
    """
    par = (
        Flow()
        .parallel([
            make_task("a", lambda d: {"r": "A"}),
            make_task("b", lambda d: {"r": "B"}),
        ])
        .register()
    )
    assert run(par.run({})) == {"a": {"r": "A"}, "b": {"r": "B"}}

    sq = Flow().map(make_task("sq", lambda d: {"v": d["x"] ** 2}), over="x").register()
    assert run(sq.run({"x": [1, 2, 3, 4]})) == {
        "results": [{"v": 1}, {"v": 4}, {"v": 9}, {"v": 16}]
    }

    empty = Flow().map(make_task("sq", lambda d: {"v": 1}), over="x").register()
    assert run(empty.run({"x": []})) == {"results": []}

    bad = Flow().map(make_task("sq", lambda d: {"v": 1}), over="x").register()
    with pytest.raises(ValueError):
        run(bad.run({"x": 42}))

    keyed = (
        Flow()
        .map(make_task("m", lambda d: {"item": d["x"], "tag": d["tag"]}), over="x")
        .register()
    )
    assert run(keyed.run({"x": [10, 20], "tag": "T"})) == {
        "results": [{"item": 10, "tag": "T"}, {"item": 20, "tag": "T"}]
    }


def test_parallel_runs_concurrently():
    """.parallel tasks overlap in time (gather), not run serially."""
    async def slow(d):
        await asyncio.sleep(0.2)
        return {"done": True}
    f = (
        Flow()
        .parallel([
            make_async_task("a", slow),
            make_async_task("b", slow),
            make_async_task("c", slow),
        ])
        .register()
    )
    start = time.monotonic()
    run(f.run({}))
    assert time.monotonic() - start < 0.5


def test_dag_basics_bundle():
    """DAG no-deps dict result, downstream reads upstream via context, unknown-dep ValueError.

    Bundles the structural DAG contracts (cycle + ordering kept as separate
    discriminators below).
    """
    no_deps = (
        Flow()
        .dag([make_task("a", lambda d: {"r": 1}), make_task("b", lambda d: {"r": 2})])
        .register()
    )
    assert run(no_deps.run({})) == {"a": {"r": 1}, "b": {"r": 2}}

    captured = {}
    def child_exec(params, context):
        captured["value"] = context.get_task_output("parent")["value"]
        return {"child_saw": captured["value"]}
    parent = create_task(id="parent", input_schema=AnyData, output_schema=AnyData,
                         execute=lambda p, c: {"value": 42})
    child = create_task(id="child", input_schema=AnyData, output_schema=AnyData,
                        execute=child_exec)
    diamond = Flow().dag([parent, child], dependencies={"child": ["parent"]}).register()
    out = run(diamond.run({}))
    assert captured["value"] == 42
    assert out["child"] == {"child_saw": 42}

    unknown = Flow().dag([make_task("a", lambda d: d)], dependencies={"a": ["ghost"]}).register()
    with pytest.raises(ValueError):
        run(unknown.run({}))


def test_dag_topological_order_each_task_runs_exactly_once():
    """A dependent never STARTS before every dependency has finished, and each task runs EXACTLY once.

    Tightened: records both start and finish events per task (not just a finish
    order), so the check is on the dependency edges directly — each task's start
    must follow the finish of every one of its declared deps — rather than on a
    single fragile finish-order list. Uses a diamond a->{b,c}->d so a correct
    scheduler is pinned (b and c each gated behind a; d gated behind both b and
    c) while every node still runs exactly once.
    """
    events = []  # ("start"|"finish", name)
    counts = {}
    deps = {"b": ["a"], "c": ["a"], "d": ["b", "c"]}

    def step(name):
        async def _fn(d):
            counts[name] = counts.get(name, 0) + 1
            events.append(("start", name))
            await asyncio.sleep(0.02)
            events.append(("finish", name))
            return {"name": name}
        return _fn

    f = (
        Flow()
        .dag([make_async_task("a", step("a")), make_async_task("b", step("b")),
              make_async_task("c", step("c")), make_async_task("d", step("d"))],
             dependencies=deps)
        .register()
    )
    run(f.run({}))

    # exactly once
    assert counts == {"a": 1, "b": 1, "c": 1, "d": 1}

    # every task started exactly once and finished exactly once
    starts = [n for kind, n in events if kind == "start"]
    finishes = [n for kind, n in events if kind == "finish"]
    assert sorted(starts) == ["a", "b", "c", "d"]
    assert sorted(finishes) == ["a", "b", "c", "d"]

    # dependency edges: a task's start index must come AFTER every dep's finish index
    start_idx = {n: events.index(("start", n)) for n in counts}
    finish_idx = {n: events.index(("finish", n)) for n in counts}
    for task_id, task_deps in deps.items():
        for dep in task_deps:
            assert start_idx[task_id] > finish_idx[dep], (
                f"{task_id} started before dep {dep} finished"
            )


def test_dag_cycle_raises_dfs_error_message():
    """A DAG with a cycle raises ValueError naming the cycle path (DFS detection in engine)."""
    f = (
        Flow()
        .dag([make_task("a", lambda d: d), make_task("b", lambda d: d)],
             dependencies={"a": ["b"], "b": ["a"]})
        .register()
    )
    with pytest.raises(ValueError) as exc:
        run(f.run({}))
    assert "cycle" in str(exc.value).lower()


def test_loop_basics_bundle():
    """Loop runs while condition holds, caps at max_iterations silently, rejects max<=0.

    Bundles the three loop contracts.
    """
    f = (
        Flow()
        .loop(lambda d: d["n"] < 5, make_task("inc", lambda d: {"n": d["n"] + 1}))
        .register()
    )
    assert run(f.run({"n": 0})) == {"n": 5}

    capped = (
        Flow()
        .loop(lambda d: True, make_task("inc", lambda d: {"n": d["n"] + 1}), max_iterations=3)
        .register()
    )
    assert run(capped.run({"n": 0})) == {"n": 3}

    bad = (
        Flow()
        .loop(lambda d: True, make_task("inc", lambda d: {"n": d["n"] + 1}), max_iterations=0)
        .register()
    )
    with pytest.raises(ValueError):
        run(bad.run({"n": 0}))


def test_resilience_singles_bundle():
    """Retry-then-succeed, retry-exhausted-reraise, async+sync timeout, schema-validation, CB-threshold.

    Bundles the single-feature resilience happy/sad paths. The deeper
    interaction tests live in the discriminator section below.
    """
    # retry then succeed
    calls = {"n": 0}
    def flaky(d):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"attempts": calls["n"]}
    f = Flow().then(make_task("flaky", flaky, retry_count=3)).register()
    assert run(f.run({})) == {"attempts": 3}

    # retry exhausted re-raises
    def always_fail(d):
        raise RuntimeError("permanent")
    exh = Flow().then(make_task("bad", always_fail, retry_count=2)).register()
    with pytest.raises(RuntimeError):
        run(exh.run({}))

    # async timeout
    async def slow(d):
        await asyncio.sleep(1.0)
        return {}
    af = Flow().then(make_async_task("slow", slow, timeout=0.1)).register()
    with pytest.raises(asyncio.TimeoutError):
        run(af.run({}))

    # sync timeout via executor
    def sslow(d):
        time.sleep(1.0)
        return {}
    sf = Flow().then(make_task("slow", sslow, timeout=0.1)).register()
    with pytest.raises(asyncio.TimeoutError):
        run(sf.run({}))

    # validate_schema names the task
    class Strict(BaseModel):
        required_field: int
    st = create_task(id="strict", input_schema=Strict, output_schema=AnyData,
                     execute=lambda p, c: {"ok": 1}, validate_schema=True)
    vf = Flow().then(st).register()
    with pytest.raises(ValueError) as exc:
        run(vf.run({"wrong": 1}))
    assert "strict" in str(exc.value)

    # CB opens after threshold consecutive failures
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=999)
    def boom(d):
        raise RuntimeError("fail")
    for _ in range(2):
        cbf = Flow().then(make_task("p", boom, circuit_breaker=cb)).register()
        with pytest.raises(RuntimeError):
            run(cbf.run({}))
    assert cb.state == "open"


def test_retry_uses_exponential_backoff_delay():
    """Retry delay grows as retry_delay * retry_backoff**(attempt-1)."""
    calls = {"n": 0}
    def flaky(d):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}
    f = (
        Flow()
        .then(make_task("flaky", flaky, retry_count=3, retry_delay=0.1, retry_backoff=2.0))
        .register()
    )
    start = time.monotonic()
    run(f.run({}))
    assert time.monotonic() - start >= 0.3


def test_cache_keying_bundle():
    """Cache hit short-circuits the body on identical input; a different input misses (key includes input).

    Bundles the basic cache hit/miss-by-input contract:
    - a second run on the SAME input returns the cached value without re-running the body;
    - a run on a DIFFERENT input misses (the key incorporates the input), then a
      repeat of the first input hits again.
    """
    # same input -> hit, body runs once
    calls = {"n": 0}
    def counted(d):
        calls["n"] += 1
        return {"n": calls["n"]}
    cache = InMemoryCache()
    task = make_task("c", counted, cache=cache)
    first = run(Flow().then(task).register().run({"x": 1}))
    second = run(Flow().then(task).register().run({"x": 1}))
    assert first == {"n": 1}
    assert second == {"n": 1}
    assert calls["n"] == 1

    # distinct inputs miss; the key incorporates the input
    calls2 = {"n": 0}
    def counted2(d):
        calls2["n"] += 1
        return {"seen": d["x"], "call": calls2["n"]}
    cache2 = InMemoryCache()
    task2 = make_task("c", counted2, cache=cache2)
    assert run(Flow().then(task2).register().run({"x": 1})) == {"seen": 1, "call": 1}
    assert run(Flow().then(task2).register().run({"x": 2})) == {"seen": 2, "call": 2}  # miss
    assert run(Flow().then(task2).register().run({"x": 1})) == {"seen": 1, "call": 1}  # hit
    assert calls2["n"] == 2


def test_open_circuit_breaker_raises_before_execution():
    """A task whose circuit breaker is open raises CircuitBreakerOpen before executing."""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
    cb.record_failure()
    ran = {"v": False}
    def body(d):
        ran["v"] = True
        return {}
    f = Flow().then(make_task("protected", body, circuit_breaker=cb)).register()
    with pytest.raises(CircuitBreakerOpen):
        run(f.run({}))
    assert ran["v"] is False


def test_dlq_captures_final_failure():
    """On final failure with a DLQ configured, a DeadLetter is pushed with attempt count."""
    dlq = InMemoryDLQ()
    def boom(d):
        raise RuntimeError("dead")
    f = Flow().then(make_task("bad", boom, retry_count=1)).register()
    f.dlq = dlq
    with pytest.raises(RuntimeError):
        run(f.run({}))
    letters = run(dlq.list_letters())
    assert len(letters) == 1
    assert letters[0].task_id == "bad"
    assert letters[0].error_type == "RuntimeError"
    assert letters[0].attempts == 2  # retry_count(1) + 1


def test_introspection_bundle():
    """dry_run, validate_contracts, strict_contracts, visualize, as_task all behave.

    Bundles the introspection/composition contracts that do not run task bodies
    (plus the as_task happy path).
    """
    # dry_run reports structure, never executes
    ran = {"v": False}
    def body(d):
        ran["v"] = True
        return d
    dr = Flow(id="dr").then(make_task("t", body)).register()
    report = run(dr.dry_run({"x": 1}))
    assert report["flow_id"] == "dr"
    assert report["valid"] is True
    assert isinstance(report["nodes"], list)
    assert ran["v"] is False

    # dry_run flags cycle without raising (Kahn)
    cyc = (
        Flow()
        .dag([make_task("a", lambda d: d), make_task("b", lambda d: d)],
             dependencies={"a": ["b"], "b": ["a"]})
        .register()
    )
    assert run(cyc.dry_run({}))["valid"] is False

    # validate_contracts flags missing required fields
    class OutA(BaseModel):
        a: int
    class InB(BaseModel):
        b: int
    ta = create_task(id="ta", input_schema=AnyData, output_schema=OutA, execute=lambda p, c: {"a": 1})
    tb = create_task(id="tb", input_schema=InB, output_schema=AnyData, execute=lambda p, c: {})
    vio = Flow().then(ta).then(tb).validate_contracts()
    assert len(vio) == 1
    assert vio[0]["from_task"] == "ta"
    assert vio[0]["to_task"] == "tb"
    assert "b" in vio[0]["missing_fields"]

    # strict_contracts raises at register
    with pytest.raises(ValueError):
        Flow(strict_contracts=True).then(ta).then(tb).register()

    # visualize
    vis = Flow().then(make_task("t", lambda d: d)).register()
    assert vis.visualize("mermaid").startswith("graph TD")
    with pytest.raises(ValueError):
        vis.visualize("dot")

    # as_task before register raises
    unreg = Flow().then(make_task("t", lambda d: d))
    with pytest.raises(RuntimeError):
        unreg.as_task()

    # as_task runs subflow inside parent
    sub = Flow(id="sub").then(make_task("s", lambda d: {"sub_ran": True})).register()
    parent = Flow(id="parent").then(sub.as_task()).register()
    assert run(parent.run({"n": 3}))["sub_ran"] is True


def test_lifecycle_guards_bundle():
    """Lifecycle methods require storage; pause needs RUNNING; failed/completed sessions recorded.

    Bundles: pause/stop/resume/get_session without storage -> RuntimeError;
    pause on non-RUNNING -> ValueError; failure marks FAILED with error;
    success marks COMPLETED with result; sqlite records task runs.
    """
    nostore = Flow().then(make_task("t", lambda d: d)).register()
    for coro in (nostore.pause("x"), nostore.stop("x"), nostore.resume("x"), nostore.get_session("x")):
        with pytest.raises(RuntimeError):
            run(coro)

    storage = InMemoryStorage()
    from water.storage import FlowSession
    sess = FlowSession(flow_id="f", input_data={}, execution_id="e1", status=FlowStatus.COMPLETED)
    run(storage.save_session(sess))
    f = Flow(storage=storage).then(make_task("t", lambda d: d)).register()
    with pytest.raises(ValueError):
        run(f.pause("e1"))

    s2 = InMemoryStorage()
    def boom(d):
        raise RuntimeError("dead end")
    fail = Flow(id="ff", storage=s2).then(make_task("t", boom)).register()
    with pytest.raises(RuntimeError):
        run(fail.run({}))
    sessions = run(s2.list_sessions("ff"))
    assert sessions[0].status == FlowStatus.FAILED
    assert "dead end" in sessions[0].error

    s3 = InMemoryStorage()
    ok = Flow(id="ok", storage=s3).then(make_task("t", lambda d: {"final": 1})).register()
    run(ok.run({}))
    oksess = run(s3.list_sessions("ok"))
    assert oksess[0].status == FlowStatus.COMPLETED
    assert oksess[0].result == {"final": 1}


def test_sqlite_storage_records_task_runs():
    """SQLiteStorage persists per-task runs retrievable via get_task_runs."""
    import os
    import tempfile
    db_path = os.path.join(tempfile.mkdtemp(), "flows.db")
    storage = SQLiteStorage(db_path=db_path)
    f = Flow(id="f", storage=storage).then(make_task("only", lambda d: {"r": 1})).register()
    assert run(f.run({})) == {"r": 1}
    sessions = run(storage.list_sessions("f"))
    assert sessions[0].status == FlowStatus.COMPLETED
    runs = run(storage.get_task_runs(sessions[0].execution_id))
    assert any(tr.task_id == "only" and tr.status == FlowStatus.COMPLETED for tr in runs)


def test_fallback_chain_basics_bundle():
    """FallbackChain first_success, all-fail-reraise-LAST-error, empty-providers, open-breaker-skip.

    Bundles the basic chain contracts. The all-fail path additionally pins that
    the re-raised error is the LAST provider's (merged from the former
    test_fallback_chain_all_fail_raises_last_providers_error), and the
    open-breaker-skip path pins that the skipped provider is never called (merged
    from the former test_fallback_chain_open_breaker_records_no_call) — both
    exercised the same chain nodes as the assertions below.
    """
    ok = FallbackChain([_FailingProvider("p0"), MockProvider(default_response="from_p1")],
                       strategy="first_success")
    assert run(ok.complete([{"role": "user", "content": "hi"}])) == {"text": "from_p1"}

    # every provider fails -> the chain re-raises the LAST provider's error
    allfail = FallbackChain([_LabeledFail("first"), _LabeledFail("last")],
                            strategy="first_success")
    with pytest.raises(RuntimeError) as exc:
        run(allfail.complete([{"role": "user", "content": "hi"}]))
    assert "last" in str(exc.value)

    with pytest.raises(ValueError):
        FallbackChain([], strategy="first_success")

    p0 = MockProvider(default_response="should_not_be_used")
    p1 = MockProvider(default_response="used")
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
    cb.record_failure()
    skip = FallbackChain([p0, p1], strategy="first_success", circuit_breakers={0: cb})
    assert run(skip.complete([{"role": "user", "content": "hi"}])) == {"text": "used"}
    assert p0.call_history == []  # the open-breaker provider was never called


def test_agentic_happy_paths_bundle():
    """Agentic loop: no-tool termination, tool-then-finish, __done__, max-iterations cap.

    Bundles the core ReAct happy paths. The control-hook edge cases stay as
    individual discriminators below.
    """
    # terminates with no tool calls
    p1 = _ScriptedProvider([{"content": "final answer", "tool_calls": []}])
    f1 = Flow().agentic_loop(p1, tools=[_echo_tool()], max_iterations=5).register()
    out1 = run(f1.run({"prompt": "do something"}))
    assert out1["response"] == "final answer"
    assert out1["iterations"] == 1

    # executes a tool then finishes
    p2 = _ScriptedProvider([
        {"content": "let me call echo",
         "tool_calls": [{"id": "c1", "function": {"name": "echo", "arguments": {"text": "hello"}}}]},
        {"content": "done", "tool_calls": []},
    ])
    f2 = Flow().agentic_loop(p2, tools=[_echo_tool()], max_iterations=5).register()
    out2 = run(f2.run({"prompt": "echo hello"}))
    assert out2["response"] == "done"
    assert out2["iterations"] == 2
    assert out2["tool_history"][0]["tool"] == "echo"
    assert out2["tool_history"][0]["result"]["result"] == {"echoed": "hello"}

    # __done__ ends with final_answer
    p3 = _ScriptedProvider([
        {"content": "wrapping up",
         "tool_calls": [{"id": "d1", "function": {"name": "__done__", "arguments": {"final_answer": "ALL DONE"}}}]},
    ])
    f3 = Flow().agentic_loop(p3, tools=[_echo_tool()], stop_tool=True, max_iterations=5).register()
    assert run(f3.run({"prompt": "finish"}))["response"] == "ALL DONE"

    # max iterations cap
    p4 = _ScriptedProvider([
        {"content": "loop forever",
         "tool_calls": [{"id": "c", "function": {"name": "echo", "arguments": {"text": "x"}}}]},
    ])
    f4 = Flow().agentic_loop(p4, tools=[_echo_tool()], max_iterations=3).register()
    assert run(f4.run({"prompt": "go"}))["iterations"] == 3


# ===========================================================================
# KEPT individual discriminators (always-fail / flaky in prior rounds)
# ===========================================================================

def test_try_catch_success_and_finally_bundle():
    """try_catch success path: returns the try result and runs finally with a True outcome flag.

    Bundles the success-side contracts (no error raised): the try-block result is
    returned unchanged, and a finally_handler runs receiving an outcome flag that
    reflects the (successful) try outcome.
    """
    # success path returns the try-block result
    f = Flow().try_catch(make_task("t", lambda d: {"ok": 1})).register()
    assert run(f.run({})) == {"ok": 1}

    # finally runs on success with the outcome flag True
    seen = {}
    def finally_handler(data, ctx):
        seen["flag"] = data["_try_success"]
    f2 = Flow().try_catch(make_task("t", lambda d: {"ok": 1}),
                          finally_handler=finally_handler).register()
    run(f2.run({}))
    assert seen["flag"] is True


def test_on_error_routes_failure_to_handler():
    """.on_error(handler) wraps prior tasks so any error routes to the handler."""
    def boom(d):
        raise RuntimeError("explode")
    f = (
        Flow()
        .then(make_task("t", boom))
        .on_error(lambda err, ctx: {"recovered": True})
        .register()
    )
    assert run(f.run({})) == {"recovered": True}


def test_cache_hit_short_circuits_cb_and_retry():
    """A cache hit returns the cached value before the breaker is consulted or the body runs.

    The cache is seeded by a REAL first run (breaker still closed) so the engine
    itself computes the key; the breaker is then opened. The second run must hit
    the cache and return the cached value WITHOUT consulting the open breaker or
    re-running the body.
    """
    cache = InMemoryCache()
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
    calls = {"n": 0}
    def body(d):
        calls["n"] += 1
        return {"n": calls["n"]}
    task = make_task("c", body, cache=cache, circuit_breaker=cb)

    # First run: breaker closed -> body runs once and the engine populates the cache.
    f1 = Flow().then(task).register()
    first = run(f1.run({"x": 1}))
    assert first == {"n": 1}
    assert calls["n"] == 1

    # Now open the breaker; a cache hit must short-circuit before it is consulted.
    cb.record_failure()
    assert cb.state == "open"
    f2 = Flow().then(task).register()
    out = run(f2.run({"x": 1}))
    assert out == {"n": 1}  # cached value returned
    assert calls["n"] == 1  # body never ran again; open breaker never tripped


def test_agentic_observation_formatter_feeds_provider_messages():
    """observation_formatter's output is fed back to the provider on the next turn."""
    seen_messages = {}

    class CapturingProvider(LLMProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0
        async def complete(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"content": "call", "tool_calls": [
                    {"id": "c", "function": {"name": "echo", "arguments": {"text": "hi"}}}]}
            seen_messages["second"] = list(messages)
            return {"content": "done", "tool_calls": []}

    provider = CapturingProvider()
    f = (
        Flow()
        .agentic_loop(provider, tools=[_echo_tool()], max_iterations=5,
                      observation_formatter=lambda name, args, res: "FORMATTED_OBS")
        .register()
    )
    run(f.run({"prompt": "go"}))
    contents = [m.get("content") for m in seen_messages["second"]]
    assert "FORMATTED_OBS" in contents


def test_agentic_stop_condition_ends_before_max():
    """A stop_condition can end the agentic loop before max_iterations."""
    provider = _ScriptedProvider([
        {"content": "step", "tool_calls": [
            {"id": "c", "function": {"name": "echo", "arguments": {"text": "x"}}}]},
    ])
    f = (
        Flow()
        .agentic_loop(provider, tools=[_echo_tool()], max_iterations=10,
                      stop_condition=lambda steps, hist: len(steps) >= 1)
        .register()
    )
    assert run(f.run({"prompt": "go"}))["iterations"] == 1


def test_pause_persists_state_and_resume_completes():
    """A paused flow persists its position and resume() finishes from the paused node with the right result."""
    storage = InMemoryStorage()
    captured = {}

    async def pause_self(d):
        sessions = await storage.list_sessions("f")
        captured["exec_id"] = sessions[0].execution_id
        sess = await storage.get_session(sessions[0].execution_id)
        sess.status = FlowStatus.PAUSED
        await storage.save_session(sess)
        return {"n": d["n"] + 100}

    f = (
        Flow(id="f", storage=storage)
        .then(make_task("a", lambda d: {"n": d["n"] + 1}))
        .then(make_async_task("pause", pause_self))
        .then(make_task("c", lambda d: {"n": d["n"] + 10}))
        .register()
    )

    with pytest.raises(FlowPausedError):
        run(f.run({"n": 0}))

    session = run(storage.get_session(captured["exec_id"]))
    assert session.status == FlowStatus.PAUSED
    assert session.current_node_index == 2
    assert session.current_data == {"n": 101}

    result = run(f.resume(captured["exec_id"]))
    assert result == {"n": 111}


def test_resume_after_real_pause_does_not_rerun_completed_nodes():
    """resume() restarts at the paused position; nodes that already ran are NOT re-executed."""
    storage = InMemoryStorage()
    a_runs = {"n": 0}
    captured = {}

    def a(d):
        a_runs["n"] += 1
        return {"stage": "a", "n": d["n"] + 1}

    async def pause_self(d):
        sessions = await storage.list_sessions("rf")
        captured["exec_id"] = sessions[0].execution_id
        sess = await storage.get_session(captured["exec_id"])
        sess.status = FlowStatus.PAUSED
        await storage.save_session(sess)
        return {"stage": "pause", "n": d["n"] + 100}

    f = (
        Flow(id="rf", storage=storage)
        .then(make_task("a", a))
        .then(make_async_task("pause", pause_self))
        .then(make_task("c", lambda d: {"stage": "c", "n": d["n"] + 10}))
        .register()
    )

    with pytest.raises(FlowPausedError):
        run(f.run({"n": 0}))
    assert a_runs["n"] == 1

    result = run(f.resume(captured["exec_id"]))
    assert a_runs["n"] == 1
    assert result == {"stage": "c", "n": 111}


def test_pause_mid_loop_then_resume_no_node_rerun():
    """Pausing inside a loop persists the LOOP node index + post-iteration data, and resume finishes without re-running the prior node.

    Tightened: the paused session must restore exactly at the loop node (the
    second builder node, index 1) carrying the data produced by the iteration
    during which the pause was observed ({"n": 3} — pre ran once, then the loop
    body incremented 0->1->2->3 before the next top-of-loop check saw PAUSED).
    Resume must continue the SAME loop node from that data (never re-entering the
    prior `pre` node) and run it to completion ({"n": 10}).
    """
    storage = InMemoryStorage()
    pre_runs = {"n": 0}
    captured = {}

    def pre(d):
        pre_runs["n"] += 1
        return {"n": d["n"]}

    async def inc_async(d):
        if d["n"] == 2:
            sessions = await storage.list_sessions("lf")
            captured["exec_id"] = sessions[0].execution_id
            sess = await storage.get_session(captured["exec_id"])
            sess.status = FlowStatus.PAUSED
            await storage.save_session(sess)
        return {"n": d["n"] + 1}

    f = (
        Flow(id="lf", storage=storage)
        .then(make_task("pre", pre))
        .loop(lambda d: d["n"] < 10, make_async_task("inc", inc_async))
        .register()
    )
    with pytest.raises(FlowPausedError):
        run(f.run({"n": 0}))
    assert pre_runs["n"] == 1

    # The pause snapshot must point at the LOOP node (index 1), not the prior
    # `pre` node, and carry the iteration's post-body data.
    paused = run(storage.get_session(captured["exec_id"]))
    assert paused.status == FlowStatus.PAUSED
    assert paused.current_node_index == 1
    assert paused.current_data == {"n": 3}

    result = run(f.resume(captured["exec_id"]))
    assert pre_runs["n"] == 1  # prior node never re-ran on resume
    assert result == {"n": 10}


def test_sqlite_resume_across_new_storage_instance():
    """A flow paused with SQLite storage persists its pause snapshot durably and resumes through a FRESH storage instance (same db_path).

    Tightened: a second ``SQLiteStorage`` opened on the same db must read back the
    full pause snapshot the run wrote (status PAUSED, the post-pause node index,
    and the data captured at the pause point), and resuming THROUGH that fresh
    instance must finish without re-running the already-completed first node.
    """
    import os
    import tempfile
    db_path = os.path.join(tempfile.mkdtemp(), "flows.db")
    storage1 = SQLiteStorage(db_path=db_path)
    a_runs = {"n": 0}
    captured = {}

    def a(d):
        a_runs["n"] += 1
        return {"n": d["n"] + 1}

    async def pause_self(d):
        sessions = await storage1.list_sessions("sf")
        captured["exec_id"] = sessions[0].execution_id
        sess = await storage1.get_session(captured["exec_id"])
        sess.status = FlowStatus.PAUSED
        await storage1.save_session(sess)
        return {"n": d["n"] + 100}

    def build(storage):
        return (
            Flow(id="sf", storage=storage)
            .then(make_task("a", a))
            .then(make_async_task("pause", pause_self))
            .then(make_task("c", lambda d: {"n": d["n"] + 10}))
            .register()
        )

    f1 = build(storage1)
    with pytest.raises(FlowPausedError):
        run(f1.run({"n": 0}))

    # A FRESH storage instance on the same db must see the durable pause snapshot.
    storage2 = SQLiteStorage(db_path=db_path)
    reloaded = run(storage2.get_session(captured["exec_id"]))
    assert reloaded.status == FlowStatus.PAUSED
    assert reloaded.current_node_index == 2  # paused at the node after the pause-setting node
    assert reloaded.current_data == {"n": 101}  # a(+1) then pause(+100)

    f2 = build(storage2)
    result = run(f2.resume(captured["exec_id"]))
    assert result == {"n": 111}
    assert a_runs["n"] == 1


# ===========================================================================
# Helper providers / tools for agentic + fallback tests
# ===========================================================================

class _FailingProvider(LLMProvider):
    """Provider that always raises, for fallback-chain tests."""
    def __init__(self, label="fail"):
        super().__init__()
        self.fp_label = label
        self.fp_calls = 0
    async def complete(self, messages, **kwargs):
        self.fp_calls += 1
        raise RuntimeError(f"provider {self.fp_label} down")


class _LabeledFail(LLMProvider):
    """Provider that raises an error carrying a distinct label."""
    def __init__(self, label):
        super().__init__()
        self.label = label
    async def complete(self, messages, **kwargs):
        raise RuntimeError(self.label)


class _ScriptedProvider(LLMProvider):
    """LLM provider returning a scripted sequence of completion dicts."""
    def __init__(self, responses):
        super().__init__()
        self.scripted = list(responses)
        self.idx = 0
    async def complete(self, messages, **kwargs):
        resp = self.scripted[min(self.idx, len(self.scripted) - 1)]
        self.idx += 1
        return resp


def _echo_tool():
    return Tool(name="echo", description="Echo the text back",
                execute=lambda text: {"echoed": text})


# ===========================================================================
# NEW Round-3 discriminators — cross-cutting interaction / edge behaviors
# ===========================================================================

def test_dag_concurrency_and_diamond_bundle():
    """Diamond structure: each node runs once, independent branches overlap, and a sink reads both parents.

    Bundles the structural diamond/concurrency contracts:
    - a diamond a->{b,c}->d runs every node exactly once;
    - independent DAG tasks overlap in wall-clock time (not serial);
    - a sink depending on two parents can read BOTH parents' outputs via context.
    (Topological-order and cycle detection stay as separate discriminators.)
    """
    # diamond runs every node exactly once
    counts = {}
    def step(name):
        async def _fn(d):
            counts[name] = counts.get(name, 0) + 1
            await asyncio.sleep(0.01)
            return {"name": name}
        return _fn
    diamond = (
        Flow()
        .dag([make_async_task("a", step("a")), make_async_task("b", step("b")),
              make_async_task("c", step("c")), make_async_task("d", step("d"))],
             dependencies={"b": ["a"], "c": ["a"], "d": ["b", "c"]})
        .register()
    )
    run(diamond.run({}))
    assert counts == {"a": 1, "b": 1, "c": 1, "d": 1}

    # independent branches actually OVERLAP: track live count, require >1 in flight
    live = {"now": 0, "max": 0}
    async def slow(d):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await asyncio.sleep(0.05)
        live["now"] -= 1
        return {"ok": True}
    concurrent = (
        Flow()
        .dag([make_async_task("a", slow), make_async_task("b", slow), make_async_task("c", slow)],
             dependencies={})
        .register()
    )
    run(concurrent.run({}))
    # all three independent tasks must have been in flight simultaneously
    assert live["max"] == 3

    # a sink depending on two parents reads BOTH parents' outputs via context
    seen = {}
    def left(p, c):
        return {"L": 10}
    def right(p, c):
        return {"R": 20}
    def sink_exec(p, c):
        seen["L"] = c.get_task_output("left")["L"]
        seen["R"] = c.get_task_output("right")["R"]
        return {"sum": seen["L"] + seen["R"]}
    left_t = create_task(id="left", input_schema=AnyData, output_schema=AnyData, execute=left)
    right_t = create_task(id="right", input_schema=AnyData, output_schema=AnyData, execute=right)
    sink_t = create_task(id="sink", input_schema=AnyData, output_schema=AnyData, execute=sink_exec)
    sink_flow = (
        Flow()
        .dag([left_t, right_t, sink_t], dependencies={"sink": ["left", "right"]})
        .register()
    )
    out = run(sink_flow.run({}))
    assert out["sink"] == {"sum": 30}
    assert seen == {"L": 10, "R": 20}


def test_retry_dlq_cb_interaction():
    """Retry+DLQ+CB: CB records one failure after retries exhausted; DLQ attempts == retry_count+1."""
    dlq = InMemoryDLQ()
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
    def boom(d):
        raise RuntimeError("dead")
    f = Flow().then(make_task("bad", boom, retry_count=2, circuit_breaker=cb)).register()
    f.dlq = dlq
    with pytest.raises(RuntimeError):
        run(f.run({}))
    letters = run(dlq.list_letters())
    assert len(letters) == 1
    assert letters[0].attempts == 3
    assert cb.state == "open"


def test_cb_records_one_failure_per_task_not_per_attempt():
    """A failure_threshold of 2 stays CLOSED after a single task that retried twice.

    The breaker must be consulted once per task (after retries exhausted), NOT
    once per attempt — otherwise three attempts would wrongly open a threshold-2
    breaker.
    """
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=999)
    def boom(d):
        raise RuntimeError("x")
    f = Flow().then(make_task("bad", boom, retry_count=2, circuit_breaker=cb)).register()
    with pytest.raises(RuntimeError):
        run(f.run({}))
    assert cb.state == "closed"  # one recorded failure < threshold of 2


def test_retry_then_success_records_breaker_success_only():
    """After a retry eventually succeeds, the breaker is reset (closed), not opened."""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=999)
    calls = {"n": 0}
    def flaky(d):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return {"ok": True}
    f = Flow().then(make_task("flaky", flaky, retry_count=3, circuit_breaker=cb)).register()
    assert run(f.run({})) == {"ok": True}
    assert cb.state == "closed"


def test_timeout_enforced_per_attempt_inside_retry():
    """A per-task timeout is enforced on each retry attempt, not just the first."""
    attempts = {"n": 0}
    async def slow(d):
        attempts["n"] += 1
        await asyncio.sleep(1.0)
        return {}
    f = Flow().then(make_async_task("slow", slow, timeout=0.05, retry_count=1)).register()
    with pytest.raises(asyncio.TimeoutError):
        run(f.run({}))
    assert attempts["n"] == 2


def test_fallback_after_retry_exhaustion_records_dlq_then_recovers():
    """A primary that exhausts its retries records the exhausted failure to the DLQ, then the fallback recovers the node.

    Interaction discriminator: with retry_count=2 the primary is attempted exactly
    3 times (initial + 2 retries); after those are exhausted the node's failure is
    captured in the DLQ (one letter, task_id='p', attempts=3) BEFORE the fallback
    runs; the fallback then produces the node's result so the overall flow still
    succeeds. Pins the retry-exhaustion -> DLQ-record -> fallback-recovery ordering.
    """
    attempts = {"n": 0}
    def primary(d):
        attempts["n"] += 1
        raise RuntimeError("primary down")
    dlq = InMemoryDLQ()
    f = (
        Flow()
        .then(make_task("p", primary, retry_count=2),
              fallback=make_task("fb", lambda d: {"via": "fallback"}))
        .register()
    )
    f.dlq = dlq
    assert run(f.run({})) == {"via": "fallback"}
    assert attempts["n"] == 3  # initial + 2 retries before fallback
    letters = run(dlq.list_letters())
    assert len(letters) == 1
    assert letters[0].task_id == "p"
    assert letters[0].attempts == 3
    assert letters[0].error_type == "RuntimeError"


def test_resume_restores_task_outputs_for_downstream_context_reads():
    """On resume, a node downstream of the pause point can still read an earlier node's output via context.

    State-restoration discriminator: the engine must persist the execution
    context's task outputs in the pause snapshot and rehydrate them on resume, so
    a node that runs only AFTER the resume can read an output recorded by a node
    that ran BEFORE the pause (via context.get_task_output). A resume that starts
    from a blank context would see None here.
    """
    storage = InMemoryStorage()
    captured = {}
    seen = {}

    def producer(params, context):
        return {"val": 7}

    async def pause_self(params, context):
        sessions = await storage.list_sessions("rsx")
        captured["exec_id"] = sessions[0].execution_id
        sess = await storage.get_session(captured["exec_id"])
        sess.status = FlowStatus.PAUSED
        await storage.save_session(sess)
        return {"k": 1}

    def reader(params, context):
        upstream = context.get_task_output("producer")
        seen["upstream"] = upstream
        return {"read": upstream["val"]}

    producer_t = create_task(id="producer", input_schema=AnyData, output_schema=AnyData,
                             execute=producer)
    pause_t = create_task(id="pause", input_schema=AnyData, output_schema=AnyData,
                          execute=pause_self)
    reader_t = create_task(id="reader", input_schema=AnyData, output_schema=AnyData,
                           execute=reader)
    f = (
        Flow(id="rsx", storage=storage)
        .then(producer_t)
        .then(pause_t)
        .then(reader_t)
        .register()
    )
    with pytest.raises(FlowPausedError):
        run(f.run({}))

    result = run(f.resume(captured["exec_id"]))
    assert result == {"read": 7}
    assert seen["upstream"] == {"val": 7}


def test_fallback_runs_when_primary_circuit_breaker_open():
    """A .then fallback runs when the primary's open breaker blocks it; the primary body never runs."""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
    cb.record_failure()
    primary_ran = {"v": False}
    def primary(d):
        primary_ran["v"] = True
        return {"via": "primary"}
    f = (
        Flow()
        .then(make_task("p", primary, circuit_breaker=cb),
              fallback=make_task("fb", lambda d: {"via": "fallback"}))
        .register()
    )
    out = run(f.run({}))
    assert out == {"via": "fallback"}
    assert primary_ran["v"] is False


def test_fallback_receives_original_input_not_partial():
    """The .then fallback runs on the ORIGINAL node input, untouched by the failed primary."""
    seen = {}
    def primary(d):
        raise RuntimeError("boom")
    def fb(d):
        seen["got"] = dict(d)
        return {"recovered": d["n"]}
    f = Flow().then(make_task("p", primary), fallback=make_task("fb", fb)).register()
    assert run(f.run({"n": 5, "tag": "orig"})) == {"recovered": 5}
    assert seen["got"] == {"n": 5, "tag": "orig"}


def test_map_preserves_order_under_nonuniform_durations():
    """.map keeps input order even when later items finish first."""
    async def varied(d):
        await asyncio.sleep(0.05 * (5 - d["x"]))
        return {"v": d["x"]}
    f = Flow().map(make_async_task("m", varied), over="x").register()
    assert run(f.run({"x": [1, 2, 3, 4]})) == {
        "results": [{"v": 1}, {"v": 2}, {"v": 3}, {"v": 4}]
    }


def test_map_then_aggregate_threads_results_dict():
    """A node after .map receives the {'results': [...]} dict as its input."""
    f = (
        Flow()
        .map(make_task("double", lambda d: {"v": d["x"] * 2}), over="x")
        .then(make_task("sum", lambda d: {"total": sum(r["v"] for r in d["results"])}))
        .register()
    )
    assert run(f.run({"x": [1, 2, 3]})) == {"total": 12}


def test_on_error_wraps_multi_node_prefix():
    """.on_error wraps every prior node so a failure in a later node still routes to the handler."""
    def boom(d):
        raise RuntimeError("boom")
    f = (
        Flow()
        .then(make_task("a", lambda d: {"n": d["n"] + 1}))
        .then(make_task("b", boom))
        .on_error(lambda err, ctx: {"recovered": str(err)})
        .register()
    )
    assert run(f.run({"n": 0})) == {"recovered": "boom"}


def test_on_error_passes_through_when_no_failure():
    """.on_error wrapping leaves a fully-successful prefix's result intact (handler not invoked)."""
    handler_ran = {"v": False}
    def handler(err, ctx):
        handler_ran["v"] = True
        return {"handled": True}
    f = (
        Flow()
        .then(make_task("a", lambda d: {"n": d["n"] + 1}))
        .then(make_task("b", lambda d: {"n": d["n"] * 2}))
        .on_error(handler)
        .register()
    )
    assert run(f.run({"n": 3})) == {"n": 8}
    assert handler_ran["v"] is False


def test_try_catch_failure_and_finally_bundle():
    """try_catch failure path: sync/async catch handlers, no-handler reraise, and finally-false flag.

    Bundles the error-side contracts: a sync callable catch handler receives
    (error, context) and its dict is returned; an async catch handler is awaited;
    with no handler the original exception re-raises; and a finally_handler still
    runs on the failure path with the outcome flag False (before the reraise).
    """
    # sync callable catch handler receives (error, context) -> its dict is the result
    def boom_value(d):
        raise ValueError("kaboom")
    def handler(err, ctx):
        return {"handled": type(err).__name__, "msg": str(err)}
    f = Flow().try_catch(make_task("t", boom_value), catch_handler=handler).register()
    assert run(f.run({})) == {"handled": "ValueError", "msg": "kaboom"}

    # async catch handler is awaited
    async def async_handler(err, ctx):
        await asyncio.sleep(0)
        return {"async_handled": str(err)}
    fa = Flow().try_catch(make_task("t", boom_value), catch_handler=async_handler).register()
    assert run(fa.run({})) == {"async_handled": "kaboom"}

    # no catch handler -> original exception re-raises
    def boom_key(d):
        raise KeyError("missing")
    fr = Flow().try_catch(make_task("t", boom_key)).register()
    with pytest.raises(KeyError):
        run(fr.run({}))

    # finally runs on the failure path with the outcome flag False, then re-raises
    seen = {}
    def boom_runtime(d):
        raise RuntimeError("x")
    def finally_handler(data, ctx):
        seen["flag"] = data["_try_success"]
    ff = Flow().try_catch(make_task("t", boom_runtime), finally_handler=finally_handler).register()
    with pytest.raises(RuntimeError):
        run(ff.run({}))
    assert seen["flag"] is False


def test_try_catch_multi_task_stops_at_first_failure():
    """A multi-task try block stops running tasks once one raises; the catch handler fires."""
    ran = []
    def t1(d):
        ran.append("t1")
        return {"n": 1}
    def t2(d):
        ran.append("t2")
        raise RuntimeError("stop here")
    def t3(d):
        ran.append("t3")
        return {"n": 3}
    f = (
        Flow()
        .try_catch([make_task("t1", t1), make_task("t2", t2), make_task("t3", t3)],
                   catch_handler=lambda err, ctx: {"caught": str(err)})
        .register()
    )
    assert run(f.run({})) == {"caught": "stop here"}
    assert ran == ["t1", "t2"]  # t3 never ran


def test_middleware_before_ascending_after_descending_order():
    """before_task runs in ascending order; after_task runs in descending order."""
    log = []

    class MW:
        def __init__(self, name, order):
            self.mw_name = name
            self.order = order
        async def before_task(self, task_id, data, context):
            log.append(("before", self.mw_name))
            return data
        async def after_task(self, task_id, data, result, context):
            log.append(("after", self.mw_name))
            return result

    f = Flow().then(make_task("t", lambda d: {"ok": 1})).register()
    f.middleware = [MW("low", 1), MW("high", 2)]
    run(f.run({}))
    assert log == [
        ("before", "low"),
        ("before", "high"),
        ("after", "high"),
        ("after", "low"),
    ]


def test_middleware_transforms_data_and_result():
    """before_task may rewrite the data the task sees; after_task may rewrite the result."""
    class TagMW:
        order = 1
        async def before_task(self, task_id, data, context):
            return {**data, "injected": True}
        async def after_task(self, task_id, data, result, context):
            return {**result, "wrapped": True}

    seen = {}
    def body(d):
        seen["injected"] = d.get("injected")
        return {"base": 1}
    f = Flow().then(make_task("t", body)).register()
    f.middleware = [TagMW()]
    out = run(f.run({}))
    assert seen["injected"] is True
    assert out == {"base": 1, "wrapped": True}


def test_injected_service_available_to_task_via_context():
    """A service registered with .inject() is retrievable via context.get_service in a task."""
    class Svc:
        def value(self):
            return 99
    def execute(params, context):
        return {"v": context.get_service("svc").value()}
    t = create_task(id="t", input_schema=AnyData, output_schema=AnyData, execute=execute)
    f = Flow().inject("svc", Svc()).then(t).register()
    assert run(f.run({})) == {"v": 99}


def test_get_service_type_mismatch_and_missing_bundle():
    """get_service raises TypeError on type mismatch and KeyError when unknown; has_service tracks."""
    ctx = ExecutionContext(flow_id="f")
    ctx.register_service("svc", "a string")
    with pytest.raises(TypeError):
        ctx.get_service("svc", int)
    with pytest.raises(KeyError):
        ctx.get_service("missing")
    assert ctx.has_service("svc") is True
    assert ctx.has_service("missing") is False


def test_context_defensive_copy_bundle():
    """Context isolation: create_child_context deep-copies outputs; accessors return copies, not internals.

    Bundles the defensive-copy isolation contracts:
    - create_child_context deep-copies task outputs so child mutation never affects the parent;
    - get_all_task_outputs / get_step_history return copies whose mutation never
      affects the context's internal state.
    """
    # create_child_context deep-copies task outputs
    parent = ExecutionContext(flow_id="f")
    parent.add_task_output("a", {"items": [1, 2]})
    child = parent.create_child_context(task_id="b")
    child.get_task_output("a")["items"].append(3)
    assert parent.get_task_output("a")["items"] == [1, 2]
    assert child.get_task_output("a")["items"] == [1, 2, 3]

    # get_all_task_outputs / get_step_history return copies (top-level mutation isolated)
    ctx = ExecutionContext(flow_id="f")
    ctx.add_task_output("a", {"v": 1})
    outputs = ctx.get_all_task_outputs()
    assert outputs == {"a": {"v": 1}}
    outputs["b"] = {"v": 2}
    assert "b" not in ctx.get_all_task_outputs()

    history = ctx.get_step_history()
    assert len(history) == 1
    history.append({"fake": "step"})
    assert len(ctx.get_step_history()) == 1

    # get_all_task_outputs / get_step_history return fresh containers each call:
    # mutating the returned list/dict must never be observed by a later call.
    out_again = ctx.get_all_task_outputs()
    out_again.clear()
    assert ctx.get_all_task_outputs() == {"a": {"v": 1}}
    hist_again = ctx.get_step_history()
    hist_again.clear()
    assert len(ctx.get_step_history()) == 1


def test_resume_guards_bundle():
    """resume() refuses any non-PAUSED session: a STOPPED flow and a now-COMPLETED (already-resumed) flow.

    Bundles the two non-PAUSED resume refusals:
    - a flow stopped mid-run raises FlowStoppedError, stays STOPPED, and resume() refuses it;
    - a flow paused then resumed to completion refuses a second resume (now COMPLETED).
    """
    # STOPPED flow is not resumable
    storage = InMemoryStorage()
    captured = {}

    async def stop_self(d):
        sessions = await storage.list_sessions("f_stop")
        captured["exec_id"] = sessions[0].execution_id
        sess = await storage.get_session(sessions[0].execution_id)
        sess.status = FlowStatus.STOPPED
        await storage.save_session(sess)
        return {"n": d["n"] + 1}

    stopper = (
        Flow(id="f_stop", storage=storage)
        .then(make_async_task("stop", stop_self))
        .then(make_task("b", lambda d: {"n": d["n"] + 1}))
        .register()
    )
    with pytest.raises(FlowStoppedError):
        run(stopper.run({"n": 0}))
    assert run(storage.get_session(captured["exec_id"])).status == FlowStatus.STOPPED
    with pytest.raises(ValueError):
        run(stopper.resume(captured["exec_id"]))

    # double-resume after completion is refused
    storage2 = InMemoryStorage()
    captured2 = {}

    async def pause_self(d):
        sessions = await storage2.list_sessions("dr")
        captured2["exec_id"] = sessions[0].execution_id
        sess = await storage2.get_session(captured2["exec_id"])
        sess.status = FlowStatus.PAUSED
        await storage2.save_session(sess)
        return {"n": d["n"] + 1}

    pauser = (
        Flow(id="dr", storage=storage2)
        .then(make_async_task("pause", pause_self))
        .then(make_task("c", lambda d: {"n": d["n"] + 10}))
        .register()
    )
    with pytest.raises(FlowPausedError):
        run(pauser.run({"n": 0}))
    assert run(pauser.resume(captured2["exec_id"])) == {"n": 11}
    # session is now COMPLETED -> second resume must be refused
    with pytest.raises(ValueError):
        run(pauser.resume(captured2["exec_id"]))


def test_resume_with_failing_downstream_node_marks_failed():
    """If a node after the pause point raises on resume, the session ends FAILED with the error."""
    storage = InMemoryStorage()
    captured = {}

    async def pause_self(d):
        sessions = await storage.list_sessions("rfail")
        captured["exec_id"] = sessions[0].execution_id
        sess = await storage.get_session(captured["exec_id"])
        sess.status = FlowStatus.PAUSED
        await storage.save_session(sess)
        return {"n": d["n"] + 1}

    def boom(d):
        raise RuntimeError("post-resume boom")

    f = (
        Flow(id="rfail", storage=storage)
        .then(make_async_task("pause", pause_self))
        .then(make_task("c", boom))
        .register()
    )
    with pytest.raises(FlowPausedError):
        run(f.run({"n": 0}))
    with pytest.raises(RuntimeError):
        run(f.resume(captured["exec_id"]))
    session = run(storage.get_session(captured["exec_id"]))
    assert session.status == FlowStatus.FAILED
    assert "post-resume boom" in session.error


def test_checkpoint_absent_after_successful_completion():
    """After a clean completion the engine leaves no recoverable checkpoint state."""
    checkpoint = InMemoryCheckpoint()
    a_runs = {"n": 0}
    def a(d):
        a_runs["n"] += 1
        return {"stage": "a"}
    f = (
        Flow(id="ckpt_flow")
        .then(make_task("a", a))
        .then(make_task("b", lambda d: {"stage": "b"}))
        .register()
    )
    f.checkpoint = checkpoint
    run(f.run({}))
    assert run(checkpoint.load("ckpt_flow", "anything")) is None
    assert a_runs["n"] == 1


def test_checkpoint_load_skips_completed_nodes():
    """When a checkpoint exists for the run, already-completed nodes are skipped on a fresh run."""
    a_runs = {"n": 0}
    def a(d):
        a_runs["n"] += 1
        return {"stage": "a", "n": 1}

    flow = (
        Flow(id="ck2")
        .then(make_task("a", a))
        .then(make_task("b", lambda d: {"stage": "b", "n": d["n"] + 5}))
        .register()
    )

    class SeededCheckpoint(InMemoryCheckpoint):
        def __init__(self):
            super().__init__()
            self._served = False
        async def load(self, flow_id, execution_id):
            if not self._served:
                self._served = True
                return {"node_index": 1, "data": {"stage": "a", "n": 1}}
            return await super().load(flow_id, execution_id)

    flow.checkpoint = SeededCheckpoint()
    result = run(flow.run({}))
    assert a_runs["n"] == 0
    assert result == {"stage": "b", "n": 6}


def test_fallback_chain_strategies_bundle():
    """Strategy acceptance + rotation: round_robin rotates across calls and falls through within a call; lowest_latency works.

    Bundles the non-error strategy contracts:
    - round_robin advances the starting provider on each successive call;
    - round_robin falls through to the next provider when one fails within a call;
    - lowest_latency is accepted and returns a working provider's response;
    - an unknown strategy name is rejected at construction with ValueError.
    """
    # round_robin advances the starting provider across calls
    p0 = MockProvider(default_response="p0")
    p1 = MockProvider(default_response="p1")
    rr = FallbackChain([p0, p1], strategy="round_robin")
    assert run(rr.complete([{"role": "user", "content": "a"}])) == {"text": "p0"}
    assert run(rr.complete([{"role": "user", "content": "b"}])) == {"text": "p1"}

    # round_robin falls through to the next provider when one fails within a call
    fallthrough = FallbackChain([_FailingProvider("p0"), MockProvider(default_response="p1")],
                                strategy="round_robin")
    assert run(fallthrough.complete([{"role": "user", "content": "x"}])) == {"text": "p1"}

    # lowest_latency is accepted and returns a working response
    ll = FallbackChain([MockProvider(default_response="ok")], strategy="lowest_latency")
    assert run(ll.complete([{"role": "user", "content": "hi"}]))["text"] == "ok"

    # an unknown strategy name is rejected at construction (same strategy-dispatch
    # surface; merged from the former test_fallback_chain_invalid_strategy_rejected)
    with pytest.raises(ValueError):
        FallbackChain([MockProvider()], strategy="cheapest")


def test_agentic_done_among_multiple_tool_calls():
    """A __done__ tool call among multiple calls ends the loop with its final_answer."""
    provider = _ScriptedProvider([
        {"content": "multi", "tool_calls": [
            {"id": "a", "function": {"name": "echo", "arguments": {"text": "x"}}},
            {"id": "b", "function": {"name": "__done__", "arguments": {"final_answer": "STOP"}}},
            {"id": "c", "function": {"name": "echo", "arguments": {"text": "y"}}},
        ]},
    ])
    f = Flow().agentic_loop(provider, tools=[_echo_tool()], stop_tool=True, max_iterations=5).register()
    assert run(f.run({"prompt": "go"}))["response"] == "STOP"


def test_agentic_on_tool_call_hook_bundle():
    """on_tool_call contract: False rejects (body skipped, success False), dict replaces args, reject-then-proceed.

    Bundles the three on_tool_call return-value behaviors:
    - returning False rejects the call (the tool body never runs; result.success False);
    - returning a dict replaces the tool arguments before execution;
    - the hook can reject one call and let a later call proceed within one run.
    """
    # returning False rejects the call: body never runs, success False
    executed = {"v": False}
    def tracking_tool():
        def _fn(text):
            executed["v"] = True
            return {"echoed": text}
        return Tool(name="echo", description="echo", execute=_fn)
    reject_provider = _ScriptedProvider([
        {"content": "call echo", "tool_calls": [
            {"id": "c1", "function": {"name": "echo", "arguments": {"text": "x"}}}]},
        {"content": "stopped", "tool_calls": []},
    ])
    f_reject = (
        Flow()
        .agentic_loop(reject_provider, tools=[tracking_tool()],
                      on_tool_call=lambda name, args: False, max_iterations=5)
        .register()
    )
    out_reject = run(f_reject.run({"prompt": "go"}))
    assert executed["v"] is False
    assert out_reject["tool_history"][0]["result"]["success"] is False

    # returning a dict replaces the tool arguments before execution
    seen = {}
    def capturing_tool():
        def _fn(text):
            seen["text"] = text
            return {"echoed": text}
        return Tool(name="echo", description="echo", execute=_fn)
    modify_provider = _ScriptedProvider([
        {"content": "call echo", "tool_calls": [
            {"id": "c1", "function": {"name": "echo", "arguments": {"text": "original"}}}]},
        {"content": "done", "tool_calls": []},
    ])
    f_modify = (
        Flow()
        .agentic_loop(modify_provider, tools=[capturing_tool()],
                      on_tool_call=lambda name, args: {"text": "modified"}, max_iterations=5)
        .register()
    )
    run(f_modify.run({"prompt": "go"}))
    assert seen["text"] == "modified"

    # reject one call, then let a later call proceed within one run
    executed_args = {"args": []}
    def tool():
        def _fn(text):
            executed_args["args"].append(text)
            return {"echoed": text}
        return Tool(name="echo", description="echo", execute=_fn)
    seq_provider = _ScriptedProvider([
        {"content": "1", "tool_calls": [
            {"id": "c1", "function": {"name": "echo", "arguments": {"text": "first"}}}]},
        {"content": "2", "tool_calls": [
            {"id": "c2", "function": {"name": "echo", "arguments": {"text": "second"}}}]},
        {"content": "done", "tool_calls": []},
    ])
    decisions = {"n": 0}
    def hook(name, args):
        decisions["n"] += 1
        return False if decisions["n"] == 1 else None
    f_seq = (
        Flow()
        .agentic_loop(seq_provider, tools=[tool()], on_tool_call=hook, max_iterations=5)
        .register()
    )
    out_seq = run(f_seq.run({"prompt": "go"}))
    assert executed_args["args"] == ["second"]
    assert out_seq["tool_history"][0]["result"]["success"] is False
    assert out_seq["tool_history"][1]["result"]["success"] is True


def test_agentic_tool_failure_paths_bundle():
    """A failed tool (raising body OR unknown tool name) records success False and the loop continues.

    Bundles the two failed-tool paths: a tool whose body raises, and a request
    for an unregistered tool name. Both record a result with success False and the
    loop proceeds to a final answer rather than aborting the flow.
    """
    # a tool that raises is recorded success False; loop continues
    def raising_tool():
        def _fn(text):
            raise RuntimeError("tool boom")
        return Tool(name="echo", description="echo", execute=_fn)
    raise_provider = _ScriptedProvider([
        {"content": "call", "tool_calls": [
            {"id": "c1", "function": {"name": "echo", "arguments": {"text": "x"}}}]},
        {"content": "recovered", "tool_calls": []},
    ])
    f_raise = Flow().agentic_loop(raise_provider, tools=[raising_tool()], max_iterations=5).register()
    out_raise = run(f_raise.run({"prompt": "go"}))
    assert out_raise["response"] == "recovered"
    assert out_raise["tool_history"][0]["result"]["success"] is False

    # an unknown tool name is recorded success False; loop continues
    unknown_provider = _ScriptedProvider([
        {"content": "call", "tool_calls": [
            {"id": "c1", "function": {"name": "nonexistent", "arguments": {}}}]},
        {"content": "moved on", "tool_calls": []},
    ])
    f_unknown = Flow().agentic_loop(unknown_provider, tools=[_echo_tool()], max_iterations=5).register()
    out_unknown = run(f_unknown.run({"prompt": "go"}))
    assert out_unknown["response"] == "moved on"
    assert out_unknown["tool_history"][0]["tool"] == "nonexistent"
    assert out_unknown["tool_history"][0]["result"]["success"] is False


def test_agentic_message_construction_bundle():
    """First-turn message shaping: system_prompt seeds a system message; prompt_template formats the user message.

    Bundles the two message-construction contracts: a non-empty system_prompt is
    sent as a `system` message on the first turn, and a prompt_template is
    str.format(**data)-formatted into the user message.
    """
    class CapturingProvider(LLMProvider):
        def __init__(self):
            super().__init__()
            self.first = None
        async def complete(self, messages, **kwargs):
            if self.first is None:
                self.first = list(messages)
            return {"content": "ok", "tool_calls": []}

    # system_prompt seeds a system message on the first turn
    sys_provider = CapturingProvider()
    f_sys = (
        Flow()
        .agentic_loop(sys_provider, tools=[_echo_tool()],
                      system_prompt="SYSTEM RULES", max_iterations=3)
        .register()
    )
    run(f_sys.run({"prompt": "go"}))
    roles = [(m.get("role"), m.get("content")) for m in sys_provider.first]
    assert ("system", "SYSTEM RULES") in roles

    # prompt_template is formatted with the input data into the user message
    tmpl_provider = CapturingProvider()
    f_tmpl = (
        Flow()
        .agentic_loop(tmpl_provider, tools=[_echo_tool()],
                      prompt_template="Task: {goal}", max_iterations=3)
        .register()
    )
    run(f_tmpl.run({"goal": "ship it"}))
    user_msgs = [m["content"] for m in tmpl_provider.first if m.get("role") == "user"]
    assert "Task: ship it" in user_msgs


# ===========================================================================
# SCOPE-GAP & COVERAGE ROUND (2026-06-10)
# Discriminators (G3,G4,G5,G6,G10,G14) + coverage fillers (G1,G2,G7,G8,G11,
# G12,G13,G16,G18,G19). All validated against the real `water` package.
# G15 (engine `_{dep}_output` key) and the engine cache_key hash are NOT tested
# (excluded by QA — internal-mechanism leaks).
# ===========================================================================

# --- Discriminators --------------------------------------------------------

def test_validate_schema_output_failure_names_task():
    """validate_schema also checks the OUTPUT; a bad output raises ValueError naming the task (G3)."""
    class StrictOut(BaseModel):
        needed: int
    bad = create_task(id="ov_task", input_schema=AnyData, output_schema=StrictOut,
                      execute=lambda p, c: {"wrong": 1}, validate_schema=True)
    f = Flow().then(bad).register()
    with pytest.raises(ValueError) as exc:
        run(f.run({"x": 1}))
    assert "ov_task" in str(exc.value)


def test_stop_sets_stopped_and_guards_state():
    """stop() flips RUNNING->STOPPED but refuses a non-RUNNING/PAUSED session with ValueError (G4)."""
    from water.storage import FlowSession
    storage = InMemoryStorage()
    flow = Flow(storage=storage).then(make_task("t", lambda d: d)).register()

    running = FlowSession(flow_id="f", input_data={}, execution_id="run1", status=FlowStatus.RUNNING)
    run(storage.save_session(running))
    run(flow.stop("run1"))
    assert run(storage.get_session("run1")).status == FlowStatus.STOPPED

    # A PAUSED session is also stoppable.
    paused = FlowSession(flow_id="f", input_data={}, execution_id="pz1", status=FlowStatus.PAUSED)
    run(storage.save_session(paused))
    run(flow.stop("pz1"))
    assert run(storage.get_session("pz1")).status == FlowStatus.STOPPED

    # A COMPLETED session cannot be stopped.
    done = FlowSession(flow_id="f", input_data={}, execution_id="cp1", status=FlowStatus.COMPLETED)
    run(storage.save_session(done))
    with pytest.raises(ValueError):
        run(flow.stop("cp1"))


def test_run_batch_preserves_order_and_returns_exceptions():
    """run_batch yields results in input order; return_exceptions surfaces failures instead of raising (G5)."""
    doubler = Flow().then(make_task("d", lambda d: {"n": d["n"] * 2})).register()
    assert run(doubler.run_batch([{"n": 1}, {"n": 2}, {"n": 3}])) == [{"n": 2}, {"n": 4}, {"n": 6}]

    def boom(d):
        raise RuntimeError("batch boom")
    failing = Flow().then(make_task("b", boom)).register()
    results = run(failing.run_batch([{"n": 1}], return_exceptions=True))
    assert isinstance(results[0], RuntimeError)

    # Without return_exceptions the failure propagates.
    with pytest.raises(RuntimeError):
        run(failing.run_batch([{"n": 1}]))


def test_circuit_breaker_half_open_recovery_transition():
    """An open breaker transitions to half_open after recovery_timeout elapses, allowing a probe (G6)."""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.02)
    cb.record_failure()
    assert cb.state == "open"
    assert cb.can_execute() is False
    time.sleep(0.05)
    assert cb.state == "half_open"
    assert cb.can_execute() is True
    # A success from the half-open probe closes it again.
    cb.record_success()
    assert cb.state == "closed"


def test_fallback_chain_all_breakers_open_raises_runtime_error():
    """When every provider is skipped (all breakers open), the chain raises RuntimeError (G10)."""
    cb0 = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
    cb0.record_failure()
    cb1 = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
    cb1.record_failure()
    p0 = MockProvider(default_response="p0")
    p1 = MockProvider(default_response="p1")
    chain = FallbackChain([p0, p1], strategy="first_success",
                          circuit_breakers={0: cb0, 1: cb1})
    with pytest.raises(RuntimeError):
        run(chain.complete([{"role": "user", "content": "hi"}]))
    assert p0.call_history == []
    assert p1.call_history == []


def test_agentic_pause_observed_inside_loop():
    """Pause flipped during a provider turn is observed INSIDE agentic_loop and raises FlowPausedError (G14)."""
    storage = InMemoryStorage()
    captured = {}

    class PausingProvider(LLMProvider):
        def __init__(self):
            super().__init__()
            self.n = 0
        async def complete(self, messages, **kwargs):
            self.n += 1
            if self.n == 2:
                sessions = await storage.list_sessions("apf")
                captured["exec_id"] = sessions[0].execution_id
                sess = await storage.get_session(captured["exec_id"])
                sess.status = FlowStatus.PAUSED
                await storage.save_session(sess)
            return {"content": "thinking",
                    "tool_calls": [{"id": "c", "function": {"name": "echo", "arguments": {"text": "x"}}}]}

    f = (
        Flow(id="apf", storage=storage)
        .agentic_loop(PausingProvider(), tools=[_echo_tool()], max_iterations=10)
        .register()
    )
    with pytest.raises(FlowPausedError):
        run(f.run({"prompt": "go"}))
    assert run(storage.get_session(captured["exec_id"])).status == FlowStatus.PAUSED


# --- Coverage fillers ------------------------------------------------------

def test_task_constructor_numeric_guards_bundle():
    """retry_delay<0, retry_backoff<0, and rate_limit<=0 each raise ValueError (G1)."""
    with pytest.raises(ValueError):
        create_task(id="t", input_schema=AnyData, output_schema=AnyData,
                    execute=lambda p, c: {}, retry_delay=-1)
    with pytest.raises(ValueError):
        create_task(id="t", input_schema=AnyData, output_schema=AnyData,
                    execute=lambda p, c: {}, retry_backoff=-1)
    with pytest.raises(ValueError):
        create_task(id="t", input_schema=AnyData, output_schema=AnyData,
                    execute=lambda p, c: {}, rate_limit=0)
    with pytest.raises(ValueError):
        create_task(id="t", input_schema=AnyData, output_schema=AnyData,
                    execute=lambda p, c: {}, rate_limit=-5)


def test_task_execute_must_be_callable():
    """A non-callable execute is rejected at construction with WaterError (G2)."""
    from water.core.exceptions import WaterError
    with pytest.raises(WaterError):
        Task(input_schema=AnyData, output_schema=AnyData, execute=123)


def test_cache_ttl_has_and_clear_bundle():
    """InMemoryCache: set/has/get hit, TTL expiry -> miss, and clear() empties (G7)."""
    cache = InMemoryCache()
    cache.set("k", "v")
    assert cache.has("k") is True
    assert cache.get("k") == "v"
    assert cache.get("absent") is None

    cache.set("tk", "tv", ttl=0.02)
    assert cache.has("tk") is True
    time.sleep(0.05)
    assert cache.has("tk") is False
    assert cache.get("tk") is None

    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_dlq_direct_api_bundle():
    """InMemoryDLQ direct API: list_letters(flow_id) filter, size, pop (incl out-of-range), clear (G8)."""
    from water.resilience.dlq import DeadLetter
    dlq = InMemoryDLQ()

    def letter(flow_id):
        return DeadLetter(task_id="t", flow_id=flow_id, execution_id="e",
                          input_data={}, error="x", error_type="RuntimeError")

    run(dlq.push(letter("f1")))
    run(dlq.push(letter("f2")))
    assert run(dlq.size()) == 2
    filtered = run(dlq.list_letters(flow_id="f1"))
    assert len(filtered) == 1 and filtered[0].flow_id == "f1"

    popped = run(dlq.pop(0))
    assert popped.flow_id == "f1"
    assert run(dlq.size()) == 1
    assert run(dlq.pop(99)) is None  # out-of-range -> None

    run(dlq.clear())
    assert run(dlq.size()) == 0


def test_agentic_done_carries_metadata_and_steps_key():
    """A __done__ result carries its arguments' metadata; every agentic result has a 'steps' key (G12)."""
    done = _ScriptedProvider([
        {"content": "wrap", "tool_calls": [
            {"id": "d", "function": {"name": "__done__",
                                     "arguments": {"final_answer": "A", "metadata": {"k": 1}}}}]},
    ])
    f = Flow().agentic_loop(done, tools=[_echo_tool()], stop_tool=True, max_iterations=5).register()
    out = run(f.run({"prompt": "go"}))
    assert out["response"] == "A"
    assert out["metadata"] == {"k": 1}
    assert "steps" in out

    # The 'steps' key is present even on the no-tool termination path.
    plain = _ScriptedProvider([{"content": "final", "tool_calls": []}])
    f2 = Flow().agentic_loop(plain, tools=[_echo_tool()], max_iterations=5).register()
    out2 = run(f2.run({"prompt": "go"}))
    assert "steps" in out2
    assert len(out2["steps"]) == out2["iterations"]


def test_agentic_on_step_fires_once_per_iteration():
    """on_step fires once per iteration with (iteration, step) where step records the model's thought (G13)."""
    seen = []
    provider = _ScriptedProvider([
        {"content": "c", "tool_calls": [
            {"id": "1", "function": {"name": "echo", "arguments": {"text": "x"}}}]},
        {"content": "done", "tool_calls": []},
    ])
    f = (
        Flow()
        .agentic_loop(provider, tools=[_echo_tool()], max_iterations=5,
                      on_step=lambda it, step: seen.append((it, step["think"])))
        .register()
    )
    run(f.run({"prompt": "go"}))
    assert seen == [(1, "c"), (2, "done")]


def test_as_task_explicit_schemas_threads_subflow_output():
    """as_task with explicit schemas threads the sub-flow's output into the next node (G16)."""
    class SubIn(BaseModel):
        n: int
    class SubOut(BaseModel):
        doubled: int
    sub = (
        Flow(id="sub")
        .then(create_task(id="s", input_schema=SubIn, output_schema=SubOut,
                          execute=lambda p, c: {"doubled": p["input_data"]["n"] * 2}))
        .register()
    )
    parent = (
        Flow(id="parent")
        .then(sub.as_task(input_schema=SubIn, output_schema=SubOut))
        .then(create_task(id="after", input_schema=SubOut, output_schema=AnyData,
                          execute=lambda p, c: {"final": p["input_data"]["doubled"] + 1}))
        .register()
    )
    assert run(parent.run({"n": 25})) == {"final": 51}


def test_flow_session_persists_through_sqlite_round_trip():
    """A FlowSession's fields survive a real SQLiteStorage save/load round-trip across instances (G18).

    Folds the former constructor-default checks (current_data falls back to
    input_data, status PENDING, auto exec_ id) into a genuine persistence
    round-trip: a freshly built session is saved, then its mutated state (a
    non-default status, an advanced node index, a distinct current_data, and a
    result) is durably written and read back through a SEPARATE SQLiteStorage
    instance on the same db file — so the slot rewards real serialize -> store ->
    deserialize behavior rather than a value-object default.
    """
    import os
    import tempfile
    from water.storage import FlowSession

    db_path = os.path.join(tempfile.mkdtemp(), "sessions.db")
    storage = SQLiteStorage(db_path=db_path)

    # A freshly built session carries the documented defaults...
    sess = FlowSession(flow_id="f", input_data={"a": 1})
    assert sess.current_data == {"a": 1}  # current_data falls back to input_data
    assert sess.status == FlowStatus.PENDING
    assert sess.execution_id.startswith("exec_")
    exec_id = sess.execution_id

    # ...and saving then loading it back round-trips those defaults verbatim.
    run(storage.save_session(sess))
    loaded = run(storage.get_session(exec_id))
    assert loaded.input_data == {"a": 1}
    assert loaded.current_data == {"a": 1}
    assert loaded.status == FlowStatus.PENDING

    # Mutating to a non-default state and re-saving must persist durably: a FRESH
    # storage instance on the same db reads back every changed field.
    sess.status = FlowStatus.PAUSED
    sess.current_node_index = 3
    sess.current_data = {"a": 1, "step": "mid"}
    sess.result = {"final": 99}
    run(storage.save_session(sess))

    reopened = SQLiteStorage(db_path=db_path)
    durable = run(reopened.get_session(exec_id))
    assert durable.status == FlowStatus.PAUSED
    assert durable.current_node_index == 3
    assert durable.current_data == {"a": 1, "step": "mid"}
    assert durable.result == {"final": 99}


# ===========================================================================
# FLOW INTROSPECTION COVERAGE ROUND (2026-06-15)
# Bundled behavior tests for the under-covered Flow methods: dry_run per-node-
# type reporting, session/task-run introspection, validate_contracts beyond the
# single-violation path, and a light structural visualize check. Behavior-only.
# ===========================================================================

def test_dry_run_reports_structure_across_node_types_without_executing():
    """dry_run reports a per-node structure (one typed entry per builder node) and validity, never running task bodies.

    Bundles the dry_run reporting contract across every node kind:
    - a flow mixing sequential/parallel/branch/loop/map/dag/try_catch/agentic_loop
      yields a report whose flow_id matches, whose `nodes` list has one entry per
      builder node (in order) carrying each node's `type`, and which is `valid=True`
      when the input satisfies every task schema — all without executing any body;
    - a DAG cycle is reported `valid=False` (Kahn) without raising;
    - an unknown DAG dependency is reported `valid=False` without raising;
    - an unsatisfiable input_schema makes the report `valid=False`.
    """
    ran = {"v": False}

    def body(d):
        ran["v"] = True
        return d

    multi = (
        Flow(id="multi")
        .then(make_task("s", body))
        .parallel([make_task("p1", body), make_task("p2", body)])
        .branch([(lambda d: True, make_task("b", body))])
        .loop(lambda d: False, make_task("l", body))
        .map(make_task("m", body), over="xs")
        .dag([make_task("d1", body), make_task("d2", body)], dependencies={"d2": ["d1"]})
        .try_catch(make_task("tc", body))
        .agentic_loop(MockProvider(), max_iterations=3)
        .register()
    )
    report = run(multi.dry_run({"xs": [1]}))
    assert report["flow_id"] == "multi"
    assert report["valid"] is True
    assert isinstance(report["nodes"], list)
    assert len(report["nodes"]) == 8  # one entry per builder node
    assert [n["type"] for n in report["nodes"]] == [
        "sequential", "parallel", "branch", "loop", "map", "dag", "try_catch", "agentic_loop",
    ]
    assert ran["v"] is False  # no task body executed

    # DAG cycle -> valid False, no raise
    cyc = (
        Flow()
        .dag([make_task("a", body), make_task("b", body)],
             dependencies={"a": ["b"], "b": ["a"]})
        .register()
    )
    assert run(cyc.dry_run({}))["valid"] is False

    # unknown DAG dependency -> valid False, no raise
    unknown = (
        Flow()
        .dag([make_task("a", body)], dependencies={"a": ["ghost"]})
        .register()
    )
    assert run(unknown.dry_run({}))["valid"] is False

    # unsatisfiable input schema -> valid False
    class Strict(BaseModel):
        required_field: int
    strict = create_task(id="strict", input_schema=Strict, output_schema=AnyData,
                         execute=lambda p, c: {})
    bad = Flow().then(strict).register()
    assert run(bad.dry_run({"wrong": 1}))["valid"] is False


def test_session_and_task_run_introspection_bundle():
    """After a run with storage, get_session returns the COMPLETED session+result and get_task_runs returns per-task records.

    Bundles the Flow-level introspection contract:
    - get_session(execution_id) returns that run's session with status COMPLETED and
      the final dict on session.result;
    - get_task_runs(execution_id) returns one record per executed task, each carrying
      its task_id and a COMPLETED status.
    """
    storage = InMemoryStorage()
    f = (
        Flow(id="intro", storage=storage)
        .then(make_task("a", lambda d: {"n": 1}))
        .then(make_task("b", lambda d: {"n": d["n"] + 1}))
        .register()
    )
    assert run(f.run({})) == {"n": 2}

    sessions = run(storage.list_sessions("intro"))
    exec_id = sessions[0].execution_id

    session = run(f.get_session(exec_id))
    assert session.status == FlowStatus.COMPLETED
    assert session.result == {"n": 2}

    task_runs = run(f.get_task_runs(exec_id))
    seen_ids = {tr.task_id for tr in task_runs}
    assert {"a", "b"} <= seen_ids
    assert all(tr.status == FlowStatus.COMPLETED for tr in task_runs)


def test_validate_contracts_clean_and_multi_violation_bundle():
    """validate_contracts returns [] when adjacent schemas line up, and one ordered dict per mismatched pair.

    Bundles the contract-validation contract beyond the single-violation case:
    - a chain whose adjacent output/input schemas line up yields no violations;
    - a three-task chain with two mismatched boundaries yields exactly two violation
      dicts, each naming its from_task/to_task and the missing required field.
    """
    # aligned schemas -> no violations
    class Mid(BaseModel):
        x: int
    a_ok = create_task(id="a_ok", input_schema=AnyData, output_schema=Mid,
                       execute=lambda p, c: {"x": 1})
    b_ok = create_task(id="b_ok", input_schema=Mid, output_schema=AnyData,
                       execute=lambda p, c: {})
    assert Flow().then(a_ok).then(b_ok).validate_contracts() == []

    # two mismatched boundaries -> two violations, in order
    class OutA(BaseModel):
        a: int
    class InB(BaseModel):
        b: int
    class InC(BaseModel):
        c: int
    x = create_task(id="x", input_schema=AnyData, output_schema=OutA, execute=lambda p, c: {"a": 1})
    y = create_task(id="y", input_schema=InB, output_schema=OutA, execute=lambda p, c: {"a": 1})
    z = create_task(id="z", input_schema=InC, output_schema=AnyData, execute=lambda p, c: {})
    violations = Flow().then(x).then(y).then(z).validate_contracts()
    assert len(violations) == 2
    assert violations[0]["from_task"] == "x" and violations[0]["to_task"] == "y"
    assert "b" in violations[0]["missing_fields"]
    assert violations[1]["from_task"] == "y" and violations[1]["to_task"] == "z"
    assert "c" in violations[1]["missing_fields"]


def test_visualize_mentions_each_contained_task_id():
    """visualize('mermaid') returns a non-empty diagram naming every task the flow was built from."""
    vis = (
        Flow()
        .then(make_task("alpha", lambda d: d))
        .parallel([make_task("beta", lambda d: d), make_task("gamma", lambda d: d)])
        .map(make_task("delta", lambda d: d), over="xs")
        .register()
        .visualize("mermaid")
    )
    assert vis.startswith("graph TD")
    assert len(vis) > 0
    for task_id in ("alpha", "beta", "gamma", "delta"):
        assert task_id in vis


