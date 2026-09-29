# organize — File Management Automation Tool

Build a Python library called `organize` that runs YAML rules to organize files: each rule scans locations, matches resources with filters, and runs actions on the matches.

## Packaging

The package must be pip-installable via `pip install -e .` with a setuptools `pyproject.toml`.

The environment is **offline**: there is no network access, and every dependency is **already installed** — do **not** install anything (no `pip install`, no `apt-get`). The project is installed for you by a `setup.sh` that runs `pip install -e . --no-build-isolation` against the pre-installed packages. Your `pyproject.toml` must declare its dependencies (so the editable install resolves them), but they are all present in the environment already.

The following runtime libraries are pre-installed and available to import: `arrow`, `docopt-ng`, `docx2txt`, `exifread`, `jinja2`, `natsort`, `pdfminer.six`, `platformdirs`, `pydantic`, `pyyaml`, `rich`, `send2trash`, and `simplematch`. Build your implementation using these; do not rely on any library outside this set.

## Python API

`from organize import Config, ConfigError`. `Config.from_string(yaml_string)` parses a config and returns a `Config`, raising `ConfigError` on an invalid config structure. `Config.execute(simulate=True, output=Default(), tags=set(), skip_tags=set())` runs all rules.

`from organize.output import SavingOutput` — an output handler whose `messages` property returns the list of message strings emitted during execution. The default `output` is `Default` (also importable from `organize.output`), a console output handler.

Top-level YAML keys outside `rules` are silently ignored.

A minimal end-to-end usage:

```python
from organize import Config
from organize.output import SavingOutput

config = """
rules:
  - locations: /inbox
    filters:
      - extension: pdf
    actions:
      - echo: "Found {path}"
"""
out = SavingOutput()
Config.from_string(config).execute(simulate=False, output=out)
# out.messages -> ["Found /inbox/report.pdf", ...] (one per matched file)
```

## Config Structure

A config has a `rules` list. Each rule has: `locations` (single path string or list; each entry a string or an object with `path` and `exclude_dirs`), `subfolders` (bool, default false), `targets` (`"files"` or `"dirs"`, default `"files"`), `filters` (list; empty/omitted matches everything), `actions` (list), `filter_mode` (`"all"`/`"any"`/`"none"`, default `"all"` — a rule matches a resource only when every filter passes; individual filters can be negated, see **Negated filters** below), `tags` (list of selector labels).

Rule selection by tags: the `execute(tags=..., skip_tags=...)` selectors decide which rules run. When `tags` is empty, every rule runs except those tagged `never`. When `tags` is **non-empty**, only rules carrying at least one of the requested tags run — all other rules, **including untagged ones, are skipped**. The two special tags override this: a rule tagged `always` runs even when it would otherwise be filtered out, and a rule tagged `never` is skipped unless `never` is explicitly in `tags`. `skip_tags` excludes any rule carrying a listed tag.

Rules without `locations` run their actions once with no file context (standalone mode).

## Template Engine

Templates use **single-brace** Jinja2 syntax: `{variable}`, with full attribute access, method calls, and expressions. Built-in variables include `{path}` (the full path of the matched resource) and `{relative_path}` (the matched resource's path relative to the root of the location that yielded it, **including the resource's own name**).

`{path}` is a `pathlib.Path` object (not a bare string): its `str()` is the full path (so `echo: "{path}"` renders `/inbox/report.pdf`), and it exposes the usual `pathlib.Path` attributes — `.name` (filename), `.stem` (filename without the final suffix), `.suffix` (the final suffix **including** the leading dot, e.g. `.txt`), and `.parent`. `{relative_path}` is likewise a `pathlib.Path`.

Each filter exposes its results under a template variable matching the filter name; access structured fields with dot notation. Filter variables accumulate across the pipeline.

## Walker

Files and directories are yielded in **case-insensitive natural sort order** (equivalent to `natsort.natsorted(..., alg=ns.IGNORECASE)`): names are compared case-folded, so e.g. `apple.txt` sorts before `Banana.txt`, and numeric runs sort numerically (`file2` before `file10`).

Recursion is **breadth-first**: within a location the walker yields that directory's own matched entries (sorted as above) before descending, and only then walks into each subdirectory in the same order. So a directory's own files are all yielded before the contents of any of its subdirectories. This ordering is observable whenever the first-seen resource decides an outcome — e.g. which file becomes a duplicate's original, which file claims an unsuffixed conflict destination, or the order of a conflict-counter cascade.

A location object's `exclude_dirs` is a list of directory **names** (basenames): during the walk, any subdirectory whose own name matches a listed entry is skipped along with all of its contents (it is neither yielded nor descended into). Matching is by directory name alone, not by a path relative to the location or an absolute path.

## Filters

