# pytest-cases

Build `pytest-cases`, a `pytest` plugin that lets people **separate test code from
test cases** and adds a much more powerful parametrization / fixture toolkit on top
of `pytest`. A user writes ordinary "case functions" that each return some input
data (or a value to assert against), and a single test function is automatically
parametrized over all of them. On top of that the library generalizes
`pytest.mark.parametrize` and `pytest.fixture` so that fixtures can be used as
parameter values, parameters can be turned into fixtures, fixtures can be unioned,
and tuples can be unpacked.

The package must be importable as `pytest_cases` and must work as an **installed
pytest plugin**: once installed (`pip install -e .`), all of its features must be
active in any `pytest` session *without* the user passing `-p` or editing
`conftest.py`. (Register a `pytest11` entry point for this.) In
particular the library must also expose a `pytest` fixture named `current_cases`
(described below).

## Example use case

You write one test function plus several small "case" functions that each supply the inputs for one scenario, and `parametrize_with_cases` fans the test out over every case (one test item per case).

```python
from pytest_cases import parametrize_with_cases, case

def case_domestic():
    return 3, 5.00      # (weight_kg, rate)

def case_express():
    return 1, 12.00

@case(id="freight")
def case_bulk():
    return 200, 0.40

@parametrize_with_cases("weight,rate", cases=".")   # "." = this module
def test_total(weight, rate):
    assert weight * rate >= 0
# collects test_total[domestic], test_total[express], test_total[freight]
```

## Target environment & dependencies

- **The environment is offline.** Every dependency is already installed — do **not**
  attempt to install anything (there is no network).
- **Python 3** and **`pytest` 8.4.x** (the grader runs `pytest==8.4.1`). The plugin
  hooks deeply into `pytest` collection internals, so target this version.
- The following libraries are pre-installed and available to your implementation:
  **`pytest`**, **`makefun`** (create functions with a programmatically-built
  signature), **`decopatch`** (authoring decorators), and **`packaging`**. You may
  use any of them (or none) — only the observable behaviour below is graded. Do
  not rely on any other third-party package, since none can be installed offline.
- Your project must be installable offline by a `setup.sh` — provide a standard
  `pyproject.toml` / `setup.py` so it is installable with
  `pip install -e . --no-build-isolation` against the pre-installed dependencies.
  Declare `makefun`, `decopatch`, and `packaging` as your runtime dependencies (they
  are already present); do not add dependencies that are not pre-installed.

Organize the internals however you like (module layout, helper classes, which
hooks you use) as long as the public import paths and the observable behaviour
below match exactly.

---

## 1. Cases and `parametrize_with_cases` — the headline feature

```python
from pytest_cases import parametrize_with_cases, case, THIS_MODULE
```

A **case function** is a plain function whose name starts with a prefix (default
`"case_"`). It returns the data for one case. `@parametrize_with_cases(argnames,
cases=...)` decorates a test function (or a fixture) and parametrizes it once per
collected case.

```python
def case_simple():
    return 42

@parametrize_with_cases("v", cases=".")
def test_x(v):
    ...
```

### `parametrize_with_cases(argnames, cases=AUTO, prefix="case_", glob=None, has_tag=None, filter=None, ids=None, idstyle=None, scope="function", import_fixtures=False, debug=False)`

- `argnames`: a comma-separated string like `pytest.mark.parametrize` uses (e.g.
  `"a,b"`). When several names are given, each case must return a tuple that is
  unpacked positionally into them.
- `cases` selects where cases come from. It accepts a single item or a list of:
  - `"."` or the `THIS_MODULE` sentinel → the module of the decorated test.
  - a module object, or a module **name string** (importable).
  - a **class**; when a class is passed explicitly it may have any name and every
    method matching the prefix is collected.
  - an explicit case **function**.
  - `AUTO` (the default) → see §1.3.
- `prefix` (default `"case_"`): only functions/methods whose name starts with this
  are collected. You can use other prefixes (e.g. `"data_"`, `"user_"`).
