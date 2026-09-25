# pingtop

Build `pingtop`, a multi-host ICMP ping monitor with a live Textual TUI. It pings
many hosts concurrently, accumulates per-host RTT/loss statistics with inline trend
sparklines, shows them in a sortable table with a per-host details panel, and on exit
prints a colored summary and optionally exports a snapshot to JSON or CSV. Targets come
from CLI arguments, CIDR ranges, or a hosts file.

## Example use case

pingtop is a multi-host ping monitor with a Textual TUI, but most of its logic is a plain library: create a `PingSession` over some targets, feed each host the `PingResult` of every ping, then read back per-host rows, an on-exit summary, or an exported snapshot.

```python
from pingtop.session import PingSession
from pingtop.models import SessionConfig, PingResult, ExportFormat
from pingtop.summary import render_summary
from pingtop.exporters import export_snapshot

session = PingSession(SessionConfig(), ["10.0.0.1", "10.0.0.2"])
gw1, gw2 = list(session.hosts)          # host ids, in insertion order
session.apply_result(gw1, PingResult(success=True, rtt_ms=12.3, resolved_ip="10.0.0.1"))
session.apply_result(gw2, PingResult(success=True, rtt_ms=11.8, resolved_ip="10.0.0.2"))

for row in session.host_snapshots():    # sorted per-host rows (dicts)
    print(row["target"], row["last_rtt_ms"], row["trend"])

print(render_summary(session.snapshot()))   # "OK | 2 hosts | tx 2 | rx 2 | loss 0.0%"
export_snapshot(session.snapshot(), "snap.json", ExportFormat.JSON)
```

## Dependencies

The environment is **offline** and every dependency is **already installed** — do not install,
download, or fetch anything (there is no network).

- Python 3.10+.
- `click` (CLI framework).
- `textual` (TUI framework; pulls in `rich`, which the trend renderers use).

No system services are required. The project is built as a standard src-layout package and is
installed for you by a `setup.sh` that runs offline (`pip install -e . --no-build-isolation`), so
your implementation only needs to provide the package source and a valid build configuration.

## Package Structure

All imports below are the exact paths the test-suite uses; organize internals however
you like as long as these resolve:

- `from pingtop.models import HostState, ExportFormat, SortKey, SessionConfig, HostConfig, PingResult, PingEngine, HostStats, HostRecord, SessionSnapshot, build_trend, trend_cells, MAX_HISTORY, TREND_BLOCKS, TIMEOUT_MARKER`
- `from pingtop.session import PingSession, infer_export_format`
- `from pingtop.summary import render_summary`
- `from pingtop.exporters import export_snapshot`
- `from pingtop.widgets.trend import render_trend, render_trend_graph, render_detailed_trend_graph, render_trend_legend`
- `from pingtop.app import PingTopApp`
- `from pingtop.engine.icmp import IcmpEngine`
- `from pingtop import cli` (exposes the Click command `cli.main`; also referenced as `PingTopApp` inside `cli` so it can be monkeypatched)

The console entry point is `pingtop = "pingtop.cli:main"`.

## Models (`pingtop.models`)

**Constants.** `MAX_HISTORY = 60` (max retained RTT samples per host). `TREND_BLOCKS` is
the 8-character Unicode block-elements gradient `"▁▂▃▄▅▆▇█"` (U+2581 LOWER ONE EIGHTH BLOCK
through U+2588 FULL BLOCK, lowest→highest RTT). `TIMEOUT_MARKER` is the single glyph `"╳"`
(U+2573 BOX DRAWINGS LIGHT DIAGONAL CROSS) used for a timed-out sample.

**Enums** (all `str`-valued):
- `HostState` (PENDING/RUNNING/PAUSED/ERROR/DELETED) and `ExportFormat` (JSON/CSV) — each value is the lowercase of its member name.
- `SortKey` — one member per sortable column (HOST, IP, SEQ, RTT, MIN, AVG, MAX, STDDEV, LOSS, LOSS_PERCENT, STATE, TREND), each sorting on the corresponding host-snapshot field.

