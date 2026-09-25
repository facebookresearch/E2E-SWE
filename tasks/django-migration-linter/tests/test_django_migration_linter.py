from __future__ import annotations

import glob
import io
import os

import pytest
from django.core.management import call_command
from django.db import migrations

from django_migration_linter import MigrationLinter
from django_migration_linter.sql_analyser import (
    BaseAnalyser,
    MySqlAnalyser,
    PostgresqlAnalyser,
    SqliteAnalyser,
    analyse_sql_statements,
    get_sql_analyser_class,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def codes(issues):
    return [i.code for i in issues]


# --------------------------------------------------------------------------- #
# Group A: SQL analyser engine (analyse_sql_statements)                        #
# --------------------------------------------------------------------------- #


def test_base_oneliner_error_checks():
    e, i, w = analyse_sql_statements(BaseAnalyser, ['DROP TABLE "app_foo";'])
    assert codes(e) == ["DROP_TABLE"] and not i and not w
    assert e[0].message == "DROPPING table"
    assert e[0].table == "app_foo"

    e, _, _ = analyse_sql_statements(
        BaseAnalyser, ['ALTER TABLE "app_foo" DROP COLUMN "bar";']
    )
    assert codes(e) == ["DROP_COLUMN"]
    assert e[0].message == "DROPPING columns"
    assert e[0].table == "app_foo" and e[0].column == "bar"

    for sql in ('ALTER TABLE "a" RENAME TO "b";', "RENAME TABLE `a` TO `b`;"):
        e, _, _ = analyse_sql_statements(BaseAnalyser, [sql])
        assert codes(e) == ["RENAME_TABLE"] and e[0].message == "RENAMING tables"

    for sql in (
        'ALTER TABLE "a" RENAME COLUMN "x" TO "y";',
        "ALTER TABLE `a` CHANGE `x` `y` integer;",
    ):
        e, _, _ = analyse_sql_statements(BaseAnalyser, [sql])
        assert codes(e) == ["RENAME_COLUMN"] and e[0].message == "RENAMING columns"

    e, _, _ = analyse_sql_statements(
        BaseAnalyser, ['ALTER TABLE "a" ALTER COLUMN "x" TYPE integer USING "x"::integer;']
    )
    assert codes(e) == ["ALTER_COLUMN"]
    assert e[0].message.startswith("ALTERING columns")


def test_not_null_check():
    def err(sql_list):
        e, _, _ = analyse_sql_statements(BaseAnalyser, sql_list)
        return codes(e)

    # A NOT NULL column without a DEFAULT is incompatible.
    assert err(['ALTER TABLE "a" ADD COLUMN "x" integer NOT NULL;']) == ["NOT_NULL"]
    # ... but harmless when a DEFAULT accompanies it.
    assert err(['ALTER TABLE "a" ADD COLUMN "x" integer DEFAULT 0 NOT NULL;']) == []
    # NOT NULL inside a CREATE TABLE is a brand-new table, not a constraint add.
    assert err(['CREATE TABLE "a" ("id" integer NOT NULL PRIMARY KEY, "x" int NOT NULL);']) == []
    # The check spans the whole transaction: SET DEFAULT before SET NOT NULL is safe.
    assert err(
        [
            'ALTER TABLE "a" ALTER COLUMN "x" SET DEFAULT 0;',
            'ALTER TABLE "a" ALTER COLUMN "x" SET NOT NULL;',
        ]
    ) == []
    # ... but dropping that default again re-introduces the incompatibility.
    assert err(
        [
            'ALTER TABLE "a" ALTER COLUMN "x" SET DEFAULT 0;',
            'ALTER TABLE "a" ALTER COLUMN "x" SET NOT NULL;',
            'ALTER TABLE "a" ALTER COLUMN "x" DROP DEFAULT;',
        ]
    ) == ["NOT_NULL"]
    # "IS NOT NULL" predicates must not be confused with constraints.
    assert err(['UPDATE "a" SET x = 0 WHERE "x" IS NOT NULL;']) == []


def test_add_unique_check():
    def err(sql_list):
        e, _, _ = analyse_sql_statements(BaseAnalyser, sql_list)
        return codes(e)

    assert err(['ALTER TABLE "a" ADD CONSTRAINT "u" UNIQUE ("x");']) == ["ADD_UNIQUE"]
    assert err(['CREATE UNIQUE INDEX "u" ON "a" ("x");']) == ["ADD_UNIQUE"]
    # A unique constraint on a table created in the same transaction is safe.
    assert err(
        [
            'CREATE TABLE "a" ("id" integer);',
            'CREATE UNIQUE INDEX "u" ON "a" ("x");',
        ]
    ) == []


def test_sqlite_table_rebuild():
    def err(sql_list):
        e, _, _ = analyse_sql_statements(SqliteAnalyser, sql_list)
        return codes(e)

    rebuild = [
        'CREATE TABLE "new__a" ("id" integer NOT NULL PRIMARY KEY, "x" integer NOT NULL);',
        'INSERT INTO "new__a" ("id", "x") SELECT "id", 0 FROM "a";',
        'DROP TABLE "a";',
        'ALTER TABLE "new__a" RENAME TO "a";',
    ]
    # The sqlite table-rebuild dance must NOT be mistaken for a rename or a drop.
    assert err(rebuild) == ["NOT_NULL"]
    # A genuine rename / drop (no rebuild) is still flagged.
    assert err(['ALTER TABLE "a" RENAME TO "b";']) == ["RENAME_TABLE"]
    assert err(['DROP TABLE "a";']) == ["DROP_TABLE"]
    # A bare ADD COLUMN ... NOT NULL on sqlite is not the rebuild form -> not flagged.
    assert err(['ALTER TABLE "a" ADD COLUMN "x" integer NOT NULL;']) == []


def test_postgresql_index_warnings():
    def split(sql_list):
        e, _, w = analyse_sql_statements(PostgresqlAnalyser, sql_list)
        return codes(e), codes(w)

    assert split(['CREATE INDEX "i" ON "a" ("x");']) == ([], ["CREATE_INDEX"])
    assert split(['CREATE INDEX CONCURRENTLY "i" ON "a" ("x");']) == ([], [])
    assert split(['CREATE TABLE "a" ("id" int);', 'CREATE INDEX "i" ON "a" ("x");']) == ([], [])
    assert split(['DROP INDEX "i";']) == ([], ["DROP_INDEX"])
    assert split(['DROP INDEX CONCURRENTLY "i";']) == ([], [])
    assert split(['REINDEX INDEX "i";']) == ([], ["REINDEX"])
    _, w = split(['BEGIN;', 'ALTER TABLE "a" ADD COLUMN "x" int;', 'CREATE INDEX "i" ON "a" ("x");', 'COMMIT;'])
    assert set(w) == {"CREATE_INDEX", "CREATE_INDEX_EXCLUSIVE"}
    # Postgres still inherits the base ERROR checks.
    e, _, _ = analyse_sql_statements(PostgresqlAnalyser, ['DROP TABLE "a";'])
    assert codes(e) == ["DROP_TABLE"]


def test_mysql_analyser():
    e, _, _ = analyse_sql_statements(MySqlAnalyser, ["DROP TABLE `a`;"])
    assert codes(e) == ["DROP_TABLE"]
    e, _, _ = analyse_sql_statements(MySqlAnalyser, ["ALTER TABLE `a` MODIFY `x` integer ;"])
    assert codes(e) == ["ALTER_COLUMN"]


def test_get_sql_analyser_class():
    assert get_sql_analyser_class("django.db.backends.sqlite3") is SqliteAnalyser
    assert get_sql_analyser_class("django.db.backends.mysql") is MySqlAnalyser
    assert get_sql_analyser_class("django.db.backends.postgresql") is PostgresqlAnalyser
    assert get_sql_analyser_class("django.db.backends.sqlite3", analyser_string="postgresql") is PostgresqlAnalyser
    with pytest.raises(ValueError):
        get_sql_analyser_class("django.db.backends.oracle")
    with pytest.raises(ValueError):
        get_sql_analyser_class("x", analyser_string="oracle")


def test_exclude_migration_tests_analyser():
    e, i, w = analyse_sql_statements(BaseAnalyser, ['DROP TABLE "a";'], ["DROP_TABLE"])
    assert not e and not w
    assert codes(i) == ["DROP_TABLE"]


# --------------------------------------------------------------------------- #
# Group B: MigrationLinter pipeline                                            #
# --------------------------------------------------------------------------- #


def make_linter(**kwargs):
    kwargs.setdefault("no_cache", True)
    kwargs.setdefault("no_output", True)
    return MigrationLinter(HERE, **kwargs)


@pytest.mark.django_db(transaction=True)
def test_lint_full_project():
    linter = make_linter()
    linter.lint_all_migrations()
    assert linter.nb_total == 12
    assert linter.nb_valid == 7
    assert linter.nb_erroneous == 3
    assert linter.nb_warnings == 1
    assert linter.nb_ignored == 1
    assert linter.has_errors is True


@pytest.mark.django_db(transaction=True)
def test_lint_single_app():
    linter = make_linter()
    linter.lint_all_migrations(app_label="app_drop_table")
    assert linter.nb_total == 2
    assert linter.nb_erroneous == 1


@pytest.mark.django_db(transaction=True)
def test_lint_single_migration():
    linter = make_linter()
    linter.lint_all_migrations(app_label="app_drop_table", migration_name="0002_delete_b")
    assert linter.nb_total == 1
    assert linter.nb_erroneous == 1


@pytest.mark.django_db(transaction=True)
def test_include_exclude_apps():
    linter = make_linter(include_apps=["app_drop_table"])
    linter.lint_all_migrations()
    assert linter.nb_total == 12 and linter.nb_valid == 1 and linter.nb_erroneous == 1

    linter = make_linter(exclude_apps=["app_drop_table", "app_rename_table"])
    linter.lint_all_migrations()
    assert linter.nb_erroneous == 1


@pytest.mark.django_db(transaction=True)
def test_ignore_name_filters():
    linter = make_linter(ignore_name_contains="initial")
    linter.lint_all_migrations()
    assert linter.nb_erroneous == 3 and linter.nb_ignored == 8


@pytest.mark.django_db(transaction=True)
def test_exclude_migration_tests_pipeline():
    linter = make_linter(exclude_migration_tests=["DROP_TABLE"])
    linter.lint_all_migrations()
    assert linter.nb_valid == 8 and linter.nb_erroneous == 2


@pytest.mark.django_db(transaction=True)
def test_warnings_as_errors():
    linter = make_linter(all_warnings_as_errors=True)
    linter.lint_all_migrations()
    assert linter.nb_erroneous == 4 and linter.nb_warnings == 0

    linter = make_linter(warnings_as_errors_tests=["RUNPYTHON_REVERSIBLE"])
    linter.lint_all_migrations()
    assert linter.nb_erroneous == 4 and linter.nb_warnings == 0


@pytest.mark.django_db(transaction=True)
def test_ignore_initial_migrations():
    linter = make_linter(ignore_initial_migrations=True)
    linter.lint_all_migrations()
    assert linter.nb_ignored == 8 and linter.nb_valid == 0 and linter.nb_erroneous == 3


@pytest.mark.django_db(transaction=True)
def test_cache(tmp_path):
    import contextlib

    cache_dir = str(tmp_path)
    first = MigrationLinter(HERE, cache_path=cache_dir, no_output=True)
    first.lint_all_migrations()
    # A cache file is persisted under cache_path (format is unspecified).
    assert os.listdir(cache_dir)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        second = MigrationLinter(HERE, cache_path=cache_dir, no_output=False)
        second.lint_all_migrations()
    assert "(cached)" in out.getvalue()
    assert second.nb_erroneous == first.nb_erroneous == 3
    assert second.nb_valid == first.nb_valid == 7


# --------------------------------------------------------------------------- #
# Group C: data migrations                                                     #
# --------------------------------------------------------------------------- #


def _data_issues(linter, *operations):
    m = migrations.Migration("0002_data", "app_correct")
    m.operations = list(operations)
    return linter.analyse_data_migration(m)


@pytest.mark.django_db
def test_runpython_checks():
    linter = make_linter()

    def not_reversible(apps, schema_editor):
        pass

    def bad_args(foo, bar):
        pass

    def direct_import(apps, schema_editor):
        A.objects.all()  # noqa: F821

    def var_mismatch(apps, schema_editor):
        Author = apps.get_model("app_correct", "A")
        Author.objects.all()

    def good(apps, schema_editor):
        A = apps.get_model("app_correct", "A")
        A.objects.all()

    e, i, w = _data_issues(linter, migrations.RunPython(not_reversible))
    assert codes(e) == [] and codes(w) == ["RUNPYTHON_REVERSIBLE"]

    e, i, w = _data_issues(linter, migrations.RunPython(bad_args))
    assert "RUNPYTHON_ARGS_NAMING_CONVENTION" in codes(w)

    # Using a directly-imported model (no apps.get_model) is an error.
    e, i, w = _data_issues(linter, migrations.RunPython(direct_import))
    assert "RUNPYTHON_MODEL_IMPORT" in codes(e)

    # A get_model call bound to a differently-named variable warns.
    e, i, w = _data_issues(linter, migrations.RunPython(var_mismatch))
    assert codes(e) == [] and "RUNPYTHON_MODEL_VARIABLE_NAME" in codes(w)

    # A correct data migration that uses apps.get_model with a matching variable
    # name only trips the reversible warning.
    e, i, w = _data_issues(linter, migrations.RunPython(good))
    assert codes(e) == [] and codes(w) == ["RUNPYTHON_REVERSIBLE"]


@pytest.mark.django_db
def test_runsql_checks():
    linter = make_linter()
    e, i, w = _data_issues(linter, migrations.RunSQL("UPDATE app_correct_a SET name='x';"))
    assert codes(w) == ["RUNSQL_REVERSIBLE"]

    e, i, w = _data_issues(linter, migrations.RunSQL("DROP TABLE app_correct_a;"))
    assert "DROP_TABLE" in codes(e)

    # A reversible, harmless data migration produces nothing.
    e, i, w = _data_issues(
        linter, migrations.RunSQL("UPDATE a SET y=1;", reverse_sql="UPDATE a SET y=0;")
    )
    assert not e and not w and not i


# --------------------------------------------------------------------------- #
# Group D: lintmigrations CLI                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db(transaction=True)
def test_lintmigrations_cli():
    import contextlib

    out = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        with contextlib.redirect_stdout(out):
            call_command("lintmigrations", no_cache=True, verbosity=1)
    assert exc.value.code == 1
    text = out.getvalue()
    assert "(app_drop_table, 0002_delete_b)... ERR" in text
    assert "DROPPING table" in text
    assert "*** Summary ***" in text
    assert "Valid migrations: 7/12" in text


@pytest.mark.django_db(transaction=True)
def test_lintmigrations_cli_options():
    import contextlib

    # Excluding the failing check makes the run succeed (no SystemExit) and the
    # app's two migrations report zero errors in the summary.
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        call_command(
            "lintmigrations",
            "app_drop_table",
            exclude_migration_tests=["DROP_TABLE"],
            no_cache=True,
            verbosity=1,
        )
    assert "Erroneous migrations: 0/2" in out.getvalue()

    # --quiet ok suppresses the OK lines.
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        call_command(
            "lintmigrations", "app_correct", quiet=["ok"], no_cache=True, verbosity=1
        )
    assert all("... OK" not in line for line in out.getvalue().splitlines())
    assert "*** Summary ***" in out.getvalue()


@pytest.mark.django_db(transaction=True)
def test_lintmigrations_config_from_settings():
    import contextlib

    from django.test import override_settings

    # Options may be supplied via the MIGRATION_LINTER_OPTIONS setting instead of
    # on the command line: excluding DROP_TABLE there clears the only error.
    out = io.StringIO()
    with override_settings(
        MIGRATION_LINTER_OPTIONS={"exclude_migration_tests": ["DROP_TABLE"]}
    ):
        with contextlib.redirect_stdout(out):
            call_command("lintmigrations", "app_drop_table", no_cache=True, verbosity=1)
    assert "Erroneous migrations: 0/2" in out.getvalue()

    # An explicit command-line flag takes precedence over the setting: excluding a
    # different check leaves the DROP_TABLE error in place (non-zero exit).
    out = io.StringIO()
    with override_settings(
        MIGRATION_LINTER_OPTIONS={"exclude_migration_tests": ["DROP_TABLE"]}
    ):
        with pytest.raises(SystemExit) as exc:
            with contextlib.redirect_stdout(out):
                call_command(
                    "lintmigrations",
                    "app_drop_table",
                    exclude_migration_tests=["NOT_NULL"],
                    no_cache=True,
                    verbosity=1,
                )
    assert exc.value.code == 1
    assert "Erroneous migrations: 1/2" in out.getvalue()


# --------------------------------------------------------------------------- #
# Group E: makemigrations --lint                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db(transaction=True)
def test_makemigrations_lint():
    import contextlib

    mdir = os.path.join(HERE, "app_makemig", "migrations")
    before = set(glob.glob(os.path.join(mdir, "0*.py")))
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            call_command("makemigrations", "app_makemig", lint=True, interactive=False, verbosity=1)
        text = out.getvalue()
        assert "Linting for 'app_makemig':" in text
        assert "NOT NULL constraint on columns" in text
        assert "Deleted" in text
        # The backward-incompatible migration was removed.
        assert set(glob.glob(os.path.join(mdir, "0*.py"))) == before
    finally:
        for f in set(glob.glob(os.path.join(mdir, "0*.py"))) - before:
            os.remove(f)
