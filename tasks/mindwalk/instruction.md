# mindwalk

Build **mindwalk**, a Go command-line tool that replays coding-agent session logs
(Claude Code and Codex) into three deterministic JSON artifacts:

- a **citymap** of a repository (`build`),
- a normalized **trace** of one agent session (`trace`), and
- an LLM-assisted **report** evaluating one session (`analyze`).

## Scope

Implement exactly these three subcommands: `build`, `trace`, `analyze`. A web UI
and `serve` / `open` / `map` commands are **out of scope** — do not implement
them (they are not exercised).

## Environment and build

- Go 1.25 toolchain. Your implementation may rely on the **Go standard library
  only** (no third-party modules are required).
- The binary must build with `go build ./cmd/mindwalk` from the module root, i.e.
  `package main` lives in `cmd/mindwalk`. You choose the module path.
- Provide a `setup.sh` at the module root that builds the binary offline. It is
  run to build the project. Use:

  ```bash
  export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOSUMDB=off GOCACHE="${GOCACHE:-/tmp/gocache}"
  go build ./cmd/mindwalk || return 1
  ```

## Global CLI conventions

- `mindwalk <command> ...`. An **unknown command** must fail with a nonzero exit
  and print `unknown command "<name>"` to stderr.
- `mindwalk -h` / `mindwalk --help` / `mindwalk help` print a usage message
  containing the word `Usage` to stdout and exit 0.
- All three commands write their JSON artifact to **stdout** by default, or to a
  file given by `-o <path>` (equivalently `--output <path>` for `build`/`trace`).
  JSON is pretty-printed with **2-space indentation**.
- Diagnostics go to **stderr**; a fatal error exits nonzero after printing
  `mindwalk: <error>`.

---

## `build` — repository citymap

```
mindwalk build <repo> [-o out]
```

Missing/extra positional args → error containing `usage` (exit nonzero).

Emit a JSON object (validated against the citymap schema) with these fields:

- `version`: integer constant `1`.
- `repo`: object
  - `root`: absolute path of `<repo>`.
  - `commit`: short git HEAD hash (`git -C <repo> rev-parse --short HEAD`).
    **Omit** the field when `<repo>` is not a git repository.
  - `dirty`: `true` when `git status --porcelain` is non-empty (this includes
    untracked, non-ignored files); `false` otherwise, and `false` when not a git
    repo.
  - `generatedAt`: current time, RFC3339, UTC.
- `files`: array, **sorted ascending by `path`**, each:
  - `id`: 0-based index into the sorted array.
  - `path`: repo-relative, slash-separated.
  - `dir`: slash-separated parent directory, or `""` for a top-level file.
  - `lines`: line count (see below).
  - `bytes`: file size in bytes.
  - `lang`: language label (see mapping below); may be omitted when empty.
  - `rect`: `{x, z, w, d}` layout rectangle (see layout).
  - `ghost`: always `false` for `build`.
- `dirs`: array, one entry per **non-root** directory in the tree, each:
  - `path`: slash-separated directory path.
  - `depth`: number of path segments (top-level directory = 1).
  - `rect`: `{x, z, w, d}`.
  - `fileCount`: number of files anywhere in that directory's subtree.
  - `lines`: sum of `lines` over all files in that subtree.
- `layout`: object with the exact literals
  - `algorithm`: `"squarified-treemap-v1"`
  - `weight`: `"sqrt(max(lines, bytes/4096, 16))"`

### File enumeration

- If `<repo>` is a git repository, list files with
  `git ls-files -co --exclude-standard` (tracked **plus** untracked files,
  honoring `.gitignore`).
- Otherwise, walk the tree recursively, **skipping** directories named `.git`,
  `node_modules`, `.venv`, `dist`, `build`. Sort the resulting paths.

### Line counting and language

- `lines`: number of `\n` bytes, **plus one** if the file is non-empty and its
  last byte is not `\n`. An empty file has `0` lines.
- A file that is **binary** counts as `1` line (not scanned). Treat as binary any
  file whose extension is one of
  `pdf png jpg jpeg gif webp ico zip gz tgz mp4 mov mp3 woff woff2 ttf otf`, or
  whose first 8 KiB contains a NUL byte.
- `lang` by lowercased extension: `go`→`go`; `ts`/`tsx`→`typescript`;
  `js`/`jsx`→`javascript`; `md`/`mdx`→`markdown`; `py`→`python`; `json`→`json`;
  `yaml`/`yml`→`yaml`; `css`→`css`; `html`→`html`; no extension→`text`;
  anything else→the lowercased extension itself (e.g. `txt`→`txt`, `png`→`png`).

### Layout

