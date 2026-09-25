# mongita

`mongita` is a lightweight, embedded document database with a **MongoDB / PyMongo-compatible API**
— "MongoDB for your local applications" with no server. You construct a client, address a database,
then a collection, and call pymongo-shaped methods (`insert_one`, `find`, `update_one`,
`create_index`, …). Documents are plain Python dicts; the library provides a query/update engine
(comparison operators, dotted-field access, sorting, indexes) over both an in-memory store and an
on-disk store.

Build this library so the behaviours below hold. You may organize the internals however you like
(module layout, helper functions, storage representation are up to you) **as long as the documented
import paths, signatures, return values, and observable behaviours resolve exactly as described.**

## Example use case

mongita is an embedded, MongoDB/PyMongo-compatible document store with no server: create a client, address a database and then a collection by attribute or key, and call the familiar pymongo methods.

```python
from mongita import MongitaClientMemory

client = MongitaClientMemory()          # or MongitaClientDisk(path) to persist to disk
books = client.bookshelf.fiction        # database "bookshelf", collection "fiction"

books.insert_many([
    {"title": "Dune", "author": "Herbert", "year": 1965},
    {"title": "Neuromancer", "author": "Gibson", "year": 1984},
])
books.update_one({"title": "Dune"}, {"$set": {"year": 1966}})
recent = [b["title"] for b in books.find({"year": {"$gte": 1965}}).sort("year")]
books.create_index("author")            # -> "author_1"
client.close()
```

## Packaging & dependencies

- The importable package is `mongita`; it must install as a standard editable project. A `setup.sh`
  installs it offline (`pip install -e . --no-build-isolation`) against the pre-installed
  dependencies, so provide a `pyproject.toml` / `setup.py` that builds with the `setuptools` backend.
- The environment is **offline** and every dependency is **already installed** — do **not** attempt
  to install anything (no `pip install`, no network access).
- Runtime dependencies you may use (already installed): **`pymongo`** (only for its bundled `bson` —
  auto-generated ids are `bson.ObjectId` instances) and **`sortedcontainers`**. No database server is
  involved.

## Public imports

```python
from mongita import (MongitaClientMemory, MongitaClientDisk, ASCENDING, DESCENDING,
                     errors, results, collection, database)
```

- `ASCENDING == 1`, `DESCENDING == -1`.
- `collection` and `database` are submodules exposing the classes `collection.Collection` and
  `database.Database` (the runtime types of collection/database handles).

### `mongita.errors`

A single exception hierarchy (all rooted at `MongitaError`):

- `MongitaError(Exception)` — the base class for every error this library raises.
- `MongitaNotImplementedError(MongitaError, NotImplementedError)` — an intentionally unimplemented
  pymongo feature.
- `InvalidName(MongitaError)`, `InvalidOperation(MongitaError)`, `OperationFailure(MongitaError)`,
  `DuplicateKeyError(MongitaError)`.
- `PyMongoError` — an alias of `MongitaError` (for pymongo compatibility).

Throughout, "raises a `MongitaError`" means that exact class or any subclass; where a **specific**
subclass is required it is named.

### `mongita.results`

Result objects returned by write methods (each has a readable `repr`):

- `InsertOneResult` — attribute `inserted_id`.
- `InsertManyResult` — attribute `inserted_ids` (a list).
- `UpdateResult` — attributes `matched_count`, `modified_count`, `upserted_id`.
- `DeleteResult` — attribute `deleted_count`.

## Clients — `MongitaClientMemory()` and `MongitaClientDisk(path)`

Both expose the same API; they differ only in storage:

- `MongitaClientMemory()` is **ephemeral**: two separate `MongitaClientMemory` instances share no
  data, and calling `client.close()` discards everything (subsequent reads return empty).
- `MongitaClientDisk(path)` **persists** under `path`: after writing and `close()`, a brand-new
  `MongitaClientDisk(path)` for the same path sees the previously written data. Values round-trip
  faithfully, including nested sub-documents and `datetime` values.

Client behaviour:

- `client.db` and `client["db"]` both return the `Database` named `"db"`, and compare equal
  (`client["db"] == client.db`). Any attribute / key names a database.
- `client.list_database_names()` → a `list[str]` of databases that currently hold data.
- `client.list_databases()` → an iterable yielding `Database` objects (consumable like an iterator).
- `client.drop_database(name_or_database)` removes a database (accepts a name or a `Database`).
- `client.close()`; `repr(client)` is a string.
- Addressing an invalid database name such as `client["$reserved"]` or `client[""]` raises a
  `MongitaError`.
- `client.close_cursor()` raises `MongitaNotImplementedError`.

## Databases — `database.Database`

- `db.name`; `repr(db)` is a string.
- `db.list_collection_names()` → a `list[str]` of collections that currently hold data.
- `db.list_collections()` → an iterable yielding `Collection` objects.
- `db.drop_collection(name_or_collection)` removes a collection.
- `db["coll"]` and `db.coll` both return the same `Collection` and compare equal.
- Collections are **lazy**: merely addressing one neither creates nor lists it. A never-written
  collection reports `count_documents({}) == 0` and does **not** appear in `list_collection_names()`
  until a document is inserted.
- Addressing an invalid collection name (`db["$reserved"]`, `db["system."]`, `db[""]`) raises a
  `MongitaError`.
- `db.add_son_manipulator()` and `db.dereference()` raise `MongitaNotImplementedError`.

## Collections — `collection.Collection`

Metadata:

- `coll.name` is the collection's own name; `coll.full_name` is `"<db>.<collection>"`
  (e.g. the `snake_hunter` collection of database `db` has `full_name == "db.snake_hunter"`).
- `coll.database` is the owning `Database`; `repr(coll)` is a string.
- Attribute access nests: `coll.blah` is a sub-collection whose `name` is `"<coll.name>.blah"`.
- `coll.read_concern` and `coll.write_concern` are objects whose `.document` is `{}`.
- `coll.with_options(read_concern=...)` returns an equivalent collection handle (same `name` and
  `database`); `coll.with_options(codec_options=...)` raises `MongitaNotImplementedError`.
- `coll.count()` and `coll.aggregate_raw_batches()` raise `MongitaNotImplementedError`.

### Inserting

- `insert_one(document)` → `InsertOneResult`. If `document` has no `_id`, one is generated as a
  `bson.ObjectId` and exposed via `inserted_id`; if it has an `_id`, that value is used verbatim.
  The call **must not mutate the caller's `document`** (e.g. it must not add an `_id` key to it).
- `insert_many(documents, ordered=True)` → `InsertManyResult` whose `inserted_ids` lists one id per
  inserted document, in order. With `ordered=True` (default), insertion **stops at the first failing
  document** (later ones are not inserted); with `ordered=False`, it continues past failures.
  Either way, a failure raises a `MongitaError`.
- Validation (each raises a `MongitaError`): a non-mapping document (string, list, …); an `_id`
  that is neither a `str` nor a `bson.ObjectId`; inserting a document whose `_id` already exists
  (a duplicate); passing `bypass_document_validation=...`. Calling `insert_one()` / `insert_many()`
  with no document argument raises `TypeError`.

### Querying — filters

A filter is a dict. With no filter (or `{}`) everything matches.

- `{field: value}` matches documents whose `field` equals `value`. If the stored field is a **list**,
  it matches when `value` is an element of that list.
- **Dotted keys** descend into nested sub-documents: `{"attrs.species": "Homo sapien"}`.
- Per-field **operators** (a dict of operator→operand): `$eq`, `$ne`, `$lt`, `$lte`, `$gt`, `$gte`,
  `$in`, `$nin`. Several operators on one field are **AND**-ed (e.g. `{"weight": {"$gt": 1, "$lt": 7}}`).
  - Ordered comparisons (`$lt`/`$lte`/`$gt`/`$gte`) select only values meaningfully comparable to the
    operand; values of an unrelated type (e.g. a string weight) or a missing field are not matched.
  - `$in` / `$nin` take a **list**. `$in []` matches nothing. `$nin` **also matches documents that
    lack the field**. For a list-valued field, `$in`/`$nin` test list membership.
