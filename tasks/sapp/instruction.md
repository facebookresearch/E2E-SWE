# SAPP — taint-analysis output parsers

Build the **taint-output parsing layer** of SAPP (Static Analysis Post Processor),
importable as the package `sapp`. SAPP ingests the raw results of taint analyzers and
normalizes them. This task covers the two parsers that read analyzer output and the
normalized data model they produce:

- the **Pysa** taint-output parser, and
- the **Mariana Trench** taint-output parser.

A parser consumes one analysis-output document and produces a normalized set of
**issues** (a detected source→sink flow) and **trace frames** (the pre/postcondition
hops of a flow). The downstream database/UI layers are out of scope.

## Dependencies

The environment is **offline** — there is no network and you must not install
anything. Every dependency is already installed, and the project is built by a
`setup.sh` that runs offline (an editable install with no build isolation). Just
write the package source and a packaging config so that editable install works;
do not add a step that fetches packages.

The following are pre-installed and available to import (Python 3.8+):

- `ordered-set` — used directly by the parsers for deduplicated, ordered leaves.
- `SQLAlchemy`, `graphene`, `graphene-sqlalchemy`, `munch`, `pyre-extensions`,
  `typing-extensions` — the data-model / normalization layer this package builds
  on. Structure your imports so the parser modules above are importable; you do
  not need to use every one of these directly.

Declare your dependencies in packaging metadata as you see fit, but rely only on
what is listed here — nothing else can be fetched offline.

## Import paths (used by the tests)

```python
from sapp.analysis_output import AnalysisOutput, Metadata, Rule
from sapp.pipeline import (
    ParseError, ParseTypeInterval, ParseTraceFeature, ParseTraceAnnotation,
    ParseTraceAnnotationSubtrace, ParseConditionTuple, ParseIssueConditionTuple,
    ParseIssueTuple, SourceLocation,
)
from sapp.pipeline.base_parser import ParseType
from sapp.pipeline.pysa_taint_parser import Parser     # Pysa parser
from sapp.pipeline.mariana_trench_parser import Parser  # Mariana Trench parser
```

`SourceLocation` is defined in `sapp.source_location` but must also be importable from
`sapp.pipeline` (the example imports it there); `ParseType` is imported from
`sapp.pipeline.base_parser`. Internal organization is otherwise up to you.

## Input: `AnalysisOutput`

`AnalysisOutput(directory=None, filename_specs=None, file_handle=None, metadata=None)`
wraps an analyzer's output. For testing, a single in-memory document is passed via
`file_handle` (an `IO[str]`). It must expose the underlying handle(s) for reading so a
parser can iterate them.

- `Metadata` carries run context; the fields used here are `repo_roots` (set of
  absolute analysis roots, used to relativize paths) and `rules` (`{int: Rule}`, used
  to build Mariana Trench issue messages). It also accepts `analysis_tool_version`.
- `Rule` has `name` and `description`.

## Output data model (`sapp.pipeline`)

Comparable value types (e.g. `NamedTuple`s) with **exactly these fields/order** — tests
build expected values and compare for equality:

- `ParseType` — enum with `PRECONDITION`, `POSTCONDITION`.
- `ParseError` — exception raised on malformed/unsupported input.
- `SourceLocation(line_no, begin_column, end_column)`.
- `ParseTypeInterval(start, finish, preserves_type_context)`.
- `ParseTraceFeature(name, locations)` — `locations` is a list (empty in this task).
- `ParseTraceAnnotationSubtrace(callee, port, position, features=[], annotations=[])`.
- `ParseTraceAnnotation(location, kind, msg, leaf_kind, leaf_depth, type_interval,
  link, trace_key, titos, subtraces)`.
- `ParseConditionTuple(type, caller, caller_port, filename, callee, callee_port,
  callee_location, leaves, type_interval, features, titos, annotations)`.
- `ParseIssueConditionTuple(callee, port, location, leaves, titos, features,
  type_interval, annotations, root_port=None)`.
- `ParseIssueTuple(code, message, callable, handle, filename, line, start, end,
  preconditions, postconditions, initial_sources, final_sinks, features,
  callable_line, fix_info)`.

`leaves` in a condition is a **sorted list of unique `(kind, distance)` pairs**.
An issue's `initial_sources` / `final_sinks` are **sets of every leaf reached by its
forward / backward trace**, each as `(leaf-name-or-None, kind, distance)` (the leaf
*name* is kept here, unlike in condition frames). `features` on an issue is a **sorted
list of feature-name strings**.

