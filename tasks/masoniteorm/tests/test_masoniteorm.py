"""Behavioral tests for a masoniteorm reimplementation.

Every test asserts the *exact* compiled SQL string produced by ``.to_sql()`` or
the exact ``(sql, bindings)`` pair from ``.to_qmark()``.  Tests center on
genuinely subtle compilation behavior -- value coercion, clause ordering,
sub-selects, relationship EXISTS/JOIN compilation, dialect quoting, and qmark
placeholder semantics -- rather than vanilla SELECT transcription.

All tests run fully offline: SQL is compiled in ``dry`` mode against a mock
connection, never executed against a live database server.
"""

import os
import sys
import tempfile
import textwrap
import unittest

# ---------------------------------------------------------------------------
# Offline config bootstrap.
#
# Model-level relationship traversal resolves connection details by importing a
# configuration module (via the DB_CONFIG_PATH environment variable) that
# exposes a ``DB`` resolver.  We generate a minimal sqlite-only config module on
# disk, put it on sys.path, and point DB_CONFIG_PATH at it BEFORE importing the
# package so no real config file or live database is ever required.
# ---------------------------------------------------------------------------

_CONFIG_DIR = tempfile.mkdtemp(prefix="masoniteorm_cfg_")
_CONFIG_MODULE = "masoniteorm_test_config"
with open(os.path.join(_CONFIG_DIR, _CONFIG_MODULE + ".py"), "w") as _fh:
    _fh.write(
        textwrap.dedent(
            """
            from masoniteorm.connections import ConnectionResolver

            DATABASES = {
                "default": "dev",
                "dev": {"driver": "sqlite", "database": "orm.sqlite3", "prefix": ""},
            }

            DB = ConnectionResolver().set_connection_details(DATABASES)
            """
        )
    )
sys.path.insert(0, _CONFIG_DIR)
os.environ["DB_CONFIG_PATH"] = _CONFIG_MODULE

from masoniteorm.query import QueryBuilder
from masoniteorm.query.grammars import (
    SQLiteGrammar,
    MySQLGrammar,
    PostgresGrammar,
)
from masoniteorm.models import Model
from masoniteorm.expressions import JoinClause, Raw
from masoniteorm.relationships import belongs_to, belongs_to_many
from masoniteorm.connections import ConnectionResolver

ConnectionResolver().set_connection_details(
    {
        "default": "dev",
        "dev": {"driver": "sqlite", "database": "orm.sqlite3", "prefix": ""},
    }
)


class MockConnection:
    """Minimal stand-in connection so the builder never needs a live DB."""

    connection_details = {}

    def make_connection(self):
        return self


def sqlite_builder(table="users", model=None):
    """A dry SQLite-grammar builder requiring no live database."""
    return QueryBuilder(
        SQLiteGrammar,
        table=table,
        connection_class=MockConnection,
        model=model if model is not None else Model(),
        dry=True,
    )


def mysql_qmark_builder(table="users"):
    """Builder used purely to inspect to_qmark() output (no execution)."""
    return QueryBuilder(grammar=MySQLGrammar, table=table)


# ---------------------------------------------------------------------------
# Relationship-bearing models for has / where_has / belongs_to_many tests.
# ---------------------------------------------------------------------------


class Logo(Model):
    __connection__ = "dev"


class Article(Model):
    __connection__ = "dev"

    @belongs_to("id", "article_id")
    def logo(self):
        return Logo


class Profile(Model):
    __connection__ = "dev"


class RelUser(Model):
    __connection__ = "dev"
    __table__ = "users"

    @belongs_to("id", "user_id")
    def articles(self):
        return Article

    @belongs_to("id", "user_id")
    def profile(self):
        return Profile


class Permission(Model):
    __connection__ = "dev"

    @belongs_to_many("permission_id", "role_id", "id", "id")
    def role(self):
        return Role


class Role(Model):
    __connection__ = "dev"

    @belongs_to_many("role_id", "permission_id", "id", "id")
    def permissions(self):
        return Permission


# ===========================================================================
# Value coercion in compiled SQL
# ===========================================================================


class TestValueCoercion(unittest.TestCase):
    maxDiff = None

    def test_integer_values_are_quoted_in_to_sql(self):
        """Non-raw scalar values compile to single-quoted strings, even ints."""
        self.assertEqual(
            sqlite_builder().where("id", 1).to_sql(),
            """SELECT * FROM "users" WHERE "users"."id" = '1'""",
        )
        self.assertEqual(
            sqlite_builder().between("id", 2, 5).to_sql(),
            """SELECT * FROM "users" WHERE "users"."id" BETWEEN '2' AND '5'""",
        )
        self.assertEqual(
            sqlite_builder().not_between("id", 2, 5).to_sql(),
            """SELECT * FROM "users" WHERE "users"."id" NOT BETWEEN '2' AND '5'""",
        )

    def test_where_in_quoting_and_empty(self):
        """where_in / where_not_in quote+comma-pack; an empty list → false predicate."""
        self.assertEqual(
            sqlite_builder().where_in("id", [1, 2, 3]).to_sql(),
            """SELECT * FROM "users" WHERE "users"."id" IN ('1','2','3')""",
        )
        self.assertEqual(
            sqlite_builder().where_not_in("id", [1, 2, 3]).to_sql(),
            """SELECT * FROM "users" WHERE "users"."id" NOT IN ('1','2','3')""",
        )
        self.assertEqual(
            sqlite_builder().where_in("age", []).to_sql(),
            """SELECT * FROM "users" WHERE 0 = 1""",
        )

    def test_where_null_and_not_null(self):
        """where_null / where_not_null emit IS [NOT] NULL; or_where_null OR-joins."""
        self.assertEqual(
            sqlite_builder().where_null("name").to_sql(),
            """SELECT * FROM "users" WHERE "users"."name" IS NULL""",
        )
        self.assertEqual(
            sqlite_builder().where_not_null("name").to_sql(),
            """SELECT * FROM "users" WHERE "users"."name" IS NOT NULL""",
        )
        self.assertEqual(
            sqlite_builder().where_null("column1").or_where_null("column2").to_sql(),
            '''SELECT * FROM "users" WHERE "users"."column1" IS NULL OR "users"."column2" IS NULL''',
        )

    def test_where_column_compares_two_columns_unquoted_value(self):
        """where_column treats the RHS as a column reference, not a value."""
        self.assertEqual(
            sqlite_builder().where_column("name", "username").to_sql(),
            """SELECT * FROM "users" WHERE "users"."name" = "users"."username\"""",
        )


# ===========================================================================
# Operators, LIKE, EXISTS, DATE
# ===========================================================================


