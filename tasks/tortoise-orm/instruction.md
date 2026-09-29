# tortoise-orm — async ORM (core + SQLite)

Build `tortoise`, an `asyncio`-native Object-Relational Mapper for Python with relations as a
first-class concept. Models are declared as Python classes; the ORM generates a database schema,
and all data access (create/query/update/delete, relations, transactions) is `async`. This task
targets the ORM **core** with the **SQLite** backend (via `aiosqlite`, including in-memory DBs).

Correctness is defined by real database behavior: a model is created, the schema is generated
against a live SQLite database, rows are inserted, and queries must return the correct results. It
is not enough to expose the right method names — the queries must actually execute and return
correct data.

## Dependencies

Already installed (the environment is offline — do not install anything):

- `pypika-tortoise` — a SQL query-builder (build SQL ASTs / statements with it rather than
  hand-concatenating SQL).
- `aiosqlite` — async SQLite driver; supports `sqlite://:memory:`.
- `iso8601` / `ciso8601` — datetime parsing. `anyio` — async utilities. `tomlkit`,
  `typing-extensions` — available.

The project is installable with `pip install -e . --no-build-isolation`; its build backend is
`pdm-backend` and the version is static in `tortoise/__init__.py`. Package directory is `tortoise/`.

## Package structure

Public objects must be importable from exactly these paths:

- `tortoise` → `Tortoise`, `Model`, `fields` (a module/namespace), `run_async`
- `tortoise.fields` → `IntField`, `CharField`, `TextField`, `BooleanField`, `DecimalField`,
  `FloatField`, `DatetimeField`, `DateField`, `JSONField`, `UUIDField`, `IntEnumField`,
  `CharEnumField`, `ForeignKeyField`, `OneToOneField`, `ManyToManyField`
- `tortoise.exceptions` → `DoesNotExist`, `MultipleObjectsReturned`, `IntegrityError`,
  `FieldError`, `OperationalError`, `NoValuesFetched`, `ParamsError`, `ValidationError`,
  `ConfigurationError`
- `tortoise.expressions` → `Q`, `F`
- `tortoise.functions` → `Count`, `Sum`, `Avg`, `Min`, `Max`
- `tortoise.transactions` → `in_transaction`, `atomic`

Internal module layout is otherwise up to you.

---

## 1. Bootstrap & connections

`Tortoise` is a class exposing classmethods to initialize the ORM and manage connections:

- `await Tortoise.init(*, db_url, modules, _enable_global_fallback=False)` — configure the ORM.
  `db_url` is a connection string (e.g. `"sqlite://:memory:"`). `modules` is a dict mapping an *app
  label* to a list of module import paths to scan for `Model` subclasses (e.g.
  `{"models": ["__main__"]}`). It connects to the database and binds discovered models to the
  connection. The default connection label is `"default"`.
  - The ORM tracks the active configuration via a context variable. Passing
    `_enable_global_fallback=True` makes the connection resolvable globally (without an active
    context manager), so model operations work in code that runs outside the `init` call's own task.
    Support this keyword.
- `await Tortoise.generate_schemas()` — emit and execute `CREATE TABLE` DDL for all registered
  models on their connection(s).
- `await Tortoise.close_connections()` — close all connections.
- `Tortoise.get_connection(label)` — return the connection client for a label. The connection
  object must support `await conn.execute_query_dict(sql)` returning a list of row dicts.
- `run_async(coro)` — a helper that runs a coroutine and closes connections afterward (for scripts).

Cross-references to other models in field definitions use the string form `"<app_label>.<ModelName>"`
(e.g. `"models.Tournament"`), resolved during `init`.

---

## 2. Models

A model is a subclass of `tortoise.Model` whose class attributes are field instances:

```python
from tortoise import Model, fields

class Tournament(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    created = fields.DatetimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
```

Contracts:

- **Primary key.** A field with `primary_key=True` is the pk. If no field declares it, the ORM must
  inject an autoincrement integer pk named `id`. The default table name is the **lowercase class
  name** (`Tournament` → table `tournament`).
