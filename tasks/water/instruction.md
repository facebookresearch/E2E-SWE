# `water` — an async workflow / agent-orchestration engine

Implement a Python package named **`water`** that provides an asynchronous workflow-orchestration
engine. A *flow* is built by chaining graph-building operators (sequential steps, branches,
parallel groups, DAGs, loops, agentic ReAct loops, try/catch) onto a `Flow` object, then
*registering* and *running* it. Every unit of work is a `Task` with Pydantic input/output schemas.
The engine layers in cross-cutting concerns: retries with backoff, timeouts, caching,
circuit-breaking, dead-letter queues, middleware, dependency injection, persistent
pause/stop/resume, and checkpoint-based crash recovery.

The public API is pure Python and fully async: build a `Flow`, call `await flow.run(input_dict)`,
get back a `dict`. There is no network access in the test environment — LLM providers are mocked.

## Setup

**The environment is fully offline — there is no network access, and you must not install
anything.** All dependencies are already installed in the image, and the project is installed for
you by a `setup.sh` that runs offline (it does `pip install -e . --no-build-isolation` against the
pre-installed packages). Just write your package so it builds and imports under that command.

The pre-installed runtime dependency the tested surface relies on is **`pydantic` (v2)**; the
async-orchestration API in this spec is built on it. (The environment also ships `fastapi` and
`uvicorn`, but the tested public surface does not require them — the suite drives async code via
`asyncio.run` and mocks all LLM providers, so no async-test plugin or network client is needed.)
The package must be importable as `water`.

## Import surface (must match exactly)

The following must be importable from the top-level `water` package:

```
Flow, Task, create_task, InMemoryStorage, SQLiteStorage, FlowStatus,
FlowPausedError, FlowStoppedError, CircuitBreaker, CircuitBreakerOpen,
InMemoryCache, InMemoryCheckpoint, InMemoryDLQ, FallbackChain, MockProvider,
ExecutionContext
```

These submodules and symbols must also exist at these exact paths:

- `water.core.exceptions` → `WaterError` (base exception class for the library)
- `water.agents.llm` → `LLMProvider`
- `water.agents.tools` → `Tool`
- `water.resilience.dlq` → `DeadLetter` (the dead-letter record type)
- `water.storage` → `FlowSession` (also re-exporting `FlowStatus`)

## Core data model

### `Task` / `create_task`
A `Task` wraps a callable with input/output schemas. `create_task(...)` is a thin factory that
constructs and returns a `Task`. Both accept (all keyword-usable):

`id`, `description`, `input_schema`, `output_schema`, `execute`,
`retry_count=0`, `retry_delay=0.0`, `retry_backoff=1.0`, `timeout=None`,
`validate_schema=False`, `rate_limit=None`, `cache=None`, `circuit_breaker=None`.

- `input_schema` / `output_schema` must be Pydantic `BaseModel` subclasses; if not, raise
  `WaterError`. `execute` must be callable (else `WaterError`).
- `execute` is invoked as `execute(params, context)` where `params` is a dict that always contains
  the key `"input_data"` (the current data dict flowing through the flow) and `context` is an
  `ExecutionContext`. `execute` may be sync or async and returns a dict.
- Constructor validation (raise `ValueError`): `retry_count < 0`, `retry_delay < 0`,
  `retry_backoff < 0`, `timeout <= 0` (when not `None`), `rate_limit <= 0` (when not `None`).
- If `id` is omitted, auto-generate one.

### `ExecutionContext`
Constructed as `ExecutionContext(flow_id=..., ...)`. It also accepts an optional `task_id` keyword
(the identifier of the current task, defaulting to `None`) among its constructor parameters. Carries
execution metadata and per-run state. Public methods/attributes the tests rely on:

- `register_service(name, service)` and `get_service(name, service_type=None)`. `get_service`
  raises `KeyError` if the name is unknown, and `TypeError` if `service_type` is given and the
  stored service is not an instance of it. Also `has_service(name)`.
- Task-output tracking: `add_task_output`, `get_task_output`, `get_all_task_outputs`,
  `get_step_history`, plus `create_child_context(task_id, ...)` — its first argument is the child
  task's `task_id` — which returns a new context deep-copying mutable state (task outputs, step
  history, services) so a child's mutations never affect the parent.
  Recording a task output (`add_task_output`) also appends exactly one entry to the step
  history, so the step history holds one entry per recorded task output.