## Parser API & frame collection

Both `Parser` classes share a base and expose:

- `Parser(repo_dirs=None)`.
- `parse_analysis_output(analysis_output) -> IssuesAndFrames`, returning an object with:
  - `.issues` — list of `ParseIssueTuple`.
  - `.preconditions`, `.postconditions` — each a `Frames` collection exposing
    `.all_frames()` (iterate its `ParseConditionTuple`s).
- While parsing, each emitted entry is either an issue (collected into `.issues`) or a
  condition frame. Condition frames are bucketed by their `ParseType`: `PRECONDITION`
  → `preconditions`, `POSTCONDITION` → `postconditions` (keyed internally by
  `(caller, caller_port)`).
- `.all_frames()` yields frames in **document (insertion) order**: frames are emitted in
  the order their producing fragments appear in the input, and multiple frames sharing the
  same `(caller, caller_port)` bucket preserve that insertion order. Only a frame's `leaves`
  and condition `features` are sorted — the frames themselves are not reordered.

## Shared normalization contracts

These apply to both parsers unless noted:

- **Positions → `SourceLocation`**: `line_no` = source line; `begin_column` = the
  analyzer's 0-based `start` column **plus 1**; `end_column` = the analyzer's `end`.
  (Mariana Trench overrides the end-column formula to `end = max(end+1, start)` — see
  the Mariana Trench objects section.)
- **Features**: each becomes `ParseTraceFeature(name, [])`; condition `features` lists
  are sorted by name. Feature *names* are derived per format:
  - **Pysa** features arrive as single-key dicts `{key: value}` → name `"key:value"`
    when `value` is a non-empty string, otherwise just `"key"`.
  - **Mariana Trench** features arrive as `{"may_features": [str, ...],
    "always_features": [str, ...]}` → each `may_feature` is used as-is and each
    `always_feature` becomes `"always-{f}"`. A taint's local features merge its
    `local_user_features` and `local_features` (same shape).
- **Type interval**: see each format below; absent interval → `None` for Mariana
  Trench, and a default for Pysa (below).
- **Leaves**: within a frame, leaves are deduplicated to unique `(kind, distance)`
  pairs and sorted; leaf *names* are dropped from frames (but retained in an issue's
  `initial_sources`/`final_sinks`).
- **Direction**: source/forward taint → `POSTCONDITION` frames and `initial_sources`;
  sink/backward taint → `PRECONDITION` frames and `final_sinks`.
- **User declarations** (and trace-less propagations) emit **no** frames.

---

## Pysa format (`pysa_taint_parser`)

A **JSON-lines** document. The **first line** is a header `{"file_version": N, ...}`;
only version **3** is accepted — any other version raises `ParseError`. Each subsequent
non-empty line is an entry `{"kind": "model"|"issue", "data": {...}}` (any other kind →
`ParseError`).

### Model entries (`kind == "model"`)
`data = {"callable": str, "filename": str|None, "sources": [...], "sinks": [...]}`.
Each of `sources`/`sinks` is a list of `{"port": str, "taint": [trace, ...]}`.

- Each source trace yields `POSTCONDITION` `ParseConditionTuple`s; each sink trace
  yields `PRECONDITION`s (`caller`=callable, `caller_port`=the trace's `port`,
  `filename`=model filename). A model whose traces actually produce a frame but has no
  `filename` is a `ParseError`; a model that produces no frames (e.g. only
  declarations) does **not** require a filename and yields nothing.

### Issue entries (`kind == "issue"`)
`data` has `code` (int), `message` (str), `callable` (str), `callable_line` (int),
`filename` (str), `line`/`start`/`end` (ints), `features` (list), `master_handle`
(str, optional), and `traces`: a list of `{"name": "forward"|"backward", "roots":
[trace, ...]}`.

- The **forward** trace → postconditions + `initial_sources`; the **backward** trace →
  preconditions + `final_sinks`. A missing forward/backward trace is a `ParseError`.
- The issue's `line`/`start`/`end` are taken from `data` (with the `start`+1 column
  convention); `callable_line` is copied through; `features` (issue-level) become a
  sorted list of names; `filename` is relativized against `repo_roots`.