class TestOperators(unittest.TestCase):
    maxDiff = None

    def test_where_scalar_operators(self):
        """The where() operator family shares one compilation node (process_wheres
        operator branch), so symbol comparisons, word-operators (LIKE/NOT LIKE,
        REGEXP/NOT REGEXP, uppercased), and OR-joining are asserted together."""
        cases = {
            "<": '''SELECT * FROM "users" WHERE "users"."age" < '20\'''',
            "<=": '''SELECT * FROM "users" WHERE "users"."age" <= '20\'''',
            ">": '''SELECT * FROM "users" WHERE "users"."age" > '20\'''',
            ">=": '''SELECT * FROM "users" WHERE "users"."age" >= '20\'''',
            "!=": '''SELECT * FROM "users" WHERE "users"."age" != '20\'''',
        }
        for op, expected in cases.items():
            self.assertEqual(
                sqlite_builder().where("age", op, "20").to_sql(), expected
            )

        # like / not like map to LIKE / NOT LIKE.
        self.assertEqual(
            sqlite_builder().where("age", "like", "%name%").to_sql(),
            '''SELECT * FROM "users" WHERE "users"."age" LIKE '%name%\'''',
        )
        self.assertEqual(
            sqlite_builder().where("age", "not like", "%name%").to_sql(),
            '''SELECT * FROM "users" WHERE "users"."age" NOT LIKE '%name%\'''',
        )

        # regexp / not regexp render the operator uppercased with a quoted value.
        self.assertEqual(
            sqlite_builder().where("name", "regexp", "^a").to_sql(),
            '''SELECT * FROM "users" WHERE "users"."name" REGEXP '^a\'''',
        )
        self.assertEqual(
            sqlite_builder().where("name", "not regexp", "^a").to_sql(),
            '''SELECT * FROM "users" WHERE "users"."name" NOT REGEXP '^a\'''',
        )

        # or_where joins with OR and coerces the int value to a quoted string.
        self.assertEqual(
            sqlite_builder().where("age", "20").or_where("age", "<", 20).to_sql(),
            '''SELECT * FROM "users" WHERE "users"."age" = '20' OR "users"."age" < '20\'''',
        )

    def test_grouped_where_is_parenthesized(self):
        """A lambda passed to where() produces a parenthesized AND group."""
        self.assertEqual(
            sqlite_builder()
            .where(lambda q: q.where("age", 2).where("name", "Joe"))
            .to_sql(),
            '''SELECT * FROM "users" WHERE ("users"."age" = '2' AND "users"."name" = 'Joe')''',
        )

    def test_where_exists_and_not_exists(self):
        """where_exists / where_not_exists wrap a sub-builder in [NOT] EXISTS (...);
        a lambda form builds a fresh sub-select over the same table. Same EXISTS
        compilation node, both input forms bundled."""
        b = sqlite_builder()
        self.assertEqual(
            b.select("age")
            .where_exists(b.new().select("username").where("age", 12))
            .to_sql(),
            '''SELECT "users"."age" FROM "users" WHERE EXISTS (SELECT "users"."username" FROM "users" WHERE "users"."age" = '12')''',
        )
        b2 = sqlite_builder()
        self.assertEqual(
            b2.select("age")
            .where_not_exists(b2.new().select("username").where("age", 12))
            .to_sql(),
            '''SELECT "users"."age" FROM "users" WHERE NOT EXISTS (SELECT "users"."username" FROM "users" WHERE "users"."age" = '12')''',
        )
        # Lambda input form to the same where_exists node.
        self.assertEqual(
            sqlite_builder().where_exists(lambda q: q.where("age", 1)).to_sql(),
            '''SELECT * FROM "users" WHERE EXISTS (SELECT * FROM "users" WHERE "users"."age" = '1')''',
        )

    def test_where_date_wraps_column_in_date_function(self):
        """where_date wraps the column in DATE(...)."""
        self.assertEqual(
            sqlite_builder().where_date("created_at", "2022-06-01").to_sql(),
            '''SELECT * FROM "users" WHERE DATE("users"."created_at") = '2022-06-01\'''',
        )

    def test_when_conditional_clause(self):
        """when(cond, cb) applies the callback only when cond is truthy; a falsy
        condition leaves the builder unchanged."""
        self.assertEqual(
            sqlite_builder()
            .when(True, lambda q: q.where("age_restricted", 1))
            .to_sql(),
            '''SELECT * FROM "users" WHERE "users"."age_restricted" = '1\'''',
        )
        self.assertEqual(
            sqlite_builder()
            .when(False, lambda q: q.where("age_restricted", 1))
            .to_sql(),
            '''SELECT * FROM "users"''',
        )

    def test_dotted_schema_table_qualifies_columns(self):
        """A dotted schema.table is quoted part-by-part, and its columns are
        qualified with the full schema.table prefix in SELECT and WHERE."""
        self.assertEqual(
            sqlite_builder("information_schema.columns")
            .select("table_name")
            .where("table_name", "users")
            .to_sql(),
            '''SELECT "information_schema"."columns"."table_name" '''
            '''FROM "information_schema"."columns" '''
            '''WHERE "information_schema"."columns"."table_name" = 'users\'''',
        )


# ===========================================================================
# Aggregates & clause reordering quirks
# ===========================================================================


class TestAggregatesAndOrdering(unittest.TestCase):
    maxDiff = None

    def test_aggregate_aliases(self):
        """sum/max/min/avg alias to the column name by default; an explicit
        `"col as alias"` form re-aliases the aggregate (bundled)."""
        self.assertEqual(
            sqlite_builder().sum("age").to_sql(),
            '''SELECT SUM("users"."age") AS age FROM "users"''',
        )
        self.assertEqual(
            sqlite_builder().max("age").to_sql(),
            '''SELECT MAX("users"."age") AS age FROM "users"''',
        )
        self.assertEqual(
            sqlite_builder().min("age").to_sql(),
            '''SELECT MIN("users"."age") AS age FROM "users"''',
        )
        self.assertEqual(
            sqlite_builder().avg("age").to_sql(),
            '''SELECT AVG("users"."age") AS age FROM "users"''',
        )
        self.assertEqual(
            sqlite_builder().sum("age as number").to_sql(),
            '''SELECT SUM("users"."age") AS number FROM "users"''',
        )

    def test_select_aggregate_ordering(self):
        """Plain columns always precede aggregate columns regardless of call order."""
        self.assertEqual(
            sqlite_builder().select("username").max("age").to_sql(),
            '''SELECT "users"."username", MAX("users"."age") AS age FROM "users"''',
        )
        self.assertEqual(
            sqlite_builder().max("age").select("username").to_sql(),
            '''SELECT "users"."username", MAX("users"."age") AS age FROM "users"''',
        )

    def test_count_star_uses_reserved_alias(self):
        """count('*') emits COUNT(*) AS m_count_reserved; count(col) aliases col."""
        self.assertEqual(
            sqlite_builder().count("*").to_sql(),
            '''SELECT COUNT(*) AS m_count_reserved FROM "users"''',
        )
        self.assertEqual(
            sqlite_builder().count("money").to_sql(),
            '''SELECT COUNT("users"."money") AS money FROM "users"''',
        )

    def test_order_by_variants(self):
        """order_by direction/multiple/inline/raw and latest/oldest in one bundle."""
        self.assertEqual(
            sqlite_builder().order_by("email", "asc").to_sql(),
            '''SELECT * FROM "users" ORDER BY "email" ASC''',
        )
        self.assertEqual(
            sqlite_builder().order_by("email, name, active").to_sql(),
            '''SELECT * FROM "users" ORDER BY "email" ASC, "name" ASC, "active" ASC''',
        )
        self.assertEqual(
            sqlite_builder().order_by("email, name desc").to_sql(),
            '''SELECT * FROM "users" ORDER BY "email" ASC, "name" DESC''',
        )
        self.assertEqual(
            sqlite_builder().order_by_raw("col asc").to_sql(),
            '''SELECT * FROM "users" ORDER BY col asc''',
        )
        self.assertEqual(
            sqlite_builder().latest("email").to_sql(),
            '''SELECT * FROM "users" ORDER BY "email" DESC''',
        )
        self.assertEqual(
            sqlite_builder().oldest("email").to_sql(),
            '''SELECT * FROM "users" ORDER BY "email" ASC''',
        )
        # order_by carve-out: a bare column is NOT table-qualified, but an
        # explicit dotted "table.col" form IS qualified.
        self.assertEqual(
            sqlite_builder().order_by("users.email").to_sql(),
            '''SELECT * FROM "users" ORDER BY "users"."email" ASC''',
        )

    def test_group_by_variants(self):
        """group_by qualifies + accumulates; group_by_raw passes through verbatim."""
        self.assertEqual(
            sqlite_builder("payments")
            .select("user_id")
            .min("salary")
            .group_by("user_id")
            .to_sql(),
            '''SELECT "payments"."user_id", MIN("payments"."salary") AS salary FROM "payments" GROUP BY "payments"."user_id"''',
        )
        self.assertEqual(
            sqlite_builder("payments")
            .select("user_id")
            .min("salary")
            .group_by("user_id")
            .group_by("salary")
            .to_sql(),
            '''SELECT "payments"."user_id", MIN("payments"."salary") AS salary FROM "payments" GROUP BY "payments"."user_id", "payments"."salary"''',
        )
        self.assertEqual(
            sqlite_builder("payments")
            .select("user_id")
            .min("salary")
            .group_by_raw("count(*)")
            .to_sql(),
            '''SELECT "payments"."user_id", MIN("payments"."salary") AS salary FROM "payments" GROUP BY count(*)''',
        )

    def test_having_variants(self):
        """having with operator qualifies; bare column vs equality forms; having_raw
        passes through verbatim (no qualification)."""
        self.assertEqual(
            sqlite_builder("payments")
            .select("user_id")
            .avg("salary")
            .group_by("user_id")
            .having("salary", ">=", "1000")
            .to_sql(),
            '''SELECT "payments"."user_id", AVG("payments"."salary") AS salary FROM "payments" GROUP BY "payments"."user_id" HAVING "payments"."salary" >= '1000\'''',
        )
        self.assertEqual(
            sqlite_builder().sum("age").group_by("age").having("age").to_sql(),
            '''SELECT SUM("users"."age") AS age FROM "users" GROUP BY "users"."age" HAVING "users"."age"''',
        )
        self.assertEqual(
            sqlite_builder().sum("age").group_by("age").having("age", 10).to_sql(),
            '''SELECT SUM("users"."age") AS age FROM "users" GROUP BY "users"."age" HAVING "users"."age" = '10\'''',
        )
        self.assertEqual(
            sqlite_builder().select_raw("COUNT(*) as counts").having_raw(
                "counts > 18"
            ).to_sql(),
            '''SELECT COUNT(*) as counts FROM "users" HAVING counts > 18''',
        )

    def test_select_distinct(self):
        """distinct() injects DISTINCT after SELECT."""
        self.assertEqual(
            sqlite_builder().select("group").distinct().to_sql(),
            '''SELECT DISTINCT "users"."group" FROM "users"''',
        )


