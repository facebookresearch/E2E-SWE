# django_migration_linter

Implement **django_migration_linter**, a Django application that detects
*backward-incompatible* database migrations. In a continuously-deployed,
highly-available service the database is migrated **before** the new code is
rolled out, so for a short window the old code runs against the new schema. Many
schema changes (dropping a column, adding a `NOT NULL` column without a default,
renaming things, …) break the old code during that window. This linter renders
each migration to SQL (via Django's `sqlmigrate`), runs a set of **checks** over
that SQL, and reports each migration as OK, an error, a warning, or ignored.

The package is installed as a Django app (added to `INSTALLED_APPS`). It provides
a `lintmigrations` management command, overrides `makemigrations` to optionally
lint freshly-generated migrations, and exposes a programmatic API.

## What it looks like in use

Running the command over a Django project prints one line per migration and a
summary, and exits non-zero if anything is backward-incompatible:

```
$ python manage.py lintmigrations
(app_add_not_null, 0001_initial)... OK
(app_add_not_null, 0002_add_field)... ERR
        NOT NULL constraint on columns
(app_drop_table, 0002_delete_b)... ERR
        DROPPING table
(app_rename_table, 0002_rename)... ERR
        RENAMING tables (table: app_rename_table_a)
(app_data_migration, 0002_data)... WARNING
        'forwards': RunPython data migration is not reversible
(app_ignore, 0002_ignored)... IGNORE

*** Summary ***
Valid migrations: 7/12
Erroneous migrations: 3/12
Migrations with warnings: 1/12
Ignored migrations: 1/12
```

The same detection is available programmatically. The low-level engine takes a
list of SQL statements (as `sqlmigrate` emits them) and returns the issues found:

```python
from django_migration_linter.sql_analyser import (
    analyse_sql_statements, PostgresqlAnalyser,
)

errors, ignored, warnings = analyse_sql_statements(
    PostgresqlAnalyser,
    ['ALTER TABLE "shop_order" ADD COLUMN "code" varchar(20) NOT NULL;'],
)
# errors[0].code     == "NOT_NULL"
# errors[0].message  == "NOT NULL constraint on columns"
```

…and the high-level `MigrationLinter` drives the whole pipeline (load migrations
→ render to SQL → analyse → categorise → count), the way the command does:

```python
from django_migration_linter import MigrationLinter

linter = MigrationLinter("/path/to/django/project", no_cache=True)
linter.lint_all_migrations()      # walks every project migration
linter.print_summary()
if linter.has_errors:             # True when nb_erroneous > 0
    raise SystemExit(1)
```

The sections below specify each piece precisely.

## Environment & dependencies

- The environment is **fully offline** — there is **no network access**. Every dependency you need
  is **already installed** in the image, so you must **not** run `pip install` or fetch anything
  over the network (it would fail); just import the packages listed below.
- Target **Python 3.13** and **Django 6.0** (both pre-installed). The grading environment runs
  against Django 6.0, so target that API (e.g. management-command internals you override must match
  Django 6.0).
- The runtime dependencies available to import are: **Django 6.0** (with its own `asgiref` and
  `sqlparse`), **`appdirs`** (a platform cache-directory helper, used for the default cache
  location), and **`toml`** (a TOML reader for `pyproject.toml` configuration; the stdlib `tomllib`
  is also available). Import only from these and the Python standard library.
- Provide a `setup.sh` at the repo root that installs **your** package offline, e.g.
  `pip install -e . --no-build-isolation`. The build backend (`setuptools`/`wheel`) is pre-baked and
  pip runs with `--no-index`, so `--no-build-isolation` is required and no network is used. Ship a
  `pyproject.toml`/`setup.py` that declares the package so the editable install succeeds.

## Public import surface

Implement these modules and importable names exactly (an importer relies on each
path):

- `django_migration_linter` re-exports `MigrationLinter`, `MessageType`, and
  `IgnoreMigration`.
- `django_migration_linter.sql_analyser` exports `BaseAnalyser`,
  `SqliteAnalyser`, `MySqlAnalyser`, `PostgresqlAnalyser`,
  `analyse_sql_statements`, and `get_sql_analyser_class`.
- `django_migration_linter.management.commands.lintmigrations` and
  `django_migration_linter.management.commands.makemigrations` provide the
  management `Command`s, discoverable via Django once the app is installed.

You are free to organize any other internal modules/helpers however you like.

## 1. The SQL analysers (`django_migration_linter.sql_analyser`)

The detection engine consumes a **list of SQL statement strings** (one element
per statement, as produced by `sqlmigrate`) and produces issues.

### `analyse_sql_statements(analyser_class, sql_statements, exclude_migration_tests=None)`

Instantiates `analyser_class`, runs every check, and returns a 3-tuple of lists
**`(errors, ignored, warnings)`**. Each element is an **issue object** with
attributes:

- `code` — the check's short code (e.g. `"DROP_TABLE"`).
- `message` — the human-readable description (see the table below).
- `table` — the table the offending statement concerns, or `None`.
- `column` — the column, or `None`.

A check whose code appears in `exclude_migration_tests` still fires, but its
issue is routed to the **ignored** list instead of errors/warnings.

Each check is either an **error** or a **warning**, and runs in one of two modes:

- **per-statement** — the check is applied to each statement string
  individually. `table`/`column` are extracted from that statement.
- **per-transaction** — the check is applied once to the whole statement list
  (so it can reason across statements). For per-transaction issues, `table` and
  `column` are `None`.

`table` is the first `TABLE "<name>"` found in the statement (quote characters
may be `"`, `` ` `` or `'`, case-insensitive); `column` is the first
`COLUMN "<name>"`. (Individual analysers may broaden this — see below.)

### Checks (codes, messages, type)

These checks apply to **every** analyser (they are the base set):

| code | message | type | mode |
|------|---------|------|------|
| `RENAME_TABLE` | `RENAMING tables` | error | per-statement |
| `NOT_NULL` | `NOT NULL constraint on columns` | error | per-transaction |
| `DROP_COLUMN` | `DROPPING columns` | error | per-statement |
| `DROP_TABLE` | `DROPPING table` | error | per-statement |
| `RENAME_COLUMN` | `RENAMING columns` | error | per-statement |
| `ALTER_COLUMN` | `ALTERING columns (Could be backward compatible. You may ignore this migration.)` | error | per-statement |
| `ADD_UNIQUE` | `ADDING unique constraint` | error | per-transaction |

Detection semantics:

- **`RENAME_TABLE`** — a statement containing `RENAME TABLE`, or matching
  `ALTER TABLE … RENAME TO`.
- **`DROP_TABLE`** — a statement that starts with `DROP TABLE`.
- **`DROP_COLUMN`** — a statement containing `DROP COLUMN`.
- **`RENAME_COLUMN`** — a statement matching `ALTER TABLE … RENAME COLUMN`, or
  `ALTER TABLE … CHANGE` (the MySQL spelling).
- **`ALTER_COLUMN`** — a statement matching `ALTER TABLE … ALTER COLUMN … TYPE`.
- **`NOT_NULL`** — looks across the whole transaction. It fires when some
  statement introduces a `NOT NULL` column **and** no default is set up for it.
  Specifically: a `NOT NULL` occurrence counts unless it is part of a
  `CREATE TABLE` / `CREATE INDEX` / `CREATE UNIQUE INDEX` statement, and unless
  it is a `DROP NOT NULL` or an `IS NOT NULL` predicate. A default suppresses the
  issue when the same transaction contains a column `DEFAULT <non-NULL>` next to
  the `NOT NULL`, or a `SET DEFAULT` (other than `SET DEFAULT NULL`); however a
  later `DROP DEFAULT` cancels that suppression.
- **`ADD_UNIQUE`** — fires when a statement matches
  `ALTER TABLE <t> ADD CONSTRAINT … UNIQUE` or `CREATE UNIQUE INDEX … ON <t>`,
  **unless** that same table `<t>` is created (`CREATE TABLE <t>`) within the same
  statement list (a unique constraint on a brand-new table is safe).

### `SqliteAnalyser`

SQLite cannot `ALTER TABLE` for most changes; Django instead **rebuilds** the
table — create `new__<t>` (or `<t>__old`), copy rows, drop the original, then
`ALTER TABLE new__<t> RENAME TO <t>`. The analyser must not mistake this dance
for a destructive change, while still catching genuine ones. It **replaces** the
base `RENAME_TABLE`, `DROP_TABLE`, and `NOT_NULL` checks with SQLite-aware ones:

- **`RENAME_TABLE`** — `ALTER TABLE … RENAME TO`, but **not** when the statement
  mentions `__old` or `new__` (those are rebuild steps).
- **`DROP_TABLE`** (per-transaction) — some statement starts with `DROP TABLE`
  **and** no statement starts with `CREATE TABLE` (a drop accompanied by a create
  is a rebuild, not a real drop).
- **`NOT_NULL`** (per-transaction) — some statement has a `NOT NULL` that is not
  `NOT NULL PRIMARY` and not `NOT NULL DEFAULT`, **and** the transaction is a
  rebuild (some `ALTER TABLE … RENAME TO` mentioning `__old`/`new__`). A bare
  `ALTER TABLE … ADD COLUMN … NOT NULL` (not a rebuild) is therefore *not* flagged
  by the SQLite analyser.

`SqliteAnalyser` also resolves `table` from an `ON "<name>"` clause when no
`TABLE "<name>"` is present.

### `PostgresqlAnalyser`

Inherits all base checks and **adds** these **warnings** (per-transaction except
where noted):

| code | message | mode |
|------|---------|------|
| `CREATE_INDEX` | `CREATE INDEX locks table` | per-transaction |
| `CREATE_INDEX_EXCLUSIVE` | `CREATE INDEX prolongs transaction, delaying lock release` | per-transaction |
| `DROP_INDEX` | `DROP INDEX locks table` | per-statement |
| `REINDEX` | `REINDEX locks table` | per-statement |

- **`CREATE_INDEX`** — a `CREATE [UNIQUE] INDEX … ON <t> (` exists, the index is
  **not** `CONCURRENTLY`, and `<t>` was **not** created earlier in the same
  statement list.
- **`CREATE_INDEX_EXCLUSIVE`** — the statement list opens with `BEGIN` and some
  later statement is an `ALTER TABLE` (which takes an exclusive lock); in that
  case a non-concurrent index creation is reported (this one *also* triggers
  `CREATE_INDEX` when the index target was not created in the transaction).
- **`DROP_INDEX`** — `DROP INDEX` not marked `CONCURRENTLY`.
- **`REINDEX`** — a statement starting with `REINDEX`.

### `MySqlAnalyser`

Inherits all base checks and **adds** one **error**: `ALTER_COLUMN` (message as
above) for a MySQL `ALTER TABLE … MODIFY …` column type change. It also resolves
`column` from a `MODIFY "<name>"` clause.

### `get_sql_analyser_class(database_vendor, analyser_string=None)`

- If `analyser_string` is given, map it directly: `"sqlite"`, `"mysql"`,
  `"postgresql"` → the corresponding class; anything else → `ValueError`
  (`Unknown SQL analyser '<s>'. Known values: 'sqlite','mysql','postgresql'`).
- Otherwise pick by substring of the vendor/engine string: `"mysql"`,
  `"postgre"`, or `"sqlite"`. An unrecognized vendor → `ValueError`
  (`Unsupported database vendor '<v>'. Try specifying an SQL analyser.`).

## 2. The linter (`django_migration_linter.MigrationLinter`)

`MigrationLinter(path=None, **options)` loads all project migrations (through
Django's migration loader) and lints them. Relevant constructor options
(all optional):

- `database` — DB alias (default Django's default); selects the analyser via the
  engine, unless `analyser_string` overrides it.
- `no_cache` / `cache_path` — caching (see §5).
- `no_output` — suppress all printing.
- `include_apps` / `exclude_apps` — only / never lint these app labels.
- `ignore_name_contains` / `include_name_contains` — substring name filters.
- `ignore_name` / `include_name` — exact migration-name filters.
- `exclude_migration_tests` — check codes whose issues are downgraded to
  *ignored* (passed through to the analysers and the data-migration checks).
- `all_warnings_as_errors` — treat every warning as an error.
- `warnings_as_errors_tests` — list of codes whose warnings become errors.
- `ignore_initial_migrations` — skip migrations marked `initial`.
- `only_applied_migrations` / `only_unapplied_migrations` — restrict by applied
  state.
- `analyser_string` — force a specific analyser (`"sqlite"`/`"mysql"`/`"postgresql"`).

### `lint_all_migrations(app_label=None, migration_name=None, git_commit_id=None, migrations_file_path=None)`

Gathers the project's migrations (excluding Django's own contrib apps) and lints
each. **Targeting** narrows *which migrations are linted at all*: with both
`app_label` and `migration_name`, only that one migration is linted; with just
`app_label`, only that app's migrations. **Filtering** options (the `include_*` /
`exclude_*` / `ignore_*` / `only_*` options above, and the `IgnoreMigration`
operation) instead mark a migration as **ignored** *after* it has been counted.

Concretely: a migration excluded by *targeting* is never counted; a migration
removed by *filtering* is counted in the total but recorded as ignored.

### Per-migration outcome and counters

For each linted migration, decide an outcome and update counters
(`nb_total`, `nb_valid`, `nb_erroneous`, `nb_warnings`, `nb_ignored`):

1. Increment `nb_total`.
2. If the migration should be ignored (any filtering option matches, or it
   contains an `IgnoreMigration` operation) → outcome **IGNORE**, `nb_ignored`.
3. Otherwise render it to SQL and run the analysers, *and* run the
   data-migration checks (§3). Combine the resulting errors/ignored/warnings,
   then apply `all_warnings_as_errors` / `warnings_as_errors_tests`. Then:
   - any errors → **ERROR**, `nb_erroneous`;
   - else any warnings → **WARNING**, `nb_warnings`;
   - else → **OK**, `nb_valid` (this includes the case where the only findings
     were downgraded to *ignored* by `exclude_migration_tests`).

`has_errors` is a property: `True` iff `nb_erroneous > 0`.

When printing (unless `no_output`), each migration emits a line
`(<app_label>, <name>)... <STATUS>` where `<STATUS>` is `OK`, `ERR`, `WARNING`,
`IGNORE` (or the cached variants in §5), followed by each issue message indented
by a tab; an error message additionally appends ` (table: <t>)` or
` (table: <t>, column: <c>)` when those are known. `print_summary()` writes:

```
*** Summary ***
Valid migrations: <nb_valid>/<nb_total>
Erroneous migrations: <nb_erroneous>/<nb_total>
Migrations with warnings: <nb_warnings>/<nb_total>
Ignored migrations: <nb_ignored>/<nb_total>
```

### `analyse_data_migration(migration) -> (errors, ignored, warnings)`

Inspects a migration's `RunPython` / `RunSQL` operations (see §3) and returns the
same kind of 3-tuple of issue objects as the SQL analyser.

## 3. Data-migration checks

Besides the schema SQL, `RunPython` and `RunSQL` operations are inspected for
these issues (this is what `analyse_data_migration` returns, and it is folded into
each migration's outcome by the linter). As with the
SQL checks, a code listed in `exclude_migration_tests` routes its issue to
*ignored*.

| code | type | when |
|------|------|------|
| `RUNPYTHON_REVERSIBLE` | warning | a `RunPython` has no reverse code |
| `RUNPYTHON_ARGS_NAMING_CONVENTION` | warning | the function's arguments are not exactly `(apps, schema_editor)` |
| `RUNPYTHON_MODEL_IMPORT` | error | the function uses `<Model>.objects` without a corresponding `…get_model(…)` call (i.e. a directly-imported model) |
| `RUNPYTHON_MODEL_VARIABLE_NAME` | warning | a model obtained via `get_model` is bound to a variable whose name differs from the model class named in the call |
| `RUNSQL_REVERSIBLE` | warning | a `RunSQL` has no reverse SQL |

A `RunSQL`'s forward (and reverse, when present) SQL is additionally run through
the SQL analysers, so e.g. a `RunSQL("DROP TABLE …")` yields a `DROP_TABLE` error.

Message formats (the function name is `RunPython.code.__name__`):

- `RUNPYTHON_REVERSIBLE`: `'<fn>': RunPython data migration is not reversible`
- `RUNPYTHON_ARGS_NAMING_CONVENTION`: `'<fn>': By convention, RunPython names the two arguments: apps, schema_editor`
- `RUNPYTHON_MODEL_IMPORT`: `'<fn>': Could not find an 'apps.get_model("...", "<Model>")' call. Importing the model directly is incorrect for data migrations.`
- `RUNPYTHON_MODEL_VARIABLE_NAME`: `'<fn>': Model variable name <name> is different from the model class name that was found in the apps.get_model(...) call.`
- `RUNSQL_REVERSIBLE`: `RunSQL data migration is not reversible`

## 4. `IgnoreMigration` operation & `MessageType`

- `IgnoreMigration` is a no-op `django.db.migrations.operations.base.Operation`
  subclass (reversible, `reduces_to_sql = False`, `elidable = True`). A migration
  whose `operations` include an `IgnoreMigration` is ignored by the linter.
- `MessageType` is an `enum.Enum` with members whose values are `"ok"`,
  `"ignore"`, `"warning"`, `"error"`. It also offers a `values()` helper
  returning that list of strings (used as the `--quiet` choices).

## 5. Caching

When caching is enabled (a `path` is set and `no_cache` is false), results are
persisted to a file under `cache_path` and reused on the next run. The cache is
keyed on the **content hash of the migration file** (so editing a migration
invalidates its entry). A cached migration prints its status with a ` (cached)`
suffix (e.g. `OK (cached)`, `ERR (cached)`) and updates the counters exactly as a
fresh result would. Caching is disabled when no `path` is provided or
`no_cache=True`.

## 6. Management commands

### `lintmigrations`

Lints the project (optionally narrowed by positional `app_label` /
`migration_name`). It mirrors the constructor options as command-line flags
(`--include-apps`, `--exclude-apps`, `--ignore-name`, `--ignore-name-contains`,
`--include-name`, `--include-name-contains`, `--exclude-migration-tests`,
`--no-cache`, `--cache-path`, `--database`, `--sql-analyser`,
`--warnings-as-errors`, `--applied-migrations`, `--unapplied-migrations`,
`--ignore-initial-migrations`, `--git-commit-id`, `--include-migrations-from`,
and `-q/--quiet` taking one or more of the `MessageType` values). It prints the
per-migration lines and the summary, and—after linting—**exits with status code
1 if any migration was erroneous** (otherwise it exits normally). `--quiet ok`
suppresses the `OK` lines, etc. Options may also be supplied via Django settings
(`MIGRATION_LINTER_OPTIONS`), `setup.cfg`/`tox.ini`/`.django_migration_linter.cfg`,
or `pyproject.toml` (`[tool.django_migration_linter]`); explicit CLI flags win.

### `makemigrations` (override)

Subclasses Django's `makemigrations`. Adds a `--lint` flag: after the new
migration files are written, each generated migration is linted and the linter's
per-migration output is shown (the lint runs with output enabled, not silently).
At verbosity ≥ 1 it writes a `Linting for '<app>':` heading, and under that
heading each generated migration produces its normal per-migration lint output —
the `(<app_label>, <name>)... <STATUS>` status line followed by each issue message
indented by a tab, exactly as the linter prints in §2 (so an erroneous generated
migration prints its `... ERR` line and then the issue message, e.g.
`NOT NULL constraint on columns`). If a generated migration is erroneous, it is
removed unless the user opts to keep it; in **non-interactive** mode the default
is to delete it, and a `Deleted <path>` line is written for each removed
migration. (Linting only happens when files were actually written, i.e. not under
`--dry-run`; it also runs without `--lint` when the
`MIGRATION_LINTER_OVERRIDE_MAKEMIGRATIONS` setting is true.)
