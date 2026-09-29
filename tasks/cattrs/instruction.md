# cattrs

Build `cattrs`, a Python library for **composable (un)structuring of typed data**. It converts
unstructured data (the dicts/lists/scalars you get from JSON and similar formats) into typed
Python objects — *attrs* classes, dataclasses, `TypedDict`s, `NamedTuple`s, enums, and standard
collections — and back again, recursively, driven entirely by type hints. It also validates data
during structuring and produces detailed, path-annotated error reports.

## Dependencies

The environment is **offline**: every dependency below is already installed, and the project is
installed for you by a `setup.sh` that runs offline (an editable install against the pre-installed
packages). **Do not install anything** — there is no network, and you do not need it.

- `attrs` (the `attrs`/`attr` package; provides `@define`, `fields`, field aliases, converters).
- `typing-extensions`.
- `exceptiongroup` (backport of the standard `ExceptionGroup`; available on this Python so the
  grouped validation errors below subclass `ExceptionGroup`).

## Package structure

All imports the tests rely on come from these paths — organize internals however you like, but keep
these import locations:

- `cattrs` — top level: `structure`, `unstructure`, `register_structure_hook`,
  `register_unstructure_hook`, `BaseConverter`, `Converter`, `UnstructureStrategy`,
  `transform_error`.
- `cattrs.gen` — `override`, `make_dict_structure_fn`, `make_dict_unstructure_fn`.
- `cattrs.strategies` — `include_subclasses`, `configure_tagged_union`, `configure_union_passthrough`,
  `use_class_methods`.
- `cattrs.errors` — `ClassValidationError`, `ForbiddenExtraKeysError`, `StructureHandlerNotFoundError`.

The top-level `structure`, `unstructure`, and `register_*` names are bound methods of a module-global
`Converter` instance.

## Converters

Two converter classes:

- **`BaseConverter`** — structures/unstructures by recursive per-call dispatch.
- **`Converter`** — subclass of `BaseConverter` that generates specialized
  conversion functions per type; it additionally supports heterogeneous-tuple unstructuring,
  `TypedDict`, generics code-generation, and the `forbid_extra_keys` / `omit_if_default` / `use_alias`
  / `unstruct_collection_overrides` features below.

Common constructor parameters (defaults in parentheses):

- `detailed_validation` (`True`) — see **Validation**.
- `unstruct_strat` (`UnstructureStrategy.AS_DICT`) — `AS_DICT` or `AS_TUPLE`; in `AS_TUPLE` mode attrs
  classes unstructure to tuples and automatic attrs-union disambiguation is disabled.
- `dict_factory` (`dict`), `prefer_attrib_converters` (`False`).

`Converter`-only constructor parameters:

- `forbid_extra_keys` (`False`), `omit_if_default` (`False`), `use_alias` (`False`),
  `unstruct_collection_overrides` (`{}`).

Converter methods:

- `structure(obj, cl)` → an instance of `cl`. `unstructure(obj, unstructure_as=None)` → unstructured
  data; when `unstructure_as` is given, dispatch on that type instead of `type(obj)`.
- `register_unstructure_hook(cls, func)` / `register_structure_hook(cl, func)` — install a custom hook.
  Structure hooks are called as `func(value, type)`; unstructure hooks as `func(value)`. The most
  recently registered hook for a type wins, and a hook registered for a subclass applies only to that
  subclass. A `Union[...]` may be passed as `cl` to register a hook for that union.
- `register_structure_hook_factory(predicate, factory)` / `register_unstructure_hook_factory(...)` —
  `factory(type)` returns the hook to use for any type matching `predicate`. A factory may also be
  written to take two arguments, `factory(type, converter)`, to build hooks that need the converter;
  both arities are accepted.
- `structure_attrs_fromdict(obj, cl)` / `structure_attrs_fromtuple(obj, cl)` — structure an attrs
  class from a mapping / from a positional sequence. `structure_attrs_fromdict` **ignores unknown
  keys** and **omits missing keys that have defaults** (using the default instead).
- `copy(**overrides)` — return a new converter with the same configuration and any custom hooks that
  were registered after construction; accepts the same parameters as the constructor to override.

`structure_attrs_fromtuple` builds the instance positionally; `structure_attrs_fromdict` builds it by
keyword.

## Supported types

Structuring converts each leaf value through its annotated type; unstructuring is the inverse.