- `glob`, `has_tag`, `filter`: selection filters, see §1.2.
- `ids`: optional custom ids — either an iterable of id strings, or a **callable**
  that receives each (original) case function and returns its id string. E.g.
  `ids=lambda f: "ID_" + get_case_id(f)` yields ids like `ID_one`, `ID_two`.
- `scope`: fixture scope to use when a case has to be turned into a fixture.

### 1.1 Case ids and ordering

Each collected case becomes one parametrization item. **The case id is computed
as follows** (this is also exactly what `get_case_id` returns, see §4):

- If `@case(id=...)` (or `set_case_id`) set an explicit id, use it.
- Otherwise take the function name and **strip the `prefix`** if the name starts
  with it (`case_simple` → `simple`, with the default prefix).
- If stripping leaves an empty string, the id is the literal `"<empty_case_id>"`.
- If the name does not start with the prefix, use the whole name.

Cases are collected and ordered by **their source-code line number** (definition
order in the file). So given case functions `case_simple_int`, `case_simple_str`,
and `@case(id="custom") case_renamed` (in that order) on a test `test_x`, the
collected items are exactly, in order:

```
test_x[simple_int]   test_x[simple_str]   test_x[custom]
```

Functions that do not match the prefix are ignored.

### 1.2 Filtering cases

- `has_tag=<tag>` (or a list/tuple/set of tags): keep only cases whose `@case`
  tags (§4) contain **all** the requested tags.
- `glob=<pattern>`: keep only cases whose **id** matches the glob pattern. The only
  special character is `*` (matches any run of characters); the pattern must match
  the **entire** id. E.g. `glob="quick*"` keeps ids `quick` and `quick_extra`.
- `filter=<callable>` (or several): each callable receives a case function and the
  case is kept only if all callables return a truthy value.

The submodule `pytest_cases.filters` provides ready-made, composable filter
factories — at least `has_tag(tag)` returning a filter callable. (They also support
`&`, `|`, `~` composition.) Example:

```python
from pytest_cases.filters import has_tag
@parametrize_with_cases("v", cases=".", filter=has_tag("slow"))
def test_x(v): ...
```

### 1.3 `AUTO` collection

When `cases` is left at its default (`AUTO`) the cases are loaded automatically
from the companion module **`test_<name>_cases.py`** that sits next to the test
module `test_<name>.py`. (Using `AUTO` is only allowed from a file whose name
starts with `test_`.)

### 1.4 Cases that need fixtures, and parametrized cases

A case function may itself **request a fixture** by listing it as an argument, or
be **parametrized** with `@parametrize` (§2). Both are supported transparently:

- **Case requiring a fixture** → it is turned into a fixture reference behind the
  scenes so `pytest` injects the fixture; the resulting test item still uses the
  plain **case id** (e.g. a `case_uses_fixture(token)` produces item
  `test_x[uses_fixture]`), and the case's returned value flows into the test.
- **Parametrized case** → it expands to one item per parameter combination, and the
  id combines the case id and the parameter id as **`<case_id>-<param_id>`**. E.g.
  `@parametrize("n", [1, 2, 3]) def case_scaled(n)` produces
  `test_x[scaled-1]`, `test_x[scaled-2]`, `test_x[scaled-3]`.

### 1.5 Marks on cases

`@case(marks=...)` (or putting a normal `@pytest.mark.*` on the case) attaches
those marks to the generated item — e.g. a case marked with `pytest.mark.skip` is
collected but skipped at run time.

### 1.6 Introspection of the active case: `current_cases` / `get_current_cases`

The plugin provides a fixture `current_cases` (and an equivalent function
`get_current_cases(request_or_item)`), giving the cases active for the current
test item:

- It returns a dict mapping each parametrized **argname** to a **`Case` namedtuple
  with fields `(id, func, params)`**:
  - `id`: the case id string actually used (computed per §1.1).
  - `func`: the original case function.
  - `params`: a dict of the case's own parameters (empty `{}` if the case is not
    parametrized; e.g. `{"k": 7}` for `@parametrize("k",[7]) case_beta`).
- `get_current_cases(request)` returns the same value as the `current_cases`
  fixture.