- `handle` is an opaque stable identifier for the issue; it must be populated but its
  exact value is not asserted.

### Trace fragments (entries in a `taint`/`roots` list)
Each trace shares optional `tito_positions` (a list of positions → frame `titos`; the
positions are deduplicated to **unique** locations and sorted, so repeated entries in one
fragment's `tito_positions` collapse to a single `titos` location),
`local_features` (→ frame `features`), `receiver_interval`/`is_self_call` (type
interval), and `extra_traces` (→ annotations). It then has exactly one of:

- **`origin`** (`{line,start,end}`): a direct/terminal frame. For each entry in the
  trace's `kinds` (each `{"kind": str, "length": int (default 0), "leaves": [{"name"?,
  "port"?}], "local_features"?, "extra_traces"?}`), produce a frame whose `callee` is
  the leaf `name` (or `"leaf"` if absent), `callee_port` is the leaf `port` (or the
  frame type `"source"`/`"sink"`), `callee_location` is the origin position, and the
  leaf is `(kind, length)`.
- **`call`** (`{"call": {"port", "position", "resolves_to": [str, ...]}}`): an indirect
  frame. For each kind and each entry in `resolves_to`, produce a frame with that
  callee, `callee_port` = the call's `port`, `callee_location` = the call's `position`.
- **`declaration`**: user-declared — emits nothing.

Fragments that share the same `(callee, port, location, type_interval, features,
annotations)` are **merged into a single frame** whose `leaves` and `titos` are the
unions. `distance` for a kind is its `length` (default 0).

### Pysa type interval
From `receiver_interval` (a list of `{"lower","upper"}`): `start` = min lower, `finish`
= max upper. If absent, default to `start=0`, `finish=sys.maxsize`.
`preserves_type_context` = the trace's `is_self_call` (default `False`).

### Pysa extra traces → annotations
A trace's optional `extra_traces` become `ParseTraceAnnotation`s. Each entry is keyed
by either `call` (`{"port","position","resolves_to":[...]}`) or `origin`
(`{line,start,end}`):
- For a `call` entry, the annotation's subtraces are one
  `ParseTraceAnnotationSubtrace(callee=resolved, port, position)` per `resolves_to`
  entry; a `call` with no `resolves_to` is skipped.
- For an `origin` entry, the annotation has no subtraces.
Besides `call`/`origin`, an entry may also carry `trace_kind`, `leaf_kind`, `message`,
and — in the older analyzer shape — a top-level `kind` field (a sibling of `call`/`origin`,
distinct from `trace_kind`/`leaf_kind`). The annotation's `location` is that entry's
position; `kind` = the entry's `trace_kind` (default `"tito_transform"`) and is independent
of the entry's top-level `kind`; `msg` = its `message` (default `""`); `leaf_kind` = the
entry's `leaf_kind` if present, otherwise the entry's top-level `kind` field; and
`leaf_depth=0`, `type_interval=None`, `link=None`, `trace_key=None`, `titos=[]`. So an entry
`{"call": {...}, "kind": "X"}` (no `leaf_kind`/`trace_kind`) yields annotation
`kind="tito_transform"`, `leaf_kind="X"`, whereas `{"call": {...}, "leaf_kind": "X",
"trace_kind": "sink"}` yields `kind="sink"`, `leaf_kind="X"`.

`extra_traces` can appear both at the trace-fragment level (shared across the
fragment's kinds) and on an individual kind entry. A frame's `annotations` are the
trace-fragment-shared `extra_traces` first, followed by that kind's own
`extra_traces`, in document order.

---

## Mariana Trench format (`mariana_trench_parser`)

A document of **per-line JSON models** (lines beginning with `//` are skipped). Only
models with a `"method"` key are processed; a JSON object that lacks a `"method"` key
(e.g. a field model) is silently skipped. A `//`-comment line and a non-`method` model are
the **only** lines that may be silently ignored — a non-comment line that is **not valid
JSON** (cannot be decoded into a model object) raises `ParseError` rather than being
skipped. Build messages from `Metadata.rules`.

A method model may contain:
- `"issues"` → `ParseIssueTuple`s,
- `"sinks"` → preconditions, `"effect_sinks"` → preconditions,
- `"generations"` → postconditions,
- `"propagation"` → preconditions (propagations).

`model["method"]` and `model["position"]` give the caller method and position.