- **Primitives** `int`, `float`, `str`, `bytes`, `bool`, `pathlib.Path` — structured by calling the
  type on the value (e.g. `int("10") == 10`; `bool` yields a real `bool`, so `1 -> True`, `0 ->
  False`). `str`/`bytes` unstructure unchanged; `Path` unstructures to `str`.
- **`Any`** — passed through unchanged on structure.
- **`Optional[T]` / `T | None`** — `None` stays `None`; otherwise structured as `T`.
- **`list[T]`, `Sequence`/`MutableSequence`** — element-wise to a list. The abstract `Sequence[T]`
  structures to a homogeneous **tuple**.
- **`tuple[T, ...]`** — homogeneous, every element converted to `T`.
- **`tuple[X, Y, Z]`** — heterogeneous, positional, length-checked. `Converter` also *unstructures*
  heterogeneous tuples, and the result is a **tuple** (the container type is preserved).
- **`set[T]`, `frozenset[T]`** — element-wise, preserving set/frozenset type in both directions (a
  set field unstructures back to a `set`, not a list, unless overridden — see
  `unstruct_collection_overrides`).
- **`dict[K, V]`, `Mapping`/`MutableMapping`** — keys and values converted per `K`/`V`; `Any` on a
  side passes that side through.
- **`collections.Counter[T]`** — keys converted to `T`, values forced to `int`.
- **`collections.defaultdict[K, V]`** — like dict, with the value type `V` used as the
  `default_factory` (so a missing key yields `V()`).
- **`NamedTuple`** — structured from an iterable, unstructured to a tuple.
- **attrs classes and dataclasses** — structured from a mapping keyed by field name (or alias, see
  `use_alias`), recursively; unstructured to a dict. Missing required field → error (see below).
- **`TypedDict`** (ordinary and generic; supports `Required`/`NotRequired` and totality) — structured
  from a mapping, converting known keys per their types; absent `NotRequired` keys are allowed.
  Structuring a non-mapping value into a `TypedDict` raises a validation error.
- **`NewType`** — uses the underlying (immediately wrapped) type's hook; nested `NewType`s resolve
  transitively, and a hook registered directly on a `NewType` is honored.
- **`Final[T]`** — structured/unstructured as `T`. A **bare** `Final` field (no parameter) that has a
  default value is converted by dispatching on the runtime type of that default value.
- **`Literal[...]`** — value must be a member (else an error is raised); enum-valued literals map
  values to members.
- **`Enum`** — structured from a member value (`structure(1, Color) is Color.RED`), unstructured to
  the member value.
- **Generics** — generic attrs classes/`TypedDict`s bind their type parameters from the concrete alias
  (e.g. `structure({"item": "5"}, Box[int]) == Box(5)`), propagating bindings into nested fields and
  collections.
- **Unions** — see **Unions** below.

A type with no applicable hook raises `StructureHandlerNotFoundError` (see **Errors**).

## Per-field and per-class customization (`cattrs.gen`)

`override(*, rename=None, omit=None, omit_if_default=None, struct_hook=None, unstruct_hook=None)`
returns a field-override object:

- `rename` — use a different dict key for this field (both directions).
- `omit` — drop this field from unstructured output.
- `omit_if_default` — when the field equals its default, drop it from unstructured output.
- `struct_hook` / `unstruct_hook` — use a custom hook for this field (`struct_hook(value, type)`,
  `unstruct_hook(value)`).

An `override(...)` may also be attached to a field type via `Annotated[T, override(...)]`; the
converter applies it as that field's override without a separately registered hook.

`make_dict_unstructure_fn(cl, converter, **field_overrides)` and
`make_dict_structure_fn(cl, converter, **field_overrides)` build specialized conversion functions for
an attrs class/dataclass; each keyword argument maps a field name to an `override(...)`. Register the
result with `register_unstructure_hook` / `register_structure_hook`. Both also accept the keyword
`_cattrs_include_init_false=True`, which makes the generated function include `init=False` fields
(read on unstructure; set after construction on structure); by default such fields are skipped.

Converter-level flags:

- `omit_if_default=True` — drop *every* field whose value equals its default during unstructure
  (including fields whose default is produced by a factory, e.g. an empty `list`).
