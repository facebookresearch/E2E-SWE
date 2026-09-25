# masoniteorm

Build `masoniteorm`, a SQL query builder with a per-dialect grammar compiler and
an Active Record-style model layer. The library constructs SQL strings from a
fluent builder API; queries are compiled (not executed) when inspected via
`to_sql()` / `to_qmark()`. Three SQL dialects must be supported: SQLite,
MySQL, and Postgres, each with its own grammar.

## Dependencies

The environment is fully **offline** — every dependency is already installed and
there is no network access. **Do not install, download, or upgrade anything**
(`pip install` from the index will fail); just implement the package. A
`setup.sh` installs your package into the environment offline (an editable
install against the pre-baked dependencies) so the tests can import it.

- Python 3.13
- Pre-installed third-party packages available at runtime: `pendulum`,
  `inflection`, `faker`, `cleo`. (Date handling on models uses `pendulum`;
  pluralization of inferred table names uses `inflection`.)
- No live database server is required or available. SQL is compiled — never
  executed — in a "dry" mode against a stand-in connection object.

## Package structure (import paths)

The following fully qualified imports must work exactly as written:

- `from masoniteorm.query import QueryBuilder`
- `from masoniteorm.query.grammars import SQLiteGrammar, MySQLGrammar, PostgresGrammar`
- `from masoniteorm.models import Model`
- `from masoniteorm.expressions import JoinClause, Raw`
- `from masoniteorm.relationships import belongs_to, belongs_to_many` (also
  `has_one`, `has_many`)
- `from masoniteorm.connections import ConnectionResolver`

## Configuration / connection resolution

`ConnectionResolver().set_connection_details(details)` registers a connection
dictionary keyed by connection name, e.g.
`{"default": "dev", "dev": {"driver": "sqlite", "database": "orm.sqlite3", "prefix": ""}}`.
Each entry's `driver` selects the grammar (`sqlite`/`mysql`/`postgres`).

Model classes that perform relationship traversal resolve their connection
details by importing a configuration module that exposes a module-level `DB`
attribute (the value returned by `ConnectionResolver().set_connection_details(...)`).
The module is located through the `DB_CONFIG_PATH` environment variable
(a dotted-or-slashed module path); if unset it defaults to `config/database`.
The lookup must read `DB_CONFIG_PATH` at call time.

## QueryBuilder

`QueryBuilder(grammar=None, table=None, connection_class=None, connection=None,
connection_details=None, model=None, dry=False, scopes=None)`. The first
positional argument is the grammar class. A `connection_class` is any object
exposing `connection_details` and `make_connection()`; in dry mode SQL is built
without contacting it. `table` may be a dotted `schema.table`.

The builder is fluent: every clause method returns `self` (or, for sub-query
callbacks, a fresh related builder). `new()` returns a fresh builder sharing the
same grammar/table; `table(name)` and `from_(name)` set the table.

### Example

A query is assembled fluently, then compiled — never executed — by `to_sql()`
or `to_qmark()`:

```python
from masoniteorm.query import QueryBuilder
from masoniteorm.query.grammars import SQLiteGrammar

# to_sql() inlines values as single-quoted strings:
QueryBuilder(SQLiteGrammar, table="users").where("id", 1).order_by("email").to_sql()
# -> SELECT * FROM "users" WHERE "users"."id" = '1' ORDER BY "email" ASC

# to_qmark() swaps each bound value for a '?' placeholder and records the
# ordered binding list on the builder's _bindings attribute:
b = QueryBuilder(SQLiteGrammar, table="users").where("id", 1)
b.to_qmark()    # -> SELECT * FROM "users" WHERE "users"."id" = '?'
b._bindings     # -> [1]
```

Swapping `SQLiteGrammar` for `MySQLGrammar` / `PostgresGrammar` changes the
dialect (e.g. MySQL quotes identifiers with backticks: `` `users`.`id` ``).

### Compilation contracts

`to_sql()` returns the compiled SQL string with all values inlined.
`to_qmark()` returns the SQL string with values replaced by placeholders and
records the ordered binding list on the builder's `_bindings` attribute.

**Identifier quoting** is dialect-specific: SQLite and Postgres wrap identifiers
in double quotes (`"users"."name"`), MySQL in backticks (`` `users`.`name` ``).
Column references in `select`, `where`, `group_by`, `having`, and join `ON`
clauses are qualified with the table name. **`order_by` is the exception**: its
columns are quoted but NOT table-qualified — `order_by("email")` compiles to
`ORDER BY "email" ASC`, never `ORDER BY "users"."email" ASC` (a column written
with an explicit `schema.col` dotted form is still qualified). When `table` is a
dotted `schema.table`, column qualification uses the full prefix, producing three
quoted segments (e.g. `"information_schema"."columns"."table_name"`).

