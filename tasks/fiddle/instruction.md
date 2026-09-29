# Fiddle — a Python-first configuration library

Build a Python library named **`fiddle`** for configuring arbitrary Python code.

The central idea is *deferred construction*. Instead of calling a class or function
directly, a user describes a call as a **configuration object** ("a recipe"): the
target callable plus the arguments to pass it. Configurations can be nested, passed
around, inspected, edited, copied, compared, and tagged — and only at the end are they
turned into real objects by **building** them. The same configuration object may appear
in several places, in which case it represents one shared object.

The library's core logic is pure Python and relies only on the standard library; the code
generation subsystem (described at the end) additionally uses `libcst`. It is imported as:

```python
import fiddle as fdl
```

### Environment and dependencies

This environment is **offline — there is no network access, and you must not install
anything** (no `pip install`, no downloads). Every dependency is already installed for you,
and the project is built and installed automatically by a `setup.sh` that runs offline (an
editable install of the package you write). Just create the package source; do not write any
install or network steps yourself.

The following runtime dependencies are pre-installed and importable:

- `libcst` — used by the code generation subsystem.
- `absl-py`
- `graphviz`
- `typing-extensions`

The test harness (`pytest`) and the `setuptools`/`wheel` build backend are also pre-installed.
Build the library using only the Python standard library plus the dependencies listed above.

## Import layout

The following names must be importable directly from the top-level `fiddle` package
(i.e. as `fdl.<name>`):

> `Config`, `Partial`, `ArgFactory`, `Tag`, `TaggedValue`, `build`, `cast`, `copy_with`,
> `deepcopy_with`, `assign`, `update_callable`, `get_callable`, `ordered_arguments`,
> `materialize_defaults`, `add_tag`, `remove_tag`, `clear_tags`, `get_tags`, `set_tagged`

The following must be importable as submodules (i.e. `from fiddle import <module>`):

> `diffing`, `selectors`, `tagging`, `printing`, `arg_factory`, `daglish`, `history`

You are free to organize the internal file structure however you like, as long as the
import paths above resolve.

---

## Core: configurations and building

### Configuration types

- **`fdl.Config(callable, *args, **kwargs)`** — a configuration for `callable` (a class
  or a function). Arguments may be supplied positionally, as keywords, or assigned later
  as attributes (`cfg.x = ...`) and read back (`cfg.x`). A configuration nests: an
  argument value may itself be a configuration, or a plain `list`/`dict` containing
  configurations.
  - Supplying an argument the target callable does not accept is rejected: passing it to
    the constructor raises `TypeError`; assigning it as an attribute raises
    `AttributeError`.
  - Variadic targets are supported: extra positional arguments are bound to the callable's
    `*args` parameter. Positional arguments are also addressable by index on the
    configuration: `cfg[i]` reads a position, `cfg[i:j]` reads a slice (as a list),
    `cfg[i] = v` reassigns a position, and `del cfg[i]` removes a position (shifting the
    later positional arguments down).
  - The full range of parameter kinds is supported: keyword-only parameters are set by
    name, and if the target has a `**kwargs` parameter, extra keyword arguments are routed
    into it.

- **`fdl.Partial(callable, ...)`** — like `Config`, but *building* it produces a callable
  (a factory) rather than the finished object. Calling that factory constructs the object,
  and may override or supply additional arguments at call time.

- **`fdl.ArgFactory(callable)`** — used as an *argument value* inside a `Partial`. It
  supplies a freshly constructed value every time the enclosing factory is called, so
  separate calls do not share the same (possibly mutable) value. By contrast, a plain
  `Config` used as an argument of a `Partial` is built once and the resulting object is
  shared across every call of that factory.

### Building

- **`fdl.build(value)`** — turn a configuration into a real object. For a `Config`, it
  calls the target callable with the configured arguments, building any nested
  configurations first. `build` also descends into plain `list`/`dict` values, building
  any configuration found inside, even when the top-level value is not itself a
  configuration.
  - **Sharing is preserved.** If one configuration object is referenced from several
    places, building yields a single shared object reused at each of those places.
  - If construction fails (for example, a required argument was never set), `build`
    propagates the original exception with its **type preserved**, and augments the error
    message with the path to the sub-configuration that failed.
  - Configurations with cycles are not supported. If a configuration refers to itself
    (directly or transitively through nested arguments), `build` raises `ValueError`.

