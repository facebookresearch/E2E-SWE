# cfgforge

Build `cfgforge`, a configuration system for Python. It loads and saves an
INI-style text format, resolves variable references between sections, and turns
config blocks into live Python objects by calling functions you register in a
**function registry**. Function arguments are validated against the registered
functions' type hints, and whole configs can be validated against schemas.

The full public API is importable from the top level:

```python
from cfgforge import (
    Config,
    registry,
    ConfigValidationError,
    Schema,
    SimpleFrozenDict,
    SimpleFrozenList,
)
```

## Dependencies

The environment is **offline**: every dependency you need is already installed,
and you must **not** install anything (there is no network). The project is
installed for you by a `setup.sh` that runs offline (an editable install), so
just organise your code as an importable `cfgforge` package.

- The core is otherwise pure Python (Python standard library only).
- **`pydantic` (v2)** is installed and available: `pydantic.BaseModel`
  subclasses must work anywhere a `Schema` is accepted (see *pydantic
  compatibility*). Even so, importing `cfgforge` itself must not require
  `pydantic` — depend on it lazily, only on the code paths that actually
  handle a pydantic model.

## The config format

Sections are headed by `[name]`; inside a section, `key = value` pairs assign
values. Three features go beyond plain INI:

1. **JSON-typed values.** Every value is parsed as JSON, yielding real types
   (`int`, `float`, `bool`, `str`, `list`, `dict`). The Python literals `True`,
   `False`, `None` are also accepted as aliases for `true`/`false`/`null`, while
   a quoted string like `"True"` stays the string `"True"`.
2. **Nested sections via dot notation.** `[a.b]` nests `b` inside `a`, giving
   `{"a": {"b": {...}}}`. Every parent in a dotted path must be declared (a
   `[a.b.c]` without `[a.b]` is an error), and a key may not collide with a child
   section's name.
3. **Registry references.** A key beginning with `@` marks a block as a call to a
   registered function (see *Function registry*).

Every value must live inside a section; a value before any header, or otherwise
malformed syntax, raises `ConfigValidationError` on load.

### Positional / list sections (`*`)

A section whose path contains a `*` component collects its named subsections into
a dict under the `"*"` key, used to pass positional arguments:

```ini
[pipeline]
@backends = "chain.v1"

[pipeline.*.first]
@backends = "memory.v1"
size = 8

[pipeline.*.second]
@backends = "memory.v1"
size = 16
```

parses to `{"pipeline": {"@backends": "chain.v1", "*": {"first": {...}, "second": {...}}}}`.
A `*` path component is created implicitly (it needs no header of its own), may
nest, and must roundtrip through serialization like any other section.

### Variable interpolation

References use `${...}` and are resolved when `interpolate=True` (the default):

- `${section.key}` (or `${section:key}`) resolves to the value of `key` in
  `section`, **preserving its JSON type** (a referenced `0.001` comes back as a
  float, a referenced `true` as a bool).
- `${key}` with no dot resolves to `key` within the *same* section.
- References resolve **transitively**: if a referenced value is itself a
  reference, it is followed until a concrete value is reached.
- `${section}` resolves to the **entire referenced section as a dict** (e.g.
  `logger = ${logger}` yields the whole `logger` section, top-level included).
- Inside a larger string, references are substituted as text: with `a.x = 42`,
  `"value is ${a.x}"` → `"value is 42"`; a referenced JSON string is unwrapped,
  so with `a.y = "hello"`, `"${a.y} world"` → `"hello world"`.
- A reference embedded in a JSON list or dict literal is substituted before the
  value is parsed (e.g. `nums = [1, ${a.n}, 3]`), and multiple references may
  appear in one value.
- `$$` is an escape for a literal `$` (`"$$100"` → `"$100"`).
- Referencing a whole section (`${section}`) inside a larger string or list is
  not allowed and raises `ConfigValidationError`; referencing an undefined
  variable also raises.

When loaded with `interpolate=False`, references are kept verbatim as strings
(e.g. `"${a.x}"`); calling `Config.interpolate()` later resolves them.

## `Config`

`Config` subclasses `dict`.

`Config(data=None, *, is_interpolated=None, section_order=None)` — build from a
dict or another `Config`. `is_interpolated` (default `True`) records whether
variables have been resolved; `section_order` (default `[]`) records a preferred
top-level section ordering. Both are readable as attributes
(`config.is_interpolated`, `config.section_order`) and carried over by `copy()`.
Constructing from a non-dict/`Config` raises `ConfigValidationError`.

Methods (keyword-only options shown with their defaults):

- `from_str(text, *, interpolate=True, overrides={}, schema=None) -> Config` —
  parse a config string. `overrides` maps dotted `section.key` paths to
  replacement values, applied during loading and re-interpolated so dependent
  references see the new value. An override's final path component may name
  either a leaf key or a whole declared (sub)section; the mapped value simply
  **replaces** whatever currently lives at that path — so a mapping value keyed
  on a declared subsection (e.g. `{"a.scorer": {"@scorers": "new.v1"}}` when
  `[a.scorer]` exists) replaces that entire subsection block wholesale. An
  override raises `ConfigValidationError` only when its key is not a dotted
  `section.key` path, or when the parent section (everything before the final
  component) is absent; a final component that names a declared subsection is
  allowed and does **not** raise. If `schema` is given, fill its defaults and
  then validate against it.