**Value coercion** (for `to_sql()`): scalar values are emitted as
single-quoted strings regardless of Python type — `where("id", 1)` →
`"users"."id" = '1'`. Booleans are special: `True`/`False` are emitted inline as
`'1'`/`'0'` and are NOT recorded as bindings. A `Raw(...)` value supplied as an
UPDATE SET assignment (e.g. `update({"name": Raw('"username"')})`) is emitted
verbatim with no quoting — `UPDATE "users" SET "name" = "username"`.
`where_column(a, b)` treats `b` as a column reference, not a value.

**`to_qmark()` placeholder style**: each bound scalar is replaced by `'?'`
(a question mark inside single quotes). `where_in([...])` in qmark mode renders
spaced placeholders: `IN ('?', '?', '?')` (note the spaces). Booleans remain
inlined as `'1'`/`'0'` with no binding; `0` (int) IS a real binding. Bindings
are collected in source order: for UPDATE, SET values precede WHERE values;
`where_raw(sql, bindings)` contributes its bindings ahead of later clauses.
`between` and `not_between` are **asymmetric** in qmark mode: `between` converts
its two endpoints to `'?'` placeholders and records both bindings
(`BETWEEN '?' AND '?'`), but `not_between` does **NOT** — its endpoints stay
inlined as quoted literals with no bindings (`NOT BETWEEN '18' AND '65'`).

### SELECT clauses

- With no explicit `select()`, the builder compiles a bare `SELECT *` — the
  implicit/default star is never table-qualified (e.g.
  `QueryBuilder(table="users").to_sql()` → `SELECT * FROM "users"`, and likewise
  inside correlated `EXISTS` sub-selects). The qualification rule above applies to
  *named* column references, not the default star.
- `select(*cols)` (accepts comma-joined strings), `select_raw(sql)`,
  `add_select(alias, callback)` (inlines a parenthesized correlated sub-select
  aliased `AS alias`), `distinct()` (`SELECT DISTINCT ...`).
- Aggregates `sum/max/min/avg/count(col)`: rendered as `FUNC("t"."col") AS col`.
  `count("*")` renders `COUNT(*) AS m_count_reserved`. A column written
  `"age as number"` aliases the aggregate to `number`. **Clause ordering quirk:**
  plain selected columns are always emitted before aggregate columns in the
  SELECT list, even when the aggregate method is called first
  (`max("age").select("username")` →
  `SELECT "users"."username", MAX("users"."age") AS age FROM "users"`).
- `where(col, value)` / `where(col, op, value)` with operators
  `=, <, <=, >, >=, !=, like, not like, regexp, not regexp`; bare
  `where(col, value)` is equality. The word-operators are emitted **uppercased**
  in the compiled SQL (`like` → `LIKE`, `not like` → `NOT LIKE`,
  `regexp` → `REGEXP`, `not regexp` → `NOT REGEXP`); the symbol operators render
  verbatim. `or_where(...)` joins with `OR`.
  Passing a lambda to `where` produces a parenthesized AND-group
  `WHERE (... AND ...)`.
- `where_null` / `where_not_null` → `IS NULL` / `IS NOT NULL`;
  `or_where_null` joins with `OR`. `where_column(a, b)`. `where_date(col, val)`
  wraps the column in `DATE(...)`.
- `where_in(col, list)` / `where_not_in(col, list)`: in `to_sql()` the values
  are single-quoted and joined by a bare comma with no spaces
  (`IN ('1','2','3')`). An **empty** `where_in` compiles to the always-false
  predicate `WHERE 0 = 1`. A `QueryBuilder` or lambda passed instead of a list
  is inlined as a sub-select. A builder/lambda passed as a `where` value becomes
  a parenthesized scalar sub-select.
- `between(col, a, b)` / `not_between(col, a, b)` → `BETWEEN 'a' AND 'b'` /
  `NOT BETWEEN ...`.
- `where_exists(x)` / `where_not_exists(x)` where `x` is a builder or lambda →
  `WHERE EXISTS (...)` / `WHERE NOT EXISTS (...)`.
- `when(conditional, callback)` applies `callback(self)` only when `conditional`
  is truthy, otherwise the builder is returned unchanged (a conditional clause
  gate). `when(True, lambda q: q.where("age_restricted", 1))` adds the where;
  `when(False, ...)` is a no-op.
- `group_by(cols)` (comma-joined accepted), `group_by_raw(sql)`,
  `having(col)` (bare column), `having(col, value)` (equality),
  `having(col, op, value)`, `having_raw(sql)`.