- **name** — matches against the file stem. Supports simplematch patterns with named wildcards, and the criteria `startswith`, `contains`, `endswith` (each a string or list) plus `case_sensitive` (default `true`). When a criterion's value is a list, that criterion passes if the stem satisfies **any** item in the list (OR within a criterion); when several criteria are given, the stem must satisfy **all** of them (AND across criteria).
- **extension** — matches by file extension, case-insensitive. Accepts a list. The exposed value is the extension without the leading dot.
- **regex** — regex search on the full filename (matches anywhere, not anchored). Named groups exposed via dot notation; multiple regex filters deep-merge their groups.
- **size** — conditions like `">= 100b, < 1kb"` (comparison operators; byte units). For directories, the recursive sum of all contained files. Exposes the size as `{size.bytes}` (int) plus three human-readable strings: `{size.traditional}` and `{size.binary}` (both base 1024, with JDEC `KB`/`MB`/… and IEC `KiB`/`MiB`/… suffixes respectively) and `{size.decimal}` (base 1000, SI `kB`/`MB`/… suffixes). Each string renders as `"1 byte"` for exactly one byte, `"<n> bytes"` (thousands-separated) below one unit, and otherwise one decimal place plus the unit.
- **duplicate** — detects duplicate files by content. `detect_original_by` chooses which of a duplicate pair is the original: `first_seen` (default; first in walk order) or `name` (alphabetically first). Only the non-original is matched. Stateful across all locations. Exposes `{duplicate.original}`.
- **empty** — matches empty files or empty directories.
- **filecontent** — regex over file text content, matching across multiple lines. Named groups exposed via dot notation.
- **python** — runs inline Python code with resource variables as locals. `path` is the same `pathlib.Path` object as the template `{path}` (so code can call `path.stem`, `path.name`, `path.read_text()`, etc.). Each prior filter's results are exposed as a dict-like local named after the filter, so earlier captures are read with subscript syntax inside the code (e.g. `regex["num"]`, `filecontent["total"]`) — distinct from the `{regex.num}` dot-notation used in templates. Return `False`/`None` to exclude; return a dict to expose values downstream.
- **lastmodified** — filters by modification time via `days`, `hours`, etc. and `mode` (`"older"`/`"newer"`). The age criteria are optional: a config-less `- lastmodified` (no `days`/`hours`/`mode`) is a valid filter that matches every file, and any omitted age narrows nothing. Captures a datetime.

### Negated filters

Any filter is negated by prefixing `not ` (the word `not` followed by a single space) to the filter's **own name in the YAML key** — not by wrapping it in a `not:` mapping. The prefixed entry is otherwise the underlying filter with the same config; the leading `not ` is stripped to recover the filter name, and its boolean result is inverted. All three filter-config forms accept the prefix:

- bare (no config): `- not empty`, `- not duplicate`
- scalar config: `- not extension: jpg`
- mapping config: `- not name:` followed by the indented config block (e.g. `startswith: ignore`)

A negated filter participates in `filter_mode` combination exactly like a positive one, contributing its inverted pass/fail (so `filter_mode: any` passes a resource when **any** listed filter — negated or not — is true). A negated filter does not expose template variables.

## Actions

Actions run sequentially. File-modifying actions are skipped in simulation mode.

- **copy** — copies to `dest` (template). If `dest` ends with `/`, copies into that directory; copying to its own location is a no-op. Supports `on_conflict` and `continue_with` (`"copy"` default or `"original"`).
- **move** — moves to destination, removing the source and updating the resource path for downstream actions.
- **rename** — renames in place. Takes a `new_name` template (the bare-string shorthand sets `new_name`) giving the new filename within the same directory; it must not contain a slash. Like `move`, rename updates the matched resource's path, so subsequent actions in the same rule operate on the renamed file.
- **delete** — permanently deletes files or directories.
- **echo** — prints a templated message.
- **shell** — runs a shell command given as `cmd` (the bare-string shorthand sets `cmd`). Supports `ignore_errors`. Exposes `{shell.returncode}`.
- **python** — runs inline code; its `print()` routes through the output handler. Prior filter results are exposed as dict-like locals read by subscript (e.g. `regex["num"]`), as in the `python` filter. Return a dict to expose values downstream.
- **write** — writes text to `outfile` (both templated). `mode` is `"append"`/`"prepend"`/`"overwrite"`; `newline` (default true) appends `\n`; `clear_before_first_write` clears the file on the first write only.

## Conflict Resolution

Copy, move, and rename accept `on_conflict`: `skip` (leave both), `overwrite` (replace existing), `rename_new` (default — rename the incoming file via the rename template), `rename_existing` (rename the existing file with the rename template, place the incoming file at the original destination), `deduplicate` (skip if byte-identical, else behave like `rename_new`).

The rename template is configurable per action via `rename_template` (default `{name} {counter}{extension}`). Its placeholders are: `{name}` — the destination's stem (filename without suffix); `{extension}` — the destination's suffix **including** the leading dot (e.g. `.txt`), so the default template reconstructs `name N.ext` (note this differs from the `extension` filter's exposed value, which omits the dot); and `{counter}` — an integer that starts at 2 and increments until the name is free (e.g. `dst.txt` becomes `dst 2.txt`).

Files created by these actions are tracked so the walker does not re-process them within the same rule.
