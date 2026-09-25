# pyyaml

Build `yaml`, a YAML parser and emitter for Python. Implements the YAML 1.1 type schema (note the
resolver deviations from literal YAML 1.1 spelled out below).

## Dependencies

The environment is **offline** — there is no network access and you must not install anything. All
required dependencies are already installed in the environment.

- No third-party runtime dependencies. This is a pure-Python implementation using only the Python
  standard library.
- The project is installed for you by a `setup.sh` that runs **offline** (`pip install -e .
  --no-build-isolation`); the build backend is already present, so do not add install steps.

## Package Structure

Importable as `yaml`. `yaml.YAMLError` is the base exception class.

## Loading

`yaml.safe_load(stream)` — parse a YAML string/stream and return a Python object.

`yaml.safe_load_all(stream)` — parse a multi-document YAML stream, yields one Python object per document.

Returns Python types: `dict` for mappings, `list` for sequences, `str`/`int`/`float`/`bool`/`None`/`datetime.date`/`datetime.datetime` for scalars, `bytes` for `!!binary`, `set` for `!!set`, and `list` of tuples for `!!omap`/`!!pairs`.

The `!!set`, `!!omap` and `!!pairs` collection tags take their standard YAML 1.1 source forms.

### Plain-scalar type resolution

When a plain (unquoted) scalar is not given an explicit tag, its Python type is decided by matching
the YAML 1.1 implicit-resolver patterns, which deviate from the literal YAML 1.1 spec in several
ways:

- **bool** — only these exact spellings resolve to a bool: `true`/`True`/`TRUE`, `false`/`False`/`FALSE`, `yes`/`Yes`/`YES`, `no`/`No`/`NO`, `on`/`On`/`ON`, `off`/`Off`/`OFF`. The single-letter forms `y`/`Y`/`n`/`N` are **not** booleans (they stay `str`), unlike literal YAML 1.1.
- **int** — `0b…` binary and `0x…` hex (underscores allowed as digit separators); a leading-zero run `0…` is octal **only when every digit is 0–7** (a leading-zero run containing an `8` or a `9` is not an integer at all and stays `str`); plain decimal otherwise. Python-style `0o…` is **not** recognized as an int (stays `str`). An optional leading `-`/`+` sign applies to every integer form — decimal, binary, hex, octal and base-60 alike.
- **float** — an exponent must carry an explicit sign; an exponent written without one leaves the scalar a `str`. The integer part before the decimal point may be omitted, so a leading-dot mantissa is still a float. `.inf`/`-.inf`/`.nan` (and case variants) are floats.
- **sexagesimal** — colon-separated base-60 values resolve to numbers: an int when every group is a whole number, a float when the last group carries a fraction. The first group may **not** start with `0` (such a value stays `str`).
- **null** — `null`/`Null`/`NULL`, `~`, and the empty value resolve to `None`.
- **timestamps** — `YYYY-MM-DD` resolves to `datetime.date`; a date with a time part (space- or `T`-separated, optional `Z`/offset) resolves to `datetime.datetime`.

Quoted scalars are always plain `str` and never type-resolved.

### Block scalars

Block scalar styles (`|` literal, `>` folded) and the chomping indicators (`-` strip, `+` keep, and
the default clip) follow YAML 1.1 unchanged.

### Explicit tags

`!!str`/`!!int`/`!!float`/`!!bool`/`!!null` force the constructor for a node. `!!bool` accepts only
the bool spellings above (so `!!bool 'yes'` → `True`, while `!!bool 'Y'` is an error). `!!null` maps
**any** content to `None` (e.g. `!!null 'foo'` → `None`).

### Anchors and errors

`&name` defines an anchor and `*name` references it; the `<<` merge key merges one or more mapping
aliases. An alias may reference an **enclosing (ancestor) node that is still being constructed**,
forming a recursive / self-referential structure: loading such a document succeeds and the alias
resolves to the *same* object as the anchored node (object identity is preserved). Referencing an
undefined alias is an error, and re-using an already-defined anchor name is an error. Invalid YAML
raises a `yaml.YAMLError` subclass — this includes bad indentation, unclosed quotes, and a **tab
character used as structural whitespace** (whether as indentation, or as a separator between
flow-collection entries / after a `,` inside `[...]` or `{...}`). Empty / whitespace-only /
comment-only input loads to `None`.