Compute rectangles with a **squarified treemap**: the root gets a square area,
each file's weight is `sqrt(max(lines, bytes/4096, 16))`, each directory's weight
is the sum of its children, and rectangles are packed to keep aspect ratios low.
The result must be **deterministic** (identical across runs on unchanged input,
ignoring `generatedAt`) and every file's and directory's `rect` must have
`w > 0` and `d > 0`. The exact coordinates are not otherwise constrained.

---

## `trace` — normalized session trace

```
mindwalk trace <session.jsonl> [-o out]
```

Auto-detect the harness by attempting to parse the file first as **Claude Code**,
then as **Codex**. If neither recognizes it, fail with a nonzero exit and an
error containing `not a` (e.g. `not a Claude Code session` / `not a Codex
session`).

Emit a JSON object (validated against the trace schema):

- `version`: constant `1`.
- `session`: `{id, harness, model?, title?, cwd?, commit?, startedAt?, endedAt?,
  eventCount, path?}`.
  - `harness` is `"claude-code"` or `"codex"`.
  - `id` defaults to the file's base name without extension, overridden by the
    session id found in the log.
  - `eventCount` equals `len(events)`.
- `events`: array in chronological order, each:
  - `seq`: 0-based position.
  - `tool`: the tool/function name from the log.
  - `action`: one of `search read edit exec verify other` (classification below).
  - `targets`: repo files touched (below).
  - `outside`: references resolving outside the session cwd (below); omit when empty.
  - `resultBytes`: byte length of the tool result text.
  - `isError`: whether the tool call failed.
  - `summary`: a short human-readable one-liner (e.g.
    `"<command/description> -> N targets, M outside[ error]"`).
- `marks`: timeline annotations (below).
- `stats`: derived statistics (below).

### Action classification

- `Read` → `read`.
- `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `apply_patch` → `edit`.
- `Grep`, `Glob`, `LS` → `search`.
- `Task`, `Agent`, `spawn_agent`, and any unrecognized tool → `other`.
- Shell-style tools (`Bash`, `exec_command`, `js`, `js_repl`, Codex `exec`)
  classify by their command text, in priority order:
  1. **verify** if the command contains any of `go test`, `go vet`, `npm test`,
     `npm run build`, `pnpm test`, `pnpm build`, `pytest`, `make test`,
     `cargo test`, `swift test`.
  2. else **search** if it is a read-only inspection: every pipeline segment runs
     a read-only program and at least one segment searches or lists — programs
     `grep rg ag find fd ls tree`, or `git grep` / `git ls-files` (a `find` with
     `-exec`/`-delete` is not search).
  3. else **read** if it only pages file contents (`cat head tail nl`, or the
     `sed -n '…p' <file>` idiom) and names at least one file.
  4. else **exec**.

### Targets and touch states

Each target is `{path, touch, lines?, weak?}` where `touch` is `hit`, `read`, or
`edit`, ranked `edit > read > hit`. When the same file appears more than once in
one event, keep the strongest touch and merge line ranges.

- Paths are made **relative to the session cwd**, slash-separated. Absolute or
  relative references that resolve **outside** cwd are not targets; instead they
  become `outside` entries `{scope, path}` where `path` is the cleaned absolute
  path and `scope` is, in priority order, `home` if under the user home dir;
  else `tmp` if under the temp dir or `/tmp`; else `other`.
- **Strong** targets come from structured tool arguments/results:
  - `Read` `file_path` → `read`; with `offset`/`limit`, `lines` =
    `[[offset, offset+limit-1]]` (or `[[offset, offset]]` when only `offset`).
  - `Edit`/`Write`/`NotebookEdit` `file_path`/`notebook_path` → `edit`.
  - `apply_patch` patch bodies (`*** Add|Update|Delete File: <path>`) → `edit`.
  - `Grep`/`Glob`/`LS` result lines: a `path:line` reference → `hit` with
    `lines` `[[line, line]]`; bare paths → `hit`.
- **Weak** targets are inferred from free-form command/output text (shell
  commands, `exec`/`js` scripts, command output). Mark them `weak: true`. A weak
  target whose file **does not exist under cwd** is dropped. Pager reads
  (`cat`/`head`/`tail`/`nl`/`sed -n`) yield a weak `read`; other extracted paths
  yield weak `hit`s. A path-like token is extracted even when it is embedded in
  surrounding quotes, brackets, or call syntax rather than standing alone as a
  whitespace-delimited argument — the enclosing quotes/brackets/parentheses (and
  a leading `./`) are stripped to recover the path before it is made cwd-relative
  and existence-filtered.

### Marks

`marks` is an array of `{seq, type, note?}` where `seq` is the number of events
recorded so far when the mark occurs, and `type` is:

- `user-message`: a real user message. `note` is the trimmed text truncated to at
  most **2000 runes** (ellipsis `…` included in the budget). **Skip injected
  messages**: any message whose trimmed text is fully wrapped in a markup tag
  (starts with `<` and ends with `>`), or starts with `# AGENTS.md instructions`.