### Conditions (`sinks`/`effect_sinks`/`generations`/`propagation`)
Each is a list of leaf-models keyed by a port field (`"port"` for sinks/generations,
`"input"` for propagation) plus a taint list (`"taint"`, or `"output"` for
propagation). Each taint has `"call_info"`, optional `"local_positions"`,
`"local_features"`/`"local_user_features"`, and `"kinds"`.

- `call_info = {"call_kind": str, "resolves_to"?: method, "port"?: str, "position"?:
  {...}}`. The `call_info` carries the call kind, an optional `position`, and (for a call
  site) the resolved callee/port — it does **not** carry the origin callee (the origin
  callee comes from a kind's `origins`, below). A `position` may be present for **any**
  call kind. Classify by `call_kind`:
  contains `"Declaration"` → declaration (skip); `== "Propagation"` → trace-less
  propagation (skip); contains `"Origin"` → origin; otherwise a call site.
- `"kinds"` is a list of kind entries. Each entry is an object
  `{"kind": kind, "distance"?: int (default 0), "callee_interval"?: [start, finish],
  "preserves_type_context"?: bool, "origins"?: [origin, ...], "local_features"?,
  "local_user_features"?, "extra_traces"?}`. **The origin callee lives here, not in
  `call_info`**: each entry of a kind's `"origins"` is an origin object
  `{"method"?, "field"?, "canonical_name"?, "port"?}` (see the Origin object below), and
  it is that origin — not `call_info` — that supplies the origin callee and leaf-port (and
  the issue-leaf name).
- Group a taint's `kinds` **by type interval** (kinds with no `callee_interval` group
  under `None`). For an **origin** call_info, emit one condition per `(interval,
  origin)` — pairing each interval group with each origin in that group's kinds — whose
  callee/callee-port come from that origin (its method/field/canonical_name and its
  leaf-port); its `leaves` are every kind in that `(interval, origin)` group, one
  `(kind, distance)` leaf each. For a **call site**, emit one condition per interval
  whose callee is the call_info's resolved method/port and whose `leaves` are all the
  kinds in that interval group.
- `caller` = the model method; `caller_port` = the leaf-model's port (normalized);
  `callee_location` = the taint's `call_info.position` when the `call_info` carries a
  `position`, otherwise the caller (model) `position`.
- A frame's `filename` is **always** the caller (model) `position.path` (relativized against
  `repo_roots`), independent of `callee_location`. Unlike `callee_location`, `filename` never
  follows the taint's `call_info.position`: even for a call-site (or PropagationWithTrace:Origin)
  frame whose `callee_location` comes from `call_info.position` and names a different file, the
  frame's `filename` still comes from the model `position.path`. (This mirrors the Pysa
  `filename` = model filename rule.)

### Issues (`model["issues"]`)
Each issue has `rule` (int → message `"{rule.name}: {rule.description}"`), `position`,
`sink_index`, `sources` and `sinks` condition lists (yielding `ParseIssueConditionTuple`s
— no caller fields), a `callee` (or `exploitability_origin`), and features
(`may_features`, `always_features`). `rule`, `position`, `sink_index`, and the `sources`
and `sinks` condition lists are **required**: an issue missing any of them is a
`ParseError` (this is distinct from the shared Position "missing field → default" rule,
which only fills optional sub-fields of a *present* `position` — a wholly-absent required
issue field still raises).

Unlike the method-model conditions above, an issue's `sources`/`sinks` list is **not**
`{"port": ..., "taint": [taint, ...]}`-wrapped: each list entry is itself a **bare taint
object**, carrying `call_info`, `kinds`, and optional `local_positions`,
`local_features`/`local_user_features` directly at the entry level (there is no outer
`port` or `taint` key — iterate each list entry as one taint). Only the per-taint parsing
(the `call_info` classification, kind grouping by interval, origin-vs-call-site leaves,
features, and titos from the Conditions section) is shared; the port/taint envelope is
absent because an issue condition carries no caller port (`ParseIssueConditionTuple` has
no caller fields and its `root_port` stays `None`).

- Sources → postconditions + `initial_sources`; sinks → preconditions + `final_sinks`.
  Issue-leaf tuples are `(origin.callee_name, kind, distance)` — the leaf *name* is the
  callee of the kind's origin (from each kind's `origins` entry), taken from the origin
  even when the frame itself is a call site (so the issue-leaf name can differ from the
  frame callee).
