# PydanticAI — Agent Framework

Build `pydantic_ai`, a Python agent framework with type-safe structured outputs, tool registration, dependency injection, and conversation management. Also build `pydantic_graph`, a companion DAG workflow engine.

## Dependencies

The environment is **offline**: every dependency is **already installed** and the project is built by a `setup.sh` that runs with no network. **Do not install anything** — no `pip install` of new packages, and you never need (or have access to) the target package itself.

`pydantic_ai` depends on `pydantic>=2.12`, `pydantic-core`, `httpx>=0.27`, `anyio`, `opentelemetry-api>=1.28.0`, `typing-inspection>=0.4.0`, `griffelib>=2.0`, `genai-prices` (used for message cost calculation), and `pydantic_graph` (the companion package, built from this same repo). `pydantic_graph` depends on `pydantic`, `httpx`, `typing-inspection`, and `logfire-api`. All of these are pre-installed.

## Package Structure

The library is split into two packages: `pydantic_ai` (agent framework) and `pydantic_graph` (DAG workflow engine).

Key modules in `pydantic_ai`: agent core (`Agent`, `RunContext`, `ModelRetry`, `capture_run_messages`), test/function models, messages (request/response with typed parts), tools (`ToolDefinition`), settings (`ModelSettings`, `merge_model_settings`), usage tracking (`UsageLimits`, `RunUsage`), exceptions (`UserError`, `UsageLimitExceeded`), prompt formatting (`format_as_xml`), and run results (`AgentRunResult`).

Public import paths for the symbols that do not live at the top level: `TestModel` is imported from `pydantic_ai.models.test`; `FunctionModel` and `AgentInfo` from `pydantic_ai.models.function`; and `format_as_xml` from `pydantic_ai.format_prompt`. (`Agent`, `RunContext`, `ModelRetry`, and `capture_run_messages` are importable from the top-level `pydantic_ai` package; `messages`, `tools`, `settings`, `usage`, and `exceptions` are their own `pydantic_ai.*` submodules.)

Key modules in `pydantic_graph`: node base class (`BaseNode`, `End`, `GraphRunContext`), graph runner (`Graph`), and persistence (`SimpleStatePersistence`).

## Agent

`Agent(model, output_type=str, system_prompt="...", deps_type=T, retries=1, end_strategy='early', model_settings=...)` is the central class. The constructor-level `model_settings` are the agent's defaults; when `model_settings` is also given at run time the two are merged via `merge_model_settings` (run-level values win, other keys preserved) and the merged settings are what reach the model. Run with `agent.run_sync(prompt, deps=..., message_history=..., model=..., model_settings=..., usage_limits=...)` (sync) or `await agent.run(...)` (async). Both return `AgentRunResult` with `.output` (parsed result), `.all_messages()` (full history), `.new_messages()`, and `.usage` (RunUsage property with `total_tokens`, `request_tokens`, `response_tokens`). The `model` kwarg at run time overrides the agent's default. `Agent()` with no model raises `UserError` on run. `end_strategy` controls how tool calls that arrive alongside a final-result (output) tool call are handled: `'early'` (default) skips those extra function tool calls once a final result is set, while `'exhaustive'` still executes them.

## Tools

`@agent.tool_plain` registers a plain tool. `@agent.tool` registers a tool receiving `RunContext[DepsT]` as its first arg (must have at least one additional parameter). Both accept `retries=N` and `prepare=func`. Tools must have docstrings. Parameters are auto-converted to JSON schema (`required` for no-default params). Each tool produces a `ToolDefinition` with `name`, `description`, `parameters_json_schema` (dict with `properties` and `required`). A prepare function `async (ctx, tool_def) -> ToolDefinition | None` can exclude a tool by returning `None`.

## Dependency Injection

`RunContext[DepsT]` provides: `ctx.deps` (dependency object), `ctx.model`, `ctx.usage`, `ctx.messages`, `ctx.retry`, `ctx.tool_name`. Pass deps via `agent.run_sync(prompt, deps=my_deps)`.

## System Prompts

Static via `Agent(..., system_prompt="text")`. Dynamic via `@agent.system_prompt` decorator on functions returning `str` (optionally taking `RunContext`). Prompt text appears as parts in the first `ModelRequest`.