### Converting between types

- **`fdl.cast(NewType, cfg)`** — return an equivalent configuration of another buildable
  type (`Config`, `Partial`, or `ArgFactory`), preserving the set arguments. Casting a
  `Config` to a `Partial` changes building from "construct the object" to "return a
  factory".

---

## Inspecting and mutating configurations

- **`fdl.get_callable(cfg)`** — the callable the configuration targets.
- **`fdl.ordered_arguments(cfg)`** — a mapping of the arguments that have been *explicitly
  set*, in the order they were set. Arguments left at their default are not included.
  Passing `include_defaults=True` additionally includes every argument left at its default
  value (using the default).
- **`fdl.assign(cfg, **kwargs)`** — set several arguments at once.
- **`fdl.update_callable(cfg, new_callable)`** — change the target callable, keeping the
  already-set arguments that remain compatible. If an already-set argument is not a valid
  parameter of `new_callable`, this raises `TypeError`; passing `drop_invalid_args=True`
  instead drops those now-invalid arguments and keeps the rest.
- **`fdl.materialize_defaults(cfg)`** — turn arguments that are currently unset but have a
  default into explicitly-set arguments. This does not change what `build` produces.

### Edit history

Each configuration records the sequence of changes made to each argument. The history for
an argument is available as `cfg.__argument_history__[name]`: an ordered sequence of entries
(oldest first). Each entry exposes:

- **`.new_value`** — the value that was assigned.
- **`.kind`** — a `fiddle.history.ChangeKind`: `ChangeKind.NEW_VALUE` for a value
  assignment, `ChangeKind.UPDATE_TAGS` for a change to the argument's tags (adding or
  removing a tag is also recorded in history).
- **`.sequence_id`** — a monotonically increasing id giving a global order across all edits.

History recording can be suspended with the **`fiddle.history.suspend_tracking()`** context
manager: edits made inside the block still take effect but are not added to the history.

---

## Tags

A **tag** marks one or more arguments so related values can be managed together. Define a
tag by subclassing `fdl.Tag`. Tags can themselves subclass other tags, forming a tag
hierarchy.

- **`fdl.add_tag(cfg, name, Tag)`**, **`fdl.remove_tag(cfg, name, Tag)`**,
  **`fdl.clear_tags(cfg, name)`** — attach a tag to argument `name`, detach one tag, or
  remove all tags from that argument. These operate on `name` whenever it is a valid
  parameter of the target callable, **whether or not it has been explicitly set** — an
  argument left at its default (never assigned a value) is a valid tag target and does not
  need to be set first.
- **`fdl.get_tags(cfg, name)`** — the set of tags on argument `name`, as a `frozenset`
  (empty when `name` is a valid but untagged argument, including one still at its default).
- **`fdl.set_tagged(cfg, tag=Tag, value=...)`** — set every argument carrying `Tag`,
  anywhere in the configuration, to `value`. This matches by tag *inheritance*: setting by
  a tag also sets any argument carrying a subclass of that tag. An argument that carries a
  tag but was otherwise unset (still at its default) is also reached and given `value`.
  Assigning a value this way only *sets the value* — it does **not** remove the tag: the
  argument keeps the tag afterward, so `get_tags` and `tagging.list_tags` still report it
  (this holds even when the argument's value was one produced by `Tag.new(...)` /
  `fdl.TaggedValue(...)`, and regardless of whether the value was ever overridden). The same
  is true of `selectors.select(cfg, tag=Tag).replace(value=...)`. Freezing a tagged value into
  its concrete value — dropping the tag — happens only through `tagging.materialize_tags` (below).
- A tag attached to an argument is independent of whether that argument has a value: an
  untouched (default) argument that has been tagged continues to build to its default until
  `set_tagged` or a tag selector (below) assigns it a value, but throughout it participates
  fully in every tag operation — `get_tags` and `tagging.list_tags` report the tag,
  `set_tagged` and `selectors.select(cfg, tag=Tag).replace(value=...)` reach and set it, and
  `diffing.build_diff` records the tag as a change.
- **`Tag.new(default=...)`** — produce a *tagged value* that can be used as an argument
  value. When built, it yields `default`, unless the tag has been given a value first
  (e.g. via `set_tagged`).