- Accessor copy vs. reference semantics differ between the plural and singular accessors:
  `get_all_task_outputs` and `get_step_history` each return a **fresh defensive copy** on every
  call — mutating the returned dict/list (e.g. `append`/`clear`) never affects the context's
  internal state. The **singular** `get_task_output(task_id)`, in contrast, returns the context's
  **live stored output object** (not a fresh copy), so mutating that object in place is observed by
  a later `get_task_output(task_id)` call on the same context.
- Attributes including `flow_id`, `execution_id`, `step_number`, `attempt_number`.

## Flow builder

`Flow(id=None, description=None, storage=None, version=None, strict_contracts=False, max_concurrency=10)`.
If `id` is omitted, auto-generate it in the form `flow_<8 lowercase hex chars>` (total length 13).
A flow has mutable, directly-settable attributes used by the tests: `middleware` (list), `dlq`,
`checkpoint`.

All builder methods **return `self`** (chainable) and **must raise `RuntimeError` if called after
`register()`**. Builder methods:

- `.then(task, when=None, fallback=None)` — append a sequential step. `when` is a *sync* predicate
  `data -> bool`; if it returns falsy the step is skipped and data passes through unchanged. If the
  task raises and `fallback` (another Task) is supplied, the fallback runs on the *same* input and
  its result is used; if the primary succeeds the fallback never runs. `.then(None)` raises
  `ValueError`.
- `.map(task, over)` — run `task` once per element of `data[over]`. Raises `ValueError` if `over`
  is empty/falsy at build time.
- `.dag(tasks, dependencies=None)` — DAG of tasks. Raises `ValueError` if `tasks` is empty.
  `dependencies` maps a task id to the list of task ids it depends on.
- `.parallel(tasks)` — run tasks concurrently. Raises `ValueError` if `tasks` is empty.
- `.branch(branches)` — `branches` is a list of `(condition, task)` pairs. Raises `ValueError` if
  empty, or if any condition is a coroutine function (async conditions are rejected at build time).
- `.loop(condition, task, max_iterations=100)` — repeat while `condition(data)` is truthy.
- `.agentic_loop(provider, tools=None, system_prompt="", prompt_template="", max_iterations=10, temperature=0.7, max_tokens=1024, stop_tool=False, on_step=None, on_tool_call=None, stop_condition=None, observation_formatter=None)`
  — a ReAct loop. Raises `ValueError` at build time if `max_iterations <= 0`.
- `.try_catch(try_tasks, catch_handler=None, finally_handler=None)` — `try_tasks` may be a single
  task or a list of tasks.
- `.on_error(handler)` — wraps all previously added nodes so any error routes to `handler`. Raises
  `ValueError` if there are no prior tasks to wrap (and if `handler` is falsy).
- `.use(middleware)`, `.inject(name, service)`, `.set_metadata(key, value)`.

### Lifecycle / introspection

- `.register()` → returns `self`. Raises `ValueError` if the flow has no tasks. If
  `strict_contracts=True`, raise `ValueError` when a sequential contract violation exists
  (see *Contracts*).
- `await .run(input_data)` → final result dict. Raises `RuntimeError` if called before
  `register()`.
- `await .run_batch(inputs, max_concurrency=10, return_exceptions=False)` → list of results.
- `await .pause(execution_id)`, `await .stop(execution_id)`, `await .resume(execution_id)`,
  `await .get_session(execution_id)`, `await .get_task_runs(execution_id)`. After a completed run on
  a flow with storage, `get_session(execution_id)` returns that run's session (status `COMPLETED`,
  final dict on `session.result`) and `get_task_runs(execution_id)` returns the per-task `TaskRun`
  records produced by the run (one per executed task; see *Storage value types* for `TaskRun` shape).
- `await .dry_run(input_data)` → validation report dict (does NOT execute tasks).
- `.validate_contracts()` → list of violation dicts.
- `.visualize(format="mermaid")` → str.
- `.as_task(input_schema=None, output_schema=None)` → a `Task` that runs this (registered) sub-flow.
- `compose_flows(*flows)` and `SubFlow(...)` should exist for flow composition (not heavily
  exercised, but `as_task` is — see below).

