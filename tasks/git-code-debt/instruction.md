# git-code-debt

Implement **git-code-debt**, a tool that walks a git repo's first-parent commit history,
computes per-commit code-debt metric deltas via a plugin architecture, records them into
SQLite, and visualizes them via a Flask dashboard. Three console scripts:
`git-code-debt-generate` (data), `git-code-debt-list-metrics` (list parsers),
`git-code-debt-server` (dashboard).

## Dependencies

Offline; already installed: `cfgv`, `flask`, `identify`, `mako`, `markdown-code-blocks`,
`pyyaml`, `pytest`. Build backend: setuptools; `setup.sh` runs
`pip install -e . --no-build-isolation`.

## Public imports

Tests import only the plugin base class that custom-metric authors extend:

```
from git_code_debt.metrics.base import SimpleLineCounterBase
```

The server tests also import the Flask app (`git_code_debt.server.app.app`), its
`AppContext` (holds mutable `database_path` and `config`), and `Config` from
`git_code_debt.server.metric_config`, driving routes via `app.test_client()` for
end-to-end route testing.

## `git-code-debt-generate`

`git-code-debt-generate -C <config.yaml> [-j N]`. Walks first-parent history forward
(`git log --first-parent --reverse`) and diffs every commit, merge commits included, against its
**first-parent** predecessor (`git diff-tree -p --no-renames`; the first commit, having no
parent, is diffed against the empty tree), runs discovered parsers, writes SQLite. Incremental
runs resume from the last stored SHA.