## Messages

`ModelRequest` has `parts: list[ModelRequestPart]` (includes `UserPromptPart`, system prompt parts, `ToolReturnPart`, `RetryPromptPart`). `ModelResponse` has `parts: list[ModelResponsePart]` (includes `TextPart`, `ToolCallPart`); it also carries a `model_name` attribute holding the name of the model that produced it (each response a model emits during a run is stamped with that model's name). `UserPromptPart.content: str`, `TextPart.content: str`, `ToolCallPart.tool_name/args`, `ToolReturnPart.tool_name/content`. A `ToolCallPart`'s `args` may be given either as a mapping of argument name to value **or** as a JSON-encoded string of such a mapping; when the framework executes the tool call it decodes a string-form `args` (JSON) into the mapping and invokes the tool with those values as keyword arguments — so a model emitting `ToolCallPart(tool_name="double", args='{"x": 5}')` results in the registered tool being called as `double(x=5)`. Continuation: pass `message_history=result.all_messages()` to a subsequent run. `pydantic_ai.messages` also exports `ModelMessage`, the union of `ModelRequest` and `ModelResponse` — i.e. the type of one element of a conversation history (the element type of the `messages` list a `FunctionModel` function receives: `(messages: list[ModelMessage], info) -> ModelResponse`, see FunctionModel below).

## Structured Output

`output_type=MyModel` (Pydantic BaseModel) uses tool-call mechanism for structured JSON. `output_type=Union[A, B]` returns matching variant. TestModel uses `custom_output_args` for structured output.

## Output Validators, Retries, Exceptions

`@agent.output_validator` validates output; raise `ModelRetry("msg")` to retry. Tools raise `ModelRetry` for retriable failures (up to `retries` times). `UserError` for invalid usage (e.g., no model). `UsageLimitExceeded` when a `UsageLimits` cap is exceeded. `UsageLimits` accepts `request_limit` (max model requests), `response_tokens_limit` (max response tokens), and `total_tokens_limit` (max total tokens).

Enforcement timing differs by which cap it is. `request_limit` is a pre-request guard: it raises before issuing a model request that would exceed the cap. The token caps (`response_tokens_limit` and `total_tokens_limit`) are instead enforced against the **cumulative** run usage **after each model response is produced and counted** — not only as a pre-request check. Consequently a token budget of `0` (or one that is already exhausted) raises `UsageLimitExceeded` as soon as a run produces any response that pushes the corresponding count over the cap: e.g. `response_tokens_limit=0` raises on a run that produces any response tokens, even a single-step run that returns after one response.

## TestModel

A deterministic model for testing. Output control: `TestModel(custom_output_text="...")` forces a fixed text response, while `TestModel(custom_output_args={...})` forces a fixed structured (tool-call) output. Tool-selection control: `TestModel(call_tools=...)` selects which registered tools to invoke — `'all'` (the default) calls every tool, or a list of tool names (e.g. `call_tools=['my_tool']`) restricts invocation to exactly those tools. When TestModel calls a tool it supplies argument values for that tool's required parameters (synthesized from the tool's `parameters_json_schema` — a placeholder of the appropriate declared type per parameter) so that even a tool with required parameters executes with valid arguments; the exact synthesized value is an arbitrary internal placeholder and is not part of the contract.

Retry-driving behavior: TestModel participates in the tool-retry loop. When one of the tools it called raises `ModelRetry`, the framework re-requests the model with a `RetryPromptPart` for that tool in the message history; on that retry turn TestModel re-issues the call for exactly the tool(s) named by a `RetryPromptPart` (rather than treating the retry prompt as a completed step and emitting final output). A tool's call is considered done — and TestModel stops re-calling it and moves on to producing output — only once that tool has produced a **successful `ToolReturnPart`**; a `RetryPromptPart` is not a completed call and does not count as done. Re-issuing stays within the tool's `retries` budget.

Usage: a run driven by TestModel reports **positive** token usage — TestModel counts at least one response token for each response it produces, so after a normal run `result.usage.response_tokens > 0` and `result.usage.total_tokens > 0` (with `request_tokens` also counted). The exact per-response token count is an arbitrary internal tokenization detail and not part of the contract, but the counts are always positive. This is what the token caps of `UsageLimits` are enforced against: a `response_tokens_limit=0` run raises `UsageLimitExceeded` because the single response contributes a positive response-token count that exceeds the zero budget.