# ===========================================================================
# LIMIT / OFFSET — including SQLite's offset-only quirk
# ===========================================================================


class TestLimitOffset(unittest.TestCase):
    maxDiff = None

    def test_limit_offset_first(self):
        """limit, limit+offset, and first() LIMIT 1. (The sqlite offset-only quirk
        is asserted cross-dialect in TestDialectQuoting.test_offset_only_differs_by_dialect.)"""
        self.assertEqual(
            sqlite_builder().limit(5).to_sql(),
            '''SELECT * FROM "users" LIMIT 5''',
        )
        self.assertEqual(
            sqlite_builder().limit(2).offset(5).to_sql(),
            '''SELECT * FROM "users" LIMIT 2 OFFSET 5''',
        )
        self.assertEqual(
            sqlite_builder().first(query=True).to_sql(),
            '''SELECT * FROM "users" LIMIT 1''',
        )


# ===========================================================================
# Joins
# ===========================================================================


class TestJoins(unittest.TestCase):
    maxDiff = None

    def test_basic_joins(self):
        """inner/left/right (sqlite) join keywords plus accumulation in call order."""
        self.assertEqual(
            sqlite_builder()
            .join("profiles", "users.id", "=", "profiles.user_id")
            .to_sql(),
            '''SELECT * FROM "users" INNER JOIN "profiles" ON "users"."id" = "profiles"."user_id"''',
        )
        self.assertEqual(
            sqlite_builder()
            .left_join("profiles", "users.id", "=", "profiles.user_id")
            .to_sql(),
            '''SELECT * FROM "users" LEFT JOIN "profiles" ON "users"."id" = "profiles"."user_id"''',
        )
        self.assertEqual(
            sqlite_builder()
            .right_join("profiles", "users.id", "=", "profiles.user_id")
            .to_sql(),
            '''SELECT * FROM "users" LEFT JOIN "profiles" ON "users"."id" = "profiles"."user_id"''',
        )
        self.assertEqual(
            sqlite_builder()
            .join("contacts", "users.id", "=", "contacts.user_id")
            .join("posts", "comments.post_id", "=", "posts.id")
            .to_sql(),
            '''SELECT * FROM "users" INNER JOIN "contacts" ON "users"."id" = "contacts"."user_id" INNER JOIN "posts" ON "comments"."post_id" = "posts"."id"''',
        )

    def test_join_clause_with_multiple_on(self):
        """A JoinClause with several .on() conditions AND-joins them with aliasing;
        on_value treats the RHS as a literal and or_on_value OR-joins (bundled)."""
        clause = (
            JoinClause("report_groups as rg")
            .on("bgt.fund", "=", "rg.fund")
            .on("bgt.dept", "=", "rg.dept")
            .on("bgt.acct", "=", "rg.acct")
            .on("bgt.sub", "=", "rg.sub")
        )
        self.assertEqual(
            sqlite_builder().join(clause).to_sql(),
            '''SELECT * FROM "users" INNER JOIN "report_groups" AS "rg" ON "bgt"."fund" = "rg"."fund" AND "bgt"."dept" = "rg"."dept" AND "bgt"."acct" = "rg"."acct" AND "bgt"."sub" = "rg"."sub"''',
        )
        value_clause = (
            JoinClause("report_groups as rg")
            .on_value("bgt.active", "=", "1")
            .or_on_value("bgt.acct", "=", "1234")
        )
        self.assertEqual(
            sqlite_builder().join(value_clause).to_sql(),
            '''SELECT * FROM "users" INNER JOIN "report_groups" AS "rg" ON "bgt"."active" = '1' OR "bgt"."acct" = '1234\'''',
        )

    def test_join_clause_null_predicates(self):
        """on_null / or_on_null and the on_not_null / or_on_not_null variants combine
        with on_value. The IS [NOT] NULL columns are quoted but NOT table-qualified,
        while on_value qualifies both sides (same grammar node)."""
        clause = (
            JoinClause("report_groups as rg")
            .on_null("bgt.acct")
            .or_on_null("bgt.dept")
            .on_value("rg.abc", "=", 10)
        )
        self.assertEqual(
            sqlite_builder().join(clause).to_sql(),
            '''SELECT * FROM "users" INNER JOIN "report_groups" AS "rg" ON "acct" IS NULL OR "dept" IS NULL AND "rg"."abc" = '10\'''',
        )
        not_null_clause = (
            JoinClause("report_groups as rg")
            .on_not_null("bgt.acct")
            .or_on_not_null("bgt.dept")
            .on_value("rg.abc", "=", 10)
        )
        self.assertEqual(
            sqlite_builder().join(not_null_clause).to_sql(),
            '''SELECT * FROM "users" INNER JOIN "report_groups" AS "rg" ON "acct" IS NOT NULL OR "dept" IS NOT NULL AND "rg"."abc" = '10\'''',
        )

    def test_join_clause_via_lambda(self):
        """join() accepts a lambda receiving a JoinClause."""
        self.assertEqual(
            sqlite_builder()
            .join(
                "report_groups as rg",
                lambda clause: clause.on("bgt.fund", "=", "rg.fund").on_null("bgt"),
            )
            .to_sql(),
            '''SELECT * FROM "users" INNER JOIN "report_groups" AS "rg" ON "bgt"."fund" = "rg"."fund" AND "bgt" IS NULL''',
        )

    def test_join_clause_mixed_on_value_and_null(self):
        """A JoinClause mixing .on(), .on_value() and .on_null() AND-joins the
        three condition kinds: on/on_value qualify both sides, but the on_null
        column is quoted WITHOUT table qualification (same rule as the bare
        null-predicate form)."""
        clause = (
            JoinClause("report_groups as rg")
            .on("bgt.fund", "=", "rg.fund")
            .on_value("rg.active", "=", "1")
            .on_null("rg.deleted_at")
        )
        self.assertEqual(
            sqlite_builder().join(clause).to_sql(),
            '''SELECT * FROM "users" INNER JOIN "report_groups" AS "rg" '''
            '''ON "bgt"."fund" = "rg"."fund" AND "rg"."active" = \'1\' '''
            '''AND "deleted_at" IS NULL''',
        )

    def test_join_clause_on_not_null_or_on_value(self):
        """A JoinClause mixing .on(), .on_not_null() and .or_on_value(): on qualifies
        both sides, the on_not_null column is quoted WITHOUT table qualification, and
        or_on_value OR-joins a qualified literal comparison."""
        clause = (
            JoinClause("report_groups as rg")
            .on("bgt.fund", "=", "rg.fund")
            .on_not_null("rg.active")
            .or_on_value("rg.flag", "=", "Y")
        )
        self.assertEqual(
            sqlite_builder().join(clause).to_sql(),
            '''SELECT * FROM "users" INNER JOIN "report_groups" AS "rg" '''
            '''ON "bgt"."fund" = "rg"."fund" AND "active" IS NOT NULL '''
            '''OR "rg"."flag" = \'Y\'''',
        )

    def test_two_join_clauses_accumulate_with_null_predicate(self):
        """Two separate JoinClause objects accumulate as two INNER JOINs; the second
        mixes on_null (unqualified) with on_value (qualified)."""
        jc1 = JoinClause("a").on("x.k", "=", "a.k")
        jc2 = JoinClause("b").on_null("b.deleted").on_value("b.f", "=", "1")
        self.assertEqual(
            sqlite_builder().join(jc1).join(jc2).to_sql(),
            '''SELECT * FROM "users" INNER JOIN "a" ON "x"."k" = "a"."k" '''
            '''INNER JOIN "b" ON "deleted" IS NULL AND "b"."f" = \'1\'''',
        )