- **`fdl.TaggedValue(tags=(TagA, TagB), default=...)`** — a tagged value carrying several
  tags at once. It can be set through any one of its tags, and `get_tags` reports all of
  them.
- **`fiddle.tagging.list_tags(cfg)`** — every tag used anywhere in the configuration, as a
  `frozenset`. Passing `add_superclasses=True` also includes the (non-`Tag`-root)
  superclasses of those tags.
- **`fiddle.tagging.materialize_tags(cfg)`** — replace tagged values with their current
  concrete values, in place.

---

## Selectors (`fiddle.selectors`)

Select parts of a configuration and edit them in bulk.

- **`selectors.select(cfg, SomeType)`** — selects every configuration in the graph whose
  target callable is `SomeType`. By default this also matches configurations whose target
  is a *subclass* of `SomeType`; pass **`match_subclasses=False`** to match the exact type
  only. Call **`.set(**kwargs)`** on the selection to set those arguments on every selected
  configuration, or **`.get(name)`** to iterate the value of argument `name` from each
  selected configuration.
- **`selectors.select(cfg, tag=Tag)`** — selects every argument carrying `Tag`. Call
  **`.replace(value=...)`** on the selection to set them all to `value`.
- Passing **`check_nonempty=True`** to `select` makes using a selection that matches
  nothing raise `ValueError` instead of silently doing nothing.

---

## Copying (`fdl.copy_with`, `fdl.deepcopy_with`)

- **`fdl.copy_with(cfg, **overrides)`** — a copy of `cfg` with `overrides` applied. The
  original is left unchanged, and internal sharing is preserved (a sub-config shared in the
  original is still shared in the copy).
- **`fdl.deepcopy_with(cfg, **overrides)`** — a deep, independent copy: editing the copy
  does not affect the original. Sharing *within* the copy is still preserved.

Configurations also support the standard library's `copy.copy`, `copy.deepcopy`, and
`pickle`. A shallow `copy.copy` shares the original's sub-configurations; `copy.deepcopy`
and a `pickle` round-trip both produce an independent equivalent. All three preserve
internal sharing — a sub-configuration referenced from several slots remains a single
shared node afterwards.

### Equality and hashing

Two configurations are equal when they have the same configuration type (a `Config` is
never equal to a `Partial`), target the same callable, have equal arguments, **and** have
the same internal sharing structure — so two configurations that are otherwise equal but
differ in whether a sub-configuration is shared across slots are *not* equal.
Configurations are mutable and therefore unhashable.

---

## Diffing (`fiddle.diffing`)

- **`diffing.build_diff(old, new)`** — compute a diff describing how to turn `old` into
  `new`. The diff exposes its individual changes as a sequence on its `.changes` attribute
  (empty when the two configurations are equal). Differences include arguments that changed
  value, arguments newly set in `new`, arguments removed in `new`, and changes nested deep
  in the graph.
- **`diffing.apply_diff(diff, target)`** — apply a diff to `target` in place. When the diff
  introduces sharing (the `new` configuration shared a sub-config across slots that were
  distinct in `old`), applying it reproduces that sharing in `target`.
- Diffs also capture **tag changes**: if `new` adds or removes a tag on an argument relative
  to `old`, that is included in the diff, and applying it reproduces the tag change on the
  target. Two configurations carrying identical tags and values diff to nothing.

---

## Printing (`fiddle.printing`)

- **`printing.as_str_flattened(cfg)`** — a string with one line per leaf argument. Each
  line has the form `path: type = value`, where `path` is the dotted path to the leaf
  (sequence elements are written with `[index]`). For example, a `units` argument equal to
  `8` two levels down might render as `model.layers[0].units: int = 8`.
- **`printing.as_dict_flattened(cfg)`** — a mapping from each *set* leaf's dotted path
  (same path style as above) to its value.

---

## Traversal (`fiddle.daglish`)

A **path** is a sequence of path elements that locates a value within a configuration:

- **`daglish.Attr(name)`** — moving into an attribute/argument named `name`.
- **`daglish.Index(index)`** — moving into position `index` of a sequence.
- **`daglish.Key(key)`** — moving into entry `key` of a dict; rendered by `path_str` as
  `['key']` (e.g. a path `Attr("components")`, `Key("enc")`, `Attr("units")` renders as
  `.components['enc'].units`).

Helpers:

- **`daglish.path_str(path)`** — render a path as a string. For example, the path made of
  `Attr("layers")`, `Index(1)`, `Attr("units")` renders as `.layers[1].units`.