It exposes `.model_name`, `.system`, and `.last_model_request_parameters` for introspection. `.system` returns the string `"test"`. `.model_name` returns the value passed to the constructor, or defaults to `"test"` when not given; this same `model_name` is recorded on every `ModelResponse` the TestModel produces. `last_model_request_parameters` exposes `function_tools`, a list of `ToolDefinition` objects for the tools offered on that request (use it to introspect which tools were offered).

## FunctionModel

A model backed by a user-supplied function `(messages: list[ModelMessage], info) -> ModelResponse` (`ModelMessage` is the request/response union from `pydantic_ai.messages`, see Messages above). The `info` argument is an `AgentInfo` exposing `function_tools` (a list of `ToolDefinition` for the available tools), `output_tools` (the `ToolDefinition` list for structured-output tools), and `model_settings`.

## ModelSettings

`ModelSettings` is a `TypedDict`-style mapping (not a class with attributes): `ModelSettings(temperature=..., max_tokens=...)` constructs one, and individual settings are read with dict access, e.g. `settings.get('temperature')`, `settings.get('max_tokens')`. When settings propagate to the model they arrive (via `AgentInfo.model_settings` in a `FunctionModel`) as this same mapping. `merge_model_settings(base, override)` merges two; override wins. Returns None if both None.

## Utilities

`capture_run_messages()` is a context manager that captures the messages exchanged during a run. The value it yields (the `with capture_run_messages() as messages` binding) **is** the run's ordered list of `ModelMessage` objects — a plain list-like sequence, not a wrapper object exposing them via an attribute. It is progressively populated as the enclosed run executes, so after the run `messages` supports `len(...)` (the number of captured messages) and direct iteration yielding the run's `ModelRequest`/`ModelResponse` objects (each with its `.parts` list). Thus a user can write `len(messages)` and `for m in messages: m.parts` directly on the bound value — e.g. capturing a single `run_sync` yields at least the request and response messages, whose parts include the run's `UserPromptPart` and `TextPart`. `format_as_xml(dict, root_tag=None)` converts a dict to an XML string: each top-level entry renders as `<key>value</key>` (the key is the tag, the value is stringified plainly with no escaping or type annotation), and there is no XML declaration and no trailing newline. When `root_tag` is omitted the entries are emitted as top-level elements joined by newlines with no outer wrapper. When `root_tag` is given the entries are wrapped in `<root_tag>...</root_tag>` on their own lines and indented two spaces.

## pydantic_graph

`BaseNode`, `End`, `GraphRunContext`, and `SimpleStatePersistence` are importable from the top-level `pydantic_graph` package; the `Graph` runner is defined in (and importable from) the `pydantic_graph.graph` submodule. Nodes extend `BaseNode[StateT, DepsT, RunEndT]` with async `run(self, ctx: GraphRunContext)` returning another node instance or `End(value)`. `GraphRunContext` provides `state` (mutable) and `deps`. `Graph(nodes=(A, B))` creates a graph; `await graph.run(start_node, state=s, deps=d)` returns `GraphRunResult` with `.output`. `graph.mermaid_code()` renders the graph as a Mermaid `stateDiagram`: transitions between nodes are written as `<SourceNodeClassName> --> <TargetNodeClassName>` (the node class names, single-space-padded arrows), and a node that returns `End(...)` renders a transition to the terminal marker `[*]`. `SimpleStatePersistence` enables in-memory state persistence via the `persistence=` kwarg of `graph.run(...)`: it records the run's snapshots and exposes the most recent one as `persistence.last_snapshot`. A completed run's terminal snapshot is an `EndSnapshot` (importable from the `pydantic_graph.persistence` submodule); the `End(value)` returned by the terminal node is available as `snapshot.result.data`, and the final graph state as `snapshot.state`.

## setup.sh

Create `setup.sh` in the working directory that installs the two packages from your source tree offline (the build backend and all dependencies are pre-installed; no network is available), e.g.:
`pip install -e ./pydantic_graph --no-build-isolation && pip install -e ./pydantic_ai_slim --no-build-isolation`