## Execution semantics (this is where the real work is)

`flow.run(data)` threads `data` through the registered nodes in order, each node returning the dict
that becomes the next node's input. The final dict is returned.

### Sequential / conditional / fallback
- Chained `.then` steps pass each task's output dict as the next task's input.
- `when=` false → step skipped, data unchanged.
- `fallback=` runs on the original input when the primary task raises; its output replaces the
  result.

### Branch
- Execute the **first** branch whose condition returns truthy (order matters). If none match,
  return the input unchanged.

### Parallel
- Run all tasks concurrently (truly overlapping, not serial awaits).
- The combined result associates each task's output with that task's id (it is *not* a flat list).

### Map
- `data[over]` must be a list; if it is not, raise `ValueError` (when run).
- Produces one result per item with the original input order preserved; an empty list yields an
  empty result collection. The map result is a dict whose `results` key holds the per-item list.
- Each invocation receives the *full* data dict with the `over` key replaced by the single item.

### DAG
- With no dependencies, run all tasks and return `{task_id: result}`.
- Honor topological ordering: a task never starts until all its declared dependencies have
  completed; independent tasks may run concurrently.
- A task's upstream-dependency outputs must be reachable from within that task (e.g. via the
  execution context's per-task output tracking), so a downstream task can consume what its
  dependencies produced.
- **Cycle detection (engine):** when `run` executes a DAG containing a cycle, raise a
  `ValueError` whose message contains the word "cycle" (and names the cycle path).
- A dependency referencing an unknown task id raises `ValueError` at execution.

### Loop
- Repeat the task while `condition(data)` is truthy, feeding each iteration's output into the next.
- Stop at `max_iterations` **without raising** (cap silently) even if the condition stays truthy.
- `max_iterations <= 0` raises `ValueError` when the loop executes.

### try_catch / on_error
- Success path returns the try-block's result. A try block may contain multiple tasks run
  sequentially; if one raises, the remaining try tasks are not run and the catch path takes over.
- A callable catch handler may be sync or async; an async handler is awaited before its result is used.
- A **callable** catch handler is invoked as `handler(error, context)` and its returned dict is the
  result. (A Task catch handler is also supported, receiving the error information injected into its
  input data.)
- With no catch handler, the original exception is re-raised (after `finally` runs).
- `finally_handler`, when given, always runs (success and failure). A callable `finally_handler`
  is invoked as `finally_handler(data, context)`, where `data` is the data dict carrying a
  `_try_success` boolean that reflects whether the try block succeeded.
- `.on_error(handler)` wraps all prior nodes; any error anywhere routes to `handler(error, context)`.

## Per-task resilience (all wired through the single task-execution path)

- **Retry:** a task with `retry_count=N` is attempted up to `N` additional times; it succeeds if any
  attempt succeeds, otherwise the last error is re-raised. `retry_delay` and `retry_backoff` control
  the wait between attempts, with `retry_backoff > 1` producing exponentially growing delays.
- **Timeout:** a task exceeding `timeout` seconds raises `asyncio.TimeoutError`. This applies to
  both async tasks and blocking sync tasks (run the sync body in an executor so the timeout is
  enforceable).
- **validate_schema:** when `True`, validate the input against the task's `input_schema` (and output
  against `output_schema`); a validation failure raises `ValueError` whose message names the task id.
- **Cache:** when a `cache` is attached, a cache hit short-circuits execution and returns the cached
  value without re-running the task body. The cache key must be derived from the task id and its
  input so identical inputs hit. The cache is consulted **before** the circuit breaker, so a cache
  hit returns its value even when the breaker is open (short-circuiting both the breaker and retry).
  (See `InMemoryCache` below.)
- **Circuit breaker:** if an attached `circuit_breaker` is open, raise `CircuitBreakerOpen`
  *before* executing the body. The breaker is consulted/updated **once per task execution, not once
  per retry attempt**: a failure is recorded only after all retry attempts are exhausted, and a
  success is recorded once if any attempt succeeds. (So a task that retries N times and then fails
  counts as a single breaker failure; repeated failing task executions eventually open the breaker.)