- `order_by(spec, direction="asc")`: accepts comma-joined columns and per-column
  inline directions (`"email, name desc"`); the direction is uppercased
  (`ASC`/`DESC`). `order_by_raw(sql)` passes through verbatim. `latest(col)` →
  `ORDER BY "col" DESC`; `oldest(col)` → `ASC`.
- `limit(n)`, `offset(n)`, `first(query=True)` (appends `LIMIT 1`). **Offset
  quirk:** MySQL and Postgres emit a bare `OFFSET n`; SQLite has no bare offset,
  so an offset without a limit emits `LIMIT -1 OFFSET n`. Combined limit+offset
  emits `LIMIT n OFFSET m` on all three.
- Locks (MySQL only): `lock_for_update()` appends `FOR UPDATE`; `shared_lock()`
  appends `LOCK IN SHARE MODE`. SQLite emits no lock text.

### Joins

`join(table, first, op, second)` → `INNER JOIN`; `left_join(...)` → `LEFT JOIN`;
`right_join(...)` compiles to `LEFT JOIN` under SQLite and `RIGHT JOIN` under
MySQL. A table written `"report_groups as rg"` is compiled with an aliased
`AS`. `join` also accepts a `JoinClause` or a lambda receiving one, in
different argument slots: a pre-built clause is passed **in place of** the
table argument — `join(clause)`, and likewise `left_join` / `right_join` —
since the clause already carries its own table and alias, whereas the lambda
form keeps the table first, `join(table, lambda clause: ...)`, and is handed a
fresh `JoinClause` built for that table.
`JoinClause(table)` supports `.on(a, op, b)` (column = column),
`.on_value(a, op, literal)` (column = quoted value), `.on_null(col)` /
`.on_not_null(col)` (→ `col IS NULL` / `col IS NOT NULL`), and the `or_*`
variants. Multiple conditions chain with `AND` (or `OR` for `or_*`).
`.on` and `.on_value` columns are table-qualified on both sides
(`"bgt"."fund" = "rg"."fund"`, `"rg"."active" = '1'`), but the `.on_null` /
`.on_not_null` column is quoted **WITHOUT** table qualification — a clause
`.on_null("rg.deleted_at")` compiles to `"deleted_at" IS NULL` (the bare column
name only), not `"rg"."deleted_at" IS NULL`.

### Writes

**Return values.** `create`, `bulk_create`, `delete`, and `first` with
`query=True`, and `update` with `dry=True`, all return the **builder itself**
(not a string) — you then call `.to_sql()` / `.to_qmark()` on it (and may keep
chaining, e.g. `update(..., dry=True).where(...)`). By contrast `increment`,
`decrement`, and `truncate` return the compiled SQL **string** directly.

- `create(dict, query=True)` / `create(query=True, **kwargs)` →
  `INSERT INTO "t" (cols) VALUES (vals)` preserving dict insertion order. Both the
  column list and the values inside a `VALUES (...)` group are joined by a comma
  followed by a space, in both output modes — the bare no-space join described for
  `where_in` / `where_not_in` is specific to those two clauses.
- `bulk_create(list_of_dicts, query=True)`: the column list is the **sorted**
  union of keys; each row's values are aligned to that sorted column order;
  rows are comma-joined. In qmark mode each row is one placeholder group
  `('?'), ('?'), ...`.
- `update(dict, dry=True)` → `UPDATE "t" SET ... [WHERE ...]`; SET assignments
  follow dict order.
- `increment(col, n, dry=True)` / `decrement(col, n, dry=True)` return the compiled
  SQL string `UPDATE "t" SET "col" = "col" + 'n'` (or `-`) directly (like `truncate`,
  they accept the same `dry=True` keyword as `update`).
- `delete(col, value, query=True)` → equality WHERE; `delete(col, list, query=True)`
  → `WHERE "col" IN (...)`; chained `where(...).delete(query=True)` AND-joins.

**Column qualification in writes is dialect-specific.** Unlike SELECT (where
columns are always table-qualified), the INSERT/UPDATE/DELETE column templates
differ per grammar:
  - Under **SQLite**, the SET columns of an UPDATE and the WHERE columns of an
    UPDATE or DELETE are quoted but **NOT** table-qualified —
    `update({"name": "Joe"})` after `where("name", "bob")` compiles to
    `UPDATE "users" SET "name" = 'Joe' WHERE "name" = 'bob'`, and
    `delete("id", 1)` compiles to `DELETE FROM "users" WHERE "id" = '1'`.
  - Under **MySQL**, those same SET and WHERE columns **ARE** table-qualified —
    `update({"name": "Bob"}).where("name", "Joe")` compiles (in qmark form) to
    `` UPDATE `users` SET `users`.`name` = '?' WHERE `users`.`name` = '?' ``.
  This divergence is driven by the per-dialect write column template, not by
  `to_sql()` vs `to_qmark()`: the same dialect produces the same qualification in
  both modes.
