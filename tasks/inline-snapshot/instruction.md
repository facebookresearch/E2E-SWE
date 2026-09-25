# inline-snapshot

Build `inline-snapshot`, a Python library and pytest plugin for **snapshot testing that
writes the expected values directly into your source code**. Instead of maintaining expected
values by hand, the user writes `snapshot()` as a placeholder and runs pytest with a flag;
inline-snapshot records the real value by **rewriting the test's own source file** so that
`snapshot()` becomes `snapshot(<value>)`. Later, when a value changes, it can rewrite the
recorded value again.

```python
from inline_snapshot import snapshot

def test_something():
    assert 1548 * 18489 == snapshot()   # run: pytest --inline-snapshot=create
    # the line above is rewritten in place to:
    # assert 1548 * 18489 == snapshot(28620972)
```

The library is driven entirely through `snapshot()` (and a few related objects) plus the
`--inline-snapshot=<flags>` pytest option. Organize the internals however you like as long as
the import paths, the pytest option, and the observable rewrites described below match
exactly.

## Example use case

You write an assertion against an empty `snapshot()`, let inline-snapshot record the value by running pytest with a flag, and from then on it behaves like a normal assertion. Given a helper `price_after_tax(amount)`:

```python
from inline_snapshot import snapshot

def test_price():
    assert price_after_tax(100) == snapshot()
```

Run `pytest --inline-snapshot=create` and the call site is rewritten in place to `snapshot(121)` (the real value); later, if the value drifts, `pytest --inline-snapshot=fix` updates it.

## Dependencies

The environment is **offline**: every dependency below is **already installed** and you must
**not install anything** (there is no network). Your project is installed for you by a `setup.sh`
that runs offline (it performs an editable install with the pre-baked build backend). The
interpreter is CPython 3.12.

- Runtime: `pytest` (>=8.3), `asttokens`, `executing`, `rich`, `typing-extensions`.
- `black` — used to format the code that inline-snapshot generates (so generated dicts/lists
  use double-quoted strings and standard spacing); your generated code must be black-formatted.
- `dirty-equals` — used for the fuzzy-matching integration described below.
- `pydantic` and `attrs` — used by the constructor-call integration (a `pydantic.BaseModel` /
  `attrs` instance is recorded as a keyword constructor call when these libraries are importable;
  see "Constructor-call values" below).

Your installable package must register a **pytest plugin via a `pytest11` entry point named
`inline_snapshot`**. The plugin adds the `--inline-snapshot` command-line option and performs
the source rewriting at the end of the test session.

## Package structure and public imports

The tests use exactly these import paths (organize the rest of the package as you wish):

```python
from inline_snapshot import snapshot
from inline_snapshot import Is
from inline_snapshot import snapshot_arg
from inline_snapshot import outsource
from inline_snapshot import external
from inline_snapshot import external_file
from inline_snapshot.extra import raises, prints, warns
```

## The `--inline-snapshot` pytest option

`--inline-snapshot=<flags>` takes a comma-separated list of flags. The flags you must support
are:

- `create` — fill in snapshots that currently have **no recorded value**.
- `fix` — change a recorded value that no longer satisfies its comparison.
- `trim` — make a recorded value **more precise** by removing parts that are not needed.
- `update` — change only the **representation** of a value, not the value itself.
- `report` — print a diff of the changes that *could* be made, grouped by category, **without
  applying them**.
- `short-report` — print a one-line summary of pending changes without applying them.
- `disable` — turn snapshot logic off entirely (see below).

A category flag (`create`/`fix`/`trim`/`update`) applies **only changes of its own
category**. Running with `--inline-snapshot=fix` therefore corrects an incorrect value but
leaves an empty `snapshot()` (a *create* change) untouched.

In **any** run where inline-snapshot is active — whether it applies changes (`create`, `fix`,
`trim`, `update`, or a `default-flags` run) or only reports them (`report`, `short-report`, or a
no-flag run) — **every** `snapshot()` / `snapshot(value)` comparison **returns `True`**, whatever
operator it uses. This is what lets the **whole test body execute to completion in one pass**, so
that every pending change across the body is collected and can be applied or enumerated per
category. The one exception is `--inline-snapshot=disable` (below), under which a comparison
behaves like an ordinary assertion and may be `False`.

### Exit status and reporting

- **No flag, snapshot already correct:** the test passes and the pytest run succeeds
  (exit code 0); nothing is changed.
- **No flag, but a value needs to be created/fixed:** inline-snapshot prints the pending
  changes and the message `These changes are not applied.` (telling the user which flag to
  use). The source file is **not** modified and the pytest run is **not** successful
  (non-zero exit code).