- **`Meta`** inner class options used here: `ordering` (default ordering, list of field names; a
  leading `-` means descending). Honor `ordering` for queries that don't specify their own.
- **Construction**: `Model(**kwargs)` builds an unsaved instance, assigning given fields and applying
  defaults to the rest. Passing `None` for a non-nullable field raises (`ValueError`).
- **`.pk`** is a property aliasing the pk field (readable/writable; usable in filters as `pk=`).
- **`__eq__`**: two instances are equal iff same class and same `pk`.
- **`__hash__`**: based on the pk; an instance whose pk is unset (`None`) is **unhashable**
  (`hash()` raises `TypeError`).
- A `__str__`/`__repr__` may be defined by the user.

### Instance lifecycle (all DB-backed)

- `await Model.create(**kwargs)` — construct, INSERT, and return the instance with its pk populated
  (for autoincrement pks, read back the new row id). Input values are **coerced** to the field's
  python type (e.g. `intnull="7"` stored/returned as `int` `7`).
- `await instance.save(*, update_fields=None)` — INSERT a new (unsaved) instance, or UPDATE an
  existing one. With `update_fields=[...]`, only those columns are written (others untouched);
  `update_fields=[]` writes nothing.
- `await instance.delete()` — DELETE the row. Deleting an instance that was never saved raises
  `OperationalError`.
- `await instance.refresh_from_db()` — reload column values from the database onto the instance.
- `await Model.get(**filters)` — return exactly one row. Zero matches → `DoesNotExist`; more than
  one → `MultipleObjectsReturned`.
- `await Model.get_or_none(**filters)` — like `get` but returns `None` for zero matches (still
  raises on multiple).
- `await Model.get_or_create(defaults=None, **filters)` — return `(instance, created: bool)`,
  creating the row (with `defaults` merged in) only if it does not already exist.

---

## 3. Fields

All fields accept the common options `null=False`, `default=...` (a value or a zero-arg callable
applied per instance at construction), `unique=False`, `primary_key=False`, `source_field=None`.

| Field | Notes / extra options | Stored & returned as |
|---|---|---|
| `IntField` | `primary_key=True` → autoincrement integer pk | `int` |
| `CharField` | **`max_length` required**; over-length value raises `ValidationError` on write | `str` |
| `TextField` | unbounded text | `str` |
| `BooleanField` | | `bool` (stored in an integer column; `True`/`False` round-trip) |
| `DecimalField` | `max_digits`, `decimal_places` required | `Decimal`, quantized to `decimal_places` and normalized on read (so `Decimal("1.10")` → `Decimal("1.1")`) |
| `FloatField` | | `float` |
| `DatetimeField` | `auto_now_add=True` sets the value once on first insert; `auto_now=True` updates it on every save (mutually exclusive) | `datetime` |
| `DateField` | | `date` |
| `JSONField` | serializes dict/list to text and parses back | the original `dict`/`list` |
| `UUIDField` | `default=uuid4` to auto-generate | `uuid.UUID` |
| `IntEnumField(enum_cls)` | enum members must be ints | the enum member (stored as its int value) |
| `CharEnumField(enum_cls)` | string enum | the enum member (stored as its `.value` string) |

Relational fields (see §6): `ForeignKeyField`, `OneToOneField`, `ManyToManyField`.

`source_field="col"` maps the python attribute to a differently-named database column; all
DDL/INSERT/UPDATE/SELECT use the aliased column name while the attribute keeps its python name.

---

## 4. QuerySet

Class-level query entry points return a lazy `QuerySet` (no SQL runs until it is awaited):
`Model.filter(...)`, `Model.exclude(...)`, `Model.all()`, `Model.annotate(...)`. A `QuerySet` is
chainable and immutable (each call returns a new queryset). Awaiting a queryset runs the query and
returns a `list` of model instances.

Methods:

- `filter(*Q, **lookups)` / `exclude(*Q, **lookups)` — add WHERE conditions (multiple chained
  filters AND together). `exclude` negates with SQL not-equal (so a row whose value is `NULL` is
  **not** returned by `exclude(field=x)`).
- `all()` — a queryset over all rows.
- `order_by(*fields)` — order ascending, or descending for a `-field`. Unknown field → `FieldError`.
- `limit(n)` / `offset(n)` — pagination; negative values raise `ParamsError`. Python slicing
  (`qs[a:b]`) maps to offset/limit.
- `values(*fields, **aliased)` — await → `list[dict]`. Fields may traverse relations with `__`
  (e.g. `values("name", "tournament__name")` projects a related-model column); `values_list`
  supports the same.
- `values_list(*fields, flat=False)` — await → `list[tuple]`; with `flat=True` and exactly one
  field → `list[scalar]` (more than one field with `flat=True` raises `TypeError`).
- `distinct()` — return a queryset that emits SQL `DISTINCT`, de-duplicating identical result
  rows; composes with `values(...)`/`values_list(...)` (dedup applies over the projected columns).
- `count()` — await → `int`. `exists()` — await → `bool`.
- `update(**kwargs)` — bulk UPDATE matching rows; await → number of affected rows. Values may be
  `F(...)` expressions for in-DB arithmetic.
- `delete()` — bulk DELETE matching rows; await → number of deleted rows.
- `first()` — await → the first matching instance or `None`.
- `in_bulk(id_list, field_name)` — await → `dict` mapping each `field_name` value to its instance.
- `select_related(*fields)` / `prefetch_related(*fields)` — see §6.

### Field-lookup operators

A filter keyword is `field` or `field__operator`. Supported operators (at least): exact (no
suffix), `gt`, `gte`, `lt`, `lte`, `in` (value is a list), `range` (inclusive `(low, high)` tuple),
`isnull` (bool), `contains`, `startswith`, `endswith`, `icontains` (and the other case-insensitive
`i*` forms). String matching uses SQL `LIKE`; on SQLite, ASCII `LIKE` is **case-insensitive** (so
`startswith="Ap"` matches both `"Apple"` and `"apricot"`). A filter value of `None`
(`filter(field=None)`) means `IS NULL` (equivalent to `field__isnull=True`).

Lookups may **span relations** with `__`: `filter(events__name="x")` joins to the related table and
filters on it.

### Q and F expressions

- `Q(**lookups)` (from `tortoise.expressions`) groups conditions; combine with `&` (AND), `|` (OR),
  and `~` (NOT). Pass `Q` objects positionally to `filter`/`exclude`.
- `F("field")` (from `tortoise.expressions`) references a column. In `update(...)` it performs
  in-DB arithmetic (e.g. `update(count=F("count") + 1)`); in `filter(...)` it compares one column
  against another (e.g. `filter(low=F("high"))`).
- A relation can be filtered by passing the **related model instance** directly as the value; its
  primary key is used (e.g. `Event.filter(tournament=tournament_obj)`).

---

## 5. Aggregation

`tortoise.functions` provides `Count`, `Sum`, `Avg`, `Min`, `Max`. Use them via
`Model.annotate(alias=Count("relation"))`. Aggregates accept `distinct=True` (count/aggregate only
distinct values) and `_filter=Q(...)` (aggregate only the rows matching the `Q`), e.g.
`Count("books__rating", distinct=True)`, `Count("books__id", _filter=Q(books__rating__gte=5))`.

- An aggregate annotation over a relation makes the query **group by** the base model's columns and
  yields a per-row aggregate (e.g. `Tournament.annotate(num=Count("events"))` → one row per
  tournament with its event count).
- The annotation alias is selectable via `.values(...)`/`.values_list(...)`, **filterable**
  (`filter(num__gt=1)` on an aggregate annotation applies a `HAVING` clause), and usable in
  `order_by(...)` (e.g. `order_by("-num")` sorts by the aggregate).
- Aggregates traverse relation paths (`Avg("books__rating")`).

---