- `truncate(dry=True)`: SQLite compiles to `DELETE FROM "t"`.

## Model

`Model` subclasses declare `__connection__` and optionally `__table__`
(otherwise inferred, pluralized, from the class name). A model instance exposes
the builder via attribute delegation, and class-level calls (e.g.
`Model.where(...)`, `Model.has(...)`) operate through a builder bound to the
model. `Model.hydrate(data)` produces a loaded instance.

### Relationships

Decorators define relationships on methods that return the related model class:

- `@belongs_to(local_key, foreign_key)`
- `@has_many(local_key, foreign_key)`, `@has_one(local_key, foreign_key)`
- `@belongs_to_many(local_key, foreign_key, local_owner_key, foreign_owner_key)`
  through an inferred pivot table: `local_key` / `foreign_key` name the pivot
  table's columns referencing the owner model and the related model, while
  `local_owner_key` / `foreign_owner_key` name the owner model's and the related
  model's own key columns.

Calling a relationship method on an instance returns a builder scoped to the
related table (e.g. `user.profile().where("name", "Joe")`). That builder starts
with no predicates of its own — the owner instance's key value is never applied
to it — so only the clauses chained onto it afterwards reach the compiled SQL;
the owner/related key correlation is added solely by the relationship-aware
builder methods below.

Relationship-aware builder methods compile to correlated `EXISTS` predicates:

- `has(relation)` → `WHERE EXISTS (SELECT * FROM <related> WHERE <related>.<fk> = <owner>.<lk>)`.
- `doesnt_have(relation)` → `WHERE NOT EXISTS (...)`.
- `has` / `doesnt_have` (and their `or_has` / `or_doesnt_have` counterparts)
  accept **one or more** relation names as positional arguments; each name
  contributes its own `[NOT] EXISTS` predicate, AND-joined onto the previous one
  (OR-joined for the `or_*` variants). `has("articles", "profile")` is therefore
  equivalent to `has("articles").has("profile")`.
- `where_has(relation, callback)` / `where_doesnt_have(relation, callback)` merge
  the callback's predicates into the EXISTS sub-query with `AND`.
- The full method family is: `has`, `doesnt_have`, `where_has`,
  `where_doesnt_have`, and their `OR`-joining counterparts `or_has`,
  `or_doesnt_have`, `or_where_has`. Each `or_*` variant joins its
  `[NOT] EXISTS` predicate onto the prior predicate with `OR` (instead of `AND`);
  the `*_doesnt_have` variants negate to `NOT EXISTS`. These compose by the same
  rules — e.g. `or_doesnt_have(relation)` → `OR NOT EXISTS (...)`, and
  `or_where_has(relation, callback)` → `OR EXISTS (... AND <callback predicates>)`.
- A dotted relation (`has("articles.logo")`) nests a second `EXISTS`, correlated
  to the first related table.
- For a **dotted** relation, `where_has` / `where_doesnt_have` (and their `or_*`
  variants) merge the callback's predicates into the **innermost** nested
  `EXISTS` — the sub-query over the final related model in the dotted chain —
  AND-joined after that sub-query's correlating key and qualified to that
  innermost related table, not the outer `EXISTS`.
- `joins(relation)` turns a relationship into an `INNER JOIN` on its keys; its `ON`
  clause follows the same operand convention as the pivot `INNER JOIN` shown for
  `belongs_to_many` below.
- `with_count(relation)` inlines a correlated `COUNT(*)` sub-select aliased
  `<related_table>_count` (and prefixes a `<owner_table>.*` select). For a
  `belongs_to_many`, the COUNT runs over the pivot table correlated to the owner,
  e.g. `Permission.with_count("role")` →
  `SELECT "permissions".*, (SELECT COUNT(*) AS m_count_reserved FROM "permission_role" WHERE "permissions"."id" = "permission_role"."permission_id") AS roles_count FROM "permissions"`.

For `belongs_to_many`, the `EXISTS` sub-query joins the pivot table, e.g.
`EXISTS (SELECT * FROM "permissions" INNER JOIN "permission_role" ON "permissions"."id" = "permission_role"."permission_id" WHERE "permission_role"."role_id" = "roles"."id")`,
and a `where_has` callback adds an `AND <related>.<id> IN (SELECT ...)` sub-select
carrying the callback predicates. The pivot table name is the singular related
and owner table names joined by `_` in alphabetical order
(e.g. `permission` + `role` → `permission_role`).