- `to_str(*, interpolate=True) -> str` — serialize. The empty config serializes
  to `""` (and `from_str("")` yields an empty config). With `interpolate=False`,
  unresolved `${...}` references are written back verbatim, so
  `from_str(..., interpolate=False)` → `to_str(interpolate=False)` round-trips
  them.
- `to_bytes` / `from_bytes` — as `to_str`/`from_str` but UTF-8 bytes.
- `to_disk(path, *, interpolate=True)` / `from_disk(path, *, interpolate=True,
  overrides={})` — write/read a file (`path` may be `str` or `pathlib.Path`).
- `copy() -> Config` — a deep, independent copy preserving `is_interpolated` and
  `section_order`.
- `interpolate() -> Config` — return a new config with all variables resolved;
  the original is unchanged.
- `merge(updates, remove_extra=False) -> Config` — deep-merge `updates` over a
  copy of this config (the base): overlapping leaves take the `updates` value,
  missing keys/sections are added, nested dicts merge recursively, and the base
  is not mutated. With `remove_extra=True`, keys absent from the base are dropped.
  A block with an `@`-key is merged with another block only if both reference the
  *same* function; otherwise the updating block replaces the base block wholesale.
- `validate(schema) -> Config` — validate against a `Schema` (or pydantic
  `BaseModel`); raises `ConfigValidationError` on failure. Returns self.
- `fill_defaults(schema) -> Config` — fill missing values from the schema's
  field defaults (recursively for nested schemas, with `Optional` fields
  defaulting to `None`); if the schema forbids extra fields, strip unknown keys.
  Only fields that *have* a default are filled — a required field that is absent
  is left absent, not invented. Modifies in place and returns self.

## Function registry

`registry` is a class that serves only as a **namespace** for individual
registries — it does **not** create, store, or wrap them itself. Users create
registry objects with a separate, third-party registry library and attach them
to `registry` (or a subclass of it) as **ordinary class attributes**:

```python
class my_registry(registry):
    backends = make_registry(...)   # a registry object from a separate library

@my_registry.backends.register("sqlite.v1")
def make_sqlite(path: str = ":memory:", timeout: float = 5.0):
    return {"path": path, "timeout": timeout}
```

Each registry object supports membership testing (`name in reg`) and lookup
(`reg.get(name)` returns the registered callable); registration goes through the
object's own `.register(name)` decorator (you do not implement registration).
Your `registry` classmethods locate a function by reading these registries as
plain class attributes. Registries may also be attached to the base `registry`
class directly.

A config block whose key starts with `@` is a **promise** to call a function:
`{"@backends": "sqlite.v1", "path": "/tmp/db"}` means "call the function
registered as `sqlite.v1` in the `backends` registry with `path="/tmp/db"`". The
classmethods below operate on such configs:

- `registry.resolve(config, *, schema=None, overrides={}, validate=True) -> dict`
  — fill defaults, then recursively replace every promise with the result of
  calling its function, returning a plain dict. Promise arguments that are
  themselves promises are resolved first (depth-first). A `"*"` block supplies
  positional arguments in declaration order. Dotted `overrides` are applied
  before resolution. Resolving a config whose top level is itself a single
  promise raises `ConfigValidationError`.
- `registry.fill(config, *, schema=None, overrides={}, interpolate=False,
  validate=True) -> Config` — like `resolve`, but instead of calling functions,
  fill each promise's missing arguments from the function's signature defaults
  and return the augmented `Config` (the `@`-key and explicitly-provided values
  are preserved). Recurses into nested promises. A promise referencing an unknown
  function is passed through unchanged. When the input was loaded with
  `interpolate=False` and `interpolate=False` is kept, `${...}` references are
  preserved while defaults are still filled.
- `registry.has(registry_name, func_name) -> bool` — whether a function is
  registered (also `False` for an unknown registry name).
- `registry.get(registry_name, func_name) -> Callable` — fetch a registered
  function; an unknown *registry* name raises `ValueError`.
- `registry.is_promise(obj) -> bool` — whether `obj` is a mapping with any
  `@`-key.
- `registry.get_constructor(obj) -> (registry_name, func_name)` — extract the
  registry and function name from a promise's single `@`-key; a block with zero
  or more than one `@`-key raises `ConfigValidationError`.

### Argument validation against type hints

With `validate=True` (the default), each promise's arguments are checked against
the registered function's parameter annotations, and a violation raises
`ConfigValidationError`. Also enforced: a **missing required argument** (a
parameter with no default that is absent) and an **unexpected argument** (a key
that is not a parameter, not `@...`, and not `*`). Values are validated but
**not coerced** — the original value is passed to the function.