# ===========================================================================
# Sub-selects
# ===========================================================================


class TestSubSelects(unittest.TestCase):
    maxDiff = None

    def test_where_in_sub_select_with_wheres(self):
        """Predicates inside the sub-builder are compiled into the sub-select; such
        sub-selects nest arbitrarily deep; and a lambda passed to where_in builds
        the sub-select the same way (same where_in sub-select node, both input
        forms bundled)."""
        b = sqlite_builder()
        self.assertEqual(
            b.where_in(
                "age", b.new().select("age").where("age", 2).where("name", "Joe")
            ).to_sql(),
            '''SELECT * FROM "users" WHERE "users"."age" IN (SELECT "users"."age" FROM "users" WHERE "users"."age" = '2' AND "users"."name" = 'Joe')''',
        )
        b2 = sqlite_builder()
        self.assertEqual(
            b2.where_in(
                "name",
                b2.new().select("age").where_in("email", b2.new().select("email")),
            ).to_sql(),
            '''SELECT * FROM "users" WHERE "users"."name" IN (SELECT "users"."age" FROM "users" WHERE "users"."email" IN (SELECT "users"."email" FROM "users"))''',
        )
        # Lambda input form to the same where_in sub-select node.
        b3 = sqlite_builder()
        self.assertEqual(
            b3.where_in(
                "age", lambda q: q.select("age").where("age", 2).where("name", "Joe")
            ).to_sql(),
            '''SELECT * FROM "users" WHERE "users"."age" IN (SELECT "users"."age" FROM "users" WHERE "users"."age" = '2' AND "users"."name" = 'Joe')''',
        )

    def test_where_value_sub_select(self):
        """A builder as the where() value becomes a parenthesized scalar sub-select."""
        b = sqlite_builder()
        self.assertEqual(
            b.where("name", b.new().sum("age")).to_sql(),
            '''SELECT * FROM "users" WHERE "users"."name" = (SELECT SUM("users"."age") AS age FROM "users")''',
        )

    def test_add_select_subquery(self):
        """add_select inlines a correlated scalar sub-select aliased to the given name."""
        sql = (
            sqlite_builder()
            .select("name")
            .add_select("phone_count", lambda q: q.count("*").table("phones"))
            .add_select("salary", lambda q: q.count("*").table("salary"))
            .to_sql()
        )
        self.assertEqual(
            sql,
            '''SELECT "users"."name", (SELECT COUNT(*) AS m_count_reserved FROM "phones") AS phone_count, (SELECT COUNT(*) AS m_count_reserved FROM "salary") AS salary FROM "users"''',
        )

    def test_add_select_subquery_carries_inner_where(self):
        """A predicate inside the add_select callback is compiled into the sub-select
        and the sub-select column is qualified to the *sub-select's* table, while the
        AS alias stays unquoted."""
        sql = (
            sqlite_builder(table=None)
            .select_raw("max(updated_at) as test")
            .from_("some_table")
            .add_select(
                "other_test",
                lambda q: q.max("updated_at")
                .from_("different_table")
                .where("some_id", "=", "3"),
            )
            .to_sql()
        )
        self.assertEqual(
            sql,
            'SELECT max(updated_at) as test, '
            '(SELECT MAX("different_table"."updated_at") AS updated_at '
            'FROM "different_table" '
            'WHERE "different_table"."some_id" = \'3\') AS other_test '
            'FROM "some_table"',
        )

    def test_add_select_two_subqueries_each_carry_inner_where(self):
        """Two add_select correlated sub-selects each compile their own inner where,
        qualified to their own sub-select table, with unquoted AS aliases."""
        sql = (
            sqlite_builder()
            .select("name")
            .add_select("a", lambda q: q.count("*").table("t1").where("x", 1))
            .add_select("b", lambda q: q.count("*").table("t2").where("y", 2))
            .to_sql()
        )
        self.assertEqual(
            sql,
            '''SELECT "users"."name", '''
            '''(SELECT COUNT(*) AS m_count_reserved FROM "t1" WHERE "t1"."x" = \'1\') AS a, '''
            '''(SELECT COUNT(*) AS m_count_reserved FROM "t2" WHERE "t2"."y" = \'2\') AS b '''
            '''FROM "users"''',
        )


# ===========================================================================
# INSERT / UPDATE / DELETE compilation
# ===========================================================================


