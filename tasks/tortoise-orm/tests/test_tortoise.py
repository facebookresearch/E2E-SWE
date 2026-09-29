"""Hidden test suite for the tortoise-orm (ORM core + sqlite) whole-repo-generation task.

Every test exercises RUNTIME behavior of the ORM against a fresh in-memory SQLite database:
models are defined inline, a schema is generated, rows are created, and real queries are run —
correctness is the actual DB-backed result, not any API shape. The suite is weighted toward the
hard runtime behaviors (deep relations, prefetch, aggregation, transactions) with a small
foundation of consolidated CRUD/field tests.

Self-contained: depends only on the agent's `tortoise` package (+ pytest/pytest-asyncio/aiosqlite).
"""

import datetime
from decimal import Decimal
from enum import Enum, IntEnum
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from tortoise import Model, Tortoise, fields
from tortoise.exceptions import (
    DoesNotExist,
    FieldError,
    IntegrityError,
    MultipleObjectsReturned,
    NoValuesFetched,
    OperationalError,
    ParamsError,
    ValidationError,
)
from tortoise.expressions import F, Q
from tortoise.functions import Avg, Count, Sum
from tortoise.transactions import atomic, in_transaction

# NOTE: `Prefetch` (from tortoise.query_utils) is imported locally inside the single test that
# uses it, so that an implementation which omits that one helper fails only that test rather than
# breaking collection of the whole module.


# --------------------------------------------------------------------------------------------- #
# Inline models
# --------------------------------------------------------------------------------------------- #
class Color(IntEnum):
    RED = 1
    GREEN = 2
    BLUE = 3


class Size(str, Enum):
    SMALL = "small"
    LARGE = "large"