- **Dead-letter queue:** if `flow.dlq` is set and a task fails terminally (after exhausting
  retries), push a `DeadLetter` describing the failure, then re-raise. The pushed letter records the
  failing `task_id`, the `error_type` (exception class name), and `attempts` (the total number of
  attempts that were made before giving up).

### Middleware ordering
`flow.middleware` is a list of middleware objects, each with an integer `order` attribute and async
`before_task(task_id, data, context)` / `after_task(task_id, data, result, context)` methods that
return (possibly transformed) `data` / `result`. Run `before_task` across all middleware in
**ascending** `order`, and `after_task` in **descending** `order` (nested-wrapper semantics).

### Dependency injection
Services registered via `flow.inject(name, service)` must be retrievable inside a task via
`context.get_service(name)`.

## Persistence: pause / stop / resume + storage

`Flow(storage=...)` takes a `StorageBackend`. Provide `InMemoryStorage` and `SQLiteStorage`
implementations. Persistence/session lifecycle:

- `pause`, `stop`, `resume`, and `get_session` raise `RuntimeError` if the flow has no storage.
- `pause(execution_id)` requires the session to be `RUNNING` (else `ValueError`); `resume` requires
  it to be `PAUSED` (a `STOPPED` session cannot be resumed → `ValueError`).
- `stop(execution_id)` requires the session to be `RUNNING` or `PAUSED` (else `ValueError`); it sets
  the session status to `STOPPED`.
- When a running session's status is flipped to `PAUSED` (by a concurrent task on the same loop),
  the engine pauses at the **next node boundary**: it raises `FlowPausedError`, and persists enough
  state on the session (its current position and the data so far, plus per-run execution state) so
  the run can continue later. The persisted `current_node_index` is the index of the *next* node to
  run, and `current_data` is the output dict produced by the last completed node.
- `resume(execution_id)` restores from the saved session and **restarts at the paused position**
  (already-completed nodes are NOT re-executed), rebuilds the per-run execution state, and returns
  the correct final result.
- When a session's status is flipped to `STOPPED`, the engine raises `FlowStoppedError`; the session
  remains `STOPPED` and `resume` refuses it.
- With storage configured, an uncaught task failure marks the session `FAILED` with the error text
  stored on `session.error`; a successful run marks it `COMPLETED` with the final result on
  `session.result`.