Validation happens *before* promises are resolved, on the literal argument
values. An argument whose value is itself a promise (a nested `@`-block) is
**not** type-checked against the consuming parameter, and a registered function's
return value is passed to its consumer **without** further type checking — so a
function returning a list may supply a `float`-annotated argument; only its own
arguments are validated.

Argument type-validation applies only to concrete literal values. An argument
whose value is still an **unresolved `${...}` reference string** (as when `fill`
keeps references — see below) is likewise **not** type-checked against the
consuming parameter; validation of a referenced value is deferred until the
reference is resolved.

Type rules (used here and by `Schema`/`validate`). Validation only accepts or
rejects a value — it never converts it; the original value is always passed
through.

- No annotation accepts any value; `str` accepts strings.
- **Numeric strictness:** `bool` accepts only real booleans (the ints `0`/`1`
  are rejected); `int` accepts ints but **not** `bool`; `float` accepts ints and
  floats but **not** `bool`.
- **String acceptance:** a string is accepted for `int`/`float` when it parses as
  that number (`"7"` for `int`, `"2.5"` for `float`), and any string is accepted
  for `pathlib.Path`/`PurePath`. (Per the rule above, the value is not converted —
  the function still receives the original string.)
- Generic and abstract collections are validated structurally, element by
  element: `List[T]`, `Dict[K, V]`, `Set[T]`, `FrozenSet[T]`, `Tuple[T1, T2]`
  (fixed length, per-position types), `Tuple[T, ...]` (uniform), and the abstract
  `Sequence[T]`/`Iterable`/`Mapping[K, V]` (a `list` satisfies `Sequence[int]`;
  note a `str` is itself a `Sequence`). Nestings such as `List[List[int]]`
  recurse.
- `Literal[...]`, `Union[...]`/`Optional[...]` (the latter also accepting
  `None`), and `Annotated[T, ...]` (validated as its underlying `T`) follow their
  usual semantics. An `enum.Enum` subclass accepts a value equal to one of its
  members (for a `str`-based enum, the member's string value).
- A `pydantic.BaseModel` parameter validates a dict value (see below).

### pydantic BaseModel arguments

If a registered function annotates a parameter with a `pydantic.BaseModel`
subclass, the resolved argument is a **constructed model instance**, not a raw
dict — both when the value is given as plain config keys and when it is produced
by a nested promise. (E.g. with `def arch(foo: str, dim: Dim) -> str` where `Dim`
is a `BaseModel`, resolving a `[model.dim]` subsection — or a nested `@dims`
promise returning a `Dim` — passes a `Dim` instance into `arch`.)

## Schema validation

`Schema` is a lightweight base class for declaring typed config schemas.
Subclass it with annotated fields; class-level assignments are defaults, and a
field with no default is required:

```python
class Server(Schema):
    host: str                # required
    port: int = 8080         # default

class AppConfig(Schema):
    server: Server           # nested schema
```

`model_config = {"extra": "forbid"}` rejects (in `validate`) or strips (in
`fill_defaults`) keys not declared as fields; the default is to allow extras.
Schemas nest, `Optional[T]` fields fill to `None`, and a `Schema` subclass
inherits its parent schemas' fields. They are used through `Config.validate`,
`Config.fill_defaults`, and `Config.from_str(..., schema=...)`.

### pydantic compatibility

Anywhere a `Schema` is accepted, a `pydantic.BaseModel` subclass must work too:
its fields, defaults and `extra` config are read off the model, validation is
delegated to pydantic (strict field types and validators keep working, with
pydantic's failure surfaced as a `ConfigValidationError`), and defaults are
filled the same way — so `Config().from_str(text, schema=SomePydanticModel)`
fills defaults and validates using a pydantic schema.

## `ConfigValidationError`

A `ValueError` subclass raised for all config/validation failures.

Constructor (keyword-only): `ConfigValidationError(config=None, errors=None,
title="Config validation error", desc=None, parent=None, show_config=True)`.

- `errors` is a sequence of dicts with keys `"loc"` (a path, list of parts),
  `"msg"`, and optional `"type"`.
- Readable attributes: `errors`, `title`, `desc`, `parent`, `config`,
  `show_config`, plus the derived `error_types` (the set of all `"type"` values
  present) and `text` (the rendered multi-line message, including each error's
  location, the `parent` prefix if given, and the title/desc).
- `from_error(err, title=None, desc=None, parent=None, show_config=None)` builds
  a new error from an existing one, overriding only the provided fields and
  inheriting the rest.

## Frozen collections

`SimpleFrozenDict(*args, error=<msg>, **kwargs)` and
`SimpleFrozenList(*args, error=<msg>)` behave like `dict`/`list` for reads but
raise `NotImplementedError` (using the `error` message) on any mutating call.
They are used as safe default arguments. Deep-copying one returns an instance of
the same frozen type.

## setup.sh

The environment is offline (`PIP_NO_INDEX` is set) and the build backend is
already installed, so the editable install must skip build isolation:

```bash
pip install -e . --no-build-isolation
```