class Tournament(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    created = fields.DatetimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Reporter(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)


class Team(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255, unique=True)


class Event(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    tournament = fields.ForeignKeyField("models.Tournament", related_name="events")
    reporter = fields.ForeignKeyField(
        "models.Reporter", related_name="events", null=True
    )
    participants = fields.ManyToManyField("models.Team", related_name="events")
    modified = fields.DatetimeField(auto_now=True)


class Profile(Model):
    id = fields.IntField(primary_key=True)
    bio = fields.TextField()
    reporter = fields.OneToOneField("models.Reporter", related_name="profile")


class Author(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)


class Book(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    rating = fields.FloatField()
    author = fields.ForeignKeyField("models.Author", related_name="books")


class Employee(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    manager = fields.ForeignKeyField(
        "models.Employee", related_name="subordinates", null=True
    )


class AllFields(Model):
    id = fields.IntField(primary_key=True)
    charf = fields.CharField(max_length=10)
    boolf = fields.BooleanField(default=False)
    decimalf = fields.DecimalField(max_digits=12, decimal_places=2, null=True)
    dtf = fields.DatetimeField(null=True)
    datef = fields.DateField(null=True)
    jsonf = fields.JSONField(null=True)
    uuidf = fields.UUIDField(null=True)
    intenumf = fields.IntEnumField(Color, null=True)
    charenumf = fields.CharEnumField(Size, null=True)
    intnull = fields.IntField(null=True)


class Aliased(Model):
    id = fields.IntField(primary_key=True)
    value = fields.CharField(max_length=255, source_field="value_col")


class Defaulted(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255, default="anon")
    uid = fields.UUIDField(default=uuid4)


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": [__name__]},
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


# --------------------------------------------------------------------------------------------- #
# Foundation (consolidated — CRUD, fields, lifecycle)
# --------------------------------------------------------------------------------------------- #
class TestFoundation:
    async def test_create_get_roundtrip_and_cast(self):
        """create() inserts + assigns pk; get() round-trips by identity; inputs are coerced."""
        t = await Tournament.create(name="A")
        assert t.id is not None
        fetched = await Tournament.get(id=t.id)
        assert fetched == t and fetched.name == "A"
        a = await AllFields.create(charf="x", intnull="7")
        assert a.intnull == 7 and isinstance(a.intnull, int)

    async def test_save_insert_then_update_fields(self):
        """A fetched object UPDATEs on save; update_fields=[] writes nothing."""
        t = await Tournament.create(name="orig")
        fetched = await Tournament.get(id=t.id)
        fetched.name = "changed"
        await fetched.save()
        assert (await Tournament.get(id=t.id)).name == "changed"
        await Tournament.filter(id=t.id).update(name="db")
        obj = await Tournament.get(id=t.id)
        obj.name = "not_saved"
        await obj.save(update_fields=[])
        assert (await Tournament.get(id=t.id)).name == "db"

    async def test_get_exception_semantics(self):
        """get() raises DoesNotExist/MultipleObjectsReturned; get_or_none/first return None."""
        await Tournament.create(name="dup")
        await Tournament.create(name="dup")
        with pytest.raises(DoesNotExist):
            await Tournament.get(name="missing")
        with pytest.raises(MultipleObjectsReturned):
            await Tournament.get(name="dup")
        assert await Tournament.get_or_none(name="missing") is None
        assert await Tournament.filter(name="missing").first() is None

    async def test_get_or_create(self):
        """get_or_create returns (obj, created) and doesn't duplicate."""
        o1, c1 = await Tournament.get_or_create(name="goc")
        o2, c2 = await Tournament.get_or_create(name="goc")
        assert c1 is True and c2 is False and o1.id == o2.id
        assert await Tournament.filter(name="goc").count() == 1

    async def test_delete_and_unsaved_guards(self):
        """delete() removes the row; deleting/hashing an unsaved instance is guarded."""
        t = await Tournament.create(name="x")
        await t.delete()
        assert await Tournament.filter(id=t.id).count() == 0
        with pytest.raises(OperationalError):
            await Tournament(name="never").delete()
        # an unsaved instance (pk is None) is unhashable; a saved one is hashable
        with pytest.raises(TypeError):
            hash(Tournament(name="u"))
        assert isinstance(hash(await Tournament.create(name="h")), int)

    async def test_field_value_roundtrips(self):
        """bool/decimal/datetime/json/uuid/enum all round-trip to the right python value."""
        u = UUID("12345678-1234-5678-1234-567812345678")
        a = await AllFields.create(
            charf="b",
            boolf=True,
            decimalf=Decimal("1.10"),
            dtf=datetime.datetime(2020, 1, 2, 3, 4, 5),
            datef=datetime.date(2021, 6, 7),
            jsonf={"a": [1, 2], "b": "x"},
            uuidf=u,
            intenumf=Color.GREEN,
            charenumf=Size.LARGE,
            intnull=2147483647,
        )
        f = await AllFields.get(id=a.id)
        assert f.boolf is True and isinstance(f.boolf, bool)
        assert f.decimalf == Decimal("1.1")
        assert f.dtf.replace(tzinfo=None) == datetime.datetime(2020, 1, 2, 3, 4, 5)
        assert f.datef == datetime.date(2021, 6, 7)
        assert f.jsonf == {"a": [1, 2], "b": "x"}
        assert f.uuidf == u and isinstance(f.uuidf, UUID)
        assert f.intenumf == Color.GREEN and isinstance(f.intenumf, Color)
        assert f.charenumf == Size.LARGE
        assert f.intnull == 2147483647

    async def test_defaults_and_auto_now(self):
        """Static/callable defaults apply on create; auto_now_add once; auto_now per save."""
        d = await Defaulted.create()
        assert d.name == "anon" and isinstance(d.uid, UUID)
        t = await Tournament.create(name="ts")
        assert t.created is not None
        e = await Event.create(name="e", tournament=t)
        first_mod = e.modified
        e.name = "e2"
        await e.save()
        assert e.modified >= first_mod

    async def test_null_handling_and_validation(self):
        """Nullable fields store None; non-null None raises; over-length CharField raises."""
        a = await AllFields.create(charf="n")
        f = await AllFields.get(id=a.id)
        assert f.decimalf is None and f.intnull is None and f.jsonf is None
        with pytest.raises((ValueError, IntegrityError)):
            await AllFields.create(charf=None)
        with pytest.raises(ValidationError):
            await AllFields.create(charf="0123456789TOOLONG")

    async def test_refresh_from_db(self):
        """refresh_from_db reloads column values onto the instance."""
        t = await Tournament.create(name="orig")
        await Tournament.filter(id=t.id).update(name="updated")
        await t.refresh_from_db()
        assert t.name == "updated"

    async def test_unique_constraint_integrity_error(self):
        """A unique-constraint violation raises IntegrityError."""
        await Team.create(name="dup")
        with pytest.raises(IntegrityError):
            await Team.create(name="dup")

    async def test_source_field_alias_and_filter(self):
        """source_field maps to a different DB column, transparent to attribute access + filters."""
        a = await Aliased.create(value="hello")
        assert (await Aliased.get(id=a.id)).value == "hello"
        assert await Aliased.filter(value="hello").count() == 1
        conn = Tortoise.get_connection("default")
        rows = await conn.execute_query_dict("SELECT value_col FROM aliased")
        assert rows[0]["value_col"] == "hello"


# --------------------------------------------------------------------------------------------- #
# Querying (operators, Q/F, shaping)
# --------------------------------------------------------------------------------------------- #
class TestQuerying:
    async def _seed(self):
        for n in range(10, 40, 3):  # 10,13,...,37
            await AllFields.create(charf=f"c{n}", intnull=n)

    async def test_comparison_in_range_operators(self):
        """gt/gte/lt/lte/in/range return exactly the matching rows."""
        await self._seed()
        assert await AllFields.filter(intnull__gt=31).count() == 2  # 34, 37
        assert sorted(
            await AllFields.filter(intnull__gte=31).values_list("intnull", flat=True)
        ) == [31, 34, 37]
        assert await AllFields.filter(intnull__in=[10, 13, 99]).count() == 2
        assert sorted(
            await AllFields.filter(intnull__range=(13, 19)).values_list(
                "intnull", flat=True
            )
        ) == [13, 16, 19]

    async def test_string_like_operators(self):
        """contains/startswith/endswith/icontains map to the right (case-insensitive) LIKE."""
        await AllFields.create(charf="Apple")
        await AllFields.create(charf="apricot")
        await AllFields.create(charf="Banana")
        assert await AllFields.filter(charf__startswith="Ap").count() == 2
        assert await AllFields.filter(charf__contains="ana").count() == 1
        assert await AllFields.filter(charf__icontains="AN").count() == 1
        assert await AllFields.filter(charf__endswith="cot").count() == 1

    async def test_exclude_and_isnull_semantics(self):
        """exclude uses SQL not-equal (NULL excluded); value=None maps to IS NULL."""
        await AllFields.create(charf="a", intnull=1)
        await AllFields.create(charf="b", intnull=2)
        await AllFields.create(charf="c", intnull=None)
        assert list(await AllFields.exclude(intnull=1).values_list("charf", flat=True)) == ["b"]
        assert await AllFields.filter(intnull=None).count() == 1
        assert await AllFields.filter(intnull__isnull=True).count() == 1

    async def test_q_object_and_or_not(self):
        """Q composes with &, |, ~ (including nesting) to the correct row sets."""
        for n in (5, 15, 25, 35):
            await AllFields.create(charf=f"v{n}", intnull=n)
        assert await AllFields.filter(Q(intnull=5) | Q(intnull=25)).count() == 2
        assert await AllFields.filter(~Q(intnull=15)).count() == 3
        assert await AllFields.filter(
            Q(intnull__gte=15) & ~Q(intnull=35)
        ).count() == 2  # 15, 25

    async def test_f_expression_update_and_filter(self):
        """F drives in-DB arithmetic in update() and column-vs-column comparison in filter()."""
        a = await AllFields.create(charf="f", intnull=10, decimalf=Decimal("3"))
        await AllFields.filter(id=a.id).update(intnull=F("intnull") + 5)
        assert (await AllFields.get(id=a.id)).intnull == 15
        # column comparison: rows where intnull == id
        await AllFields.create(charf="g", intnull=999)
        match = await AllFields.filter(intnull=F("id")).count()
        assert match == 0  # 15 != its id, 999 != its id

    async def test_order_by_limit_offset_slice(self):
        """order_by asc/desc + limit/offset/slice return the right window; bad params raise."""
        for n in [30, 10, 20, 40]:
            await AllFields.create(charf=f"c{n}", intnull=n)
        assert list(
            await AllFields.all().order_by("intnull").values_list("intnull", flat=True)
        ) == [10, 20, 30, 40]
        assert list(
            await AllFields.all().order_by("-intnull").values_list("intnull", flat=True)
        ) == [40, 30, 20, 10]
        assert list(
            await AllFields.all().order_by("intnull").limit(2).offset(1).values_list(
                "intnull", flat=True
            )
        ) == [20, 30]
        assert list(
            await AllFields.all().order_by("intnull")[1:3].values_list("intnull", flat=True)
        ) == [20, 30]
        with pytest.raises(ParamsError):
            AllFields.all().limit(-1)

    async def test_values_valueslist_distinct(self):
        """values→dicts, values_list→tuples/scalars, distinct dedups; flat multi-field errors."""
        await AllFields.create(charf="a", intnull=1)
        await AllFields.create(charf="a", intnull=1)
        assert await AllFields.all().values("charf", "intnull") == [
            {"charf": "a", "intnull": 1},
            {"charf": "a", "intnull": 1},
        ]
        assert await AllFields.all().values_list("charf", "intnull") == [("a", 1), ("a", 1)]
        assert list(
            await AllFields.all().distinct().values_list("charf", flat=True)
        ) == ["a"]
        with pytest.raises(TypeError):
            await AllFields.all().values_list("charf", "intnull", flat=True)

    async def test_count_exists_bulk_update_delete(self):
        """count/exists reflect the DB; bulk update/delete return affected row counts."""
        for n in range(5):
            await AllFields.create(charf=f"c{n}", intnull=n)
        assert await AllFields.all().count() == 5
        assert await AllFields.filter(intnull__gte=3).exists() is True
        assert await AllFields.filter(intnull__lt=2).update(charf="z") == 2
        assert await AllFields.filter(intnull__gte=3).delete() == 2
        assert await AllFields.all().count() == 3

    async def test_in_bulk(self):
        """in_bulk returns a dict keyed by the requested field."""
        a = await Tournament.create(name="a")
        b = await Tournament.create(name="b")
        result = await Tournament.filter(id__in=[a.id, b.id]).in_bulk(
            [a.id, b.id], field_name="id"
        )
        assert set(result.keys()) == {a.id, b.id} and result[a.id].name == "a"

    async def test_unknown_field_filter_and_order_raise(self):
        """Filtering or ordering by an unknown field raises FieldError."""
        with pytest.raises(FieldError):
            await Tournament.filter(nope="x")
        with pytest.raises(FieldError):
            await Tournament.all().order_by("nope")


# --------------------------------------------------------------------------------------------- #
# Relations (the hard core)
# --------------------------------------------------------------------------------------------- #
class TestRelations:
    async def test_fk_assignment_and_lazy_fetch(self):
        """Assigning an FK sets the shadow *_id; awaiting the FK fetches the related row."""
        t = await Tournament.create(name="t")
        e = await Event.create(name="e", tournament=t)
        assert e.tournament_id == t.id
        e2 = await Event.get(id=e.id)
        related = await e2.tournament
        assert related == t and related.name == "t"

    async def test_fk_unsaved_target_raises(self):
        """Passing an unsaved related object as an FK value raises OperationalError."""
        with pytest.raises(OperationalError):
            await Event.create(name="e", tournament=Tournament(name="unsaved"))

    async def test_filter_by_related_object(self):
        """A relation can be filtered by passing the related instance (its pk is used)."""
        t1 = await Tournament.create(name="t1")
        t2 = await Tournament.create(name="t2")
        await Event.create(name="e1", tournament=t1)
        await Event.create(name="e2", tournament=t2)
        names = await Event.filter(tournament=t1).values_list("name", flat=True)
        assert list(names) == ["e1"]

    async def test_reverse_fk_query_and_guards(self):
        """Reverse FK is a chainable manager (.all()/.filter()/.order_by()/.create()) with guards."""
        t = await Tournament.create(name="t")
        await Event.create(name="e1", tournament=t)
        await t.events.create(name="e2")  # reverse .create injects the FK
        names = await t.events.all().order_by("name").values_list("name", flat=True)
        assert list(names) == ["e1", "e2"]
        assert await t.events.filter(name="e1").count() == 1
        # iterating before fetch raises; querying from an unsaved parent raises
        with pytest.raises(NoValuesFetched):
            list(t.events)
        with pytest.raises(OperationalError):
            await Tournament(name="unsaved").events.all()

    async def test_o2o_forward_and_backward(self):
        """OneToOne forward fetch returns the object; backward returns the single owner."""
        r = await Reporter.create(name="r")
        p = await Profile.create(bio="hi", reporter=r)
        assert p.reporter_id == r.id
        assert (await (await Profile.get(id=p.id)).reporter) == r
        assert (await r.profile) == p

    async def test_m2m_add_remove_clear(self):
        """M2M add (idempotent)/remove/clear mutate the relation; all() reflects it."""
        t = await Tournament.create(name="t")
        e = await Event.create(name="e", tournament=t)
        a = await Team.create(name="A")
        b = await Team.create(name="B")
        await e.participants.add(a, b)
        await e.participants.add(a)  # idempotent
        assert await e.participants.all().count() == 2
        await e.participants.remove(a)
        assert list(await e.participants.all().values_list("name", flat=True)) == ["B"]
        await e.participants.clear()
        assert await e.participants.all().count() == 0

    async def test_m2m_filter_both_directions(self):
        """M2M membership is filterable from either side."""
        t = await Tournament.create(name="t")
        e1 = await Event.create(name="e1", tournament=t)
        e2 = await Event.create(name="e2", tournament=t)
        a = await Team.create(name="A")
        b = await Team.create(name="B")
        await e1.participants.add(a)
        await e2.participants.add(b)
        assert list(await Event.filter(participants__name="A").values_list("name", flat=True)) == ["e1"]
        assert list(await Team.filter(events__name="e2").values_list("name", flat=True)) == ["B"]

    async def test_relation_spanning_filter_multihop(self):
        """Filtering spans relations, including a two-hop join through an M2M."""
        t1 = await Tournament.create(name="t1")
        t2 = await Tournament.create(name="t2")
        e1 = await Event.create(name="alpha", tournament=t1)
        await Event.create(name="beta", tournament=t2)
        team = await Team.create(name="winners")
        await e1.participants.add(team)
        assert list(await Tournament.filter(events__name="alpha").values_list("name", flat=True)) == ["t1"]
        # two hops: tournament -> events -> participants
        assert list(
            await Tournament.filter(events__participants__name="winners").values_list(
                "name", flat=True
            )
        ) == ["t1"]

    async def test_self_referential_fk(self):
        """A self-referential FK exposes forward (manager) and reverse (subordinates)."""
        boss = await Employee.create(name="boss")
        await Employee.create(name="alice", manager=boss)
        await Employee.create(name="bob", manager=boss)
        subs = await boss.subordinates.all().order_by("name").values_list("name", flat=True)
        assert list(subs) == ["alice", "bob"]
        alice = await Employee.get(name="alice")
        assert (await alice.manager).name == "boss"

    async def test_values_across_relation(self):
        """values()/values_list() can project related-model columns via __ traversal."""
        t = await Tournament.create(name="t1")
        await Event.create(name="e1", tournament=t)
        assert await Event.all().values("name", "tournament__name") == [
            {"name": "e1", "tournament__name": "t1"}
        ]
        assert await Event.all().values_list("name", "tournament__name") == [("e1", "t1")]


# --------------------------------------------------------------------------------------------- #
# Eager loading (select_related / prefetch_related)
# --------------------------------------------------------------------------------------------- #
class TestEagerLoading:
    async def test_select_related_single_query(self):
        """select_related populates forward FK/O2O synchronously; null FK becomes None."""
        t = await Tournament.create(name="t")
        r = await Reporter.create(name="rep")
        await Event.create(name="e1", tournament=t, reporter=r)
        await Event.create(name="e2", tournament=t, reporter=None)
        events = await Event.all().select_related("tournament", "reporter").order_by("name")
        assert events[0].tournament.name == "t"
        assert events[0].reporter.name == "rep"
        assert events[1].reporter is None

    async def test_prefetch_related_batched(self):
        """prefetch_related populates a reverse relation per parent."""
        t1 = await Tournament.create(name="t1")
        t2 = await Tournament.create(name="t2")
        await Event.create(name="e1", tournament=t1)
        await Event.create(name="e2", tournament=t1)
        ts = await Tournament.all().prefetch_related("events").order_by("name")
        assert sorted(e.name for e in ts[0].events) == ["e1", "e2"]
        assert list(ts[1].events) == []

    async def test_prefetch_nested(self):
        """Nested prefetch (relation__subrelation) populates the deep relation synchronously."""
        t = await Tournament.create(name="t")
        e = await Event.create(name="e", tournament=t)
        a = await Team.create(name="A")
        b = await Team.create(name="B")
        await e.participants.add(a, b)
        ts = await Tournament.all().prefetch_related("events__participants")
        ev = list(ts[0].events)[0]
        assert sorted(team.name for team in ev.participants) == ["A", "B"]

    async def test_prefetch_with_custom_queryset_and_to_attr(self):
        """Prefetch(...) accepts a filtered queryset and a custom to_attr."""
        from tortoise.query_utils import Prefetch

        t = await Tournament.create(name="t")
        await Event.create(name="keep", tournament=t)
        await Event.create(name="drop", tournament=t)
        ts = await Tournament.all().prefetch_related(
            Prefetch("events", queryset=Event.filter(name="keep"), to_attr="kept")
        )
        kept = ts[0].kept
        assert [e.name for e in kept] == ["keep"]


# --------------------------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------------------------- #
class TestAggregation:
    async def _seed(self):
        t1 = await Tournament.create(name="t1")
        t2 = await Tournament.create(name="t2")
        r = await Reporter.create(name="r")
        for nm in ["e1", "e2", "e3"]:
            await Event.create(name=nm, tournament=t1, reporter=r)
        await Event.create(name="e4", tournament=t2, reporter=r)
        return t1, t2

    async def test_annotate_count_groups_per_row(self):
        """annotate(Count(relation)) groups by the model and yields per-row counts."""
        await self._seed()
        rows = await Tournament.annotate(num=Count("events")).order_by("name").values(
            "name", "num"
        )
        assert rows == [{"name": "t1", "num": 3}, {"name": "t2", "num": 1}]

    async def test_count_distinct_and_filtered(self):
        """Count(distinct=True) dedups; Count(_filter=Q(...)) counts only matching rows."""
        a = await Author.create(name="auth")
        await Book.create(name="b1", rating=5.0, author=a)
        await Book.create(name="b2", rating=5.0, author=a)
        await Book.create(name="b3", rating=1.0, author=a)
        rows = await Author.filter(id=a.id).annotate(
            distinct_ratings=Count("books__rating", distinct=True),
            high=Count("books__id", _filter=Q(books__rating__gte=5.0)),
        ).values("distinct_ratings", "high")
        assert rows[0]["distinct_ratings"] == 2  # {5.0, 1.0}
        assert rows[0]["high"] == 2  # two books with rating>=5

    async def test_avg_sum_over_relation(self):
        """Avg/Sum aggregate over a related numeric column return correct numbers."""
        a = await Author.create(name="auth")
        for r in (2.0, 4.0, 6.0):
            await Book.create(name=f"b{r}", rating=r, author=a)
        agg = await Author.filter(id=a.id).annotate(
            avg=Avg("books__rating"), total=Sum("books__rating")
        ).values("avg", "total")
        assert agg[0]["avg"] == pytest.approx(4.0)
        assert agg[0]["total"] == pytest.approx(12.0)

    async def test_annotate_filter_having_and_order(self):
        """Filtering on an aggregate annotation is a HAVING; ordering by it sorts by the aggregate."""
        await self._seed()
        names = await Tournament.annotate(num=Count("events")).filter(
            num__gt=1
        ).order_by("-num").values_list("name", flat=True)
        assert list(names) == ["t1"]
        # With no HAVING both groups survive, so the aggregate ordering itself is observable
        # (t1 has 3 events, t2 has 1). Ascending is the discriminating direction: it is the
        # reverse of the name ordering a queryset that ignored the alias would fall back to.
        desc = await Tournament.annotate(num=Count("events")).order_by("-num").values_list(
            "name", flat=True
        )
        assert list(desc) == ["t1", "t2"]
        asc = await Tournament.annotate(num=Count("events")).order_by("num").values_list(
            "name", flat=True
        )
        assert list(asc) == ["t2", "t1"]


# --------------------------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------------------------- #
class TestTransactions:
    async def test_transaction_rolls_back_on_exception(self):
        """A transaction commits on clean exit and rolls back all writes on exception."""
        with pytest.raises(RuntimeError):
            async with in_transaction():
                await Tournament.create(name="rolledback")
                raise RuntimeError("boom")
        assert await Tournament.filter(name="rolledback").count() == 0
        async with in_transaction():
            await Tournament.create(name="committed")
        assert await Tournament.filter(name="committed").count() == 1

    async def test_nested_savepoint_rollback(self):
        """A nested transaction that raises rolls back only its own writes; outer commits."""
        async with in_transaction():
            await Tournament.create(name="outer")
            try:
                async with in_transaction():
                    await Tournament.create(name="inner")
                    raise RuntimeError("inner fail")
            except RuntimeError:
                pass
        assert await Tournament.filter(name="outer").count() == 1
        assert await Tournament.filter(name="inner").count() == 0

    async def test_atomic_decorator(self):
        """@atomic() commits on success and rolls back on exception."""

        @atomic()
        async def good():
            await Tournament.create(name="ok")

        @atomic()
        async def bad():
            await Tournament.create(name="nope")
            raise RuntimeError("x")

        await good()
        with pytest.raises(RuntimeError):
            await bad()
        assert await Tournament.filter(name="ok").count() == 1
        assert await Tournament.filter(name="nope").count() == 0