- Pause/stop must also be observed *inside* `loop`/`agentic_loop` iterations, not only at top-level
  node boundaries. For such an intra-loop pause (or stop), the persisted snapshot is loop-relative
  rather than following the top-level node-boundary rule above: `current_node_index` is the index of
  the loop node **itself** (so `resume` re-enters that same loop node rather than advancing to the
  next node), and `current_data` is the output dict produced by the loop-body iteration that had just
  completed when the paused/stopped status was observed (i.e. the loop's most recent iteration
  output, not the loop's pre-entry input). Thus `resume` continues the *same* loop mid-stream from
  that iteration's data, without re-running any node that preceded the loop.

### Storage value types
`FlowStatus` is a string enum with members `PENDING`, `RUNNING`, `PAUSED`, `STOPPED`, `COMPLETED`,
`FAILED`.

`FlowSession` (constructible directly in tests) takes keyword args:
`flow_id`, `input_data`, `execution_id`, `status` (a `FlowStatus`), `current_node_index`,
`current_data`, `context_state`, `result`, `error`. `context_state` carries whatever per-run
execution state is needed to rebuild an `ExecutionContext` on resume. Defaults: `execution_id` is
not required — when omitted it is auto-generated as `exec_<hex>`; `current_data` defaults to
`input_data`; `status` defaults to `PENDING`.

`StorageBackend` is an async interface; both storages implement:
`save_session(session)`, `get_session(execution_id) -> FlowSession|None`,
`list_sessions(flow_id=None) -> list`, `save_task_run(task_run)`,
`get_task_runs(execution_id) -> list`. A `TaskRun` record has at least `task_id` and `status`
(its `status` for a completed task equals `FlowStatus.COMPLETED`). `SQLiteStorage(db_path=...)`
persists across calls within a run and records a `TaskRun` per executed task.

## Checkpoint crash recovery

A flow may have a `checkpoint` backend (`flow.checkpoint = ...`). Implement `InMemoryCheckpoint`
(and an abstract `CheckpointBackend`). The backend stores per-`(flow_id, execution_id)` recovery
state. Its async API:

- `save(flow_id, execution_id, node_index, data)` — record the next node index and the data so far.
- `load(flow_id, execution_id) -> {"node_index": int, "data": dict} | None`.
- `clear(flow_id, execution_id)`.

Engine behavior: after each node, save a checkpoint; on a fresh `run`, consult `load(...)` and, if a
checkpoint is present, **skip already-completed nodes** (resume at the saved `node_index` with the
saved `data`); clear the checkpoint on successful completion. (The engine generates the
`execution_id` internally, so a test may subclass the checkpoint and override `load` to seed state.)

## dry_run / contracts / visualize / as_task

- `dry_run(input_data)` returns a dict with keys `flow_id`, `valid` (bool), `nodes` (a list), and
  `errors`, and must **not** execute any task body. It validates structure only. The `nodes` list
  has one entry per builder node, in order; each entry carries that node's `type` (the node-kind
  string, e.g. `sequential`/`parallel`/`branch`/`loop`/`map`/`dag`/`agentic_loop`/`try_catch`).
  A structurally-sound flow (input data satisfies every task's `input_schema`) reports `valid=True`;
  a flow with an unsatisfiable schema or a DAG defect reports `valid=False`.
- **Cycle detection (dry_run):** a DAG cycle is reported as `valid=False` *without raising*
  (a different path from the engine, which raises at run time). An
  unknown DAG dependency is likewise reported as `valid=False` without raising.
- `validate_contracts()` returns a list of violation dicts for adjacent sequential tasks where task
  N's `output_schema` cannot supply all required fields of task N+1's `input_schema`. Each violation
  dict has at least `from_task`, `to_task`, and `missing_fields` (a collection naming the missing
  required field). No violations → empty list.
- `register()` with `strict_contracts=True` raises `ValueError` if any contract violation exists.
- `visualize("mermaid")` returns a string beginning with `graph TD`. Any unsupported format (e.g.
  `"dot"`) raises `ValueError`. The string mentions each contained task's id (every node a flow was
  built from is represented in the diagram).
- `as_task()` before `register()` raises `RuntimeError`. After registering, it returns a `Task` that
  executes the sub-flow; embedding that task in a parent flow runs the sub-flow as one step.

## Resilience primitives

### `CircuitBreaker` / `CircuitBreakerOpen`
`CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)`. Methods `record_success()`,
`record_failure()`, `can_execute() -> bool`, and a `state` property returning one of
`"closed"`, `"open"`, `"half_open"`. It starts closed; after `failure_threshold` consecutive
failures it becomes `"open"`; after `recovery_timeout` seconds an open breaker transitions to
`"half_open"` (allowing a probe). `record_success()` resets it to closed. `CircuitBreakerOpen` is an
`Exception`.

### `InMemoryCache`
A task-result cache with `get(key)`, `set(key, value, ttl=None)`, `has(key)`, `clear()`. A miss
returns `None`. Used by the engine to memoize task results across runs of the *same* `Task` instance
on identical input.

### `InMemoryDLQ` / `DeadLetter`
`InMemoryDLQ()` with async methods `push(letter)`, `list_letters(flow_id=None) -> list`,
`pop(index=0)`, `clear()`, `size()`. `pop(index)` removes and returns the letter at `index`, or
returns `None` if the index is out of range (including a negative index). A `DeadLetter` is a
record with fields including `task_id`,
`flow_id`, `execution_id`, `input_data`, `error`, `error_type`, and `attempts`. Only the failure
descriptors are required to construct one: `attempts` is optional (it defaults when omitted), so a
`DeadLetter` can be built from just `task_id`/`flow_id`/`execution_id`/`input_data`/`error`/`error_type`.

## Agents: providers, fallback chain, tools, agentic loop