- Invalid filters raise a `MongitaError`: an unknown operator (e.g. `{"weight": {"$nope": 7}}`); a
  non-list operand to `$in`/`$nin`; a filter that is not a dict; a non-string top-level key; an
  `_id` operand that is not a `str`/`ObjectId`.

### Querying — `find_one` / `find`

- `find_one(filter=None, sort=None, skip=0)` → a single matching document (a `dict`) or `None`.
  `sort` accepts a bare field name (`sort="name"`) or a list of `(field, direction)` pairs
  (`sort=[("weight", -1)]`); `skip` skips leading results.
- `find(filter=None, sort=None, limit=0, skip=0)` → a `Cursor` (see below); `sort`/`limit`/`skip`
  may be passed here or chained on the cursor.
- Returned documents include their `_id`. An auto-generated `_id` is a `bson.ObjectId`. Returned
  documents are **independent copies**: mutating a document returned from a query must not change
  what is stored (and vice-versa for documents handed to `insert_*`).

### Cursors — `cursor.Cursor`

A cursor is a **single-pass** iterator (once fully consumed it yields nothing further).

- `.sort(key_or_list, direction=ASCENDING)` — sort by a bare field name (optionally with a
  direction) or by a list of `(field, direction)` pairs (a multi-key sort applies keys left to
  right). **Sort order across mixed types:** missing/`None` values sort first, then numbers, then
  strings. This describes the **ascending** total order; a `DESCENDING` sort reverses that whole
  order (it is not an anchoring rule that keeps missing/`None` first regardless of direction), so
  under `DESCENDING` string values sort first, then numbers, and missing/`None` values sort **last**.
  A direction other than `ASCENDING`/`DESCENDING`, or a malformed sort spec (e.g. a pair whose first
  element is not a field name), raises a `MongitaError`.
- `.limit(n)` and `.skip(n)` — `n` must be an `int` (otherwise `TypeError`); a negative `skip`
  raises `ValueError`. `limit`/`skip` combine with `sort` regardless of the order they are chained.
- `.sort()`, `.limit()`, `.skip()` called **after iteration has begun** raise
  `errors.InvalidOperation`.
- `.next()` (and the builtin `next(cursor)`) return the next document. `.clone()` returns a fresh
  cursor that restarts from the beginning. `.close()` ends the cursor, so a subsequent `next()`
  raises `StopIteration`.
- `.count()`, `.allow_disk_use()`, and indexing (`cursor[0]`) raise `MongitaNotImplementedError`;
  an unknown attribute raises `AttributeError`.

### Counting & distinct

- `count_documents(filter)` → the number of matching documents. The `filter` argument is required
  (calling `count_documents()` raises `TypeError`).
- `distinct(key, filter=None)` → a `list` of the distinct values of `key` (dotted keys allowed)
  across matching documents. A non-string `key` raises a `MongitaError`.

### Updating & replacing

- `update_one(filter, update, upsert=False)` and `update_many(filter, update, upsert=False)` →
  `UpdateResult`. `update_one` modifies at most one matching document; `update_many` modifies all
  matches. `update` is a dict of **update operators**:
  - `$set` — set fields to values; dotted keys set/create nested fields (`{"$set": {"attrs.smart": True}}`).
  - `$inc` — add a number to a numeric field.
  - `$push` — append to a list field; pushing to a missing field creates a new single-element list.
  - `UpdateResult` reports `matched_count` (documents matched), `modified_count` (documents
    changed), and `upserted_id` (always `None` for these methods). With no match, both counts are `0`.
  - These methods do **not** implement upsert: `update_one`/`update_many` with `upsert=True` raises
    `MongitaNotImplementedError` (to upsert, use `replace_one`). The keyword still exists with a
    default of `False`; passing `upsert=False` is a no-op.