- `subagent`: a subagent launch (Claude `Task`/`Agent` tool call, Codex
  `spawn_agent`); `note` is the tool name.
- `compaction`: a context-compaction boundary.

### Stats

`stats` (all counters default 0):

- `filesInRepo`: `0`.
- `fovea`: number of distinct files whose strongest touch is `read` or `edit`.
- `parafovea`: number of distinct files whose strongest touch is only `hit`.
- `edited`: number of distinct files edited.
- `eventsBeforeFirstEdit`: `seq` of the first edit event, or `len(events)` if
  there was none.
- `regressionRate`: (re-reads of a file at an unchanged edit-version) / (read
  events); `0` when there are no reads.
- `errorRate`: errored events / total events; `0` when no events.
- `actions`: per-action counts `{search, read, edit, exec, verify, other}`.
- `errors`: same shape, counting only errored events.
- `maxEditsPerFile`: largest number of edit events on a single file.
- `churnFiles`: number of files edited in **3 or more** events.
- `userTurns`, `compactions`, `subagents`: counts of the respective marks.
- `resultBytes`: sum of `resultBytes` over events.
- `editsAfterLastVerify`: edit events after the last verify event; if the session
  never verified, every edit event counts.
- `observability`: `{reads, errors}`, each `exact` | `estimated` | `unavailable`:
  - `reads`: `unavailable` if there were no read targets; else `estimated` if any
    read target was weak; else `exact`.
  - `errors`: `exact` for Claude Code (the log flags failures structurally),
    `estimated` for Codex (failures inferred from output text).

### Harness formats

**Claude Code** — JSON-lines, one record per line, e.g.
`{"type":"user|assistant|system|ai-title", "timestamp":..., "sessionId":...,
"cwd":..., "message":{"role":..., "model":..., "content":[...]}}`. Assistant
`content` holds `tool_use` items `{id,name,input}`; user `content` is either the
user's typed text as a plain JSON string (a real user message) or an array of
`tool_result` items `{tool_use_id, content, is_error}` (a tool-result carrier).
The plain-string form is what feeds the `user-message` mark note, the `userTurns`
count, and the `analyze` evidence document / `inputDigest`. Pair a `tool_use` with its
`tool_result` by id to form one event (`isError` from `is_error`; `resultBytes`
from the result content). A `tool_use` with no matching result still becomes an
event. `compaction` mark: a `system` line whose `subtype` contains `compact`.
`model` comes from `message.model`. A record is recognized as Claude Code when it
carries a `sessionId` or is a known type with a timestamp/message.