**Dataclasses.**
- `SessionConfig(interval=1.0, timeout=1.0, packet_size=56, summary=True, export_path=None, export_format=None, log_file=None, log_level="info")`. The path-bearing fields `export_path` and `log_file` are stored as their string path form (`str | None`) — the CLI passes the `--export` / `--log-file` values through as plain strings — so e.g. `config.log_file == str(path)`.
- `HostConfig(id, target, enabled=True)`.
- `PingResult(success, rtt_ms=None, resolved_ip=None, error_message=None)`.
- `PingEngine` is a `Protocol` with `async def ping_once(self, target, timeout, packet_size, flag) -> PingResult`.

**`HostStats`** accumulates one host's measurements. Its fields include `resolved_ip`,
`seq`, `last_rtt_ms`, `min_rtt_ms`, `avg_rtt_ms`, `max_rtt_ms`, `stddev_ms`, `lost`,
`loss_percent`, `history_ms` (list of `float | None`), `trend`, `last_error`, `state`, and
`last_updated_at`.

- `register_success(rtt_ms, resolved_ip, when)` records a reply: it advances `seq`, sets
  `last_rtt_ms` to this reply's RTT, updates the RTT figures — including the **mean** and the
  **sample** standard deviation (`0.0` for a single sample) over the non-timeout samples —
  recomputes `loss_percent`, updates `resolved_ip` to the latest non-empty value (a `None`
  `resolved_ip` leaves the existing value unchanged), and sets state RUNNING.
- `register_timeout(when)` advances `seq` and `lost` and appends a timeout to history. It leaves
  `last_rtt_ms` **unchanged**: `last_rtt_ms` is the RTT of the most recent *successful* reply, so
  a timeout neither resets it to `None` nor updates it — only a later success replaces it, and only
  `reset()` clears it back to `None`.
- `register_error(message, when)` records the error and ERROR state **without** changing
  `seq`/`lost`.
- `mark_paused`/`mark_pending`/`mark_deleted` set `state`; `reset()` clears all statistics back
  to their initial empty state.
- `snapshot()` returns a serializable dict carrying **one key per `HostStats` field** — i.e. all
  of `resolved_ip`, `seq`, `last_rtt_ms`, `min_rtt_ms`, `avg_rtt_ms`, `max_rtt_ms`, `stddev_ms`,
  `lost`, `loss_percent`, `history_ms`, `trend`, `last_error`, `state`, and `last_updated_at` — with
  two fields serialized specially: `state` as its string value, and `last_updated_at` as an
  ISO-8601 UTC string (or `None`). The timestamp string is the value's `.isoformat()` output
  normalized to UTC, i.e. it carries a `+00:00` offset, not a `Z` suffix (e.g.
  `2026-01-01T12:00:00+00:00`). In particular `history_ms` (the retained list of `float | None`
  RTT samples) **is** a key of the snapshot dict, even though it is not one of the CSV export
  columns below (a list does not map to a single CSV cell).

History is capped at `MAX_HISTORY` and `trend` is kept in sync via `build_trend`.

`HostRecord(config, stats=HostStats(), paused=False)` bundles a host; `record.snapshot()`
returns `{"id", "target", "enabled", **stats.snapshot()}`.

`SessionSnapshot(generated_at, config, hosts, aggregates)` is the exported snapshot shape.

**Trend helpers.**
- `trend_cells(history) -> list[tuple[str, int | None]]`: one cell per sample. Empty history
  → `[]`. Each non-timeout sample maps to `(block_char, bucket)` where `bucket` is an integer
  in `0..len(TREND_BLOCKS)-1` scaled linearly between the min and max sample (a single
  distinct value → bucket `0`). Each timeout sample → `(TIMEOUT_MARKER, None)`.
- `build_trend(history) -> str`: the concatenation of the cell glyphs (empty history → `""`).

## Session (`pingtop.session`)

`PingSession(config, targets)` adds every target on construction and selects the first one.

- `hosts` (property): the live `OrderedDict[host_id, HostRecord]`.
- `add_host(target) -> host_id`: trims the target; empty → `ValueError`; rejects a duplicate
  (compared after trimming + lowercasing) with `ValueError`; assigns a short host id; selects
  it if nothing is selected yet.
- `edit_host(host_id, new_target)`: re-targets a host (same trimming/dup rules) and resets
  its stats.