class TestWrites(unittest.TestCase):
    maxDiff = None

    def _builder(self):
        return QueryBuilder(SQLiteGrammar, table="users")

    def test_create_uses_insertion_order(self):
        """create() preserves dict insertion order; keyword form behaves identically."""
        self.assertEqual(
            self._builder()
            .create(
                {"name": "Corentin All", "email": "corentin@yopmail.com"}, query=True
            )
            .to_sql(),
            '''INSERT INTO "users" ("name", "email") VALUES ('Corentin All', 'corentin@yopmail.com')''',
        )
        self.assertEqual(
            self._builder().create(name="Joe", query=True).to_sql(),
            '''INSERT INTO "users" ("name") VALUES ('Joe')''',
        )

    def test_bulk_create_sorts_columns_and_aligns_values(self):
        """bulk_create sorts column keys and aligns each row's values to them
        (to_sql); and to_qmark uses one '?' placeholder group per row (same
        bulk_create method, both output modes bundled)."""
        self.assertEqual(
            self._builder()
            .bulk_create(
                [
                    {"name": "Joe", "age": 5},
                    {"age": 35, "name": "Bill"},
                    {"name": "John", "age": 10},
                ],
                query=True,
            )
            .to_sql(),
            '''INSERT INTO "users" ("age", "name") VALUES ('5', 'Joe'), ('35', 'Bill'), ('10', 'John')''',
        )
        self.assertEqual(
            self._builder()
            .bulk_create(
                [{"name": "Joe"}, {"name": "Bill"}, {"name": "John"}], query=True
            )
            .to_qmark(),
            '''INSERT INTO "users" ("name") VALUES ('?'), ('?'), ('?')''',
        )

    def test_update_single_and_multiple(self):
        """update SET lists assignments in dict order; WHERE columns not table-qualified."""
        self.assertEqual(
            self._builder()
            .where("name", "bob")
            .update({"name": "Joe"}, dry=True)
            .to_sql(),
            '''UPDATE "users" SET "name" = 'Joe' WHERE "name" = 'bob\'''',
        )
        self.assertEqual(
            self._builder()
            .update({"name": "Joe", "email": "joe@yopmail.com"}, dry=True)
            .to_sql(),
            '''UPDATE "users" SET "name" = 'Joe', "email" = 'joe@yopmail.com\'''',
        )

    def test_increment_decrement_return_sql_string(self):
        """increment/decrement (in dry mode) return the compiled UPDATE SQL *string*
        directly (not the builder), unlike create/update which return the builder."""
        inc = self._builder().increment("age", 1, dry=True)
        self.assertIsInstance(inc, str)
        self.assertEqual(inc, '''UPDATE "users" SET "age" = "age" + '1\'''')
        dec = self._builder().decrement("age", 1, dry=True)
        self.assertIsInstance(dec, str)
        self.assertEqual(dec, '''UPDATE "users" SET "age" = "age" - '1\'''')

    def test_update_raw_value_emitted_verbatim(self):
        """A Raw(...) value supplied as an UPDATE SET assignment is emitted verbatim
        with no quoting, unlike a scalar which is single-quoted."""
        self.assertEqual(
            self._builder().update({"name": Raw('"username"')}, dry=True).to_sql(),
            '''UPDATE "users" SET "name" = "username"''',
        )

    def test_delete_scalar_list_and_where(self):
        """delete(col, scalar) -> equality; delete(col, list) -> IN; chained where AND-joins."""
        self.assertEqual(
            self._builder().delete("id", 1, query=True).to_sql(),
            '''DELETE FROM "users" WHERE "id" = '1\'''',
        )
        self.assertEqual(
            self._builder().delete("id", [1, 2, 3], query=True).to_sql(),
            '''DELETE FROM "users" WHERE "id" IN ('1','2','3')''',
        )
        self.assertEqual(
            self._builder()
            .where("age", 20)
            .where("profile", 1)
            .delete(query=True)
            .to_sql(),
            '''DELETE FROM "users" WHERE "age" = '20' AND "profile" = '1\'''',
        )

    def test_truncate(self):
        """SQLite truncate compiles to a plain DELETE FROM."""
        self.assertEqual(
            self._builder().truncate(dry=True),
            '''DELETE FROM "users"''',
        )


# ===========================================================================
# to_qmark() — placeholder style and binding ordering
# ===========================================================================


class TestQmark(unittest.TestCase):
    maxDiff = None

    def test_select_where_binding(self):
        """Scalar where values become a quoted '?' placeholder with one binding."""
        b = mysql_qmark_builder().select("username").where("name", "Joe")
        self.assertEqual(
            b.to_qmark(),
            "SELECT `users`.`username` FROM `users` WHERE `users`.`name` = '?'",
        )
        self.assertEqual(b._bindings, ["Joe"])

    def test_where_in_qmark_spaced_placeholders(self):
        """where_in qmark placeholders are spaced ('?', '?', '?') with int bindings."""
        b = mysql_qmark_builder().where_in("id", [1, 2, 3])
        self.assertEqual(
            b.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`id` IN ('?', '?', '?')",
        )
        self.assertEqual(b._bindings, [1, 2, 3])

    def test_between_qmark_asymmetry(self):
        """between converts to '?' placeholders in qmark mode; not_between does NOT."""
        b = mysql_qmark_builder().between("age", 18, 65)
        self.assertEqual(
            b.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`age` BETWEEN '?' AND '?'",
        )
        self.assertEqual(b._bindings, [18, 65])

        bn = mysql_qmark_builder().not_between("age", 18, 65)
        self.assertEqual(
            bn.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`age` NOT BETWEEN '18' AND '65'",
        )
        self.assertEqual(bn._bindings, [])

    def test_where_not_null_has_no_binding(self):
        """IS NOT NULL produces no placeholder and no binding."""
        b = mysql_qmark_builder().where_not_null("id")
        self.assertEqual(
            b.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`id` IS NOT NULL",
        )
        self.assertEqual(b._bindings, [])

    def test_boolean_inlined_but_falsy_zero_bound(self):
        """Scalar binding edge cases (bundled): True/False compile inline as
        '1'/'0' with NO placeholder or binding, but an int 0 IS a real binding."""
        bt = mysql_qmark_builder().where("is_admin", True)
        self.assertEqual(
            bt.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`is_admin` = '1'",
        )
        self.assertEqual(bt._bindings, [])

        bf = mysql_qmark_builder().where("is_admin", False)
        self.assertEqual(
            bf.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`is_admin` = '0'",
        )
        self.assertEqual(bf._bindings, [])

        bz = mysql_qmark_builder().where("name", 0)
        self.assertEqual(
            bz.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`name` = '?'",
        )
        self.assertEqual(bz._bindings, [0])

    def test_grouped_or_where_binding_order(self):
        """Bindings inside a parenthesized OR-group preserve left-to-right order."""
        b = mysql_qmark_builder().where(
            lambda query: query.where("challenger", 1)
            .or_where("proposer", 1)
            .or_where("referee", 1)
        )
        self.assertEqual(
            b.to_qmark(),
            "SELECT * FROM `users` WHERE (`users`.`challenger` = '?' OR `users`.`proposer` = '?' OR `users`.`referee` = '?')",
        )
        self.assertEqual(b._bindings, [1, 1, 1])

    def test_where_raw_bindings_then_where(self):
        """where_raw bindings precede subsequent where() bindings in order."""
        b = (
            mysql_qmark_builder()
            .where_raw("`age` = '?' AND `is_admin` = '?'", [18, True])
            .where("email", "test@example.com")
        )
        self.assertEqual(
            b.to_qmark(),
            "SELECT * FROM `users` WHERE `age` = '?' AND `is_admin` = '?' AND `users`.`email` = '?'",
        )
        self.assertEqual(b._bindings, [18, True, "test@example.com"])

    def test_update_multi_set_multi_where_binding_order(self):
        """Multiple SET assignments bind in dict order, then multiple WHERE values
        bind in source order — all SET before all WHERE. Under the MySQL grammar the
        SET and WHERE columns of an UPDATE are table-qualified
        (`` `users`.`name` ``); SQLite would leave them unqualified."""
        b = (
            mysql_qmark_builder()
            .update({"name": "Bob", "active": "yes"}, dry=True)
            .where("id", 1)
            .where("name", "Joe")
        )
        self.assertEqual(
            b.to_qmark(),
            "UPDATE `users` SET `users`.`name` = '?', `users`.`active` = '?' "
            "WHERE `users`.`id` = '?' AND `users`.`name` = '?'",
        )
        self.assertEqual(b._bindings, ["Bob", "yes", 1, "Joe"])

    def test_where_then_between_qmark_binding_order(self):
        """A scalar where binding precedes the two between bindings in source order."""
        b = mysql_qmark_builder().where("age", ">", 18).between("salary", 1, 2)
        self.assertEqual(
            b.to_qmark(),
            "SELECT * FROM `users` WHERE `users`.`age` > '?' "
            "AND `users`.`salary` BETWEEN '?' AND '?'",
        )
        self.assertEqual(b._bindings, [18, 1, 2])

    def test_mixed_raw_grouped_between_binding_order(self):
        """Across a where_raw, a parenthesized OR-group, and a between, every clause
        keeps placeholder syntax in qmark mode and bindings accumulate strictly in
        source order: the raw binding first, then the group's values left-to-right,
        then the between's low/high."""
        b = (
            mysql_qmark_builder()
            .where_raw("`x` = '?'", [99])
            .where(lambda q: q.where("a", 1).or_where("b", 2))
            .between("c", 3, 4)
        )
        self.assertEqual(
            b.to_qmark(),
            "SELECT * FROM `users` WHERE `x` = '?' "
            "AND (`users`.`a` = '?' OR `users`.`b` = '?') "
            "AND `users`.`c` BETWEEN '?' AND '?'",
        )
        self.assertEqual(b._bindings, [99, 1, 2, 3, 4])