- **`--inline-snapshot=report`:** prints, per category, a section titled `Create snapshots`,
  `Fix snapshots`, `Trim snapshots` (only the categories that have changes), each showing a
  diff with the proposed new code (e.g. the text `snapshot(1)` for a created value), followed
  by `These changes are not applied.`. The file is not modified; the run is not successful.
  *Update* changes are not shown in the report unless `show-updates` is enabled (see
  Configuration).
- **`--inline-snapshot=short-report`:** prints, per pending category, a one-line summary
  naming the flag to use; for a single missing value the line is exactly
  `Error: one snapshot is missing a value (--inline-snapshot=create)`.
- **`--inline-snapshot=disable`:** `snapshot(x)` simply returns `x`, so comparisons behave
  like ordinary assertions (a matching comparison passes, a non-matching one fails) and the
  source is never rewritten.

All of these user-facing messages are written to **standard output** (stdout): the no-flag
pending-changes report and its `These changes are not applied.` line, the per-category
`--inline-snapshot=report` sections, and the one-line `--inline-snapshot=short-report` message
(including its `Error: ...` summary).

## `snapshot()` and the comparison operators

`snapshot()` (empty) is a placeholder to be filled by `create`. `snapshot(value)` holds a
recorded value. A snapshot supports four kinds of operations, each with its own
create/fix/trim behavior:

**Equality — `value == snapshot(...)`**
- create: record `value`.
- fix: replace the stored value with the new `value`.

**Bounds — `value <= snapshot(...)` / `value >= snapshot(...)`**
- create: record `value` as the bound.
- fix: when the comparison fails, change the bound to `value`.
- trim: lower an `<=` bound (raise a `>=` bound) to the tightest value that still passed,
  i.e. the most precise bound for the values actually seen.

**Membership — `value in snapshot(...)`**
- The recorded value is a **list** of all values tested for membership.
- create: record `[value]`.
- fix: append a missing `value` to the list.
- trim: drop list entries that were never required.

**Sub-snapshots — `snapshot()[key]`**
- A snapshot can be indexed to produce sub-snapshots; the recorded value is a dict.
- create: record `{key: value}` (and add missing keys as they are used).
- trim: remove keys that are never read.
- `fix` and `update` apply recursively to the stored sub-values.

Worked example (run with `--inline-snapshot=create`):

```python
def test_something():
    assert 5 == snapshot()        # -> snapshot(5)
    assert 5 <= snapshot()        # -> snapshot(5)
    assert 5 in snapshot()        # -> snapshot([5])
    s = snapshot()                # -> snapshot({"key": 5})
    assert 5 == s["key"]
```

### Snapshots compared multiple times

The **same** `snapshot()` may be evaluated in several test executions (most commonly a
parametrized test, but also a loop). inline-snapshot records a **single** value that satisfies
*every* comparison across those executions, according to the operator:

- `==` records the common value (all executions compare equal to it).
- `<=` records the **maximum** value seen (`>=` the minimum); the recorded bound is satisfied by
  every execution.
- `in` records the **union** of all tested members, in first-seen order.

```python
@pytest.mark.parametrize("x", [1, 2, 3])
def test_a(x):
    assert x <= snapshot()    # --inline-snapshot=create -> snapshot(3)

@pytest.mark.parametrize("x", [1, 2])
def test_b(x):
    assert x in snapshot()    # --inline-snapshot=create -> snapshot([1, 2])
```

## How values are turned into code

inline-snapshot converts the recorded runtime value into source code:

- Scalars (`int`, `float`, `bool`, `None`, `bytes`, tuples, …) are rendered as the literal
  that reproduces them: `snapshot(3.14)`, `snapshot(True)`, `snapshot(None)`,
  `snapshot((1, 2))`, `snapshot(b"x")`.
- Lists and dicts are rendered as literals **formatted with black** (double-quoted strings,
  insertion order preserved): `{'b': 2}` is recorded as `snapshot({"b": 2})`.
- A single-line string is a normal string literal: `snapshot("single")`.
- The triple-quoted block form is used **only** for a string with an **interior** newline (a
  `\n` that is not the final character). A string whose sole newline is a **trailing** one is
  **not** triple-quoted — it stays a normal single-line double-quoted literal.
- When the triple-quoted block form applies, its opening `"""` is immediately followed by a
  backslash-escaped newline, so the content starts on the next line and the exact characters
  (including a trailing newline) are preserved:

  ```python
  assert "a\nb\nc\n" == snapshot("""\
  a
  b
  c
  """)
  ```

## Values inline-snapshot must not manage