### `LLMProvider` / `MockProvider`
`LLMProvider` (in `water.agents.llm`) is an abstract base with an async method
`complete(messages, **kwargs) -> dict`. Subclasses (including the tests' own) call
`super().__init__()`, so the base must be instantiable in that sense. `complete` returns a dict
containing at least a `"text"` key.

`MockProvider(default_response="mock response", responses=None)`: each `complete(...)` call appends
the received `messages` to a public `call_history` list and returns `{"text": <response>}`. If
`responses` is given, return them in order (cycling); otherwise always return `default_response`.

### `FallbackChain`
`FallbackChain(providers, strategy="first_success", circuit_breakers=None)` — itself an
`LLMProvider`. Constructing with an empty `providers` list raises `ValueError`. `circuit_breakers`,
when given, is a dict mapping a provider **index** to a `CircuitBreaker`.

`await chain.complete(messages, **kwargs)` with `strategy="first_success"` tries providers in list
order and returns the first successful response; if every provider raises, it re-raises the **last**
error. A provider whose mapped circuit breaker is open is **skipped entirely** (its `complete` is
never called). If no provider is ever called because *every* mapped circuit breaker is open (so
there is no last error to re-raise), `complete` raises `RuntimeError`. An unknown strategy name is
rejected with `ValueError` at construction. Two other
strategies must also be accepted: `round_robin` (advances the starting provider forward by one on
each successive `complete` call, so consecutive calls to a healthy 2-provider chain answer from
provider 0 then provider 1) and `lowest_latency` (orders providers by observed average latency).

### `Tool`
`Tool(name=..., description=..., execute=...)` (in `water.agents.tools`). `execute` is a callable
invoked with keyword arguments matching the tool-call arguments. The agentic loop runs a tool and
records the outcome (see below).

### Agentic ReAct loop output
`agentic_loop` drives the provider in a think/act/observe loop. The provider returns completion
dicts shaped like `{"content": <str>, "tool_calls": [...]}`, where each tool call looks like
`{"id": <str>, "function": {"name": <tool name>, "arguments": {<kwargs>}}}`. The final flow result
is a dict with keys:

- `response` — the model's final text answer.
- `iterations` — number of loop iterations performed.
- `tool_history` — a list of executed-tool records, each a dict
  `{"iteration": int, "tool": <name>, "arguments": {...}, "result": {...}}`.
- `steps` — always present: a record of the per-iteration think/act/observe steps taken (one entry
  per loop iteration performed). When the loop ends via the `__done__` stop tool, the result also
  carries a `metadata` key holding the value of the call's `arguments["metadata"]`.

Message construction: if `system_prompt` is non-empty it is sent as the first message (role
`system`) on the first turn. If `prompt_template` is given it is `str.format(**data)`-formatted with
the input data to build the user message; otherwise the user message comes from `data["prompt"]`.

Termination and control:

- If a completion has no tool calls, the loop ends immediately; `response` is that completion's
  `content` and `iterations` counts that turn.
- When a tool is requested, execute it, feed the result back to the provider, and continue. Each
  tool record's `result` carries a `success` flag and, on success, the tool's output under a
  `result` field. If a tool raises, or the requested tool name is not registered, the record's
  `result` has `success` False (with error info) and the loop continues to the next turn rather than
  aborting the flow.
- With `stop_tool=True`, a tool call named `__done__` ends the loop with `response` set to the
  call's `arguments["final_answer"]`.
- `on_tool_call(name, args)` hook: returning `False` **rejects** the call (the tool is not executed;
  its recorded `result` has `success` False); returning a dict **replaces** the arguments before
  execution; otherwise the call proceeds unchanged.
- `on_step(iteration, step)` hook fires once per loop iteration. `iteration` is 1-based (the first
  loop iteration is `iteration=1`, the second `2`, …), matching the value reported in the result's
  `iterations` count for that turn; e.g. a two-turn run fires with `iteration=1` then `iteration=2`.
  `step` is the per-iteration record dict, which always carries a `think` key holding that turn's
  model content (alongside its act / observe records).
- `observation_formatter(tool_name, arguments, result)` is called for each executed tool; its
  returned string is injected into the conversation as the observation fed back to the provider in
  the next turn's messages.
- `stop_condition(steps, tool_history)` may end the loop early.
- If the model keeps calling tools, the loop stops at `max_iterations`, reporting that count in
  `iterations`.