### 1.7 Programmatic equivalents: `get_all_cases` / `get_parametrize_args`

`@parametrize_with_cases` is exactly equivalent to two public steps, useful for
debugging:

- `get_all_cases(parametrization_target=None, cases=AUTO, prefix="case_", glob=None, has_tag=None, filter=None)`
  → returns the **list of collected case functions** (after applying prefix, glob,
  has_tag and filter), in source order. `parametrization_target` is the test
  function (or module) whose module is scanned for `"."`/`AUTO`.
- `get_parametrize_args(host_class_or_module, cases_funs, prefix, scope="function", import_fixtures=False, debug=False)`
  → turns that list of case functions into the list of argvalues (one entry per
  case, more if a case is parametrized).

---

## 2. Enhanced `@parametrize`

```python
from pytest_cases import parametrize, fixture_ref, lazy_value, is_lazy
```

`@parametrize(argnames, argvalues, ids=None, ...)` is a drop-in superset of
`pytest.mark.parametrize`:

- Plain usage matches `pytest`: `@parametrize("a,b", [(1, 2), (3, 4)])` produces
  ids `1-2` and `3-4`; a single name `@parametrize("x", [1, 2])` produces `1`, `2`;
  custom `ids=[...]` and per-value `pytest.param(value, marks=...)` work as usual.
- **`fixture_ref(fixture)`** may appear among the argvalues to inject a fixture's
  value as one of the parameter values. The test is expanded so that plain values
  keep their normal ids and the fixture contributes one item whose id is the
  **fixture name**. E.g. `@parametrize("v", [1, 2, fixture_ref(special)])` →
  items `v=1` (id `1`), `v=2` (id `2`), and `v=<special's value>` (id `special`).
  Several `fixture_ref`s may be mixed with plain values. If the referenced fixture
  is itself **parametrized**, the reference contributes one item *per fixture
  parameter* (a cross-product), each id combining the fixture name and the
  parameter id — e.g. referencing a `wf` parametrized over `[1, 2]` yields ids
  `wf-1` and `wf-2`. A `fixture_ref` also works when several argnames are given and
  the fixture returns a tuple to unpack.
- **`lazy_value(valuegetter, id=None, marks=())`** wraps a zero-arg callable whose
  return value is used as the parameter value, but **the callable is only invoked
  when the test actually runs** (not at collection time). Its id defaults to the
  callable's name. `is_lazy(x)` returns whether `x` is such a lazy value.

---

## 3. Fixtures: `@fixture`, unions, params, unpacking

```python
from pytest_cases import (
    fixture, fixture_union, param_fixture, param_fixtures, unpack_fixture,
)
```

### `fixture(scope="function", autouse=False, name=None, unpack_into=None, **kwargs)`

An enhanced replacement for `pytest.fixture`. In addition to the standard
behaviour it allows **`@parametrize` to be applied directly to a fixture**, so the
fixture (and every test using it) is expanded once per parameter:

```python
@fixture(name="base")
@parametrize("raw", [2, 5])
def base_fixture(raw):
    return raw * 10
# a test using `base` runs with base=20 (id "2") and base=50 (id "5")
```

`name=` overrides the fixture name that tests request. **Generator (`yield`)
fixtures are supported**, including when parametrized: the pre-`yield` value is
injected and the post-`yield` teardown runs once per parameter. **`unpack_into="x,y"`**
makes the fixture additionally create the listed fixtures by unpacking the tuple it
returns (so a test can request `x` and `y` directly).

### `fixture_union(name, fixtures, scope="function", idstyle="compact", ids=None, ...)`

Creates a new fixture whose value is taken, for each generated test item, from one
of the **member fixtures** (given by object or by name). A test that uses the union
is expanded into **one item per member**. The `idstyle` controls the
parametrization id of those items:

- `idstyle="compact"` (the default) → id is `/<member_name>` (e.g. `/first`,
  `/second`).
- `idstyle="explicit"` → id is `<union_name>/<member_name>` (e.g.
  `u_explicit/first`, `u_explicit/second`).