Some sub-values are considered *developer-controlled*: inline-snapshot keeps them as written
and never rewrites them, even while fixing the surrounding snapshot (but it still records and
fixes the other parts normally):

- **`Is(value)`** — wraps a runtime value (e.g. a loop variable) so it stays dynamic:

  ```python
  for c in "abc":
      assert [c, "correct"] == snapshot([Is(c), "wrong"])
  # --inline-snapshot=fix -> snapshot([Is(c), "correct"])   (Is(c) preserved, "wrong" fixed)
  ```

- **A `snapshot()` used inside another snapshot** — the inner reference is preserved in the
  outer snapshot, while the inner snapshot is fixed independently:

  ```python
  inner = snapshot(5)
  assert {"a": 8, "b": 8} == snapshot({"a": inner, "b": 5})
  # --inline-snapshot=fix -> inner = snapshot(8); snapshot({"a": inner, "b": 8})
  ```

### dirty-equals integration

When a value being **created** is a `datetime` equal to the current time, record it as a
`dirty_equals.IsNow()` expression (adding `from dirty_equals import IsNow`) instead of an
exact timestamp, so the snapshot keeps passing on later runs. Stable siblings are recorded as
plain values:

```python
assert {"when": datetime.datetime.now(), "id": 1} == snapshot()
# --inline-snapshot=create -> snapshot({"when": IsNow(), "id": 1})
```

These dirty-equals expressions are themselves unmanaged (left untouched on later fixes).

## `update`: representation-only changes

`update` rewrites a value's *code* without changing the value. Two cases you must handle: a
plain string that holds newlines is converted to the triple-quoted block form, and an
expression like `4 + 1` is replaced by its evaluated result `5`:

```python
assert "a\nb\nc\n" == snapshot("a\nb\nc\n")   # -> the triple-quoted block form
assert 5 == snapshot(4 + 1)                    # -> snapshot(5)
```

## The `extra` context managers

`inline_snapshot.extra` provides context managers that snapshot side effects. Each takes a
snapshot of the captured value the same way `snapshot()` does (so `create`/`fix` fill or
correct the recorded argument).

Which category applies when a *default* invocation (e.g. `with prints():`) is first recorded
follows from the argument's declared default, exactly like `snapshot_arg`: a snapshot argument
whose default is `...` is unrecorded, so recording it is a **create** change; a snapshot
argument that has a concrete (non-`...`) default already carries a recorded value, so replacing
it with the captured value is a **fix** change.

- **`raises(exception=...)`** — records the exception raised in the block as a string. The
  format is `f"{type(ex).__name__}: {message}"` when there is a message,
  `type(ex).__name__` alone when the message is empty, and the literal `"<no exception>"`
  when nothing is raised.

  ```python
  with raises():
      1 / 0
  # create -> with raises("ZeroDivisionError: division by zero"):
  ```

- **`prints(*, stdout="", stderr="")`** — captures everything written to stdout/stderr in the
  block and records them as keyword snapshots:

  ```python
  with prints():
      print("hello world"); print("some error", file=sys.stderr)
  # fix -> with prints(stderr="some error\n", stdout="hello world\n"):
  ```

- **`warns(expected_warnings=..., /, include_line=False, include_file=False)`** — records the
  warnings emitted in the block as a list. By default each entry is the string
  `f"{category.__name__}: {message}"`. With `include_line=True` only, each entry is a tuple
  `(line_number, message)` (the line of the statement that raised the warning); with
  `include_file=True` only, `(filename, message)`; with both, `(filename, line_number, message)`.

  When the filename is recorded (`include_file=True`), it is **not** rendered as a literal path
  string. Because the warning originates in the test file being rewritten, the filename is
  emitted as the bare source token `__file__` (the `__file__` reference, not a quoted path), so
  the recorded snapshot stays portable across machines.

  ```python
  with warns():
      warn("problem one"); warn("problem two")
  # create -> with warns(["UserWarning: problem one", "UserWarning: problem two"]):

  with warns(include_line=True):
      warn("some problem")
  # create -> with warns([(6, "UserWarning: some problem")], include_line=True):

  with warns(include_file=True):
      warn("some problem")
  # create -> with warns([(__file__, "UserWarning: some problem")], include_file=True):
  ```

## `snapshot_arg`

`snapshot_arg(param)` records the value of a **function parameter** by rewriting the
function's **call site** to pass that value. A parameter whose default is `...` is a *create*
target. The first positional parameter is filled positionally; later parameters are filled by
keyword:

```python
def get_stats(numbers, expected_sum=..., expected_max=...):
    assert sum(numbers) == snapshot_arg(expected_sum)
    assert max(numbers) == snapshot_arg(expected_max)

def test_example():
    get_stats([1, 2, 3])
    # create -> get_stats([1, 2, 3], expected_sum=6, expected_max=3)
```