**Codex** — JSON-lines with `{type, timestamp, payload}` (plus legacy top-level
`message` records). Relevant `type`s: `session_meta` (`payload.id`,
`session_id`, `cwd`, `git.branch`, `git.commit_hash`), `turn_context`
(`payload.cwd`, `payload.model`), `response_item` (payload `type` in
`function_call` / `custom_tool_call` for calls, `function_call_output` /
`custom_tool_call_output` for results, `message` for user text), and `event_msg`
(`payload.type` = `context_compacted` → compaction; `patch_apply_end` refines an
`apply_patch` call's touched files and success). Pair calls and results by
`call_id` (falling back to the item `id`). A call's body lives in a different field
per payload type: a `function_call` carries its arguments in `payload.arguments` (a
JSON string) — for an `exec_command` (or `exec`) call the parsed arguments hold the
shell command under the `cmd` key and, when present, the working directory under the
`workdir` key — whereas a `custom_tool_call` carries its raw payload in `payload.input`
(a plain string) — for an `apply_patch` call that `input` is the raw patch body (the
`*** Add|Update|Delete File:` lines are parsed from it, independent of any
`patch_apply_end` refinement), and for a `js`/`js_repl` call it is the script text.
Result items carry their text in `payload.output`. `commit` comes from
`git.commit_hash`. Because Codex logs carry no structural error flag, infer
`isError` from the output text: a JSON envelope `exit_code`/`metadata.exit_code`
≠ 0 or `timed_out:true`; a line `Process exited with code N` / `Exit code: N`
with N≠0; `Script failed`; `apply_patch verification failed`; `aborted by user`
in the header. `Script completed`/`Script running` are successes. A
`patch_apply_end` with `success:true` overrides a textual failure.

---

## `analyze` — LLM-assisted session report

```
mindwalk analyze <session.jsonl> [-o out] [--judge claude|codex] [--model NAME] [--no-cache] [--timeout DUR]
```

Parse the session into a trace (as `trace` does), render a text **evidence
document** from it, run a local agent CLI (the "judge") over that document as a
sealed, tool-free text function, parse the judge's JSON, and emit a report
(validated against the report schema). Flags may appear before or after the
positional argument.

### Judge CLI selection and protocol

- `--judge` picks `claude` or `codex`. When unset, auto-detect on PATH,
  preferring `claude`, then `codex`. If none is found, error.
- `--model` overrides the judge's model (an alias like `sonnet` or a full name).
- **claude**: invoke `claude -p --output-format json [--model NAME] <flags>
  <PROMPT>` with the evidence document on **stdin**. The CLI replies with a JSON
  envelope `{"result": "<text>", "modelUsage": {"<model>": {"inputTokens":...,
  "cacheReadInputTokens":..., "cacheCreationInputTokens":...}}}`. The judge's
  answer is `result`; the **model that judged** is the `modelUsage` key with the
  largest total input tokens. Pass `--model` only when `--model` was given.
- **codex**: invoke `codex exec <flags> [-c model=NAME] -` with
  `<PROMPT>\n\n<evidence>` on **stdin**. The reply is the CLI's stdout; the model
  is read from a `model: <name>` line the CLI prints in its preamble (check
  stderr, then stdout). Pass `-c model=NAME` only when `--model` was given.
- Run the judge sealed (no tools, MCP, or user/project settings) — the evaluated
  trace is untrusted input.

### Judge output and report assembly

The judge is asked to return exactly one JSON object:

```json
{
  "task_summary": "...",
  "dimensions": [
    {"name": "exploration|scope|wandering|verification",
     "findings": [{"claim": "...", "severity": "info|warning|problem", "evidence_seqs": [1,2]}]}
  ],
  "notable_moments": [{"seq": 1, "note": "..."}],
  "narrative": "..."
}
```

Extract the first balanced top-level JSON object from the reply (tolerate
surrounding log noise / markdown fences). Then build the report:

- **Dimensions**: exactly the four `exploration`, `scope`, `wandering`,
  `verification`, in that order. If the parsed output does not cover all four,
  the output is invalid.
- **Evidence validation**: keep only `evidence_seqs` that are real event `seq`s;
  drop the invalid ones. A finding left with **no** valid evidence seq is dropped
  entirely (and cannot influence the verdict). A finding with an empty `claim` is
  dropped.
- **Severity**: `info|warning|problem`, case-insensitive (trim/lowercase). Any
  other severity makes the whole output invalid.
- **Invalid output** (bad JSON, unknown severity, missing a dimension) → retry
  the judge **once**; a second failure is a fatal error.
- **Verdict** per dimension (the judge never sets verdicts): the max finding
  severity — `problem` → `problem`, else `warning` → `warning`, else `good`. But
  if `stats.observability.reads == unavailable`, force `exploration` and
  `wandering` to `insufficient-data`; if `stats.observability.errors ==
  unavailable`, force `verification` to `insufficient-data`.
- `notable_moments`: keep only those whose `seq` is a valid event and whose
  `note` is non-empty.

Report shape:

- `version`: `1`.
- `session`: `{id, harness, model?, eventCount, userTurns?}` from the trace.
- `judge`: object
  - `cli`: the judge CLI used (`claude` / `codex`).
  - `model`: the model the CLI reported (fall back to the requested `--model`);
    may be omitted when unknown.
  - `requestedModel`: the `--model` value (omit when unset).
  - `promptVersion`: integer constant `2`.
  - `generatedAt`: RFC3339 UTC.
  - `inputDigest`: **SHA-256 hex** of the evidence document. It must change
    whenever the evidence changes — in particular when a user message is added
    (user messages are part of the evidence document, even though they are marks
    rather than events).
- `taskSummary`, `narrative`: passed through from the judge.
- `dimensions`: the four dimensions with computed `verdict` and surviving
  `findings` (`{claim, severity, evidenceSeqs}`).
- `notableMoments`: surviving moments (omit when empty).

### Report cache

Cache reports on disk under `~/.mindwalk/reports`, one file per session, so
re-opening a session does not re-run the judge.

- On `analyze`, unless `--no-cache`, load any cached report. Reuse it only when it
  is **fresh** — same `promptVersion` **and** same `inputDigest` — **and** it
  matches the requested judge: the requested `--judge` (if given) equals the
  cached `cli`, and the requested `--model` (if given) equals the cached `model`
  or `requestedModel`. On reuse, print a stderr line containing
  `using cached report` and emit the cached report without running the judge.
- Otherwise, print a stderr line containing `judging` (e.g.
  `mindwalk: judging N events, …`), run the judge, store the fresh report, and
  emit it.
- `--no-cache` always re-runs the judge.
- The evidence document (and thus `inputDigest`) is derived from the trace:
  session meta, the user messages, the precomputed stats, and a one-line-per-event
  narrative. Injected messages are excluded from it, as in `trace`.
