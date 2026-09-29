# SQLAlchemy-Continuum

Implement a **versioning and auditing extension for SQLAlchemy**. When a model is
marked as versioned, every `INSERT`/`UPDATE`/`DELETE` committed through a session
is recorded as a row in an automatically-generated *version table*, so the full
history of every row can be queried, navigated, and reverted.

The package must be importable as `sqlalchemy_continuum`.

**Public API.** Library symbols named below are importable directly from the
top-level `sqlalchemy_continuum` package, unless the section that introduces one
states an explicit submodule path.

## Dependencies

The environment is **offline** — do **not** install anything (no `pip install`,
no network access). The only runtime dependency, `SQLAlchemy` (2.0.x, exercised
here with the built-in SQLite backend), is **already installed**, as is the
`setuptools` build backend. Provide a `setup.sh` that installs *your* package
into this environment offline — a `pyproject.toml` / `setup.py` that
`pip install -e . --no-build-isolation` can build against the pre-installed
SQLAlchemy. Do not add SQLAlchemy (or any other package) as something to be
downloaded.

Everything below describes observable behavior the test suite relies on. Internal
organization is up to you, except where an exact import path or attribute name is
stated — those are part of the public contract and must match.

## Quickstart

A minimal end-to-end use of the library — this is how a user drives it and what
the tests exercise. It describes usage only, not how to implement the internals.

```python
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy_continuum import make_versioned, version_class, count_versions

make_versioned(user_cls=None)          # call before any models are defined
Base = declarative_base()

class Article(Base):
    __tablename__ = 'article'
    __versioned__ = {}
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.Unicode(255))

sa.orm.configure_mappers()             # builds ArticleVersion + the shared transaction model
engine = sa.create_engine('sqlite://')
Base.metadata.create_all(engine)       # creates article, article_version, transaction tables

session = Session(engine)
a = Article(name='first'); session.add(a); session.commit()
a.name = 'second'; session.commit()

assert count_versions(a) == 2
assert a.versions[0].operation_type == 0      # INSERT
assert a.versions[1].operation_type == 1      # UPDATE
assert a.versions[1].name == 'second'
ArticleVersion = version_class(Article)       # the generated version class
```

## Building the version classes (mapping requirements)

The version classes and the shared transaction model are generated as real,
fully-mapped SQLAlchemy ORM classes at `configure_mappers()` time. They must
satisfy the structural requirements below — this is where a naive implementation
collapses. (The *behavior* of each subsystem in §§3–13 is still up to you; only
the foundational mapping is pinned here.)

- **The transaction model is a mapped class on a table named `transaction`, in the
  same `MetaData`/registry as the user's models**, with an integer primary key
  `id`. Every version table's `transaction_id` (and, under validity,
  `end_transaction_id`) is a foreign key to `transaction.id`, so the transaction
  table must exist in that metadata for the foreign keys to resolve and for
  `Base.metadata.create_all()` to create it.
- **Each version class is a mapped class with its own mapped table** — set a
  `__tablename__`/`__table__`, or map it imperatively to a `Table`. It is not a
  plain class: `create_all()` must create its `<table>_version` table and
  `session.query(VersionClass)` must work.
- **Build and map each generated class exactly once per configuration.** Calling
  `configure_mappers()` again, or reconfiguring after `versioning_manager.reset()`,
  must not map an already-mapped class a second time (SQLAlchemy raises
  `ArgumentError: ... already has a primary mapper defined`).
- **Joined-table inheritance needs an explicit `inherit_condition`** joining the
  parent and child version tables on both the PK column(s) and the transaction
  column — there is no foreign key between version tables (see §10).
- **Configuration must be complete and self-consistent after `configure_mappers()`
  returns.** By that point the `transaction` table and every `<table>_version`
  table must exist in the user's metadata and every version class must be mapped,
  so the following `Base.metadata.create_all()` builds a consistent schema with all
  foreign keys resolvable. A partial or order-dependent build that leaves the
  transaction table out of the metadata on some runs will fail foreign-key
  resolution.

## 1. Enabling versioning

`make_versioned(options=None, user_cls='User', plugins=None)` — call once before
models are defined. It installs SQLAlchemy event listeners that build version
classes and record history. `options` is a dict of defaults (see §7). A model
opts in with `__versioned__ = {}`. After all versioned models are defined, call
`sqlalchemy.orm.configure_mappers()` to build version classes and the shared
transaction model.