# ===========================================================================
# Dialect quoting differences
# ===========================================================================


class TestDialectQuoting(unittest.TestCase):
    maxDiff = None

    def _b(self, grammar):
        return QueryBuilder(
            grammar,
            table="users",
            connection_class=MockConnection,
            model=Model(),
            dry=True,
        )

    def test_dialect_quoting(self):
        """SQLite/Postgres use double quotes; MySQL uses backticks; applies to WHERE too."""
        self.assertEqual(
            self._b(SQLiteGrammar).select("username", "password").to_sql(),
            '''SELECT "users"."username", "users"."password" FROM "users"''',
        )
        self.assertEqual(
            self._b(PostgresGrammar).select("username", "password").to_sql(),
            '''SELECT "users"."username", "users"."password" FROM "users"''',
        )
        self.assertEqual(
            self._b(MySQLGrammar).select("username", "password").to_sql(),
            "SELECT `users`.`username`, `users`.`password` FROM `users`",
        )
        self.assertEqual(
            self._b(MySQLGrammar)
            .select("username", "password")
            .where("id", 1)
            .to_sql(),
            "SELECT `users`.`username`, `users`.`password` FROM `users` WHERE `users`.`id` = '1'",
        )
        self.assertEqual(
            self._b(PostgresGrammar)
            .select("username", "password")
            .where("id", 1)
            .to_sql(),
            '''SELECT "users"."username", "users"."password" FROM "users" WHERE "users"."id" = '1\'''',
        )

    def test_offset_only_differs_by_dialect(self):
        """MySQL/Postgres emit a bare OFFSET; SQLite forces LIMIT -1 OFFSET n."""
        self.assertEqual(
            self._b(MySQLGrammar).offset(5).to_sql(),
            "SELECT * FROM `users` OFFSET 5",
        )
        self.assertEqual(
            self._b(PostgresGrammar).offset(5).to_sql(),
            '''SELECT * FROM "users" OFFSET 5''',
        )
        self.assertEqual(
            self._b(SQLiteGrammar).offset(5).to_sql(),
            '''SELECT * FROM "users" LIMIT -1 OFFSET 5''',
        )

    def test_right_join_mysql_keeps_right(self):
        """right_join compiles to RIGHT JOIN under MySQL (LEFT JOIN under SQLite)."""
        self.assertEqual(
            self._b(MySQLGrammar)
            .right_join("profiles", "users.id", "=", "profiles.user_id")
            .to_sql(),
            "SELECT * FROM `users` RIGHT JOIN `profiles` ON `users`.`id` = `profiles`.`user_id`",
        )

    def test_locks_are_dialect_specific(self):
        """MySQL renders lock clauses; SQLite renders none."""
        self.assertEqual(
            self._b(MySQLGrammar).where("votes", ">=", 100).lock_for_update().to_sql(),
            "SELECT * FROM `users` WHERE `users`.`votes` >= '100' FOR UPDATE",
        )
        self.assertEqual(
            self._b(MySQLGrammar).where("votes", ">=", 100).shared_lock().to_sql(),
            "SELECT * FROM `users` WHERE `users`.`votes` >= '100' LOCK IN SHARE MODE",
        )
        self.assertEqual(
            self._b(SQLiteGrammar).where("votes", ">=", 100).lock_for_update().to_sql(),
            '''SELECT * FROM "users" WHERE "users"."votes" >= '100\'''',
        )


# ===========================================================================
# Relationship compilation — has / where_has / joins / belongs_to_many
# ===========================================================================