## Constructor-call values (dataclass / pydantic / attrs)

A value that is an instance of a "constructor-style" class is recorded as a **keyword
constructor call**, and on `fix` only the field whose value changed is rewritten (other fields
are preserved). This must work for at least three kinds of classes, detected when their
libraries are importable:

- a standard library `@dataclass`,
- a `pydantic.BaseModel` subclass,
- an `attrs` class (`@attrs.define`).

```python
assert Point(1, 2) == snapshot()                 # create -> snapshot(Point(x=1, y=2))
assert Point(1, 9) == snapshot(Point(x=1, y=2))  # fix    -> snapshot(Point(x=1, y=9))

# pydantic BaseModel M(x, y):   M(x=1, y=2) == snapshot()  -> snapshot(M(x=1, y=2))
# attrs class P(a, b):          P(1, 2)     == snapshot()  -> snapshot(P(a=1, b=2))
```

## External storage: `outsource` and `external`

Large or binary values can be stored in **external files** instead of inline, referenced by
an `external("<protocol>:<name>.<suffix>")` object that is used like a snapshot.

- **`outsource(value)`** returns a marker that forces the value to be stored externally. When
  created, the comparison `outsource(value) == snapshot()` is rewritten to
  `snapshot(external("uuid:<generated-uuid>.<suffix>"))` (importing `external`), and the
  value is written to the external file.

- **`external(name="")`** is used directly like `snapshot()` but stores the value externally.
  When created, an empty `external()` is filled with a generated name
  `"uuid:<generated-uuid>.<suffix>"`, choosing the **suffix from the value's type**:
  - `str` → `.txt` (file contains the string),
  - `bytes` → `.bin` (file contains the bytes),
  - lists/dicts and other JSON-serializable structures → `.json` (file contains the value
    serialized with `json.dump`, indented).

  `external()` may only be used in test files located under a `tests/` directory.

The default **`uuid:` storage protocol** writes each external file under an
`__inline_snapshot__` directory next to the test file, named `<generated-uuid>.<suffix>`. The
generated UUID is a standard random UUID4.

```python
# in tests/test_x.py, run with --inline-snapshot=create:
assert "some text" == external()   # -> external("uuid:<uuid>.txt"),  file contains: some text
assert b"raw bytes" == external()  # -> external("uuid:<uuid>.bin"),  file contains: raw bytes
assert ["json", "data"] == external()  # -> external("uuid:<uuid>.json"), file: ["json", "data"]
```

### The `hash:` storage protocol

The storage protocol used by `external()` is configurable (see Configuration: `default-storage`,
`"uuid"` or `"hash"`). With `default-storage = "hash"`, a created `external()` records a
**content-addressed** reference instead of a random uuid:

- The inline reference is `external("hash:<prefix>*.<suffix>")`, where `<prefix>` is the first
  **12 hex characters** of the **SHA-256** of the stored content and the trailing `*` marks it
  as a hash prefix.
- The external file is named by the **full** SHA-256 hex digest (`<full-sha256>.<suffix>`) and
  is stored under an `.inline-snapshot/external/` directory.

```python
# with default-storage="hash":
assert "hello" == external()
# -> external("hash:2cf24dba5fb0*.txt")   (2cf24dba5fb0 = sha256("hello")[:12])
# file .inline-snapshot/external/2cf24dba5fb0...<rest of sha256>.txt contains: hello
```

### `external_file(path)`

`external_file(path)` is used like `external()` but stores the value at an **explicit path**
(relative to the test file) that you choose, rather than an auto-generated uuid/hash name. On
`create` the call site is left exactly as written and the value is written to that path.

```python
# in tests/test_x.py:
assert "stored text" == external_file("data/value.txt")
# create -> call site unchanged; the file tests/data/value.txt is created containing: stored text
```

## Configuration

inline-snapshot reads a `[tool.inline-snapshot]` table from `pyproject.toml`. The options the
tests rely on are:

- `show-updates` (boolean): when `true`, *update*-category changes are included in reports and
  applied by `--inline-snapshot=update`.
- `default-flags` (list of strings): the flag categories applied when pytest runs **without** an
  explicit `--inline-snapshot=` option. For example `default-flags = ["create"]` makes a plain
  `pytest` run fill empty snapshots in place (equivalent to `--inline-snapshot=create`).
- `default-storage` (string, `"uuid"` or `"hash"`, default `"uuid"`): selects the external
  storage protocol used by `external()` (see The `hash:` storage protocol above).