- `delete_host(host_id)`: removes the host; if it was selected, selection moves to the next
  remaining host; `selected_host_id` becomes `None` only when no hosts remain.
- `pause_host`/`resume_host`/`toggle_host_pause`; `pause_all`/`resume_all`/`toggle_all_pause`
  (toggle-all pauses every host if any host is currently unpaused (active), otherwise resumes
  every host — keyed off the paused flag, not the RUNNING lifecycle state).
- `reset_host(host_id)` / `reset_all()`: reset stats; a host that is paused stays paused.
- `apply_result(host_id, result, when=None)`: a paused host ignores the result; otherwise a
  successful result with `rtt_ms` registers a success, a result with `error_message` registers
  an error, and anything else registers a timeout. A non-empty `resolved_ip` on an error or
  timeout result updates (overwrites) the host's `resolved_ip` to that latest value; a `None`
  `resolved_ip` leaves the existing value unchanged.
- `select(host_id)`, `current_host()`, `require_host(host_id)` (raises `KeyError` for an
  unknown id), `host_snapshot(host_id)`, `host_snapshots()` (all rows, sorted).
- `set_sort(sort_key, reverse=None)` sets `sort_key`; it updates `sort_reverse` only when
  `reverse` is given (a `None` `reverse` leaves the current direction unchanged).
  `cycle_sort()` advances `sort_key` to the next `SortKey` and leaves `sort_reverse` unchanged
  (changing the sort column does **not** reset the direction). `toggle_sort_order()` flips
  `sort_reverse` in place.
- Readable public state attributes: `config` (the `SessionConfig` this session was constructed
  with, exposed as a readable and mutable public attribute — the same object passed to the
  constructor; mutating it, e.g. setting `config.export_format`, is reflected in a subsequent
  `snapshot()`), `selected_host_id` (id of the currently selected host, or `None`), `sort_key`
  (the current `SortKey`, initially `SortKey.HOST`), and `sort_reverse` (bool, initially
  `False`). Construction selects the first host; the selection and sort helpers update these
  attributes in place.
- `aggregates() -> dict` with keys `total_hosts`, `active_hosts` (not paused),
  `paused_hosts`, `error_hosts` (state ERROR), `total_sent` (Σ seq), `total_lost` (Σ lost),
  `loss_percent` (`total_lost/total_sent*100`, `0.0` when nothing sent).
- `snapshot() -> SessionSnapshot`: its `config` is the session's own `config` object (identity —
  `snapshot().config is session.config`).

**Sort semantics.** `host_snapshots()` sorts rows by the current key, ascending unless
reversed. For `HOST` and `IP`, compare by dotted segments numerically (so `1.1.1.9` sorts
before `1.1.1.10`); note that a target may be a hostname rather than an IP literal, and a host's
`resolved_ip` may still be `None`. For numeric columns, rows whose value is `None`
sort **after** all present values in ascending order.

`infer_export_format(export_path, explicit)`: returns the `ExportFormat` named by `explicit`
if given; otherwise infers from the path suffix (`.json`/`.csv`); an unknown suffix with no
explicit format raises `ValueError`.

## Summary (`pingtop.summary`)

`render_summary(snapshot, *, color=False, max_issues=5) -> str`.

The first line joins these parts with `" | "`: the status word, `"{total_hosts} hosts"`,
`"tx {total_sent}"`, `"rx {total_received}"` (received = sent − lost),
`"loss {loss_percent:.1f}%"`, then — only when nonzero — `"err {error_hosts}"`,
`"lossy {lossy_hosts}"`, `"idle {idle_hosts}"`. A *lossy* host has `seq>0` and `lost>0`; an
*idle* host has `seq==0` and no `last_error`.

Status word: `"ERR"` if any host errored (`seq==0` with a `last_error` other than `"timeout"`)
or any host is fully down (`seq>0` and `lost==seq`); else `"WARN"` if any packets were lost;
else `"OK"`.

After the header come up to `max_issues` issue lines:
- Errored host (`seq==0`, error other than timeout): `"ERR {target} {error}"`.
- Otherwise a host with `seq>0` and `lost>0`: label is `"DOWN"` if `lost==seq` else `"LOSS"`,
  formatted `"{LABEL} {target} {loss:.1f}% loss ({lost}/{seq})"`, with `", avg {avg:.1f} ms"`
  appended when an average RTT exists.