class TestRelationshipCompilation(unittest.TestCase):
    maxDiff = None

    def _builder(self, model=None):
        return QueryBuilder(
            grammar=SQLiteGrammar,
            connection_class=MockConnection,
            table="users",
            model=model if model is not None else RelUser(),
        )

    def test_has_compiles_correlated_exists(self):
        """has(rel) emits a correlated WHERE EXISTS over the related table."""
        self.assertEqual(
            self._builder().has("articles").to_sql(),
            '''SELECT * FROM "users" WHERE EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id"'''
            ''')''',
        )

    def test_doesnt_have_compiles_not_exists(self):
        """doesnt_have(rel) emits WHERE NOT EXISTS."""
        self.assertEqual(
            self._builder().doesnt_have("articles").to_sql(),
            '''SELECT * FROM "users" WHERE NOT EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id"'''
            ''')''',
        )

    def test_where_has_adds_callback_predicate_inside_exists(self):
        """where_has merges the callback's predicates into the EXISTS sub-query."""
        self.assertEqual(
            self._builder()
            .where_has("articles", lambda q: q.where("active", 1))
            .to_sql(),
            '''SELECT * FROM "users" WHERE EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id" AND "articles"."active" = '1\''''
            ''')''',
        )

    def test_where_has_merges_multiple_callback_predicates(self):
        """where_has merges EVERY predicate from the callback into the EXISTS
        sub-query, each AND-joined after the correlating key condition and each
        qualified to the related table."""
        self.assertEqual(
            self._builder()
            .where_has(
                "articles", lambda q: q.where("active", 1).where("views", ">", 10)
            )
            .to_sql(),
            '''SELECT * FROM "users" WHERE EXISTS ('''
            '''SELECT * FROM "articles" '''
            '''WHERE "articles"."user_id" = "users"."id" '''
            '''AND "articles"."active" = \'1\' AND "articles"."views" > \'10\''''
            ''')''',
        )

    def test_where_doesnt_have(self):
        """where_doesnt_have negates the EXISTS while keeping the callback predicate."""
        self.assertEqual(
            self._builder()
            .where_doesnt_have("articles", lambda q: q.where("title", "Eggs and Ham"))
            .to_sql(),
            '''SELECT * FROM "users" WHERE NOT EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id" AND "articles"."title" = 'Eggs and Ham\''''
            ''')''',
        )

    def test_joins_relation_compiles_inner_join(self):
        """joins(rel) turns a relationship into an INNER JOIN on its keys."""
        self.assertEqual(
            self._builder().joins("articles").to_sql(),
            '''SELECT * FROM "users" INNER JOIN "articles" ON "users"."id" = "articles"."user_id"''',
        )

    def test_callable_belongs_to_returns_related_query(self):
        """Calling a belongs_to relationship method yields a builder on the related table."""
        self.assertEqual(
            RelUser().profile().where("name", "Joe").to_sql(),
            '''SELECT * FROM "profiles" WHERE "profiles"."name" = 'Joe\'''',
        )

    def test_belongs_to_many_has_compiles_pivot_join(self):
        """has() over a belongs_to_many joins the pivot table inside EXISTS."""
        self.assertEqual(
            Role.has("permissions").to_sql(),
            '''SELECT * FROM "roles" WHERE EXISTS (SELECT * FROM "permissions" INNER JOIN "permission_role" ON "permissions"."id" = "permission_role"."permission_id" WHERE "permission_role"."role_id" = "roles"."id")''',
        )

    def test_belongs_to_many_where_has_adds_id_subselect(self):
        """where_has over belongs_to_many adds an id IN (...) sub-select for the predicate."""
        self.assertEqual(
            Role.where_has(
                "permissions", lambda q: q.where("name", "Creates Users")
            ).to_sql(),
            '''SELECT * FROM "roles" WHERE EXISTS (SELECT * FROM "permissions" INNER JOIN "permission_role" ON "permissions"."id" = "permission_role"."permission_id" WHERE "permission_role"."role_id" = "roles"."id" AND "permissions"."id" IN (SELECT "permissions"."id" FROM "permissions" WHERE "permissions"."name" = 'Creates Users'))''',
        )

    def test_belongs_to_many_where_has_merges_multiple_callback_predicates(self):
        """where_has over belongs_to_many carries EVERY callback predicate into the
        id IN (...) sub-select; the sub-select's selected id and each predicate
        column are qualified to the related table."""
        self.assertEqual(
            Role.where_has(
                "permissions", lambda q: q.where("name", "X").where("active", 1)
            ).to_sql(),
            '''SELECT * FROM "roles" WHERE EXISTS ('''
            '''SELECT * FROM "permissions" INNER JOIN "permission_role" '''
            '''ON "permissions"."id" = "permission_role"."permission_id" '''
            '''WHERE "permission_role"."role_id" = "roles"."id" '''
            '''AND "permissions"."id" IN ('''
            '''SELECT "permissions"."id" FROM "permissions" '''
            '''WHERE "permissions"."name" = \'X\' AND "permissions"."active" = \'1\''''
            '''))''',
        )

    def test_belongs_to_many_where_has_or_predicate_in_subselect(self):
        """An OR inside the where_has callback is preserved inside the belongs_to_many
        id IN (...) sub-select (the OR joins the two predicate branches there)."""
        self.assertEqual(
            Role.where_has(
                "permissions", lambda q: q.where("name", "X").or_where("name", "Y")
            ).to_sql(),
            '''SELECT * FROM "roles" WHERE EXISTS ('''
            '''SELECT * FROM "permissions" INNER JOIN "permission_role" '''
            '''ON "permissions"."id" = "permission_role"."permission_id" '''
            '''WHERE "permission_role"."role_id" = "roles"."id" '''
            '''AND "permissions"."id" IN ('''
            '''SELECT "permissions"."id" FROM "permissions" '''
            '''WHERE "permissions"."name" = \'X\' OR "permissions"."name" = \'Y\'))''',
        )

    def test_belongs_to_many_or_has_joins_with_or(self):
        """or_has joins the EXISTS clause onto the prior predicate with OR."""
        self.assertEqual(
            Role.where("name", "role_name").or_has("permissions").to_sql(),
            '''SELECT * FROM "roles" WHERE "roles"."name" = 'role_name' OR EXISTS (SELECT * FROM "permissions" INNER JOIN "permission_role" ON "permissions"."id" = "permission_role"."permission_id" WHERE "permission_role"."role_id" = "roles"."id")''',
        )

    def test_nested_has_compiles_nested_exists(self):
        """A dotted relation nests a second EXISTS correlated to the first related
        table (articles.logo: outer correlates to users, inner to articles)."""
        self.assertEqual(
            RelUser.has("articles.logo").to_sql(),
            '''SELECT * FROM "users" WHERE EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id" '''
            '''AND EXISTS ('''
            '''SELECT * FROM "logos" WHERE "logos"."article_id" = "articles"."id"'''
            '''))''',
        )

    def test_multiple_has_chains_and_exists(self):
        """has(a, b) and has(a).has(b) both AND-join two EXISTS predicates."""
        expected = (
            '''SELECT * FROM "users" WHERE EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id"'''
            ''') AND EXISTS ('''
            '''SELECT * FROM "profiles" WHERE "profiles"."user_id" = "users"."id"'''
            ''')'''
        )
        self.assertEqual(self._builder().has("articles", "profile").to_sql(), expected)
        self.assertEqual(
            self._builder().has("articles").has("profile").to_sql(), expected
        )

    def test_where_has_nested_merges_predicate_in_inner_exists(self):
        """where_has on a dotted relation nests EXISTS and merges the callback's
        predicate into the *innermost* sub-query with AND."""
        self.assertEqual(
            RelUser.where_has("articles.logo", lambda q: q.where("active", 1)).to_sql(),
            '''SELECT * FROM "users" WHERE EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id" '''
            '''AND EXISTS ('''
            '''SELECT * FROM "logos" WHERE "logos"."article_id" = "articles"."id" '''
            '''AND "logos"."active" = \'1\''''
            '''))''',
        )

    def test_or_where_has_joins_with_or(self):
        """or_where_has OR-joins an EXISTS carrying the callback predicate."""
        self.assertEqual(
            self._builder()
            .where("name", "Joe")
            .or_where_has("articles", lambda q: q.where("active", 1))
            .to_sql(),
            '''SELECT * FROM "users" WHERE "users"."name" = 'Joe' OR EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id" '''
            '''AND "articles"."active" = \'1\''''
            ''')''',
        )

    def test_belongs_to_many_or_where_has_adds_id_subselect(self):
        """or_where_has over belongs_to_many OR-joins the pivot EXISTS and appends
        the id IN (...) sub-select carrying the callback predicate."""
        self.assertEqual(
            Role.where("name", "role_name")
            .or_where_has("permissions", lambda q: q.where("permission_id", 1))
            .to_sql(),
            '''SELECT * FROM "roles" WHERE "roles"."name" = 'role_name' OR EXISTS ('''
            '''SELECT * FROM "permissions" INNER JOIN "permission_role" '''
            '''ON "permissions"."id" = "permission_role"."permission_id" '''
            '''WHERE "permission_role"."role_id" = "roles"."id" '''
            '''AND "permissions"."id" IN ('''
            '''SELECT "permissions"."id" FROM "permissions" '''
            '''WHERE "permissions"."permission_id" = \'1\'))''',
        )

    def test_belongs_to_many_where_doesnt_have_negates_with_and(self):
        """where_doesnt_have over belongs_to_many AND-joins a NOT EXISTS carrying the
        id IN (...) sub-select."""
        self.assertEqual(
            Role.where("name", "role_name")
            .where_doesnt_have(
                "permissions", lambda q: q.where("name", "Creates Users")
            )
            .to_sql(),
            '''SELECT * FROM "roles" WHERE "roles"."name" = 'role_name' AND NOT EXISTS ('''
            '''SELECT * FROM "permissions" INNER JOIN "permission_role" '''
            '''ON "permissions"."id" = "permission_role"."permission_id" '''
            '''WHERE "permission_role"."role_id" = "roles"."id" '''
            '''AND "permissions"."id" IN ('''
            '''SELECT "permissions"."id" FROM "permissions" '''
            '''WHERE "permissions"."name" = \'Creates Users\'))''',
        )

    def test_belongs_to_many_or_doesnt_have(self):
        """or_doesnt_have over belongs_to_many OR-joins a bare pivot NOT EXISTS."""
        self.assertEqual(
            Role.where("name", "role_name").or_doesnt_have("permissions").to_sql(),
            '''SELECT * FROM "roles" WHERE "roles"."name" = 'role_name' OR NOT EXISTS ('''
            '''SELECT * FROM "permissions" INNER JOIN "permission_role" '''
            '''ON "permissions"."id" = "permission_role"."permission_id" '''
            '''WHERE "permission_role"."role_id" = "roles"."id")''',
        )

    def test_belongs_to_many_with_count_correlated_subselect(self):
        """with_count over belongs_to_many inlines a correlated COUNT(*) sub-select
        on the pivot table, aliased <related_table>_count."""
        self.assertEqual(
            Permission.with_count("role").to_sql(),
            '''SELECT "permissions".*, (SELECT COUNT(*) AS m_count_reserved '''
            '''FROM "permission_role" '''
            '''WHERE "permissions"."id" = "permission_role"."permission_id") '''
            '''AS roles_count FROM "permissions"''',
        )

    def test_where_has_combined_with_outer_clauses(self):
        """An EXISTS predicate from where_has is AND-joined to a preceding plain
        where, and trailing order_by / limit are appended after the WHERE."""
        self.assertEqual(
            self._builder()
            .where("name", "Joe")
            .where_has("articles", lambda q: q.where("active", 1))
            .order_by("name")
            .limit(5)
            .to_sql(),
            '''SELECT * FROM "users" WHERE "users"."name" = \'Joe\' '''
            '''AND EXISTS ('''
            '''SELECT * FROM "articles" '''
            '''WHERE "articles"."user_id" = "users"."id" '''
            '''AND "articles"."active" = \'1\''''
            ''') ORDER BY "name" ASC LIMIT 5''',
        )

    def test_has_combined_with_outer_where_and_order(self):
        """has() emits its EXISTS first; a subsequent plain where is AND-joined
        after it and latest() appends an ORDER BY ... DESC."""
        self.assertEqual(
            self._builder()
            .has("articles")
            .where("active", 1)
            .latest("id")
            .to_sql(),
            '''SELECT * FROM "users" WHERE EXISTS ('''
            '''SELECT * FROM "articles" '''
            '''WHERE "articles"."user_id" = "users"."id"'''
            ''') AND "users"."active" = \'1\' ORDER BY "id" DESC''',
        )

    def test_where_combined_with_doesnt_have(self):
        """A preceding plain where is AND-joined to a NOT EXISTS from doesnt_have."""
        self.assertEqual(
            self._builder()
            .where("active", 1)
            .doesnt_have("articles")
            .to_sql(),
            '''SELECT * FROM "users" WHERE "users"."active" = \'1\' '''
            '''AND NOT EXISTS ('''
            '''SELECT * FROM "articles" '''
            '''WHERE "articles"."user_id" = "users"."id"'''
            ''')''',
        )

    def test_or_has_joins_belongs_to_exists_with_or(self):
        """or_has OR-joins a belongs_to EXISTS onto the prior predicate."""
        self.assertEqual(
            self._builder()
            .where("name", "Joe")
            .or_has("articles")
            .to_sql(),
            '''SELECT * FROM "users" WHERE "users"."name" = \'Joe\' '''
            '''OR EXISTS ('''
            '''SELECT * FROM "articles" '''
            '''WHERE "articles"."user_id" = "users"."id"'''
            ''')''',
        )

    def test_doesnt_have_dotted_nested_negates_outer_only(self):
        """doesnt_have on a dotted relation negates the OUTER EXISTS while the inner
        nested EXISTS stays positive (only the outermost correlation is negated)."""
        self.assertEqual(
            RelUser.doesnt_have("articles.logo").to_sql(),
            '''SELECT * FROM "users" WHERE NOT EXISTS ('''
            '''SELECT * FROM "articles" WHERE "articles"."user_id" = "users"."id" '''
            '''AND EXISTS ('''
            '''SELECT * FROM "logos" WHERE "logos"."article_id" = "articles"."id"'''
            '''))''',
        )

    def test_belongs_to_many_with_count_combined_with_outer_where(self):
        """with_count over belongs_to_many inlines the correlated COUNT(*) pivot
        sub-select AND still applies a trailing outer where after FROM."""
        self.assertEqual(
            Permission.where("active", 1).with_count("role").to_sql(),
            '''SELECT "permissions".*, (SELECT COUNT(*) AS m_count_reserved '''
            '''FROM "permission_role" '''
            '''WHERE "permissions"."id" = "permission_role"."permission_id") '''
            '''AS roles_count FROM "permissions" WHERE "permissions"."active" = \'1\'''',
        )

    def test_where_has_qmark_binding_order_across_exists(self):
        """In qmark mode a where_has still emits '?' placeholders inside the EXISTS,
        and bindings accumulate outer-where-first then the callback predicate."""
        b = RelUser().where("name", "Joe").where_has(
            "articles", lambda q: q.where("active", 1)
        )
        self.assertEqual(
            b.to_qmark(),
            '''SELECT * FROM "users" WHERE "users"."name" = \'?\' '''
            '''AND EXISTS (SELECT * FROM "articles" '''
            '''WHERE "articles"."user_id" = "users"."id" AND "articles"."active" = \'?\')''',
        )
        self.assertEqual(b._bindings, ["Joe", 1])

    def test_belongs_to_many_with_count_qmark(self):
        """with_count's correlated COUNT(*) pivot sub-select carries no binding; the
        trailing outer where contributes the only '?' + binding."""
        b = Permission.where("active", 1).with_count("role")
        self.assertEqual(
            b.to_qmark(),
            '''SELECT "permissions".*, (SELECT COUNT(*) AS m_count_reserved '''
            '''FROM "permission_role" '''
            '''WHERE "permissions"."id" = "permission_role"."permission_id") '''
            '''AS roles_count FROM "permissions" WHERE "permissions"."active" = \'?\'''',
        )
        self.assertEqual(b._bindings, [1])

    def test_belongs_to_many_or_where_has_qmark_binding_order(self):
        """or_where_has over belongs_to_many in qmark mode: the outer where binding
        precedes the id-subselect predicate binding in source order."""
        b = Role.where("name", "r").or_where_has(
            "permissions", lambda q: q.where("a", 1)
        )
        self.assertEqual(
            b.to_qmark(),
            '''SELECT * FROM "roles" WHERE "roles"."name" = \'?\' OR EXISTS ('''
            '''SELECT * FROM "permissions" INNER JOIN "permission_role" '''
            '''ON "permissions"."id" = "permission_role"."permission_id" '''
            '''WHERE "permission_role"."role_id" = "roles"."id" '''
            '''AND "permissions"."id" IN ('''
            '''SELECT "permissions"."id" FROM "permissions" '''
            '''WHERE "permissions"."a" = \'?\'))''',
        )
        self.assertEqual(b._bindings, ["r", 1])


if __name__ == "__main__":
    unittest.main()