- An issue condition's `location` follows the same `callee_location` fallback as frame
  conditions: the taint's `call_info.position` when present, otherwise the caller (model)
  `position`.
- The issue's `line`/`start`/`end` are its own `position` run through the shared Position
  contract.
- An issue with a declaration-frame source/sink is a `ParseError`.
- `handle` must be populated (opaque; exact value not asserted).

### Mariana Trench objects (normalization the tests pin)
- **Method name**: a string, or `{"name": ..., "parameter_type_overrides"?: [{"parameter","type"}]}`
  → `"name[p1: t1, p2: t2]"`.
- **Port**: dotted; the first element is lowercased, and `return` becomes `result`.
  A **leaf/terminal port** (the port of an origin's callee) is the frame type joined
  to the normalized actual port, e.g. `source:argument(1)` or `sink:result`; an origin
  with no port (e.g. a field origin) uses just the frame type (`source`/`sink`).
- **Position**: `start`+1; `end` = `max(end+1, start)`; a missing `start` or `end`
  defaults to 0 (so a position carrying only a line normalizes to `begin_column=1`,
  `end_column=1`); missing `path` is derived from the method signature (text before
  `;`/`$`, leading char stripped); a `"__SYNTHETIC:..."` path collapses to
  `"__SYNTHETIC"`; missing line = `-1`.
- **Kind name**: a plain string is used as-is. A **transform kind** arrives as an
  object `{"base": str, "global"?: str, "local"?: str}` and renders to
  `{local}@{global}:{base}` — i.e. prepend `"{local}@"` when a `local` transform is
  present and `"{global}:"` when a `global` transform is present, then append `base`
  (e.g. `{base:"LocalReturn", global:"T1", local:"T2"}` → `"T2@T1:LocalReturn"`;
  `{base:"LocalReturn", global:"T2"}` → `"T2:LocalReturn"`).
- **Origin**: from `method`/`field`/`canonical_name`; field origins have no port and
  default to a leaf port of the frame type.
- **Type interval**: from a kind's `callee_interval` `[start, finish]` +
  `preserves_type_context`; `None` if absent.
- **Features**: `may_features` plus `always_features` rendered as `"always-{f}"`; a
  taint's local features merge `local_user_features` and `local_features`.
- **Local positions** become a frame's sorted `titos`.
- **Extra traces** become `ParseTraceAnnotation`s, with a subtrace for callsite callees.
  Each extra-trace object carries its **own** `frame_type` field (`"source"` | `"sink"`),
  its own `call_info`, and its own kind at a **top-level `kind` field** (a sibling of
  `frame_type`/`call_info`, **not** nested under a `kinds` list — the `kinds`-list shape is
  the taint-level structure only). That top-level `kind` is rendered by the shared Kind-name
  rule (a plain string is used as-is; a transform-kind object `{base, global?, local?}`
  renders per the Kind-name rule) and is what the annotation's `leaf_kind` and the `{kind}`
  token in its `msg` are built from.
  The extra trace's `frame_type` — not the enclosing taint's direction — sets the
  annotation's `kind` and the `{frame_type}` token in its `msg`. So a `"source"` extra trace
  nested in a sink condition (e.g. under `effect_sinks`) yields `kind="source"` and
  `msg="To source kind: {kind}"`, and vice versa. The `msg` is built from the rendered
  leaf-kind and is selected by the extra trace's own `call_info.call_kind`: an extra trace
  whose `call_kind` **contains** `"PropagationWithTrace"` — i.e. any member of the
  PropagationWithTrace family, including both `"PropagationWithTrace:CallSite"` and
  `"PropagationWithTrace:Origin"` — is a *propagation-with-trace extra trace* and uses
  `"Propagation through {kind}"`; every other extra trace uses
  `"To {frame_type} kind: {kind}"`. This `msg` selection is governed solely by the
  `"PropagationWithTrace"` test above: it takes precedence over the taint-level
  `call_kind` classification in the Conditions section (so a `"PropagationWithTrace:Origin"`
  extra trace still uses `"Propagation through {kind}"` even though that `call_kind` also
  contains `"Origin"`), and a bare `"Origin"` extra trace (no `"PropagationWithTrace"`) uses
  `"To {frame_type} kind: {kind}"`. A callsite extra trace, which also carries a subtrace,
  additionally prefixes `"Subtrace: "`.