`config.yaml` keys: `repo` (str, required), `database` (str, required),
`skip_default_metrics` (bool, `false`), `metric_package_names` (list, `[]`), `exclude`
(byte-regex string, `^$`; matched with `re.search` against each file's diff-header path).
Missing file / required key / wrong type → non-zero exit.

### SQLite

Three tables populated once at init from parsers' `get_metrics_info()`:

- `metric_names(id INTEGER PK ASC, name CHAR(255) NOT NULL, has_data INTEGER DEFAULT 0, description BLOB)`.
  `has_data` flips 0 → 1 on the metric's first non-zero emission.
- `metric_data(sha CHAR(40), metric_id INTEGER, timestamp INTEGER, running_value INTEGER; PRIMARY KEY (sha, metric_id))`.
  One row per (commit, metric) for metrics with `has_data=1`. `running_value` cumulative from
  walk start; `timestamp` = git committer epoch.
- `metric_changes(sha CHAR(40), metric_id INTEGER, value INTEGER; PRIMARY KEY (sha, metric_id))`.
  One row per (commit, metric) whose delta this commit is non-zero.

## Plugin architecture

Parsers subclass `git_code_debt.metrics.base.DiffParserBase` and provide
`get_metrics_from_stat(commit, file_diff_stats) -> Iterable[Metric]` and
`get_metrics_info() -> list[MetricInfo]`, with `Metric = namedtuple('Metric', ['name', 'value'])`
and `MetricInfo = namedtuple('MetricInfo', ['name', 'description'])`.

`SimpleLineCounterBase(DiffParserBase)` (with `__metric__ = False`): override
`line_matches_metric(line: bytes, file_diff_stat) -> bool` and optionally
`should_include_file(file_diff_stat) -> bool` (default `True`). Base counts added-matches minus
removed-matches per commit and emits `Metric(<class_name>, delta)` if delta ≠ 0.

Discovery walks `git_code_debt.metrics` recursively (unless `skip_default_metrics`) plus every
package in `metric_package_names`. Classes with `__metric__ = False` in their own class dict
are skipped.

## Built-in metrics

Class names = exact `metric_names.name`:

- `BinaryFileCount`, `SymlinkCount`, `SubmoduleCount`: `±1` on add/delete. Binary via git's
  `Binary files ... differ`; symlink mode `120000`; submodule mode `160000`. With
  `--no-renames`, a rename is delete + add. Diffs for these special files are classified by
  mode/marker and their pseudo-content (the symlink target line, the submodule gitlink line,
  binary blobs) is routed only to these counters: line-based parsers (`LinesOfCodeParser` and
  every `SimpleLineCounterBase` counter) receive no added/removed lines for a special file, so a
  symlink, submodule, or binary entry contributes 0 to `TotalLinesOfCode` and the other line
  metrics.
- `PythonImportCount`: `^\s*(import\s|from\s.*\simport\s)` in `.py` files.
- `CheetahTemplateImportCount`: same but `#`-prefixed lines in `.tmpl` files.
- `TODOCount`: every line containing byte `TODO`.
- `Python__init__LineCount`: every line in files named `__init__.py`.
- `LinesOfCodeParser`: emits `TotalLinesOfCode` plus `TotalLinesOfCode_<tag>` for each
  `identify.tags_from_filename(name)` tag (sentinel `unknown` when no tags). Allowed tags =
  `identify.ALL_TAGS` − `{directory, symlink, file, executable, non-executable, text, binary}`.
- `CurseWordsParser`: emits `TotalCurseWords` plus `TotalCurseWords_<tag>` (same tag rules as
  `LinesOfCodeParser`) for curse-word tokens (whitespace-split). Provide `word_list` as
  `frozenset[bytes]` at `git_code_debt.metrics.curse_words.word_list` (lowercase; at least
  `crap`, `damn`). Byte-exact, case-sensitive.

## `git-code-debt-list-metrics`

`git-code-debt-list-metrics -C <config.yaml> [--color always|never|auto]`. Same yaml (only
`skip_default_metrics` and `metric_package_names` affect discovery). Prints one header line per
parser containing the class's `__module__` and name, then indented lines per metric name from
`get_metrics_info()`. `--color never` → plain text (no ANSI escapes).

## `git-code-debt-server`

`git-code-debt-server <db.sqlite> [--port N] [--processes N]`. Missing DB → error,
`SystemExit(1)`. `--port` optional. On startup: `create_metric_config_if_not_exists()` writes a
sample `metric_config.yaml` in cwd if missing (never overwrites); load it; build `Config` via
`Config.from_data`; start Flask.

`metric_config.yaml` has four required top-level keys: `Groups` (list of
`{Name: {metrics: [...], metric_expressions: [...]}}`), `ColorOverrides` (list of names),
`CommitLinks` (dict `{name: url}`; `{sha}` substituted per commit), `WidgetMetrics` (dict/list
of names).

`Group` is a namedtuple `(name, metrics: frozenset[str], metric_expressions: tuple[re.Pattern])`
with `Group.from_yaml(name, metrics, metric_expressions)` (raises `TypeError` if both empty) and
`Group.contains(metric_name) -> bool` (name in `metrics` OR any pattern matches via `re.search`).

`Config` is a namedtuple `(color_overrides: frozenset[str], commit_links: tuple[(name, url)],
groups: tuple[Group], widget_metrics)`.
`Config.from_data(dict)` requires all four top-level keys; missing → `KeyError`.

`app` is the Flask app (tests use `app.test_client()`). `AppContext` carries mutable
`database_path` and `config`; tests patch these to inject scenarios. Each request opens a fresh
`sqlite3.Connection` to `AppContext.database_path` as `flask.g.db`; `flask.g.config` mirrors
`AppContext.config`.

Routes:

- `GET /` — index with metric groups. Lists only metrics with `has_data = 1` (those that have
  recorded at least one non-zero value), so a metric that never recorded a non-zero value is
  omitted from every bucket, including `All`. Auto-injects an `Uncategorized` bucket (metrics
  not in any defined group) and an `All` bucket. Per-metric current value plus historic deltas
  over standard time windows. Metrics in `Config.color_overrides` get a `color-override` marker
  (applied wherever per-metric rows are rendered — both this page and `/commit/<sha>`).
- `GET /commit/<sha>` — per-metric deltas for that sha: a table of each changed metric's name
  alongside its integer delta value for the commit. `Config.color_overrides` metrics carry the
  `color-override` marker here too.
- `GET /graph/<name>?start=<int>&end=<int>` — graph over range. Both required; missing → 4xx.
- `GET /graph/<name>/all_data` — 3xx redirect to `/graph/<name>` over the metric's full range.
- `GET /changes/<name>/<int:start>/<int:end>` — changes over range. Returns JSON
  `{"body": "<html>"}` whose body lists each change in the `[start, end)` window with its commit
  time, commit sha, and integer delta value.
- `GET /widget/frame` — iframe body with at least one `<script>` element.
- `POST /widget/data` — POST only (GET → 405); requires form `diff` (missing → 4xx); runs
  parsers over the posted diff, keeps only non-zero metrics in `Config.widget_metrics`, and
  returns `{"metrics": "<html>"}` whose fragment shows each such metric's name alongside its
  computed integer delta value (same row shape as `/commit/<sha>`); reads
  `generate_config.yaml` from cwd.
- `GET /status/healthcheck` — 200, empty.

## Offline install

Editable install needs `--no-build-isolation`; image forces `PIP_NO_INDEX` and bakes setuptools.
Don't vendor `git_code_debt` in `setup.sh`.