## 6. Relations

### Foreign key (`ForeignKeyField("models.Target", related_name="...", null=...)`)

- Stored as a scalar column named `<field>_id`. Assigning a (saved) related object sets
  `instance.<field>_id` immediately; the related object must already be saved or `create`/`save`
  raises `OperationalError`.
- `await instance.<field>` returns the related object (querying the DB if not already loaded);
  `instance.<field>_id` is the raw key, available synchronously.
- The reverse side (named by `related_name`) is a relation manager on the target. Its querying
  methods — `.all()`, `.filter(...)`, `.order_by(...)`, etc. — return a **chainable `QuerySet`**
  (which you then `await`), exactly like the class-level query API; e.g.
  `await parent.<related_name>.all().order_by("name")`. It also offers
  `await parent.<related_name>.create(**kwargs)`, which creates a child with the FK set. Iterating
  the relation object itself **before it has been fetched** raises `NoValuesFetched`; querying it
  from an **unsaved** parent raises `OperationalError`.

### One-to-one (`OneToOneField(...)`)

Like a foreign key but unique. Forward access `await instance.<field>` returns the related object;
the reverse accessor returns the single owning object (or `None`).

### Many-to-many (`ManyToManyField("models.Target", related_name="...")`)

Backed by an automatically created join (through) table. The relation manager supports the
mutating coroutines `await rel.add(*objs)` (idempotent on duplicates), `await rel.remove(*objs)`,
`await rel.clear()`, plus the querying methods `rel.all()` / `rel.filter(...)` which return a
**chainable `QuerySet`** (then `await`ed). Both sides must be saved before `add`. Iterating the
relation object before fetch raises `NoValuesFetched`. Membership is filterable from either side
(`Event.filter(participants__name=...)` and `Team.filter(events__name=...)`).

### Eager loading

- `select_related(*fk_or_o2o_fields)` — fetch forward FK/O2O relations in the **same** query (a
  JOIN); afterwards `instance.<field>` is populated without a further await, and a `NULL` FK yields
  `None`.
- `prefetch_related(*relation_fields)` — fetch the named relations (including reverse-FK and M2M) in
  **separate batched** queries and populate each parent's relation container; afterwards the
  relation is iterable synchronously (e.g. `list(parent.children)`). A field may be a nested path
  (`"events__participants"`) to prefetch a relation of a relation.
- A `Prefetch` helper, importable from `tortoise.query_utils`, customizes a prefetch:
  `Prefetch("events", queryset=Event.filter(...), to_attr="kept")` prefetches using the given
  queryset and stores the result list under the attribute named by `to_attr`.

---

## 7. Transactions

`tortoise.transactions`:

- `async with in_transaction():` — run a block in a transaction. On clean exit it commits; if an
  exception propagates out, all writes in the block are rolled back. Nesting uses savepoints: an
  inner block that raises (and whose exception is caught outside it) rolls back only its own writes
  while the outer transaction still commits.
- `@atomic()` — a decorator wrapping an async function body in `in_transaction()` (commit on
  success, rollback on exception).

---

## 8. Exceptions (`tortoise.exceptions`)

- `DoesNotExist` — `get()` matched no rows.
- `MultipleObjectsReturned` — `get()` matched more than one row.
- `IntegrityError` — a database constraint violation (e.g. a `unique` collision, a NOT NULL
  violation on insert).
- `FieldError` — a query referenced an unknown field, or another field-level misuse.
- `OperationalError` — an invalid operation (deleting an unsaved instance; using an unsaved related
  object as an FK value; querying a reverse relation from an unsaved parent).
- `NoValuesFetched` — iterating a reverse/M2M relation that has not been fetched.
- `ParamsError` — invalid query parameters (e.g. negative `limit`/`offset`).
- `ValidationError` — a field validator failed (e.g. a `CharField` value exceeding `max_length`).
- `ConfigurationError` — invalid model/relation configuration.

`ValueError` is raised when constructing an instance with `None` for a non-nullable field.
