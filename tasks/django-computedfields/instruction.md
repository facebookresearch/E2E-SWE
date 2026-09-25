# django-computedfields

Build `computedfields`, a Django application that provides **auto-updated
denormalized model fields**. A *computed field* is a real, concrete database
column whose value is produced by a Python method from other fields — on the
same model or on related models. The library keeps every computed field in sync
automatically: whenever a value it depends on changes (via `save()`, `delete()`,
or many-to-many changes), the dependent computed fields are recalculated and
written back to the database. The set of dependencies is declared per field and
compiled into a dependency graph at startup so updates propagate transitively
through chains of related models.

## Dependencies

The environment is **offline** — every dependency below is **already installed**.
Do **not** attempt to install anything (there is no network).

- Python 3.10+, **Django** (the test environment uses the 5.2 line) — already installed.
- `django-fast-update` (its `fast_update.fast.fast_update` is imported by the
  resolver) — already installed; list it in your project's install requirements so
  the project's own metadata is correct.
- `typing_extensions` — already installed.

The project must be installable/buildable by a `setup.sh` that runs **offline** in this
environment — for this Python project, a `setup.py` / `pyproject.toml` installable with
`pip install -e . --no-build-isolation` against the pre-installed dependencies above.

The package is a Django app named `computedfields`. It must be usable by adding
`"computedfields"` to `INSTALLED_APPS`. Its `AppConfig.ready()` must, on startup:
collect every model and computed-field declaration, **seal** the registry, build
the dependency maps, and connect the ORM signal handlers (`pre_save`, `post_save`,
`pre_delete`, `post_delete`, `m2m_changed`) that drive automatic updates. Models
without computed fields, and the `makemigrations`/`migrate` commands, must still
boot cleanly.

**Django app-loading lifecycle constraint:** model registration (via a metaclass
or `__init_subclass__`) happens at class-definition time, before the app registry
is fully populated. At that point you may inspect the class's own declared fields,
but you must **not** call `_meta.get_fields()` or traverse relation metadata —
those require the full registry and will raise `AppRegistryNotReady`. All
relation introspection, dependency-graph construction, and signal wiring must be
deferred to `AppConfig.ready()`.

## Package layout (import paths the tests rely on)

The public API is importable from `computedfields.models`:

```python
from computedfields.models import (
    ComputedFieldsModel, ComputedField, computed, precomputed,
    compute, update_dependent, preupdate_dependent,
    has_computedfields, get_computedfields, is_computedfield, get_contributing_fks,
    not_computed, active_resolver,
    ComputedFieldsAdminModel, ContributingModelsModel,
)
```

Additional import paths used:

- `from computedfields.resolver import ResolverException`
- `from computedfields.graph import CycleException`
- `from computedfields.signals import resolver_start, resolver_exit, resolver_update`

Management commands `updatedata`, `checkdata`, `showdependencies` must live in the
app so they are runnable via `django.core.management.call_command`.

## Declaring computed fields

### `ComputedFieldsModel`

Abstract base model. Every model that defines a computed field must subclass it.
It overrides `save()` so that local computed field values are recalculated and
included in the write before the row is persisted. `save()` accepts the normal
Django arguments plus a keyword `skip_computedfields: bool = False` that, when
true, skips the local recomputation (used by `@precomputed`, below).

### `@computed` decorator

```python
@computed(field, depends=None, select_related=None, prefetch_related=None,
          querysize=None, default_on_create=False)
def method(self): ...
```

`field` is a concrete Django field instance (e.g. `models.CharField(...)`,
`models.IntegerField(...)`, even `models.ForeignKey(...)`) that will hold the
result. The decorated method takes only `self` and returns the value to store.
The decorator turns the method into a real, non-editable model field.

### `ComputedField` (declarative form)

```python
area = ComputedField(models.IntegerField(default=0),
                     depends=[('self', ['width', 'height'])],
                     compute=lambda inst: inst.width * inst.height)
```

Identical semantics to `@computed`, but the compute function is passed as the
`compute=` keyword (a callable taking the instance). Same other keyword
arguments as `@computed`.

### The `depends` argument

A list of `(path, fieldnames)` rules. `path` is a string naming a relation to
traverse; `fieldnames` is a list of concrete field names on the model reached by
`path`. Forms:

- `('self', ['a', 'b'])` — local fields on the same model. Required for any
  dependency on the model's own fields, **including other computed fields on the
  same model**.