Issues are ordered errors → fully-down → lossy (lossy by descending loss, ties by target).
If more than `max_issues` issues exist, a final `"MORE +{n} more issues"` line is appended.

With `color=True`, fields are wrapped in ANSI styling (via `click.style`); with `color=False`
the output is plain text. Example healthy output: `OK | 2 hosts | tx 2 | rx 2 | loss 0.0%`.

## Exporters (`pingtop.exporters`)

`export_snapshot(snapshot, destination, export_format) -> Path`: creates any missing parent
directories and writes the file, returning its `Path`.

- JSON: an object with keys `generated_at` (ISO string), `config` (the config fields, with
  `export_format` serialized to its string value or `None`), `aggregates`, and `hosts`.
- CSV: one row per host under this exact header, in order: `id, target, enabled, resolved_ip,
  seq, last_rtt_ms, min_rtt_ms, avg_rtt_ms, max_rtt_ms, stddev_ms, lost, loss_percent, trend,
  last_error, state, last_updated_at`.

## Trend visualizations (`pingtop.widgets.trend`)

The trend renderers turn an RTT history (a list of `float | None`) into `rich.text.Text` for
the TUI: the inline sparkline shown in the host table's Trend column, the larger RTT chart
shown in the details panel (returned as a list of `Text` lines), and the gradient legend.

- `render_trend(history, *, width=None)`: the single-line sparkline rendered into each table
  row's Trend cell — one block glyph per sample, colored along the `TREND_BLOCKS` gradient by the
  sample's bucket (timeouts use the timeout marker, styled distinctly). Empty/`None` history
  renders `"-"`. A positive `width` keeps only the most recent `width` cells (the latest samples).
  The bucket gradient is always scaled over the entire history and is **not** rescaled to the
  clipped window.
- `render_trend_graph(history, *, width=None, height=4)`: a `height`-row bar chart (rows joined
  by newlines). Filled cells use block glyphs, unfilled cells use `"·"`. A timed-out sample has
  no RTT level, so it fills its **entire** column with the timeout marker — the marker appears in
  all `height` rows of that column (a single timeout column therefore contributes `height`
  markers). Empty history renders `"-"`.
- `render_detailed_trend_graph(history, *, width=None, height=6)`: a list of `Text` lines. The
  first line is titled `"RTT Graph"`. With samples, it draws scaled rows labeled with RTT
  values (each label rendered to one decimal place) and a bottom axis line containing `"└"`
  followed by a horizontal rule spanning the graph width. With only timeouts, it renders a row
  labeled `"timeouts"` (using the timeout marker), an axis, and an `"oldest -> newest"` caption.
  Empty history renders the title plus a `"waiting for samples"` line.
- `render_trend_legend()`: a legend `Text` naming the gradient (`"Trend Legend"`, `"low RTT"`,
  `"high RTT"`) and the timeout marker. It renders the full gradient itself: every glyph of
  `TREND_BLOCKS`, laid out in low→high order, appears between the `"low RTT"` and `"high RTT"`
  labels.

## Application (`pingtop.app`)

`PingTopApp(session, engine)` is a Textual `App`. `session` is a `PingSession`; `engine`
implements the `PingEngine` protocol. It must be runnable headlessly via Textual's
`app.run_test()` test harness.

On start it renders a `DataTable` (one row per host) plus a details panel and status strip,
and begins one asynchronous ping loop per host: each loop repeatedly calls
`engine.ping_once(...)` and feeds the result into the session, so host `seq` counters advance
over time at roughly the configured `interval`. Newly applied results become visible in the
session within a short, bounded delay. The status strip summarizes session state as
space-separated `Label value` fields: it reports the host counts `Active <active_hosts>`,
`Paused <paused_hosts>`, and `Errors <error_hosts>`, the traffic counters `Sent <total_sent>`
and `Lost <total_lost>`, and a `Sort <field>` field naming the active sort column by its
host-snapshot field name (e.g. `Sort target` for the HOST column) followed by the sort
direction as `ASC` or `DESC`.