A union may itself contain other unions (members can be unions). The test is then
expanded across the flattened set of leaf members, and the compact ids reflect the
nesting — e.g. `u2 = fixture_union("u2", [u1, c])` where `u1 = fixture_union("u1",
[a, b])` yields ids `/u1-/a`, `/u1-/b`, `/c`. `unpack_into="x,y"` is also accepted
here, unpacking each member's returned tuple into the named fixtures.

### `param_fixture(argname, argvalues, ...)` and `param_fixtures(argnames, argvalues, ...)`

Shortcuts that create fixtures driven directly by a list of parameter values:

- `param_fixture("color", ["red", "green"])` returns a single fixture `color`; a
  test using it runs once per value, with ids `red`, `green`.
- `param_fixtures("width,height", [(1, 2), (3, 4)])` returns **several** fixtures at
  once (here `width` and `height`), unpacking each tuple; ids are `1-2`, `3-4`.

### `unpack_fixture(argnames, fixture)`

Splits a fixture that returns a tuple/sequence into several independent fixtures:

```python
@fixture
def point():
    return (10, 20)

x, y = unpack_fixture("x,y", point)   # now `x` is 10 and `y` is 20 in tests
```

---

## 4. Case metadata: `@case` and introspection helpers

```python
from pytest_cases import (
    case, get_case_id, get_case_tags, get_case_marks, set_case_id,
    copy_case_info, matches_tag_query, is_case_class, is_case_function,
    with_case_tags,
)
```

### `case(id=None, tags=None, marks=())`

Decorator to customize a case function: set an explicit `id`, attach `tags` (a
single tag or an iterable, used by `has_tag` filtering), and/or attach pytest
`marks`.

### Introspection helpers

- `get_case_id(case_func, prefix_for_default_ids="case_")` → the id, computed per
  the rules in §1.1 (explicit id wins; else strip prefix; else `<empty_case_id>`;
  else full name). The prefix used for stripping is `prefix_for_default_ids`.
- `set_case_id(id, case_func)` → set an explicit id on a case function.
- `get_case_tags(case_func)` → the tuple of tags set via `@case` (empty tuple if
  none).
- `get_case_marks(case_func, concatenate_with_fun_marks=False, as_decorators=False)`
  → the marks attached via `@case` (returns a non-empty sequence when marks were
  set, and `None` when no marks were set via `@case`).
- `copy_case_info(from_func, to_func)` → copy a case's id/tags/marks metadata onto
  another function.
- `matches_tag_query(case_func, has_tag=None, filter=None)` → `True` iff the case
  passes the query: all of `has_tag` present **and** every `filter` callable
  returns truthy.
- `with_case_tags(*tags)` → a **class** decorator that adds the given tags to every
  case method defined in the class.
- `is_case_class(cls, case_marker_in_name="Case", check_name=True)` → whether `cls`
  is a class and (unless `check_name=False`) its name contains `"Case"`.
- `is_case_function(f, prefix="case_", check_prefix=True)` → whether `f` is a
  (non-class) callable and (unless `check_prefix=False`) its name starts with
  `prefix`.

---

## 5. Exception assertion helpers

```python
from pytest_cases import assert_exception, unfold_expected_err
```

- `assert_exception(expected)` → a context manager asserting the wrapped block
  raises a matching exception. `expected` may be:
  - an **exception type** → checked with `isinstance`;
  - a **regex string** → matched against `repr(caught)`;
  - an **exception instance** → the caught exception must be of the same type
    **and** compare equal (`==`) to the given instance, so a matching type with an
    unequal value, or an equal-looking value of the wrong type, both fail;
  - an **exception validation callable** → must not return `False`.
  On a failed check it raises an `AssertionError` (subclass). The four accepted
  forms are exactly those normalized by `unfold_expected_err` (below).
- `unfold_expected_err(expected)` → normalizes `expected` into a 4-tuple
  `(error_type, pattern, instance, validator)`:
  - an exception **type** → `(type, None, None, None)`;
  - a **regex string** → `(BaseException, re.compile(string), None, None)`;
  - an exception **instance** → `(type(instance), None, instance, None)`;
  - a **callable** → `(BaseException, None, None, callable)`.