- `('relation', ['field'])` — a single relation hop: a forward `ForeignKey`,
  `OneToOneField`, a reverse FK/O2O accessor (the relation's `related_name`), or
  a `ManyToManyField` / its reverse accessor.
- `('a.b.c', ['field'])` — a multi-hop path; dots chain relation accessors.

A path may resolve to a single object (FK/O2O) or to a queryset (reverse FK,
M2M); the compute method is responsible for aggregating querysets (e.g. joining
related values). When a depended-upon value changes anywhere along a declared
path, the computed field is recomputed.

## Update semantics

- **On `save()`**, all of the instance's own computed fields are recomputed and
  written, regardless of what they depend on — a field declared on the model is
  "local" to it whether its `depends` reference `'self'` or related models, so
  e.g. a field depending only on a foreign key is (re)computed from the current
  related object every time the instance is saved (including on first create).
  They are recomputed in an order that respects local dependencies: a computed
  field that lists another of the model's computed fields in its `depends` is
  always computed *after* that field (local MRO). After the row is written, the
  change propagates to computed fields on *other* models that declared a
  dependency on the saved model.
- **`save(update_fields=[...])`** still works: the passed set is automatically
  expanded to include any local computed fields that depend on the named fields,
  so they are recomputed and written too.
- **Propagation is dependency-aware**: a change to a field is only propagated to
  a dependent computed field if that field name appears in the dependent's
  `depends` for the relevant path. A save touching only unrelated fields does not
  trigger unrelated recomputation.
- **`delete()`** triggers recomputation of computed fields that aggregated the
  deleted instance (e.g. a parent's reverse-FK aggregate shrinks).
- **Many-to-many changes** (`add`, `remove`, `set`, `clear`) recompute the
  computed fields on both sides of the relation.
- A **nullable relation** that becomes `None` recomputes the dependent field
  (the compute method handles the missing relation).
- A **computed field that is a `ForeignKey`** stores the returned model instance
  (object identity is preserved on reload), and ordinary relational behaviour
  such as `on_delete=CASCADE` applies to it.
- **Inheritance**: a computed field declared on an *abstract* base applies to
  each concrete subclass; a *multi-table* child may declare a computed field
  depending (via `'self'`) on a computed field inherited from its parent; a
  *proxy* model of a computed-fields model is recognised as having computed
  fields and behaves identically to its base.

## Inspecting and updating explicitly

### `compute(instance, fieldname) -> value`

Returns the value the named computed field *would* take, given the instance's
current in-memory state, **without mutating the instance or the database**. Used
to preview a result before saving.

### `update_dependent(instance_or_queryset, model=None, update_fields=None, old=None)`

Recomputes computed fields that depend on the given instance or queryset. Call
this after a **bulk** operation (e.g. `QuerySet.update()`, `bulk_create`) that
bypasses `save()` signals. `update_fields` narrows which source fields changed.

When a bulk operation **reassigns a foreign key** (moving rows from one related
object to another), the previously-related objects also have stale aggregates.
To handle this, capture the old relations *before* the bulk change with
`preupdate_dependent(...)` and pass the result as `old=` to `update_dependent`
*after* the change, so both the old and new related records are recomputed.

### `preupdate_dependent(instance_or_queryset, model=None, update_fields=None)`

Returns an opaque mapping of the currently-dependent records (as primary-key
lists) to feed back into `update_dependent(..., old=...)` after a bulk FK change.

## `@precomputed` — custom `save()` that needs current computed values

By default a custom `save()` body sees *stale* local computed field values
(they are recomputed by `ComputedFieldsModel.save` only after your body runs).
Decorate a custom `save()` with `@precomputed` to have local computed fields
brought up to date **before** the body executes:

```python
@precomputed
def save(self, *args, **kwargs):
    ...  # self.<computed_field> already reflects current data here
    return super().save(*args, **kwargs)
```

`@precomputed(skip_after=True)` additionally skips the post-body recomputation,
so a field changed *after* the precompute is not re-synced by the save (the
stored value reflects the precompute-time state). Calling the decorator with
invalid arguments (e.g. two positional args) raises `ResolverException`.

### `default_on_create`

With `default_on_create=True` on `@computed`/`ComputedField`, the field is **not**
computed on INSERT of a new (or pk-less) instance; instead its inner field's
`default` is used. On subsequent updates it is computed normally.

## The `not_computed` context

`not_computed` is a context manager that **disables** all automatic computed-field
updates within its block:

```python
with not_computed():
    ...  # saves here do not propagate to dependents (deliberate desync)
```

- Nesting shares a single context: entering a `not_computed` block while one is
  already active reuses the **outer** context rather than starting a new one, so
  leaving the inner block does nothing on its own and only exiting the outermost
  block ends suppression.
- `with not_computed(recover=True):` records the suppressed changes and, on exit
  of the outermost context, replays them so the database ends up consistent.
  Because nesting reuses the outer context, the replay happens exactly once, when
  the outermost block exits (not on each inner block exit).

## Resolver helpers

- `has_computedfields(model) -> bool` — whether the model has any computed field.
  A `ComputedFieldsModel` subclass that declares **no** computed field is *not*
  tracked and returns `False`.
- `get_computedfields(model)` — iterable of the model's computed field names.
- `is_computedfield(model, fieldname) -> bool`.
- `get_contributing_fks() -> {model: set_of_fk_field_names}` — for each model, the
  local foreign-key fields that participate (in reverse) in some computed-field
  dependency. These are exactly the FK fields requiring the
  `preupdate_dependent`/`old=` pattern on bulk reassignment.

`active_resolver` is the singleton resolver (importable from
`computedfields.models` or `computedfields.resolver`). Relevant methods:

- `get_select_related(model) -> set` and `get_prefetch_related(model) -> list` —
  the `select_related` / `prefetch_related` rules declared on the model's
  computed fields (empty set / empty list when none).
- `get_querysize(model) -> int` — the query batch size for the model: the minimum
  of the per-field `querysize` values and the global default
  `COMPUTEDFIELDS_QUERYSIZE` (which defaults to `10000`).
- `get_local_mro(model) -> list[str]` — the model's local computed field names in
  the topological order they must be evaluated in, so a computed field that
  depends on another local computed field (including one inherited from a parent
  model) is listed *after* it.
- `get_graphs() -> (intermodel_graph, {model: model_graph}, union_graph)` — the
  three dependency graphs. Each graph exposes `is_cyclefree`. Cyclicity is a
  property of an individual computed field, not of a model: a mutual dependency
  between two *models* — e.g. both sides of an M2M relation, or both sides of an
  O2O pair — is **cycle-free**, and it is only a cycle when some individual
  computed field transitively depends on itself. So a healthy configuration
  yields `is_cyclefree == True` for all three graphs even when models depend on
  each other mutually.
- `load_maps()` — (re)build the resolver's dependency maps from the current
  computed-field declarations. `AppConfig.ready()` invokes it at startup; calling
  it again rebuilds the maps. If the (possibly mutated) `depends` declarations form
  a cyclic computed-field dependency — local or across relations — it raises a
  `CycleException` (see below), unless cycle checking is disabled via
  `COMPUTEDFIELDS_ALLOW_RECURSION=True`.

## Cyclic dependencies (`computedfields.graph`)

Computed-field dependencies must be acyclic. When the resolver builds its maps
(at startup, or on a later `active_resolver.load_maps()`) and the `depends`
declarations form a cycle — whether local to one model or via relations — it
**rejects** the configuration by raising a `CycleException`, importable from
`computedfields.graph` as `from computedfields.graph import CycleException`.
`CycleException` is a subclass of `ComputedFieldsException`. (Setting
`COMPUTEDFIELDS_ALLOW_RECURSION=True` disables this check for intentionally
recursive setups such as tree structures.)

`computedfields.graph` also exposes the small directed-graph primitives the
resolver uses to detect cycles, usable on their own:

```python
from computedfields.graph import Graph, Node, Edge, CycleException, CycleEdgeException
```

- `Graph()` is a directed graph; `g.add_edge(Edge(Node(a), Node(b)))` adds an
  `a -> b` edge (inserting both nodes). `Node(x)` / `Edge(x, y)` are interned, so
  constructing the same node/edge twice yields the same object.
- `g.is_cyclefree` is a boolean property: `True` when the graph has no cycle,
  `False` when it does.
- `g.get_edgepaths()` / `g.get_nodepaths()` linearize the graph's paths and raise
  a `CycleException` if a cycle is present — respectively `CycleEdgeException` /
  `CycleNodeException`, both subclasses of `CycleException`.

The three dependency graphs returned by `active_resolver.get_graphs()` are
`Graph` instances and expose the same `is_cyclefree` property.

## Resolver signals (`computedfields.signals`)

Each automatic update of the dependency tree is bracketed by `resolver_start` and
`resolver_exit` (both send only `sender`). Between them, `resolver_update` is sent
for each model whose computed fields were written, with keyword arguments
`sender`, `model` (the model class), `fields` (a set of computed-field names), and
`pks` (a list of updated primary keys).

## `ComputedFieldsAdminModel` / `ContributingModelsModel`

Two `ContentType` proxy models (managed=False) usable as admin helper views:

- `ComputedFieldsAdminModel.objects` — a queryset of the content types of all
  models that have computed fields.
- `ContributingModelsModel.objects` — a queryset of the content types of all
  models that have foreign keys contributing to a computed-field dependency.

## Management commands

- **`updatedata [app_label[.ModelName] ...]`** — recompute and rewrite stored
  computed field values for the selected models (resyncs desynced rows).
- **`checkdata [app_label[.ModelName] ...]`** — verify stored computed values
  match recomputed values. If any row is out of sync it raises
  `django.core.management.base.CommandError`; when everything is in sync it
  completes without error.
- **`showdependencies [app_label ...]`** — print the dependency edges, one line
  per source field as `<source_field> -> <app_label>.<model> [<fields>]`, where
  `<model>` is the **lowercased** Django model name (`model._meta.model_name`),
  not the CamelCase class name. For example, a dependency targeting a `Post`
  model in an app labelled `blogapp` renders as `... -> blogapp.post [...]`.
  A source line is printed for **every** dependency source of a target model's
  computed fields — both each concrete field listed in a `depends` rule **and**
  each contributing foreign-key field that connects a related model back to the
  target (the local FK field name, i.e. the FK fields surfaced by
  `get_contributing_fks`). So for a `Comment` model contributing to `Post`'s
  reverse-FK computed fields via `depends=[('comments', ['text'])]`, where
  `Comment.post` is the foreign key back to `Post`, `showdependencies` prints
  both `text -> blogapp.post [...]` (the declared field) and
  `post -> blogapp.post [...]` (the contributing FK field).