`versioning_manager` is a module-level singleton with:
- `.plugins` — assignable list of active plugins.
- `.user_cls` — class/string name for transaction→user relationship; `None` disables.
- `.transaction_cls` — the transaction model (see `TransactionFactory` below).
- `.reset()` — clears per-run state for fresh configuration.

`sqlalchemy_continuum.transaction` exposes `TransactionFactory`: assign
`versioning_manager.transaction_cls = TransactionFactory()` before
`configure_mappers()` to (re)build the transaction model.

`remove_versioning()` tears down the listeners installed by `make_versioned`.
`ClassNotVersioned` is raised by accessors in §4 for non-versioned classes.

## 2. Version classes and tables

For a versioned model `Article` (table `article`), a version class `ArticleVersion`
mapped to `article_version` is generated (default pattern `%s_version`). The version
table contains each versioned data column plus:
- `transaction_id` — part of the PK alongside the parent's PK column(s);
- `operation_type` — non-nullable small integer (see §3);
- under **validity** strategy only, `end_transaction_id` (see §6).

Parent PK columns remain `NOT NULL`. For composite PKs, all original key columns
plus the transaction column form the version table's PK.

Each version object has a `version_parent` attribute — a viewonly relationship on
the PK columns — returning the live parent object, or `None` if deleted.

## 3. Recording changes

On each `session.commit()` that changes versioned data, one version row per
affected object is written with an **operation type**: `INSERT`→`0`,
`UPDATE`→`1`, `DELETE`→`2`.
- Re-assigning a column to its current value is **not** a change — no version row
  and no transaction. Updating only an *excluded* column (§7) likewise creates none.
- `UPDATE` stores the full row state (changed + unchanged versioned columns).
- `DELETE` preserves the row's last-known values (unless `NullDeletePlugin`, §12).
- Deleting then re-inserting the same PK within one commit → single `UPDATE` (op 1).

## 4. History access and utilities

- `obj.versions` — viewonly dynamic relationship returning version objects ordered
  by transaction id ascending. Returns a `Query` supporting indexing, `.all()`,
  `.count()`.
- `version.previous` / `.next` — adjacent version of the same object by transaction
  order, or `None` at boundaries.
- `version.index` — 0-based position in that object's history.
- `version.transaction` — the transaction object; `version.transaction_id ==
  version.transaction.id`.
- `version_class(Model)` → version class. `count_versions(obj)` → count. Both
  raise `ClassNotVersioned` for non-versioned input.

**Changesets.**
- `version.changeset` — dict mapping changed column names to `[old, new]`. INSERT:
  every column `None → value` (including PK). UPDATE: only changed columns.
  Internal columns (transaction/operation/end-transaction/plugin) never appear.
- `changeset(obj)` — pending change of a live ORM object, reversed ordering
  `[new, old]`: new object → `{col: [new, None]}`; dirty persisted →
  `{col: [new, old]}`; marked for deletion → `{col: [None, old]}` for non-None
  non-PK columns.

## 5. Point-in-time lookup

`ArticleVersion.version_at(session, {'id': pk}, transaction_id=tx)` returns the
version with the greatest transaction id `<=` tx (the row "active" at that point),
`None` if tx precedes the object's first version, and `None` for an unknown PK.

## 6. Versioning strategies

- **`validity`** (default) — each version carries `end_transaction_id`. When a
  newer version is written, the previous row's end-transaction is set to the new
  transaction id; the latest version has `None`. DELETE closes the last open range.
- **`subquery`** — neighbors computed on demand; no end-transaction column at all.

Both strategies expose the identical history-navigation API (§4).

## 7. Per-model configuration (`__versioned__` / options)

Options may be passed globally to `make_versioned(options=...)` or per model via
`__versioned__`. Supported options:
- `exclude` — column name(s) not to version. Excluded columns are absent from the
  version class; updating only an excluded column produces no new version.
- `strategy` — `'validity'` or `'subquery'` (§6).
- `transaction_column_name` / `end_transaction_column_name` — rename the transaction
  and end-transaction columns. When renamed, the default names must not appear.
- `base_classes` — a tuple of base classes for the generated version class. When
  `base_classes` contains a class already in the model's inheritance chain (e.g.
  the declarative base), the version class builder must deduplicate — do not
  include the same base twice in the MRO.

Models with composite primary keys are supported (§2).

## 8. Relationship reflection

Version classes expose relationship accessors returning related state as of that
version's transaction `T`:
- **one-to-many** → list of child version objects current at `T` (latest child
  version with tx ≤ T, excluding deletes), ordered by child PK.