- **`daglish.follow_path(root, path)`** — return the value reached by following `path` from
  `root`.
- **`daglish.iterate(value, memoized=...)`** — yield `(sub_value, path)` pairs for nodes
  reachable in `value`, where `path` locates `sub_value` relative to `value`. Traversal is
  depth-first in argument order, yielding each node before its children. With `memoized=True`,
  a node reachable from several places is yielded only once, at the FIRST path on which it is
  encountered during traversal; with `memoized=False`, it is yielded once per path that reaches
  it.
- **`daglish.collect_paths_by_id(value, memoizable_only=True)`** — return a mapping from
  each reachable object's `id()` to the list of all paths that reach it (so a shared node
  maps to every path that references it).

---

## The `arg_factory` module (`fiddle.arg_factory`)

Standalone helpers for "fresh value per call" arguments, independent of configurations.

- **`arg_factory.partial(fn, name=factory)`** — like `functools.partial`, except an
  argument bound to a *factory* (a zero-argument callable) is reconstructed on every call,
  so each call receives a fresh value. A factory may also be bound positionally
  (`arg_factory.partial(fn, factory)` binds `fn`'s first parameter). If a factory-bound
  argument is supplied explicitly at call time, the factory is not invoked for that call
  and the supplied value is used instead.
- **`@arg_factory.supply_defaults`** together with **`arg_factory.default_factory(factory)`**
  — declare a parameter's default as a factory. Each call that leaves the parameter unset
  receives a freshly constructed default.

---

## Serialization (`fiddle.experimental.serialization`)

Configurations can be serialized to JSON and back. Accessed as:

```python
from fiddle.experimental import serialization
```

- **`serialization.dump_json(config) -> str`** — serialize a configuration to a JSON string.
- **`serialization.load_json(s) -> config`** — reconstruct the configuration from that
  string. The round-trip preserves values **and shared-node structure** (a sub-config
  referenced from several slots is a single shared node again after loading). The callables
  a configuration targets must be importable by their module path so they can be resolved on
  load.

---

## Code generation (`fiddle.codegen.codegen`)

The reverse of building: turn a configuration *back* into Python source code that
reconstructs it. Accessed as:

```python
from fiddle.codegen import codegen
```

This subsystem depends on `libcst`. Generated code imports whatever symbols it references
(the target callables, `fiddle`), so the callables a configuration targets must be
importable by their module path.

- **`codegen.new_codegen(config, *, top_level_fixture_name="config_fixture", sub_fixtures=None)`**
  — return a string containing a self-contained Python module. The module defines a
  function (named by `top_level_fixture_name`, default `config_fixture`) that takes no
  arguments and returns a configuration **equal to `config`**, including its shared-node
  structure: a sub-configuration referenced from several places must be rebuilt as a single
  shared object, not duplicated. `Config`, `Partial`, `ArgFactory`, nested `list`/`dict`
  containers, and positional/variadic arguments are all reproduced. Tagged values are not
  required to be supported by this generator.
  - **`sub_fixtures={name: node}`** — emit each given node as its own separate top-level
    function named `name`, which the main fixture (and other fixtures) call instead of
    inlining that node. A node passed as a sub-fixture that is also shared elsewhere is
    emitted once and its single result reused, preserving sharing.

- **`codegen.auto_config_codegen(config)`** — return source for a fixture decorated with
  `@auto_config` (see below), written in ordinary call syntax (e.g. `MyClass(x=1)` rather
  than `fdl.Config(MyClass, x=1)`). The decorated `config_fixture` exposes
  **`config_fixture.as_buildable()`**, which returns a configuration equal to `config`
  (including shared nodes).

- **`codegen.codegen_dot_syntax(config)`** — a legacy generator. It returns an object whose
  **`.lines()`** method yields the lines of an imperative module that defines
  `build_config()` returning a configuration equal to `config`.

### `auto_config` (`fiddle.experimental.auto_config`)

- **`@auto_config.auto_config`** — a decorator for a function written in ordinary Python
  call syntax. The decorated function still runs normally, but also exposes
  **`.as_buildable()`**, which returns the corresponding configuration (each ordinary call
  `Cls(...)` inside the function body becomes an `fdl.Config(Cls, ...)`), preserving values
  shared between calls as shared nodes.
