# dj_cqrs — Django CQRS replication (master/replica core)

Build `dj_cqrs`, a Django library that keeps a read-only **replica** copy of a
model in one service synchronized with the **master** copy in another, using the
CQRS (Command Query Responsibility Segregation) pattern. When a master model
changes, it emits an event through a pluggable **transport**; a **consumer**
receives the event and applies it to the matching replica model. A per-record
revision number keeps updates correctly ordered.

This task covers the **in-process core**: the model mixins, the
master→transport→consumer→replica pipeline, transaction semantics, and the
revision logic. It does **not** require a live message broker — the configured
transport may be any class; in tests it forwards events in process.

## Dependencies

- **The environment is offline.** Every dependency below is already installed —
  do **not** install anything (there is no network).
- Python 3.10+ and **Django** (5.2.x is installed) are available. A few other
  libraries are also pre-installed and importable should you want them
  (`pika`, `kombu`, `ujson`, `django-model-utils`, `python-dateutil`,
  `watchfiles`); none are required — the in-process core in this task only needs
  Django.
- The project must be installable by a `setup.sh` that runs **offline** in this
  environment: provide a `pyproject.toml` or `setup.py` so that
  `pip install -e . --no-build-isolation` succeeds against the pre-installed
  dependencies. Declare `django` as a dependency. No system services are needed
  (tests run against an in-memory sqlite database with an in-process transport).

## Package structure (exact import paths the tests use)

```
dj_cqrs.mixins                # MasterMixin, ReplicaMixin
dj_cqrs.transport             # BaseTransport
dj_cqrs.controller.consumer   # consume(payload)
```

## Configuration

The library is configured through a `CQRS` dict in Django settings:

```python
CQRS = {
    'transport': 'dotted.path.to.TransportClass',   # subclass of BaseTransport
    'queue': 'replica',                             # this service's queue name
}
```

(Additional optional keys may be present.)

## Transport

`BaseTransport` (in `dj_cqrs.transport`) is the abstract base every transport
inherits from. Subclasses override three `@staticmethod`s:

- `produce(payload)` — send an event payload from a master model toward replicas.
- `consume(*args, **kwargs)` — receive an event payload.
- `clean_connection(*args, **kwargs)` — release any transport resources.

The transport named by `CQRS['transport']` is the one used to send a master's
events. The payload object produced by the master is the same object handed to
the consumer (see Pipeline); its internal shape is up to your implementation.

## Master models — `MasterMixin`

`MasterMixin` (in `dj_cqrs.mixins`) is an **abstract** Django model mixin. A
concrete master model subclasses it and declares its own fields.

Class attributes:

- `CQRS_ID` — a unique string identifying this model across services.
- `CQRS_PRODUCE` — bool, default `True`. When `False`, saving the model emits no
  event (the model still tracks its revision).
- `CQRS_FIELDS` — optional list of field names to include in the payload (default
  is all fields); it must include the primary key. When set, `to_cqrs_dict()`
  serializes only those fields (plus `cqrs_revision` and `cqrs_updated`).

The mixin contributes two bookkeeping fields:

- `cqrs_revision` — integer, starts at `0`.
- `cqrs_updated` — timestamp of the last change. The library runs inside host
  projects whose timezone configuration it does not control, so whatever it
  stores in this field must be a datetime that host project's Django settings and
  database will accept.

Behavior:

- **Revision.** Creating a new instance leaves `cqrs_revision` at `0`. Saving
  changes to an already-persisted instance increments `cqrs_revision` by one.
  The increment is applied **atomically at the database level** (`new = stored +
  1`), so that two independently loaded copies saved in sequence each advance the
  stored revision (`0 → 1 → 2`) rather than overwriting it from a stale
  in-memory value.
- **`to_cqrs_dict()`** — returns the serialized representation used as the event
  payload data: a dict containing each of the model's own concrete fields keyed
  by field name (including the primary key), plus `cqrs_revision` (the current
  integer revision) and `cqrs_updated` (a string). `date`/`datetime`/`UUID`
  values are serialized as strings.