- Invalid updates: an `update` with no operator (a plain field dict like `{"name": "x"}`) raises a
  `MongitaError`; `$unset` raises `MongitaNotImplementedError`; `$inc` of/with a non-numeric value
  raises a `MongitaError`; `$push` to an existing non-list (scalar) field raises a `MongitaError`.
- `replace_one(filter, replacement, upsert=False)` → `UpdateResult`. Replaces the entire content of
  a matched document (its `_id` is preserved). `upsert=True` with no match inserts the replacement
  (`matched_count == 0`, `modified_count == 1`, `upserted_id` a new `ObjectId`; if the `filter`
  carried an `_id`, the inserted document uses it). With no match and no upsert, both counts are `0`.
  Calling `replace_one(filter)` with no replacement argument raises `TypeError`.

### Dotted paths & list-index addressing

Dotted keys (`"a.b.c"`) traverse nested sub-documents and lists in both queries and `$set` updates;
lists are addressed by integer position (`"attrs.pts.0"`).

- **`$set` builds nested structure:** a dotted `$set` creates any missing intermediate dictionaries
  (`{"$set": {"attrs.adorable": True}}` adds `adorable` under `attrs`).
- **`$set` extends a list:** assigning a list index at or beyond the list's current length extends
  the list, filling every newly-created position with `None` (e.g. setting index `5` of `[1, 2, 3]`
  to `10` yields `[1, 2, 3, None, None, 10]`). A dotted path that descends *past* a newly-created
  list position still extends the list, but stores nothing beyond that position — the position
  itself is left as `None`.
- **Invalid `$set` paths raise a `MongitaError`:** using a non-integer component to index a list
  (e.g. `"attrs.pts.seven"`), or descending into a scalar (non-container) list element
  (e.g. `"attrs.pts.0.boo.hoo"`).
- **Queries that don't resolve match nothing (no error):** a dotted query path that uses a
  non-integer list index, an out-of-range index, or descends into a scalar simply matches no
  document (it does not raise).
- **Whole-value equality is structural:** `{"field": [1, 2, 3]}` matches a document whose `field`
  is exactly that list; a nested mapping such as `{"attrs.dd": {"hello": ["w", "orld"]}}` matches
  only an identical nested value.

### Deleting

- `delete_one(filter)` removes at most one matching document; `delete_many(filter)` removes all
  matches. Both return a `DeleteResult` with `deleted_count`. The `filter` is required (calling them
  with no argument raises `TypeError`).

### Indexes

- `create_index(key)` → the index **name** as a string. `key` is a bare field name (ascending by
  default) or a single `[(field, direction)]` pair. The name is `"<field>_1"` for ascending and
  `"<field>_-1"` for descending (e.g. `create_index("kingdom") == "kingdom_1"`,
  `create_index([("weight", DESCENDING)]) == "weight_-1"`).
- Only **single-field** indexes are supported. The following raise a `MongitaError`: an empty/`int`/
  empty-list/dict key; a multi-field (compound) spec; a bad direction (e.g. `[("a", 2)]`); any extra
  keyword such as `background=True`.
- `index_information()` → a mapping of the collection's indexes that always includes the implicit
  `_id` index, so a collection with no user indexes has exactly **one** entry and each
  `create_index` adds one more.
- `drop_index(name_or_list)` removes an index by its name (`"kingdom_1"`) or by an equivalent
  `[(field, direction)]` pair. Any **string** is treated as a candidate index name (a name with no
  `_1` / `_-1` direction suffix is interpreted as ascending, i.e. as if `_1` were appended), so
  dropping a name that no index currently has — including a bare word like `"nope"` or `"kingdom1"`
  — raises `errors.OperationFailure`. A `name_or_list` that is **not** a string (e.g. `None`) is
  malformed and raises a `MongitaError`.
- Indexes only affect performance — query/update/delete results are identical with or without them.

## Module-level behaviour

Accessing a known pymongo top-level name that this library deliberately does not implement (for
example `mongita.InsertOne`) raises `MongitaNotImplementedError`; accessing a genuinely unknown
attribute raises `AttributeError`.