Key bindings: `a`/`e`/`d` add/edit/delete the selected host (via a modal), `space` pause/resume
the selected host, `p` pause/resume all hosts, `r` reset the selected host, `ctrl+r` reset all
hosts, `i` toggle the details panel, `h`/`?` open help, `q` quit. Sorting hotkeys map an
uppercase letter to a `SortKey` and select that column; pressing the same key again reverses
the order: `H`→HOST, `G`→IP, `S`→SEQ, `R`→RTT, `I`→MIN, `A`→AVG, `M`→MAX, `T`→STDDEV, `L`→LOSS,
`P`→LOSS_PERCENT, `U`→STATE, `W`→TREND.

**Host table.** The `DataTable` shows one row per host; its columns are keyed by the
host-snapshot field names (`target`, `resolved_ip`, `seq`, `last_rtt_ms`, …, `loss_percent`,
`state`, `trend`), so a cell is addressable as `table.get_cell(host_id, "last_rtt_ms")`. RTT
columns (`last_rtt_ms`, `min_rtt_ms`, `avg_rtt_ms`, `max_rtt_ms`, `stddev_ms`) render to one
decimal place; `loss_percent` renders as `"{value:.1f}%"`; the `trend` column shows the
sparkline. The visible column set adapts to the terminal width: all 12 columns at width ≥150,
a reduced set of 8 at widths 105–149, and a minimal 6 below 105. The header of the active sort
column carries an ascending (`▲`) or descending (`▼`) marker.

**Details panel.** Toggling it with `i` displays the selected host's details: a `"Host:"`
line with the target, plus `"IP:"`, `"State:"`, and the RTT figures, alongside the detailed
RTT chart (its first line is titled `"RTT Graph"`).

**Dialogs.** `a` and `e` open a modal form containing a single text `Input` for the host;
typing a value and pressing Enter adds it (or, for `e`, re-targets the selected host). `d`
opens a confirmation dialog whose destructive confirm button (Textual `variant="error"`)
deletes the selected host; cancelling any dialog leaves the session unchanged.

## ICMP engine (`pingtop.engine.icmp`)

`IcmpEngine` implements `PingEngine`. `ping_once(target, timeout, packet_size, flag)` resolves
the target (accepting an IP literal directly, otherwise via DNS), sends a single ICMP echo using
an unprivileged ICMP socket where possible, and returns a `PingResult`. On a successful reply it
returns `success=True` with `rtt_ms` and `resolved_ip`; on timeout, `success=False` with the
`resolved_ip`. If the target cannot be resolved it returns `success=False` with an
`error_message` (it does not raise).

## CLI (`pingtop.cli`)

`pingtop [OPTIONS] [HOSTS]...` (the Click command `cli.main`). Options:

```
-i, --interval FLOAT            ping interval seconds (default 1.0)
-t, --timeout FLOAT             timeout seconds (default 1.0)
-s, --packet-size INTEGER       ICMP payload bytes (default 56)
    --hosts-file FILE           newline-delimited host list (must exist)
    --summary / --no-summary    print a colored summary on exit (default summary)
    --export FILE               export the final snapshot
    --export-format [json|csv]  override the export format
    --log-file FILE             write logs to a file
    --log-level [debug|info|warning|error|critical]   (default info)
-h, --help
```

Behavior:
- Build the target list from positional `HOSTS` followed by the `--hosts-file` lines (the file
  is newline-delimited; blank lines and lines starting with `#` are ignored). Expand any
  `addr/prefix` CIDR argument into its usable host addresses. Deduplicate the merged list
  case-insensitively while preserving first-seen order.
- If no targets remain, fail with a message containing `"Provide at least one host"`.
- An unparseable network/host raises a Click error containing `"Invalid network or host"`.
- Reject `--interval`, `--timeout`, or `--packet-size` ≤ 0 with a message containing
  `"greater than zero"`.
- Resolve the export format: if `--export` is given, infer it (Click error containing
  `"Unable to infer export format"` if ambiguous and no `--export-format`); if `--export-format`
  is given without `--export`, fail with `"--export-format requires --export"`.
- Run `PingTopApp(session=..., engine=IcmpEngine())`. On exit, print the summary unless
  `--no-summary`, then write the export if requested.