- **many-to-one** → single parent version with greatest tx ≤ T, or `None`.
- **one-to-one** (`uselist=False`) → single version object, or `None`.
- **many-to-many** → list of associated version objects linked at `T`, backed by
  an association version table recording link history. Removing an association
  drops that object from later versions. Self-referential M2M with explicit
  `primaryjoin`/`secondaryjoin` works in both directions.
- **custom `primaryjoin`** with extra filter → filter preserved on reflected accessor.
- **`lazy='dynamic'`** → reflected as a Query yielding child version objects.
- **related class not versioned** → returns live original object(s).

**M2M association version tables.** For each association table `<assoc>` backing a
M2M between versioned models, a version table `<assoc>_version` is created containing
the original FK columns plus `transaction_id` and `operation_type`. Link additions
record operation_type `0` (INSERT); link removals record operation_type `2` (DELETE).

## 9. Revert

`version.revert()` restores the parent to that version's scalar column state.
`version.revert(relations=['tags'])` also restores listed relationships.
- INSERT version of a deleted object → resurrects with original PK/values.
  DELETE version → removes the object.
- `revert(relations=[...])` reifies relationships recursively. Nested paths use
  dotted names (e.g. `relations=['articles', 'articles.tags']`). After deep revert,
  the collection matches the reverted version exactly: removed children resurrected,
  later-added children pruned. One-to-one and M2M relationships likewise restored.
- Passing a relation name in `revert(relations=[...])` that is not a relationship
  on the parent class raises `ReverterException` (importable from
  `sqlalchemy_continuum.reverter`) before any revert is performed.

## 10. Inheritance

Version classes mirror the model hierarchy (`<Model>Version`):
- **single-table** — all version classes share one version table (`<base>_version`);
  child version classes inherit the parent version table.
- **joined-table** — each model gets its own version table (`<table>_version`); each
  carries the transaction column and PK. An insert writes a row to every level. The
  child version class must supply an explicit `inherit_condition` joining on both PK
  and transaction column (no FK between version tables).
- **concrete-table** — each concrete model gets its own version table.
- A subclass adding no table shares its parent's version table.

The version class builder replicates `polymorphic_on`, `polymorphic_identity`,
`with_polymorphic`, and `concrete` from the parent model. Version-class subclass
relationships hold (e.g. `version_class(Article)` is a subclass of
`version_class(TextItem)`).

## 11. Transactions

A `Transaction` model (one row per committing transaction) links all version rows:
- `versioning_manager.transaction_cls` is the transaction class. One row per commit
  that records changes (none for no-op). Transaction ids strictly increase.
- `transaction.issued_at` — a `datetime`, populated at creation time.
- `transaction.changed_entities` → dict mapping each version class to its list of
  version objects created in that transaction.
- `repr(transaction)` (no user class) is exactly
  `'<Transaction id={id}, issued_at={issued_at!r}>'`.

## 12. Plugins

Plugins are passed to `make_versioned(plugins=[...])` or assigned to
`versioning_manager.plugins`. They live in `sqlalchemy_continuum.plugins`.
- **`TransactionChangesPlugin`** — maintains a `transaction_changes` table with
  `(transaction_id, entity_name)` rows per changed class; `entity_name` is the changed
  model's **class name** (its `__name__`), not its table name. Exposes
  `transaction.entity_names` and `transaction.changes` — `changes` iterates that
  transaction's `transaction_changes` row objects (each exposing `entity_name`). The
  per-model changes class is reachable as `Model.__versioned__['transaction_changes']`.
- **`TransactionMetaPlugin`** — `transaction.meta` behaves as a dict (default `{}`),
  settable/mutable, persisted to `transaction_meta` table. Meta model at
  `versioning_manager.transaction_meta_cls` with `transaction_id`, `key`, `value`.
- **`PropertyModTrackerPlugin`** — adds non-nullable Boolean `<col>_mod` per
  versioned non-PK column. True if set/changed, False otherwise. INSERT: only set
  columns True. DELETE: all non-PK `*_mod` True. PK columns get no `*_mod`. `*_mod`
  never appears in changesets.
- **`NullDeletePlugin`** — DELETE version stores NULL for all non-PK columns
  (instead of deleted values); still records operation_type 2 and preserves PK.

## 13. Sessions and savepoints

- Versioning integrates with normal session usage, including manual flushes.
- Nested transactions (savepoints via `session.begin_nested()`) fold into the
  enclosing transaction: multiple committed savepoints within one outer commit
  produce a single transaction and a single version reflecting the final state.
- Rolling back a savepoint discards its changes from version history.