- `use_alias=True` — read/write the attrs field **alias** as the dict key instead of the field name.
- `forbid_extra_keys=True` — unknown keys in the input cause a `ForbiddenExtraKeysError` (see below).
- `unstruct_collection_overrides={collection_type: callable}` — force collections of that type to
  unstructure via `callable` (e.g. `{set: sorted}` emits sets as sorted lists). An override keyed on
  an abstract collection type propagates to its concrete subtypes (e.g. an override on
  `collections.abc.Sequence` also applies to `list` fields).

## Unions

When structuring a `Union` of attrs classes/dataclasses, the converter automatically **disambiguates**
which member a mapping belongs to:

- If the members share a common `Literal` field, its value selects the member (a discriminator).
- Otherwise, each member's **unique required field** (a field present on only that member) selects it.
- A member all of whose fields have defaults (so it has no unique *required* field) serves as the
  **fallback**, chosen when no other member's unique field is present in the input.
- When a member's field is renamed via an `override(rename=...)` registered for that class,
  disambiguation matches on the renamed key.

Registering a structure hook directly on a `Union[...]` overrides automatic disambiguation.

Explicit strategies (`cattrs.strategies`):

- `configure_tagged_union(union, converter, *, tag_name="_type", tag_generator=<type name>,
  default=<none>)` — unstructuring adds a tag field (default key `_type`, default value the member's
  class name) to the output; structuring reads it to pick the member. `tag_name` customizes the key;
  `default` selects a member to use when the tag is missing/unknown.
- `include_subclasses(cl, converter, *, union_strategy=None, subclasses=None, overrides=None)` —
  configure `cl` so that a value typed as `cl` may be any of its (registered) subclasses. When a
  `union_strategy` is given (e.g. `configure_tagged_union`) the value round-trips via that strategy;
  when no `union_strategy` is given, structuring resolves to the correct subclass using the same
  automatic unique-field disambiguation as for unions (each subclass selected by a field unique to it).
- `configure_union_passthrough(union, converter)` — for a union of scalar types (e.g.
  `Union[int, str, None]`), validate that a value matches one of the members and pass it through
  unchanged. When the union includes `float`, an `int` value is accepted in place of a float.
- `use_class_methods(converter, structure_method_name=None, unstructure_method_name=None)` — route
  conversion through methods defined on the class: a classmethod named `structure_method_name`
  (called as `cls.method(data, type)`) and an instance method named `unstructure_method_name` (called
  as `instance.method()`), falling back to the defaults when a class lacks them.

## Validation and errors (`cattrs.errors`, `transform_error`)

With `detailed_validation=True` (the default), structuring **collects all errors** in the payload and
raises a grouped exception (an `ExceptionGroup` subclass):

- `ClassValidationError` — raised for attrs/dataclass/`TypedDict` structuring failures. Attributes:
  `.cl` (the class being structured) and `.exceptions` (the list of per-field sub-exceptions).
- `ForbiddenExtraKeysError` — raised when `forbid_extra_keys` is on and unknown keys are present;
  appears among a `ClassValidationError`'s sub-exceptions. Attribute `.extra_fields` is the set of
  offending key names.
- `StructureHandlerNotFoundError` — raised when no hook exists for a type. Attribute `.type_` is the
  unsupported type.

With `detailed_validation=False`, the first underlying native exception propagates directly instead of
being collected — e.g. a missing required field raises `KeyError(field_name)`.

`transform_error(exc)` converts a grouped validation error into a list of human-readable strings, one
per leaf failure, each of the form `"<description> @ <path>"`:

- Paths start at `$` (the root). Class attributes append `.<name>`; sequence/tuple indices append
  `[<int>]`; mapping keys append `[<repr-of-key>]` (so a string key `bad` renders as `['bad']`).
- Descriptions for common failures:
  - missing required field → `"required field missing"`
  - wrong type (a `ValueError`/`TypeError` from the leaf conversion) → `"invalid value for type,
    expected <type-name>"`
  - extra keys (with `forbid_extra_keys`) → `"extra fields found (<comma-separated names>)"`, reported
    at the class's path (e.g. `@ $`).

Example: structuring `{"b": [1, "z", 3], "c": {"x": "nope"}}` into a class with fields `a: int`,
`b: list[int]`, `c: Inner` (where `Inner` has `x: int`) yields, via `transform_error`:

```
required field missing @ $.a
invalid value for type, expected int @ $.b[1]
invalid value for type, expected int @ $.c.x
```