- **`CQRS_SERIALIZER`** — optional class attribute: a dotted path to a serializer
  class. When set, `to_cqrs_dict()` builds the payload from the serializer class
  named by `CQRS_SERIALIZER` (resolved from its dotted path), constructed with the
  instance and read via its `.data` dict, instead of the default field-by-field
  serialization, then appends `cqrs_revision` and `cqrs_updated`.
- **`CQRS_TRACKED_FIELDS`** — optional class attribute: a list of field names (or
  `'__all__'`). When set, the model tracks changes to those fields so that, after
  a `save()`, the **previous** values of the tracked fields are captured and
  returned by **`get_tracked_fields_data()`**: for an update, a dict
  `{field: old_value}` for each changed tracked field; for a create, `{field:
  None}` for each tracked field that was set. (These previous values also travel
  with the event so a replica can receive them.)

## Pipeline (produce → consume)

- When a master instance with `CQRS_PRODUCE = True` is **saved** or **deleted**,
  the library produces an event through the configured transport
  (`BaseTransport.produce`). A save event carries the instance's serialized data;
  a delete event carries at least the primary key.
- **Events are emitted on transaction commit.** If the change happens inside a
  database transaction, the event is sent only after that transaction commits;
  if the transaction rolls back, no event is emitted.
- **Transaction-scoped de-duplication.** Multiple saves of the *same* instance
  within a single transaction produce **exactly one** event, carrying the
  instance's final state, and the revision is incremented **once** for that
  transaction. Saves in separate transactions produce separate events.
- **`dj_cqrs.controller.consumer.consume(payload)`** — the consumer controller.
  Given a produced payload, it selects the replica model whose `CQRS_ID` matches
  the payload and applies the event: a save event creates or updates the replica
  (via the replica's `cqrs_save`), a delete event removes it (via `cqrs_delete`).
  Matching is by `CQRS_ID`, so the master and its replica share the same value.

## Bulk operations

Each master model exposes a CQRS-aware manager as `Model.cqrs` (a Django
`Manager`). Plain Django bulk operations skip per-row signals, so this manager
re-emits CQRS events for them:

- **`Model.cqrs.bulk_create(objs)`** — bulk-inserts the objects and emits one
  **create** event per object (each at `cqrs_revision` 0).
- **`Model.cqrs.bulk_update(queryset, **kwargs)`** — applies `**kwargs` to every
  row in `queryset`, increments each row's `cqrs_revision` by one, and emits one
  **update** event per affected instance. Each affected row's `cqrs_updated`
  reflects the bulk change.

## Replica models — `ReplicaMixin`

`ReplicaMixin` (in `dj_cqrs.mixins`) is an **abstract** Django model mixin for
the read side. A concrete replica model subclasses it, declares the fields it
mirrors from the master, and shares the master's `CQRS_ID`. It also carries
`cqrs_revision` and `cqrs_updated` fields.

Class attributes:

- `CQRS_MAPPING` — optional `{master_field_name: replica_field_name}` dict. When
  set, `cqrs_save` renames incoming master fields to the replica's field names
  accordingly (the mapping must include the primary key; `cqrs_revision` and
  `cqrs_updated` are always carried through unmapped).

Classmethods (these must not need overriding for the default case):

- **`cqrs_save(master_data: dict)`** — create or update the replica row from a
  master payload dict (the shape `to_cqrs_dict()` produces). The row is keyed by
  primary key; field values are taken from `master_data` by matching field name
  (or via `CQRS_MAPPING` when set), and `cqrs_revision`/`cqrs_updated` are stored
  as received. Conflict resolution
  by `cqrs_revision`: create when absent; update when the incoming revision is
  greater than the stored one; ignore (leave the row unchanged) when the incoming
  revision is less than or equal to the stored one.
- **`cqrs_delete(master_data: dict) -> bool`** — delete the replica row keyed by
  the payload's primary key. Returns `True` on success (including when no row
  matches).