## Dumping

`yaml.safe_dump(data, stream=None, default_flow_style=False, sort_keys=True, indent=None, width=None, allow_unicode=None, explicit_start=None, explicit_end=None, default_style=None)` — serialize a Python object to YAML. Returns a string if stream is None.

`yaml.safe_dump_all(documents, stream=None, **kwds)` — serialize multiple documents.

### Dump output format

The emitter uses **block style** by default (`default_flow_style=False`):

- Mappings indent nested values by `indent` spaces (default 2). Block sequences are emitted with a
  `- ` marker at the **same** indentation as their parent key (not indented under it), e.g.
  `{"features": ["a", "b"]}` → `"features:\n- a\n- b\n"`. When a block-sequence item is itself a
  mapping (or sequence), its first entry is placed **compactly on the same line as the `- ` marker**,
  with any remaining entries indented beneath that first entry — the item is not pushed to a
  following indented line, e.g. `[{"a": 1, "b": 2}]` → `"- a: 1\n  b: 2\n"`.
- Scalars: `None` → `null`, `True`/`False` → `true`/`false`, float infinities/NaN → `.inf` / `-.inf` / `.nan`, empty mapping/sequence → `{}` / `[]`.
- `datetime.datetime` is emitted as `YYYY-MM-DD HH:MM:SS` (space between date and time, no `T`); a
  timezone-aware value appends its offset immediately after the seconds with **no separating space**,
  formatted as `+HH:MM` / `-HH:MM` (`+00:00` for UTC) — e.g. `2024-01-15 10:30:00+00:00` and
  `2024-01-15 10:30:00+05:30`, while a naive datetime has no offset suffix (`2024-01-15 10:30:00`).
  `datetime.date` is emitted as `YYYY-MM-DD`.
- A string is emitted **single-quoted** when leaving it plain would make it re-resolve to a
  non-string type (e.g. `"true"`, `"42"`, `"null"`, `"yes"`, `""`, `"1.0e+3"`) or would otherwise be
  ambiguous YAML (e.g. starts with an indicator like `#`/`*`/`&`, or contains `": "`). Strings that
  are unambiguous stay plain (e.g. `"y"`, `"abc:def"`, `"1.0e3"`). A string whose only special
  characters are line breaks (`\n`) is still emitted **single-quoted**, with each break expressed as
  a folded blank/continued line (e.g. `"a\nb"` → `"v: 'a\n\n  b'\n"`). Only non-foldable control
  characters — tab, NUL (`\0`), carriage return (`\r`) — force a **double-quoted** scalar carrying
  the corresponding escape sequences.
- When `allow_unicode` is falsy (the default), non-ASCII characters are escaped inside a
  double-quoted scalar; with `allow_unicode=True` they are emitted literally.
- When the root node is a plain scalar, a `...` document-end marker is appended
  (`safe_dump(42)` → `"42\n...\n"`); root mappings and sequences get no such marker.
- `sort_keys=True` (default) sorts mapping keys; `explicit_start`/`explicit_end` add `---` / `...`
  document markers; `default_flow_style=True` emits inline flow style, e.g.
  `{"z": 1, "m": [3, 4]}` → `"{m: [3, 4], z: 1}\n"`.
- `width` sets the preferred maximum line width (a best-effort default around 80 when `None`). A
  long scalar value is folded across multiple continuation lines so emitted lines stay near that
  width — e.g. dumping a string much longer than a small `width` produces more than one output line
  rather than a single long line.

`bytes` is emitted with a `!!binary` tag (base64), `set` with `!!set`. Non-serializable objects
(e.g. `complex`, `frozenset`) raise a `yaml.YAMLError` subclass.

## Usage

```python
import yaml

obj = yaml.safe_load("name: Alice\ntags: [a, b]\n")   # -> {"name": "Alice", "tags": ["a", "b"]}
text = yaml.safe_dump(obj)                              # round-trip back to YAML text

for doc in yaml.safe_load_all("---\nx: 1\n---\nx: 2\n"):
    ...                                                 # iterate multiple documents
```

## setup.sh

```bash
pip install -e . --no-build-isolation
```
