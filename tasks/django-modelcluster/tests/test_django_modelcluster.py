"""Hidden end-to-end test suite for the django-modelcluster WRG task.

Each test exercises a distinct, user-facing capability of the library the way a
real user would: defining ClusterableModel subclasses wired together with
ParentalKey / ParentalManyToManyField / ClusterTaggableManager, building
"clusters" of related objects in memory, querying them through the QuerySet-like
API before they hit the database, serializing / copying them, and driving them
through cluster-aware forms and formsets.

The models under ``tests_app`` form the fixture; they are hidden from the agent.
"""

import datetime
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.db.models import Q
from django.forms import Textarea
from django.test import TestCase
from django.utils import timezone

from modelcluster.fields import ParentalKey
from modelcluster.forms import (
    ClusterForm,
    childformset_factory,
    transientmodelformset_factory,
)
from modelcluster.models import (
    get_all_child_m2m_relations,
    get_all_child_relations,
)
from modelcluster.queryset import FakeQuerySet
from modelcluster.utils import ManyToManyTraversalError

from tests_app.models import (
    Album,
    Article,
    Author,
    Band,
    BandMember,
    Category,
    Chef,
    Comment,
    Document,
    Feature,
    Gallery,
    House,
    Log,
    NewsPaper,
    NonClusterPlace,
    Person,
    Place,
    RecordLabel,
    Restaurant,
    Review,
    Room,
    SeafoodRestaurant,
    Song,
)


# ---------------------------------------------------------------------------
# In-memory cluster lifecycle (ParentalKey + deferring related manager)
# ---------------------------------------------------------------------------


class ClusterLifecycleTest(TestCase):
    def test_build_query_and_save_cluster(self):
        """A child relation can be populated and queried before the parent is
        saved; calling save() then writes the whole cluster to the database."""
        beatles = Band(name="The Beatles")
        self.assertEqual(0, beatles.members.count())

        beatles.members = [
            BandMember(name="John Lennon"),
            BandMember(name="Paul McCartney"),
        ]
        self.assertEqual(2, beatles.members.count())
        self.assertEqual("John Lennon", beatles.members.all()[0].name)

        # nothing in the database yet
        self.assertFalse(Band.objects.filter(name="The Beatles").exists())
        self.assertFalse(BandMember.objects.filter(name="John Lennon").exists())

        beatles.save()
        self.assertTrue(Band.objects.filter(name="The Beatles").exists())
        self.assertEqual(2, Band.objects.get(name="The Beatles").members.count())

    def test_reassigning_relation_defers_until_save(self):
        """Reassigning a saved cluster's children takes effect in memory
        immediately but only reaches the database (deleting removed children)
        on the next save()."""
        beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon"), BandMember(name="Paul McCartney")],
        )
        beatles.save()

        john = BandMember.objects.get(name="John Lennon")
        beatles.members = [john]
        # in-memory updated, database untouched
        self.assertEqual(1, beatles.members.count())
        self.assertEqual(2, Band.objects.get(name="The Beatles").members.count())

        beatles.save()
        self.assertEqual(1, Band.objects.get(name="The Beatles").members.count())
        # the removed member is deleted from the database entirely
        self.assertEqual(0, BandMember.objects.filter(name="Paul McCartney").count())

    def test_related_manager_add_remove_create_set(self):
        """add() (de-duplicating), remove(), create() and set() all mutate the
        in-memory child set without touching the database."""
        beatles = Band(name="The Beatles")
        john = BandMember(name="John Lennon")
        paul = BandMember(name="Paul McCartney")

        beatles.members.add(john)
        beatles.members.add(paul)
        beatles.members.add(paul)  # duplicate ignored
        self.assertEqual(2, beatles.members.count())

        beatles.members.remove(john)
        self.assertEqual(1, beatles.members.count())
        self.assertEqual(paul, beatles.members.all()[0])

        george = beatles.members.create(name="George Harrison")
        self.assertEqual("George Harrison", george.name)
        self.assertEqual(2, beatles.members.count())

        beatles.members.set([john])
        self.assertEqual(1, beatles.members.count())
        self.assertEqual(john, beatles.members.all()[0])

    def test_child_relations_as_constructor_kwargs(self):
        """Child relations can be supplied as constructor kwargs, and each child
        gets a back-reference to the parent instance."""
        beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon"), BandMember(name="Paul McCartney")],
        )
        self.assertEqual(2, beatles.members.count())
        self.assertEqual(beatles, beatles.members.all()[0].band)

    def test_child_relations_of_superclass(self):
        """Child relations declared against a superclass are accessible (and
        savable) from a multi-table-inheritance subclass instance."""
        fat_duck = Restaurant(
            name="The Fat Duck",
            reviews=[Review(author="Michael Winner", body="Rubbish.")],
        )
        self.assertEqual(1, fat_duck.reviews.count())
        self.assertEqual("Michael Winner", fat_duck.reviews.first().author)
        self.assertEqual(fat_duck, fat_duck.reviews.all()[0].place)

        fat_duck.save()
        reloaded = Restaurant.objects.get(id=fat_duck.id)
        self.assertEqual(1, reloaded.reviews.count())
        self.assertEqual("Michael Winner", reloaded.reviews.first().author)

    def test_commit_requires_saved_parent(self):
        """Committing a child relation on an unsaved parent raises IntegrityError;
        after the parent is saved the commit succeeds."""
        beatles = Band(name="The Beatles", members=[BandMember(name="John Lennon")])
        with self.assertRaises(IntegrityError):
            beatles.members.commit()

        beatles.save()
        beatles.members.commit()  # no error

    def test_save_with_update_fields_selective_commit(self):
        """save(update_fields=[...]) only commits the named child relations,
        leaving the others' in-memory changes uncommitted."""
        beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon"), BandMember(name="Paul McCartney")],
            albums=[
                Album(name="Please Please Me", sort_order=1),
                Album(name="With The Beatles", sort_order=2),
                Album(name="Abbey Road", sort_order=3),
            ],
        )
        beatles.save()

        beatles.members.clear()
        beatles.albums.clear()
        beatles.name = "The Rutles"
        beatles.save(update_fields=["name", "members"])

        updated = Band.objects.get(pk=beatles.pk)
        self.assertEqual("The Rutles", updated.name)
        self.assertEqual(0, updated.members.count())
        self.assertEqual(3, updated.albums.count())  # albums change not committed

    def test_meta_ordering_and_order_by(self):
        """Children are returned in the order declared by the child model's Meta
        ordering, and order_by() supports multiple fields and reversal."""
        beatles = Band(
            name="The Beatles",
            albums=[
                Album(name="Please Please Me", sort_order=2),
                Album(name="With The Beatles", sort_order=1),
                Album(name="Abbey Road", sort_order=2),
            ],
        )
        # default order from Album.Meta.ordering == ["sort_order"]
        self.assertEqual(
            ["With The Beatles", "Please Please Me", "Abbey Road"],
            [a.name for a in beatles.albums.all()],
        )
        self.assertEqual(
            ["With The Beatles", "Abbey Road", "Please Please Me"],
            [a.name for a in beatles.albums.order_by("sort_order", "name")],
        )
        self.assertEqual(
            ["With The Beatles", "Please Please Me", "Abbey Road"],
            [a.name for a in beatles.albums.order_by("sort_order", "-name")],
        )


# ---------------------------------------------------------------------------
# FakeQuerySet field lookups
# ---------------------------------------------------------------------------


class FakeQuerySetLookupTest(TestCase):
    def setUp(self):
        self.beatles = Band(
            name="The Beatles",
            members=[
                BandMember(name="John Lennon"),
                BandMember(name="Paul McCartney"),
            ],
        )

    def test_text_lookups(self):
        """String field lookups (exact/iexact/contains/icontains/startswith/
        endswith and their case-insensitive variants, plus in) filter the
        in-memory recordset correctly."""
        m = self.beatles.members
        self.assertEqual("Paul McCartney", m.filter(name="Paul McCartney")[0].name)
        self.assertEqual("Paul McCartney", m.filter(name__exact="Paul McCartney")[0].name)
        self.assertEqual("Paul McCartney", m.filter(name__iexact="paul mccartNEY")[0].name)
        self.assertEqual(1, m.filter(name__contains="Cart").count())
        self.assertEqual(1, m.filter(name__icontains="carT").count())
        self.assertEqual("Paul McCartney", m.filter(name__startswith="Paul")[0].name)
        self.assertEqual("Paul McCartney", m.filter(name__istartswith="pauL")[0].name)
        self.assertEqual("Paul McCartney", m.filter(name__endswith="ney")[0].name)
        self.assertEqual("Paul McCartney", m.filter(name__iendswith="Ney")[0].name)
        self.assertEqual(
            1, m.filter(name__in=["Paul McCartney", "Linda McCartney"]).count()
        )

    def test_comparison_lookups(self):
        """Ordered comparison lookups (lt/lte/gt/gte) return the expected counts
        and rows for the in-memory recordset."""
        m = self.beatles.members
        self.assertEqual(0, m.filter(name__lt="B").count())
        self.assertEqual(1, m.filter(name__lt="M").count())
        self.assertEqual("John Lennon", m.filter(name__lt="M")[0].name)
        self.assertEqual(2, m.filter(name__lt="Z").count())
        self.assertEqual(2, m.filter(name__lte="Paul McCartney").count())
        self.assertEqual(2, m.filter(name__gt="B").count())
        self.assertEqual("Paul McCartney", m.filter(name__gt="M")[0].name)
        self.assertEqual(0, m.filter(name__gt="Paul McCartney").count())
        self.assertEqual(1, m.filter(name__gte="Paul McCartney").count())
        self.assertEqual(0, m.filter(name__gte="Z").count())

    def test_regex_lookups(self):
        """regex / iregex lookups match against the field value."""
        m = self.beatles.members
        self.assertEqual("John Lennon", m.get(name__regex=r"n{2}").name)
        self.assertEqual("John Lennon", m.get(name__iregex=r"N{2}").name)

    def test_get_exists_first_last_count(self):
        """get() returns a single match and raises the right errors;
        exists()/first()/last()/count() behave like Django's queryset API."""
        m = self.beatles.members
        self.assertEqual("Paul McCartney", m.get(name="Paul McCartney").name)
        with self.assertRaises(BandMember.DoesNotExist):
            m.get(name="Reginald Dwight")
        with self.assertRaises(BandMember.MultipleObjectsReturned):
            m.get()

        self.assertTrue(m.filter(name="Paul McCartney").exists())
        self.assertFalse(m.filter(name="Reginald Dwight").exists())
        self.assertEqual(2, m.count())
        self.assertEqual("John Lennon", m.first().name)
        self.assertEqual("Paul McCartney", m.last().name)

    def test_exclude(self):
        """exclude() returns the complement of the matching set across lookup
        types."""
        m = self.beatles.members
        self.assertEqual(1, m.exclude(name="Paul McCartney").count())
        self.assertEqual("John Lennon", m.exclude(name="Paul McCartney").first().name)
        self.assertEqual("John Lennon", m.exclude(name__contains="Cart").first().name)
        self.assertEqual("John Lennon", m.exclude(name__startswith="Paul").first().name)
        self.assertEqual(
            "Paul McCartney", m.exclude(name__lt="M").first().name
        )

    def test_filter_with_nulls(self):
        """Lookups correctly distinguish empty strings, None and real values;
        isnull selects/deselects rows with a None field."""
        tmbg = Band(
            name="They Might Be Giants",
            albums=[
                Album(name="Flood", release_date=datetime.date(1990, 1, 1)),
                Album(name="John Henry", release_date=datetime.date(1994, 7, 21)),
                Album(name="", release_date=None),
                Album(name=None, release_date=None),
            ],
        )
        self.assertEqual("Flood", tmbg.albums.get(name="Flood").name)
        self.assertEqual("", tmbg.albums.get(name="").name)
        self.assertEqual(None, tmbg.albums.get(name=None).name)
        self.assertEqual("", tmbg.albums.get(name__lt="A").name)
        self.assertEqual("John Henry", tmbg.albums.get(name__gt="J").name)
        self.assertEqual(None, tmbg.albums.get(name__in=[None, "Mink Car"]).name)
        self.assertEqual(1, tmbg.albums.filter(name__isnull=True).count())
        self.assertEqual(3, tmbg.albums.filter(name__isnull=False).count())

    def test_filter_token_name_clash(self):
        """A field literally named like a lookup token (``range``) reached via a
        relation is treated as a field, and rows whose relation is null are
        silently excluded rather than crashing."""
        label = RecordLabel.objects.create(name="Parlophone", range=7)
        beatles = Band(
            name="The Beatles",
            albums=[
                Album(name="Please Please Me", label=label, sort_order=1),
                Album(name="With The Beatles", sort_order=2),
                Album(name="A Hard Day's Night", sort_order=3),
            ],
        )
        self.assertEqual(1, beatles.albums.filter(label__range=7).count())
        self.assertEqual(2, beatles.albums.exclude(label__range=7).count())


# ---------------------------------------------------------------------------
# FakeQuerySet relational lookups / Q objects / ordering
# ---------------------------------------------------------------------------


class FakeQuerySetRelationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gordon_ramsay = Chef.objects.create(name="Gordon Ramsay")
        cls.strawberry_fields = Restaurant.objects.create(
            name="Strawberry Fields", proprietor=cls.gordon_ramsay
        )
        cls.marco = Chef.objects.create(name="Marco Pierre White")
        cls.yellow_submarine = Restaurant.objects.create(
            name="The Yellow Submarine", proprietor=cls.marco
        )

    def _band(self):
        return Band(
            name="The Beatles",
            members=[
                BandMember(name="John Lennon", favourite_restaurant=self.strawberry_fields),
                BandMember(name="Ringo Starr", favourite_restaurant=self.yellow_submarine),
            ],
        )

    def test_filter_across_foreignkeys(self):
        """Filters spanning one and two foreign-key hops (with both exact and
        alternative lookups, and direct instance comparison) select the right
        children."""
        band = self._band()
        john = band.members.get(name="John Lennon")
        ringo = band.members.get(name="Ringo Starr")
        self.assertEqual(
            (john,),
            tuple(band.members.filter(favourite_restaurant__name="Strawberry Fields")),
        )
        self.assertEqual(
            (ringo,),
            tuple(band.members.filter(favourite_restaurant__name__icontains="yello")),
        )
        self.assertEqual(
            (john,),
            tuple(
                band.members.filter(
                    favourite_restaurant__proprietor__name="Gordon Ramsay"
                )
            ),
        )
        self.assertEqual(
            (ringo,),
            tuple(band.members.filter(favourite_restaurant__proprietor=self.marco)),
        )

    def test_filter_matches_models_by_id_not_reference(self):
        """Filtering on a model-valued field matches saved instances by pk (so a
        reloaded parent matches) while keeping distinct unsaved instances apart."""
        beatles = Band(
            name="The Beatles",
            members=[BandMember(id=1, name="John"), BandMember(id=2, name="Paul")],
        )
        self.assertEqual(2, beatles.members.filter(band=beatles).count())
        rutles = Band(name="The Rutles")
        self.assertEqual(0, beatles.members.filter(band=rutles).count())

        beatles.save()
        beatles.members.add(BandMember(id=3, name="George"))
        also_beatles = Band.objects.get(id=beatles.id)
        self.assertEqual(3, beatles.members.filter(band=also_beatles).count())

    def test_filter_matching_respects_inheritance(self):
        """Comparing a related field against a less- or more-specific instance in
        a multi-table-inheritance hierarchy matches when one is a subclass of
        the other."""
        john = BandMember(name="John Lennon", favourite_restaurant=self.strawberry_fields)
        beatles = Band(name="The Beatles", members=[john])
        place = Place.objects.get(name="Strawberry Fields")
        self.assertEqual(
            [john], list(beatles.members.filter(favourite_restaurant=place))
        )

    def test_filter_via_reverse_foreignkey(self):
        """A child can be filtered via the reverse accessor back to its parent."""
        band = self._band()
        self.assertEqual(
            tuple(band.members.all()),
            tuple(band.members.filter(band__name="The Beatles")),
        )
        self.assertEqual((), tuple(band.members.filter(band__name="The Monkeys")))

    def test_filter_with_q_objects(self):
        """Q-object filters combine with AND / OR / XOR / negation semantics."""
        band = self._band()
        john = band.members.get(name="John Lennon")
        ringo = band.members.get(name="Ringo Starr")
        self.assertEqual(
            (john, ringo),
            tuple(
                band.members.filter(
                    Q(name="John Lennon")
                    | Q(favourite_restaurant__name="The Yellow Submarine")
                )
            ),
        )
        self.assertEqual(
            (john,),
            tuple(
                band.members.filter(
                    Q(name="John Lennon")
                    & ~Q(favourite_restaurant__name="The Yellow Submarine")
                )
            ),
        )
        self.assertEqual(
            (john, ringo),
            tuple(
                band.members.filter(
                    Q(name="John Lennon")
                    ^ Q(favourite_restaurant__name="The Yellow Submarine")
                )
            ),
        )

    def test_order_by_across_foreignkeys(self):
        """order_by() can sort across related fields, in forward and reverse
        direction."""
        band = self._band()
        john = band.members.get(name="John Lennon")
        ringo = band.members.get(name="Ringo Starr")
        self.assertEqual(
            (john, ringo), tuple(band.members.order_by("favourite_restaurant__name"))
        )
        self.assertEqual(
            (ringo, john), tuple(band.members.order_by("-favourite_restaurant__name"))
        )

    def test_random_ordering(self):
        """order_by('?') returns all rows in some order."""
        beatles = Band(
            name="The Beatles",
            members=[BandMember(name=n) for n in ["John", "Paul", "George", "Ringo"]],
        )
        self.assertCountEqual(
            [m.name for m in beatles.members.order_by("?")],
            ["John", "Paul", "George", "Ringo"],
        )

    def test_manytomany_traversal_raises(self):
        """Filtering across a many-to-many relationship is unsupported and raises
        ManyToManyTraversalError."""
        bay_window = Feature.objects.create(name="Bay window", desirability=6)
        living_room = Room.objects.create(name="Living room", features=[bay_window])
        house = House.objects.create(name="House", address="1 Road", main_room=living_room)
        tenant = Person(name="Alex", houses=[house])
        with self.assertRaises(ManyToManyTraversalError):
            tenant.houses.filter(main_room__features__name="Bay window")


# ---------------------------------------------------------------------------
# FakeQuerySet output shaping: values / values_list / distinct / none
# ---------------------------------------------------------------------------


class FakeQuerySetShapeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gordon = Chef.objects.create(name="Gordon Ramsay")
        cls.strawberry = Restaurant.objects.create(
            name="Strawberry Fields", proprietor=cls.gordon
        )

    def _band(self):
        return Band(
            name="The Beatles",
            members=[
                BandMember(name="John Lennon", favourite_restaurant=self.strawberry),
                BandMember(name="George Harrison"),
            ],
        )

    def test_values(self):
        """values() returns dicts of all or selected fields, can span relations,
        and get()/first()/last() return dicts."""
        band = self._band()
        self.assertEqual(
            [{"name": "John Lennon"}],
            list(band.members.filter(name="John Lennon").values("name")),
        )
        self.assertEqual(
            [
                {"name": "John Lennon", "favourite_restaurant__proprietor__name": "Gordon Ramsay"},
                {"name": "George Harrison", "favourite_restaurant__proprietor__name": None},
            ],
            list(band.members.all().values("name", "favourite_restaurant__proprietor__name")),
        )
        self.assertEqual(
            {"name": "John Lennon"},
            band.members.filter(name="John Lennon").values("name").get(),
        )

    def test_values_list(self):
        """values_list() returns tuples (or flat values with flat=True), can span
        relations, and get()/first()/last() return tuples."""
        band = self._band()
        self.assertEqual(
            [("John Lennon",)],
            list(band.members.filter(name="John Lennon").values_list("name")),
        )
        self.assertEqual(
            ["John Lennon"],
            list(band.members.filter(name="John Lennon").values_list("name", flat=True)),
        )
        self.assertEqual(
            [("John Lennon", "Gordon Ramsay"), ("George Harrison", None)],
            list(band.members.all().values_list("name", "favourite_restaurant__proprietor__name")),
        )
        self.assertEqual(
            ("John Lennon",),
            band.members.filter(name="John Lennon").values_list("name").first(),
        )

    def test_values_list_flat_multiple_fields_raises(self):
        """values_list(flat=True) with more than one field raises TypeError."""
        band = self._band()
        with self.assertRaises(TypeError):
            band.members.values_list("name", "id", flat=True)

    def test_ordering_after_values_puts_none_first(self):
        """Ordering by a related field after values()/values_list() works and
        sorts rows with a None value first."""
        band = self._band()
        rows = band.members.all().values("name", "favourite_restaurant__proprietor__name")
        self.assertEqual(
            [
                {"name": "George Harrison", "favourite_restaurant__proprietor__name": None},
                {"name": "John Lennon", "favourite_restaurant__proprietor__name": "Gordon Ramsay"},
            ],
            list(rows.order_by("favourite_restaurant__proprietor__name")),
        )

    def test_distinct(self):
        """distinct() collapses duplicate rows, optionally restricted to given
        fields."""
        beatles = Band(
            name="The Beatles",
            albums=[
                Album(name="Please Please Me", sort_order=1),
                Album(name="With The Beatles", sort_order=2),
                Album(name="Abbey Road", sort_order=2),
            ],
        )
        self.assertEqual(
            ["Please Please Me", "With The Beatles"],
            [a.name for a in beatles.albums.order_by("sort_order").distinct("sort_order")],
        )
        self.assertEqual(
            3, beatles.albums.order_by("sort_order").distinct("name").count()
        )

    def test_none_is_empty_and_chainable(self):
        """none() returns an empty queryset that stays empty under further
        filtering/ordering."""
        beatles = Band(
            name="The Beatles",
            albums=[Album(name="Please Please Me", sort_order=1)],
        )
        self.assertEqual([], list(beatles.albums.none()))
        self.assertEqual(0, beatles.albums.none().count())
        self.assertEqual([], list(beatles.albums.none().filter(name="Please Please Me")))
        self.assertEqual([], list(beatles.albums.none().order_by("name")))


# ---------------------------------------------------------------------------
# Date / datetime derivative lookups
# ---------------------------------------------------------------------------


class DateFilterTest(TestCase):
    def _logs(self):
        return FakeQuerySet(
            Log,
            [
                Log(time=datetime.datetime(1979, 7, 1, 1, 1, 1), data="nobody died"),
                Log(time=datetime.datetime(1980, 2, 2, 2, 2, 2), data="one person died"),
                Log(time=None, data="nothing happened"),
            ],
        )

    def test_date_field_derivative_filters(self):
        """DateField lookups (range / year / month / day / week / quarter etc.)
        derive the right component from in-memory date values."""
        tmbg = Band(
            name="They Might Be Giants",
            albums=[
                Album(name="Flood", release_date=datetime.date(1990, 1, 1)),
                Album(name="John Henry", release_date=datetime.date(1994, 7, 21)),
                Album(name="The Complete Dial-A-Song", release_date=None),
            ],
        )
        self.assertEqual(
            "John Henry",
            tmbg.albums.get(
                release_date__range=(datetime.date(1994, 1, 1), datetime.date(1994, 12, 31))
            ).name,
        )
        self.assertEqual("John Henry", tmbg.albums.get(release_date__year="1994").name)
        self.assertEqual("John Henry", tmbg.albums.get(release_date__month=7).name)
        self.assertEqual("John Henry", tmbg.albums.get(release_date__day="21").name)
        self.assertEqual("John Henry", tmbg.albums.get(release_date__week=29).name)
        self.assertEqual("John Henry", tmbg.albums.get(release_date__quarter=3).name)

    def test_datetime_field_derivative_filters(self):
        """DateTimeField lookups expose date/time plus the time components
        (hour/minute/second) and the date components on in-memory datetimes."""
        logs = self._logs()
        self.assertEqual(
            "one person died", logs.get(time__date=datetime.date(1980, 2, 2)).data
        )
        self.assertEqual("one person died", logs.get(time__time=datetime.time(2, 2, 2)).data)
        self.assertEqual("one person died", logs.get(time__year=1980).data)
        self.assertEqual("one person died", logs.get(time__hour=2).data)
        self.assertEqual("one person died", logs.get(time__minute="2").data)
        self.assertEqual("one person died", logs.get(time__second=2).data)
        self.assertEqual("one person died", logs.get(time__week_day=7).data)
        self.assertEqual("one person died", logs.get(time__iso_week_day=6).data)

    def test_datetime_derivatives_via_values(self):
        """The same datetime derivatives are exposed through values()/values_list()
        projections, including None passthrough for null datetimes."""
        logs = self._logs()
        self.assertEqual(
            [
                {"time__date": datetime.date(1979, 7, 1), "time__time": datetime.time(1, 1, 1)},
                {"time__date": datetime.date(1980, 2, 2), "time__time": datetime.time(2, 2, 2)},
                {"time__date": None, "time__time": None},
            ],
            list(logs.all().values("time__date", "time__time")),
        )
        self.assertEqual(
            [
                (1979, 7, 1, 1, 1, 1),
                (1980, 2, 2, 2, 2, 2),
                (None, None, None, None, None, None),
            ],
            list(
                logs.all().values_list(
                    "time__year",
                    "time__month",
                    "time__day",
                    "time__hour",
                    "time__minute",
                    "time__second",
                )
            ),
        )
        self.assertEqual(
            [
                (26, 1, 7, 3),
                (5, 7, 6, 1),
                (None, None, None, None),
            ],
            list(
                logs.all().values_list(
                    "time__week", "time__week_day", "time__iso_week_day", "time__quarter"
                )
            ),
        )


# ---------------------------------------------------------------------------
# ParentalManyToManyField
# ---------------------------------------------------------------------------


class ParentalM2MTest(TestCase):
    def setUp(self):
        self.author_1 = Author.objects.create(name="Author 1")
        self.author_2 = Author.objects.create(name="Author 2")
        self.category_1 = Category.objects.create(name="Category 1")
        self.category_2 = Category.objects.create(name="Category 2")
        self.article = Article(title="Test Title")
        self.article.authors = [self.author_1, self.author_2]
        self.article.categories = [self.category_1, self.category_2]

    def test_m2m_lifecycle(self):
        """A parental m2m relation supports add/remove/clear/set in memory and
        round-trips through the database on save()."""
        self.assertFalse(Article.objects.filter(title="Test Title").exists())
        self.assertEqual(2, self.article.authors.count())

        author_3 = Author.objects.create(name="Author 3")
        self.article.authors.add(author_3)
        self.assertEqual(3, self.article.authors.count())
        self.article.authors.remove(author_3)
        self.assertEqual(2, self.article.authors.count())
        self.article.authors.clear()
        self.assertEqual(0, self.article.authors.count())
        self.article.authors.set([self.author_2])
        self.assertEqual(["Author 2"], [a.name for a in self.article.authors.all()])

        self.article.authors = [self.author_1, self.author_2]
        self.article.save()
        reloaded = Article.objects.get(title="Test Title")
        self.assertEqual(
            ["Author 1", "Author 2"],
            [a.name for a in reloaded.authors.order_by("name")],
        )

    def test_m2m_uninitialised_and_model_property(self):
        """An m2m relation on a freshly built instance reads as empty and exposes
        a ``model`` attribute pointing at the target model."""
        fresh = Article(title="Fresh")
        self.assertEqual([], list(fresh.authors.all()))
        self.assertEqual(0, fresh.authors.count())
        self.assertEqual(Author, fresh.authors.model)

    def test_m2m_respects_target_ordering(self):
        """The fake queryset for a parental m2m respects the target model's Meta
        ordering."""
        authors = [
            Author.objects.create(name=n)
            for n in ["Janis", "William", "Bela", "Simon", "Graham"]
        ]
        article = Article(title="Ordered")
        article.authors = authors
        self.assertEqual(
            ["Bela", "Graham", "Janis", "Simon", "William"],
            [a.name for a in article.authors.all()],
        )

    def test_m2m_add_requires_saved_target(self):
        """Adding an unsaved object to a parental m2m raises ValueError (the
        related objects must already exist in the database)."""
        with self.assertRaises(ValueError):
            self.article.authors.add(Author(name="Unsaved"))

    def test_m2m_save_with_update_fields(self):
        """save(update_fields=[...]) commits only the named parental-m2m field."""
        self.article.save()
        self.article.authors.clear()
        self.article.categories.clear()
        self.article.title = "Updated title"
        self.article.save(update_fields=["title", "authors"])

        updated = Article.objects.get(pk=self.article.pk)
        self.assertEqual("Updated title", updated.title)
        self.assertEqual(0, updated.authors.count())
        self.assertEqual(2, updated.categories.count())

    def test_reverse_m2m(self):
        """The reverse accessor of a parental m2m only reflects saved parents and
        supports the queryset API."""
        self.assertEqual(0, self.author_1.articles_by_author.count())
        self.article.save()
        self.assertEqual(1, self.author_1.articles_by_author.count())
        self.assertEqual(self.article, self.author_1.articles_by_author.get())

    def test_value_from_object_includes_unsaved(self):
        """ParentalManyToManyField.value_from_object returns the in-memory
        relation even before the parent is saved."""
        authors_field = Article._meta.get_field("authors")
        self.assertEqual(
            {self.author_1, self.author_2},
            set(authors_field.value_from_object(self.article)),
        )


# ---------------------------------------------------------------------------
# Introspection helpers + ParentalKey system checks
# ---------------------------------------------------------------------------


class IntrospectionAndChecksTest(TestCase):
    def test_get_all_child_relations_includes_superclass(self):
        """get_all_child_relations finds ParentalKey relations declared on the
        model and its ancestors."""
        self.assertEqual(
            {"tagged_items", "reviews", "menu_items"},
            {rel.name for rel in get_all_child_relations(Restaurant)},
        )

    def test_get_all_child_m2m_relations(self):
        """get_all_child_m2m_relations lists the ParentalManyToManyFields on a
        model."""
        names = {f.name for f in get_all_child_m2m_relations(Article)}
        self.assertEqual({"authors", "categories", "related_articles"}, names)

    def test_parental_key_must_point_to_clusterable_model(self):
        """A ParentalKey targeting a non-ClusterableModel reports system check
        modelcluster.E001."""
        from django.db import models

        class Instrument(models.Model):
            member = ParentalKey(BandMember, on_delete=models.CASCADE)

            class Meta:
                app_label = "tests_app"
                abstract = True

        errors = Instrument.check()
        self.assertEqual(1, len(errors))
        self.assertEqual("modelcluster.E001", errors[0].id)
        self.assertEqual(
            "ParentalKey must point to a subclass of ClusterableModel.", errors[0].msg
        )

    def test_parental_key_related_name_cannot_be_plus(self):
        """A ParentalKey with related_name='+' reports system check
        modelcluster.E002."""
        from django.db import models

        class Instrument(models.Model):
            band = ParentalKey(Band, related_name="+", on_delete=models.CASCADE)

            class Meta:
                app_label = "tests_app"
                abstract = True

        errors = Instrument.check()
        self.assertEqual(1, len(errors))
        self.assertEqual("modelcluster.E002", errors[0].id)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class SerializeTest(TestCase):
    def test_serializable_data_nests_children(self):
        """serializable_data() produces a nested dict including child relations,
        with pk None for unsaved objects."""
        beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon"), BandMember(name="Paul McCartney")],
        )
        expected = {
            "pk": None,
            "albums": [],
            "name": "The Beatles",
            "members": [
                {"pk": None, "name": "John Lennon", "band": None, "favourite_restaurant": None},
                {"pk": None, "name": "Paul McCartney", "band": None, "favourite_restaurant": None},
            ],
        }
        self.assertEqual(expected, beatles.serializable_data())

    def test_json_roundtrip_with_dates(self):
        """to_json()/from_json() round-trips a cluster including date values."""
        beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon")],
            albums=[Album(name="Rubber Soul", release_date=datetime.date(1965, 12, 3))],
        )
        beatles_json = beatles.to_json()
        self.assertIn("1965-12-03", beatles_json)
        unpacked = Band.from_json(beatles_json)
        self.assertEqual(datetime.date(1965, 12, 3), unpacked.albums.all()[0].release_date)

    def test_deserialize_sets_pk_and_children(self):
        """from_serializable_data builds the parent (with its pk) and rebuilds the
        child relation."""
        beatles = Band.from_serializable_data(
            {
                "pk": 9,
                "albums": [],
                "name": "The Beatles",
                "members": [
                    {"pk": None, "name": "John Lennon", "band": None},
                    {"pk": None, "name": "Paul McCartney", "band": None},
                ],
            }
        )
        self.assertEqual(9, beatles.id)
        self.assertEqual(2, beatles.members.count())
        self.assertEqual(BandMember, beatles.members.all()[0].__class__)

    def test_serialize_and_deserialize_m2m(self):
        """Parental m2m relations serialize as lists of pks and deserialize back
        into the relation."""
        authors = [Author.objects.create(name="Author %d" % i) for i in range(1, 4)]
        article = Article(title="A", authors=authors[:2])
        data = article.serializable_data()
        self.assertIn(authors[0].pk, data["authors"])
        self.assertEqual([], data["categories"])

        rebuilt = Article.from_serializable_data(
            {"pk": 1, "title": "A", "authors": [authors[0].pk, authors[1].pk]}
        )
        self.assertEqual(2, rebuilt.authors.count())

    def test_multi_table_inheritance_serialization(self):
        """Serialization of a multi-table-inheritance model captures subclass
        fields and child relations, and deserialization populates the pointer
        ids up the inheritance chain."""
        fat_duck = Restaurant(
            name="The Fat Duck",
            serves_hot_dogs=False,
            reviews=[Review(author="Michael Winner", body="Rubbish.")],
        )
        data = json.loads(fat_duck.to_json())
        self.assertEqual("The Fat Duck", data["name"])
        self.assertEqual(False, data["serves_hot_dogs"])
        self.assertEqual("Michael Winner", data["reviews"][0]["author"])

        oyster = SeafoodRestaurant.from_json('{"pk": 43, "name": "The Oyster Club"}')
        self.assertEqual(43, oyster.id)
        self.assertEqual(43, oyster.restaurant_ptr_id)
        self.assertEqual(43, oyster.place_ptr_id)

    def test_dangling_foreign_keys_on_deserialize(self):
        """On deserialization, a foreign key whose target has been deleted is
        nullified (SET_NULL) or drops the child (CASCADE) according to
        on_delete."""
        from tests_app.models import Dish, MenuItem, Wine

        heston = Chef.objects.create(name="Heston Blumenthal")
        dish = Dish.objects.create(name="Snail ice cream")
        wine = Wine.objects.create(name="Chateauneuf")
        fat_duck = Restaurant(
            name="The Fat Duck",
            proprietor=heston,
            menu_items=[MenuItem(dish=dish, price="20.00", recommended_wine=wine)],
        )
        fat_duck_json = fat_duck.to_json()

        heston.delete()
        rebuilt = Restaurant.from_json(fat_duck_json)
        self.assertIsNone(rebuilt.proprietor)  # SET_NULL on base object

        wine.delete()
        rebuilt = Restaurant.from_json(fat_duck_json)
        self.assertIsNone(rebuilt.menu_items.all()[0].recommended_wine)  # SET_NULL

        dish.delete()
        rebuilt = Restaurant.from_json(fat_duck_json)
        self.assertEqual(0, rebuilt.menu_items.count())  # CASCADE drops child

    def test_deserialize_applies_sort_order(self):
        """Children deserialized from JSON are ordered per the child model's Meta
        ordering."""
        beatles = Band.from_json(
            '{"pk": null, "albums": ['
            '{"pk": null, "name": "With The Beatles", "sort_order": 2}, '
            '{"pk": null, "name": "Please Please Me", "sort_order": 1}], '
            '"name": "The Beatles", "members": []}'
        )
        self.assertEqual("Please Please Me", beatles.albums.all()[0].name)
        self.assertEqual("With The Beatles", beatles.albums.all()[1].name)

    def test_naive_and_aware_datetimes_serialize_as_utc(self):
        """Naive datetimes are interpreted in the local zone and stored as UTC;
        aware datetimes are converted to UTC; deserialization restores the local
        zone."""
        naive = datetime.datetime(2014, 8, 1, 11, 1, 42)
        log = Log(time=naive, data="release")
        self.assertEqual("2014-08-01T16:01:42Z", json.loads(log.to_json())["time"])

        aware = timezone.make_aware(naive, timezone.get_fixed_timezone(-60))
        log = Log(time=aware, data="release")
        self.assertEqual("2014-08-01T12:01:42Z", json.loads(log.to_json())["time"])

        restored = Log.from_json('{"data": "release", "time": "2014-08-01T16:01:42Z", "pk": null}')
        expected = timezone.make_aware(naive, timezone.get_default_timezone())
        self.assertEqual(expected, restored.time)

    def test_null_datetime_serialization(self):
        """A null datetime serializes to null and deserializes back to None."""
        self.assertIsNone(json.loads(Log(time=None, data="x").to_json())["time"])
        self.assertIsNone(Log.from_json('{"data": "x", "time": null, "pk": null}').time)

    def test_file_field_serialization_roundtrip(self):
        """FileField contents survive a to_json()/from_json() round-trip."""
        doc = Document(title="Hello")
        doc.file = SimpleUploadedFile("hello.txt", b"Hello world")
        new_doc = Document.from_json(doc.to_json())
        self.assertEqual(b"Hello world", new_doc.file.read())

    def test_fields_marked_not_serializable_are_ignored(self):
        """Fields declared with serialize=False are omitted from serialized data
        and left untouched across a save/restore cycle."""
        orwell = Author.objects.create(name="George Orwell")
        rel_article = Article(title="Related", authors=[orwell])
        rel_article.save()
        article = Article(
            title="Main", authors=[orwell], related_articles=[rel_article], view_count=123
        )
        data = article.serializable_data()
        self.assertNotIn("related_articles", data)
        self.assertNotIn("view_count", data)

        rel_article.save()
        article.save()
        restored = Article.from_json(article.to_json())
        restored.save()
        restored = Article.objects.get(pk=restored.pk)
        self.assertIn(rel_article, restored.related_articles.all())


# ---------------------------------------------------------------------------
# copy_cluster / copy_child_relation / copy_all_child_relations
# ---------------------------------------------------------------------------


class CopyClusterTest(TestCase):
    def test_copy_cluster_deep_copies_children(self):
        """copy_cluster() returns an unsaved deep copy whose children carry the
        same data but fresh primary keys, plus a child-object map."""
        band_members_rel = {
            rel.related_model: rel for rel in get_all_child_relations(Band)
        }[BandMember]

        beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon"), BandMember(name="Paul McCartney")],
        )
        beatles.save()

        copy, child_object_map = beatles.copy_cluster()
        self.assertIsNone(copy.pk)
        copy.save()

        self.assertEqual(
            [m.name for m in beatles.members.all()],
            [m.name for m in copy.members.all()],
        )
        self.assertNotEqual(beatles.pk, copy.pk)
        self.assertNotEqual(
            [m.pk for m in beatles.members.all()],
            [m.pk for m in copy.members.all()],
        )
        old_john = beatles.members.get(name="John Lennon")
        new_john = copy.members.get(name="John Lennon")
        self.assertEqual(new_john, child_object_map[(band_members_rel, old_john.pk)])

    def test_copy_cluster_copies_parental_m2m(self):
        """copy_cluster() carries parental m2m relations onto the copy."""
        author = Author.objects.create(name="Author 1")
        category = Category.objects.create(name="Category 1")
        article = Article(title="T", authors=[author], categories=[category])
        article.save()

        copy, child_object_map = article.copy_cluster()
        copy.save()
        self.assertEqual(
            [a.name for a in article.authors.all()],
            [a.name for a in copy.authors.all()],
        )
        self.assertEqual({}, child_object_map)

    def test_copy_cluster_recursive(self):
        """copy_cluster() recurses into clusterable children, giving nested
        grandchildren fresh primary keys."""
        old_album = Album(
            name="Please Please Me",
            songs=[Song(name="I Saw Her Standing There"), Song(name="Love Me Do")],
        )
        beatles = Band(name="The Beatles", albums=[old_album])
        beatles.save()

        clone, _ = beatles.copy_cluster()
        new_album = clone.albums.get(name="Please Please Me")
        new_song = new_album.songs.get(name="I Saw Her Standing There")
        old_song = old_album.songs.get(name="I Saw Her Standing There")
        self.assertNotEqual(old_song.pk, new_song.pk)


class CopyChildRelationsTest(TestCase):
    def setUp(self):
        self.band_members_rel = {
            rel.related_model: rel for rel in get_all_child_relations(Band)
        }[BandMember]
        self.beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon"), BandMember(name="Paul McCartney")],
        )

    def test_copy_child_relation_from_unsaved_source(self):
        """copy_child_relation() from an unsaved source produces unsaved children
        on the target (back-referenced to it), grouped under a None pk key."""
        clone = Band(name="Comeback")
        mapping = self.beatles.copy_child_relation("members", clone)
        new_john = clone.members.get(name="John Lennon")
        self.assertIsNone(new_john.pk)
        self.assertEqual(clone, new_john.band)
        self.assertEqual(2, len(mapping[(self.band_members_rel, None)]))

    def test_copy_child_relation_from_saved_source_maps_by_pk(self):
        """copy_child_relation() from a saved source keys the returned mapping by
        each source child's primary key."""
        self.beatles.save()
        john = self.beatles.members.get(name="John Lennon")
        clone = Band(name="Comeback")
        mapping = self.beatles.copy_child_relation("members", clone)
        new_john = clone.members.get(name="John Lennon")
        self.assertEqual(new_john, mapping[(self.band_members_rel, john.pk)])

    def test_copy_child_relation_overwrite_vs_append(self):
        """By default copy_child_relation() overwrites the target relation;
        append=True keeps the target's existing children."""
        self.beatles.save()
        clone = Band(name="Comeback")
        clone.members.add(BandMember(name="Julian Lennon"))
        clone.save()

        self.beatles.copy_child_relation("members", clone)
        self.assertFalse(clone.members.filter(name="Julian Lennon").exists())

        clone2 = Band(name="Comeback 2")
        clone2.members.add(BandMember(name="Julian Lennon"))
        clone2.save()
        self.beatles.copy_child_relation("members", clone2, append=True)
        self.assertTrue(clone2.members.filter(name="Julian Lennon").exists())
        self.assertTrue(clone2.members.filter(name="John Lennon").exists())

    def test_copy_child_relation_commit_requires_saved_target(self):
        """copy_child_relation(commit=True) saves children immediately, but
        raises IntegrityError if the target is unsaved."""
        self.beatles.save()
        unsaved_target = Band(name="Comeback")
        with self.assertRaises(IntegrityError):
            self.beatles.copy_child_relation("members", unsaved_target, commit=True)

        saved_target = Band(name="Comeback saved")
        saved_target.save()
        self.beatles.copy_child_relation("members", saved_target, commit=True)
        self.assertIsNotNone(saved_target.members.get(name="John Lennon").pk)

    def test_copy_all_child_relations_with_exclude(self):
        """copy_all_child_relations() copies every child relation onto the target
        except those named in ``exclude``."""
        self.beatles.albums = [Album(name="Abbey Road", sort_order=1)]
        clone = Band(name="Comeback")
        self.beatles.copy_all_child_relations(clone, exclude=["albums"])
        self.assertEqual(2, clone.members.count())
        self.assertFalse(clone.albums.exists())


# ---------------------------------------------------------------------------
# Transient and child formsets
# ---------------------------------------------------------------------------


class FormsetTest(TestCase):
    def test_transient_formset_accepts_unsaved_queryset(self):
        """transientmodelformset_factory builds a formset over an unsaved child
        relation and parses submitted data without writing to the database."""
        Formset = transientmodelformset_factory(
            BandMember, exclude=["band"], extra=3, can_delete=True
        )
        beatles = Band(name="The Beatles", members=[BandMember(name="George Harrison")])
        formset = Formset(
            {
                "form-TOTAL_FORMS": 3,
                "form-INITIAL_FORMS": 1,
                "form-MAX_NUM_FORMS": 1000,
                "form-0-name": "John Lennon",
                "form-0-id": "",
                "form-1-name": "Paul McCartney",
                "form-1-id": "",
                "form-2-name": "",
                "form-2-id": "",
            },
            queryset=beatles.members.all(),
        )
        self.assertTrue(formset.is_valid())
        members = formset.save(commit=False)
        self.assertEqual(2, len(members))
        self.assertEqual("John Lennon", members[0].name)
        self.assertFalse(BandMember.objects.filter(name="John Lennon").exists())

    def test_child_formset_create_and_count(self):
        """childformset_factory exposes initial children plus ``extra`` blank
        forms, and an empty instance yields only the extras."""
        BandMembersFormset = childformset_factory(Band, BandMember, extra=3)
        beatles = Band(
            name="The Beatles",
            members=[BandMember(name="John Lennon"), BandMember(name="Paul McCartney")],
        )
        formset = BandMembersFormset(instance=beatles)
        self.assertEqual(5, len(formset.forms))
        self.assertEqual("John Lennon", formset.forms[0].instance.name)
        self.assertEqual(3, len(BandMembersFormset().forms))

    def test_child_formset_save_defers_then_commits(self):
        """Saving a child formset with commit=False stages adds/edits/deletes in
        memory; the parent relation commit() then applies them to the database."""
        john = BandMember(name="John Lennon")
        ringo = BandMember(name="Richard Starkey")
        beatles = Band(name="The Beatles", members=[john, ringo])
        beatles.save()
        john_id, ringo_id = john.id, ringo.id

        BandMembersFormset = childformset_factory(Band, BandMember, extra=3)
        formset = BandMembersFormset(
            {
                "form-TOTAL_FORMS": 4,
                "form-INITIAL_FORMS": 2,
                "form-MAX_NUM_FORMS": 1000,
                "form-0-name": "John Lennon",
                "form-0-DELETE": "form-0-DELETE",
                "form-0-id": john_id,
                "form-1-name": "Ringo Starr",  # edit existing
                "form-1-id": ringo_id,
                "form-2-name": "George Harrison",  # add
                "form-2-id": "",
                "form-3-name": "",
                "form-3-id": "",
            },
            instance=beatles,
        )
        self.assertTrue(formset.is_valid())
        formset.save(commit=False)
        # database unchanged until commit()
        self.assertEqual("Richard Starkey", BandMember.objects.get(id=ringo_id).name)

        beatles.members.commit()
        self.assertEqual("Ringo Starr", BandMember.objects.get(id=ringo_id).name)
        self.assertTrue(BandMember.objects.filter(name="George Harrison").exists())
        self.assertFalse(BandMember.objects.filter(id=john_id).exists())

    def test_child_formset_max_and_min_num_validation(self):
        """childformset_factory enforces max_num/min_num only when
        validate_max/validate_min are set."""
        TooMany = childformset_factory(Band, BandMember, max_num=2, validate_max=True)
        formset = TooMany(
            {
                "form-TOTAL_FORMS": 3,
                "form-INITIAL_FORMS": 1,
                "form-MAX_NUM_FORMS": 1000,
                "form-0-name": "John",
                "form-0-id": "",
                "form-1-name": "Paul",
                "form-1-id": "",
                "form-2-name": "Ringo",
                "form-2-id": "",
            }
        )
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            "too_many_forms", formset.non_form_errors().as_data()[0].code
        )

        Lenient = childformset_factory(Band, BandMember, max_num=2)
        lenient = Lenient(
            {
                "form-TOTAL_FORMS": 3,
                "form-INITIAL_FORMS": 1,
                "form-MAX_NUM_FORMS": 1000,
                "form-0-name": "John",
                "form-0-id": "",
                "form-1-name": "Paul",
                "form-1-id": "",
                "form-2-name": "Ringo",
                "form-2-id": "",
            }
        )
        self.assertTrue(lenient.is_valid())

    def test_child_formset_with_parental_m2m(self):
        """A child formset whose child model carries a parental m2m defers the
        m2m change until commit=True."""
        joyce = Author.objects.create(name="James Joyce")
        dickens = Author.objects.create(name="Charles Dickens")
        paper = NewsPaper.objects.create(title="the daily record")
        article = Article.objects.create(paper=paper, title="Test article", authors=[joyce])

        ArticleFormset = childformset_factory(
            NewsPaper, Article, exclude=["categories", "tags"], extra=3
        )
        formset = ArticleFormset(
            {
                "form-TOTAL_FORMS": 1,
                "form-INITIAL_FORMS": 1,
                "form-MAX_NUM_FORMS": 10,
                "form-0-id": article.id,
                "form-0-title": article.title,
                "form-0-authors": [joyce.id, dickens.id],
            },
            instance=paper,
        )
        self.assertTrue(formset.is_valid())
        formset.save(commit=True)
        db_article = Article.objects.get(id=article.id)
        self.assertIn(joyce, db_article.authors.all())
        self.assertIn(dickens, db_article.authors.all())

    def test_ordered_formset_assigns_sort_order(self):
        """A formset with can_order assigns the model's sort_order_field from the
        submitted ORDER values."""
        AlbumsFormset = childformset_factory(Band, Album, extra=3, can_order=True)
        beatles = Band(name="The Beatles")
        formset = AlbumsFormset(
            {
                "form-TOTAL_FORMS": 2,
                "form-INITIAL_FORMS": 0,
                "form-MAX_NUM_FORMS": 1000,
                "form-0-name": "With The Beatles",
                "form-0-id": "",
                "form-0-ORDER": "2",
                "form-1-name": "Please Please Me",
                "form-1-id": "",
                "form-1-ORDER": "1",
            },
            instance=beatles,
        )
        self.assertTrue(formset.is_valid())
        formset.save(commit=False)
        self.assertEqual(
            ["Please Please Me", "With The Beatles"],
            [a.name for a in beatles.albums.all()],
        )

    def test_nested_child_formset(self):
        """A child formset whose form is a ClusterForm exposes nested grandchild
        formsets."""
        beatles = Band(
            name="The Beatles",
            albums=[
                Album(
                    name="Please Please Me",
                    songs=[Song(name="I Saw Her Standing There"), Song(name="Misery")],
                )
            ],
        )
        AlbumsFormset = childformset_factory(
            Band, Album, form=ClusterForm, formsets=["songs"], extra=3
        )
        formset = AlbumsFormset(instance=beatles)
        self.assertEqual(4, len(formset.forms))
        self.assertEqual(5, len(formset.forms[0].formsets["songs"].forms))


# ---------------------------------------------------------------------------
# ClusterForm
# ---------------------------------------------------------------------------


class ClusterFormTest(TestCase):
    def test_formsets_built_from_meta(self):
        """ClusterForm only builds the child formsets named (or not excluded) in
        Meta, and renders their fields."""
        class WithFormsets(ClusterForm):
            class Meta:
                model = Band
                fields = ["name"]
                formsets = ["members", "albums"]

        class NoFormsets(ClusterForm):
            class Meta:
                model = Band
                fields = ["name"]

        self.assertTrue(WithFormsets.formsets)
        self.assertFalse(NoFormsets.formsets)
        beatles = Band(name="The Beatles", members=[BandMember(name="John Lennon")])
        form = WithFormsets(instance=beatles)
        self.assertEqual(4, len(form.formsets["members"].forms))  # 1 initial + 3 extra
        html = form.as_p()
        self.assertInHTML('<label for="id_albums-0-name">Name:</label>', html)

    def test_exclude_formsets(self):
        """exclude_formsets removes a relation's formset while keeping the rest."""
        class BandForm(ClusterForm):
            class Meta:
                model = Band
                exclude_formsets = ("albums",)
                fields = ["name"]

        form = BandForm()
        self.assertTrue(form.formsets.get("members"))
        self.assertFalse(form.formsets.get("albums"))

    def test_incoming_data_save_commit_false_then_model_save(self):
        """A bound ClusterForm validates and, with commit=False, applies child
        changes to the in-memory instance only; the model's own save() then
        persists the cluster."""
        class BandForm(ClusterForm):
            class Meta:
                model = Band
                fields = ["name"]
                formsets = ["members", "albums"]

        beatles = Band(name="The Beatles", members=[BandMember(name="George Harrison")])
        form = BandForm(
            {
                "name": "The Beatles",
                "members-TOTAL_FORMS": 4,
                "members-INITIAL_FORMS": 1,
                "members-MAX_NUM_FORMS": 1000,
                "members-0-name": "George Harrison",
                "members-0-DELETE": "members-0-DELETE",
                "members-0-id": "",
                "members-1-name": "John Lennon",
                "members-1-id": "",
                "members-2-name": "Paul McCartney",
                "members-2-id": "",
                "members-3-name": "",
                "members-3-id": "",
                "albums-TOTAL_FORMS": 0,
                "albums-INITIAL_FORMS": 0,
                "albums-MAX_NUM_FORMS": 1000,
            },
            instance=beatles,
        )
        self.assertTrue(form.is_valid())
        result = form.save(commit=False)
        self.assertEqual(result, beatles)
        self.assertEqual(2, beatles.members.count())
        self.assertEqual("John Lennon", beatles.members.all()[0].name)
        self.assertFalse(BandMember.objects.filter(name="John Lennon").exists())

        beatles.save()
        self.assertTrue(BandMember.objects.filter(name="John Lennon").exists())

    def test_creation_through_form(self):
        """A ClusterForm with no instance creates the parent and its children on
        save(), honouring DELETE flags."""
        class BandForm(ClusterForm):
            class Meta:
                model = Band
                fields = ["name"]
                formsets = ["members", "albums"]

        form = BandForm(
            {
                "name": "The Beatles",
                "members-TOTAL_FORMS": 3,
                "members-INITIAL_FORMS": 0,
                "members-MAX_NUM_FORMS": 1000,
                "members-0-name": "John Lennon",
                "members-0-id": "",
                "members-1-name": "Pete Best",
                "members-1-DELETE": "members-1-DELETE",
                "members-1-id": "",
                "members-2-name": "",
                "members-2-id": "",
                "albums-TOTAL_FORMS": 0,
                "albums-INITIAL_FORMS": 0,
                "albums-MAX_NUM_FORMS": 1000,
            }
        )
        self.assertTrue(form.is_valid())
        beatles = form.save()
        self.assertTrue(beatles.id)
        self.assertEqual(1, beatles.members.count())
        self.assertTrue(BandMember.objects.filter(name="John Lennon").exists())
        self.assertFalse(BandMember.objects.filter(name="Pete Best").exists())

    def test_widget_overrides(self):
        """Meta.widgets overrides apply to both parent fields and child formset
        fields."""
        class BandForm(ClusterForm):
            class Meta:
                model = Band
                widgets = {"name": Textarea(), "members": {"name": Textarea()}}
                fields = ["name"]
                formsets = ["members", "albums"]

        form = BandForm()
        self.assertIsInstance(form["name"].field.widget, Textarea)
        self.assertIsInstance(
            form.formsets["members"].forms[0]["name"].field.widget, Textarea
        )

    def test_unique_together_and_unique_constraint(self):
        """ClusterForm validation rejects child formsets that violate a child
        model's unique_together / UniqueConstraint."""
        class BandForm(ClusterForm):
            class Meta:
                model = Band
                fields = ["name"]
                formsets = ["members", "albums"]

        form = BandForm(
            {
                "name": "The Beatles",
                "members-TOTAL_FORMS": 2,
                "members-INITIAL_FORMS": 0,
                "members-MAX_NUM_FORMS": 1000,
                "members-0-name": "John Lennon",
                "members-0-id": "",
                "members-1-name": "John Lennon",
                "members-1-id": "",
                "albums-TOTAL_FORMS": 0,
                "albums-INITIAL_FORMS": 0,
                "albums-MAX_NUM_FORMS": 1000,
            }
        )
        self.assertFalse(form.is_valid())

    def test_ignore_validation_on_deleted_items(self):
        """A child form marked for deletion is not validated, so an otherwise
        invalid value on it does not block the form."""
        class BandForm(ClusterForm):
            class Meta:
                model = Band
                fields = ["name"]
                formsets = ["members", "albums"]

        please_please_me = Album(name="Please Please Me", release_date=datetime.date(1963, 3, 22))
        beatles = Band(name="The Beatles", albums=[please_please_me])
        beatles.save()

        base = {
            "name": "The Beatles",
            "members-TOTAL_FORMS": 0,
            "members-INITIAL_FORMS": 0,
            "members-MAX_NUM_FORMS": 1000,
            "albums-TOTAL_FORMS": 1,
            "albums-INITIAL_FORMS": 1,
            "albums-MAX_NUM_FORMS": 1000,
            "albums-0-name": "With The Beatles",
            "albums-0-release_date": "1963-02-31",  # invalid date
            "albums-0-id": please_please_me.id,
            "albums-0-ORDER": 1,
            "albums-0-songs-TOTAL_FORMS": 0,
            "albums-0-songs-INITIAL_FORMS": 0,
            "albums-0-songs-MAX_NUM_FORMS": 1000,
        }
        self.assertFalse(BandForm(dict(base), instance=beatles).is_valid())

        deleted = dict(base)
        deleted["albums-0-DELETE"] = "albums-0-DELETE"
        form = BandForm(deleted, instance=beatles)
        self.assertTrue(form.is_valid())
        form.save(commit=False)
        self.assertEqual(0, beatles.albums.count())

    def test_inherit_kwargs_propagation(self):
        """Without inherit_kwargs, kwargs given to a ClusterForm do not reach
        child forms; listing them in inherit_kwargs makes them propagate."""
        class WithoutInherit(ClusterForm):
            class Meta:
                model = Band
                formsets = {"members": {"fields": ["name"]}}
                fields = ["name"]

        class WithInherit(ClusterForm):
            class Meta:
                model = Band
                formsets = {"members": {"fields": ["name"], "inherit_kwargs": ["label_suffix"]}}
                fields = ["name"]

        html = WithoutInherit(label_suffix="!!!:").as_p()
        self.assertInHTML('<label for="id_name">Name!!!:</label>', html)
        self.assertInHTML('<label for="id_members-0-name">Name!!!:</label>', html, count=0)

        html = WithInherit(label_suffix="!!!:").as_p()
        self.assertInHTML('<label for="id_members-0-name">Name!!!:</label>', html)

    def test_media_and_is_multipart(self):
        """A ClusterForm aggregates widget media and reports is_multipart() True
        when a file field exists on the parent or a child form."""
        class DocumentForm(ClusterForm):
            class Meta:
                model = Document
                fields = ["title", "file"]

        class BandForm(ClusterForm):
            class Meta:
                model = Band
                formsets = ["members"]
                fields = ["name"]

        self.assertTrue(DocumentForm().is_multipart())
        self.assertFalse(BandForm().is_multipart())

        class GalleryForm(ClusterForm):
            class Meta:
                model = Gallery
                formsets = ["images"]
                fields = ["title"]

        self.assertTrue(GalleryForm().is_multipart())

    def test_formsets_from_superclass(self):
        """ClusterForm exposes child formsets inherited from a model superclass
        (multi-table inheritance)."""
        class RestaurantForm(ClusterForm):
            class Meta:
                model = Restaurant
                fields = ["name", "serves_hot_dogs", "proprietor"]
                formsets = ["menu_items", "reviews"]

        self.assertIn("reviews", RestaurantForm.formsets)
        form = RestaurantForm(
            {
                "name": "The Fat Duck",
                "menu_items-TOTAL_FORMS": 0,
                "menu_items-INITIAL_FORMS": 0,
                "menu_items-MAX_NUM_FORMS": 1000,
                "reviews-TOTAL_FORMS": 1,
                "reviews-INITIAL_FORMS": 1,
                "reviews-MAX_NUM_FORMS": 1000,
                "reviews-0-id": "",
                "reviews-0-author": "Michael Winner",
                "reviews-0-body": "Rubbish.",
            }
        )
        self.assertTrue(form.is_valid())
        instance = form.save(commit=False)
        self.assertEqual(1, instance.reviews.count())
        self.assertEqual("Michael Winner", instance.reviews.first().author)


class ClusterFormM2MTest(TestCase):
    def setUp(self):
        self.joyce = Author.objects.create(name="James Joyce")
        self.dickens = Author.objects.create(name="Charles Dickens")
        self.article = Article.objects.create(title="Test article", authors=[self.joyce])

    def test_save_form_with_parental_m2m_commit_true(self):
        """Saving a ClusterForm with a parental m2m field updates both the
        in-memory instance and the database."""
        class ArticleForm(ClusterForm):
            class Meta:
                model = Article
                fields = ["title", "authors"]
                formsets = []

        form = ArticleForm(
            {"title": "Updated", "authors": [self.dickens.id]}, instance=self.article
        )
        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual([self.dickens], list(self.article.authors.all()))
        self.assertEqual(
            [self.dickens], list(Article.objects.get(pk=self.article.pk).authors.all())
        )

    def test_save_form_with_parental_m2m_commit_false(self):
        """With commit=False the parental m2m change lands on the in-memory
        instance but not the database until model.save()."""
        class ArticleForm(ClusterForm):
            class Meta:
                model = Article
                fields = ["title", "authors"]
                formsets = []

        form = ArticleForm(
            {"title": "Updated", "authors": [self.dickens.id]}, instance=self.article
        )
        self.assertTrue(form.is_valid())
        form.save(commit=False)
        self.assertEqual([self.dickens], list(self.article.authors.all()))
        self.assertEqual(
            [self.joyce], list(Article.objects.get(pk=self.article.pk).authors.all())
        )
        self.article.save()
        self.assertEqual(
            [self.dickens], list(Article.objects.get(pk=self.article.pk).authors.all())
        )

    def test_standard_m2m_deferred_save_m2m(self):
        """A standard (non-parental) m2m on a ClusterForm is committed via
        save_m2m() after the instance is saved when commit=False."""
        class ArticleForm(ClusterForm):
            class Meta:
                model = Article
                fields = ["title", "authors", "comments"]
                formsets = []

        comment = Comment.objects.create(content="Interesting")
        form = ArticleForm(
            {"title": "New", "authors": [self.joyce.id], "comments": [comment.id]}
        )
        self.assertTrue(form.is_valid())
        article = form.save(commit=False)
        self.assertIsNone(article.pk)
        article.save()
        self.assertQuerySetEqual(Article.objects.get(pk=article.pk).comments.all(), [])
        form.save_m2m()
        self.assertQuerySetEqual(
            Article.objects.get(pk=article.pk).comments.all(), [comment]
        )


class NestedClusterFormTest(TestCase):
    def test_nested_formsets_save_and_sort_order(self):
        """A ClusterForm with nested formsets creates the full parent →
        album → song hierarchy on save() and commits the submitted song order."""
        class BandForm(ClusterForm):
            class Meta:
                model = Band
                fields = ["name"]
                formsets = {"members": {}, "albums": {"formsets": ["songs"]}}

        form = BandForm(
            {
                "name": "The Beatles",
                "members-TOTAL_FORMS": 0,
                "members-INITIAL_FORMS": 0,
                "members-MAX_NUM_FORMS": 1000,
                "albums-TOTAL_FORMS": 1,
                "albums-INITIAL_FORMS": 0,
                "albums-MAX_NUM_FORMS": 1000,
                "albums-0-name": "Please Please Me",
                "albums-0-id": "",
                "albums-0-ORDER": 1,
                "albums-0-songs-TOTAL_FORMS": 2,
                "albums-0-songs-INITIAL_FORMS": 0,
                "albums-0-songs-MAX_NUM_FORMS": 1000,
                "albums-0-songs-0-name": "Misery",
                "albums-0-songs-0-id": "",
                "albums-0-songs-0-ORDER": 2,
                "albums-0-songs-1-name": "I Saw Her Standing There",
                "albums-0-songs-1-id": "",
                "albums-0-songs-1-ORDER": 1,
            }
        )
        self.assertTrue(form.is_valid())
        beatles = form.save()
        self.assertTrue(Band.objects.filter(name="The Beatles").exists())
        album = beatles.albums.first()
        self.assertEqual("Please Please Me", album.name)
        self.assertEqual(
            ["I Saw Her Standing There", "Misery"],
            [s.name for s in album.songs.all()],
        )

    def test_explicit_and_excluded_nested_formset_lists(self):
        """Nested formsets are present when listed under a relation's formsets
        and absent when excluded."""
        class IncludeForm(ClusterForm):
            class Meta:
                model = Band
                formsets = {"albums": {"formsets": ["songs"]}}
                fields = ["name"]

        class ExcludeForm(ClusterForm):
            class Meta:
                model = Band
                formsets = {"albums": {"exclude_formsets": ["songs"]}}
                fields = ["name"]

        self.assertTrue(IncludeForm().formsets["albums"].forms[0].formsets["songs"])
        self.assertIn("songs", IncludeForm().as_p())
        self.assertNotIn("songs", ExcludeForm().as_p())


# ---------------------------------------------------------------------------
# contrib.taggit (ClusterTaggableManager)
# ---------------------------------------------------------------------------


class TaggitTest(TestCase):
    def test_tags_on_unsaved_instance_defer_until_save(self):
        """Tags can be added/removed/cleared/set on an unsaved instance; the
        in-memory tag set updates immediately but the database is only touched on
        save()."""
        from taggit.models import Tag

        place = Place(name="Mission Burrito")
        self.assertEqual(0, place.tags.count())

        place.tags.add("mexican", "burrito")
        self.assertEqual(2, place.tags.count())
        self.assertEqual(Tag, place.tags.all()[0].__class__)
        from tests_app.models import TaggedPlace

        place.save()
        self.assertEqual(
            2, TaggedPlace.objects.filter(content_object_id=place.id).count()
        )

        place.tags.remove("burrito")
        self.assertEqual(1, place.tags.count())
        self.assertEqual(
            2, TaggedPlace.objects.filter(content_object_id=place.id).count()
        )
        place.save()
        self.assertEqual(
            1, TaggedPlace.objects.filter(content_object_id=place.id).count()
        )

        place.tags.set(["mexican", "burrito"])
        self.assertEqual(2, place.tags.count())
        place.save()
        self.assertEqual(
            2, TaggedPlace.objects.filter(content_object_id=place.id).count()
        )

    def test_tag_form_create(self):
        """A ClusterForm with a tag field parses a comma-separated tag string and
        creates the tagged object with those tags."""
        from taggit.models import Tag

        class PlaceForm(ClusterForm):
            class Meta:
                model = Place
                exclude_formsets = ["tagged_items", "reviews"]
                fields = ["name", "tags"]

        form = PlaceForm(
            {"name": "Mission Burrito", "tags": "burrito, fajita"}, instance=Place()
        )
        self.assertTrue(form.is_valid())
        place = form.save()
        reloaded = Place.objects.get(pk=place.pk)
        self.assertEqual(
            {Tag.objects.get(name="burrito"), Tag.objects.get(name="fajita")},
            set(reloaded.tags.all()),
        )

    def test_plain_taggable_manager_still_works(self):
        """A ClusterForm over a model using a plain (non-cluster) TaggableManager
        still saves tags correctly."""
        from taggit.models import Tag

        class PlaceForm(ClusterForm):
            class Meta:
                model = NonClusterPlace
                exclude_formsets = ["tagged_items", "reviews"]
                fields = ["name", "tags"]

        form = PlaceForm(
            {"name": "Mission Burrito", "tags": "burrito, fajita"},
            instance=NonClusterPlace(),
        )
        self.assertTrue(form.is_valid())
        place = form.save()
        reloaded = NonClusterPlace.objects.get(pk=place.pk)
        self.assertEqual(
            {Tag.objects.get(name="burrito"), Tag.objects.get(name="fajita")},
            set(reloaded.tags.all()),
        )

    def test_adding_integer_tag_raises(self):
        """Adding a non-string, non-Tag value as a tag raises ValueError."""
        place = Place(name="Mission Burrito")
        with self.assertRaises(ValueError):
            place.tags.add(1)


# ---------------------------------------------------------------------------
# Prefetching across fake querysets
# ---------------------------------------------------------------------------


class PrefetchTest(TestCase):
    def test_prefetch_child_relation(self):
        """prefetch_related on a ParentalKey relation collapses per-parent child
        queries into a single extra query and yields identical results."""
        Band.objects.create(
            name="The Beatles",
            members=[BandMember(id=1, name="John"), BandMember(id=2, name="Paul")],
        )
        with self.assertNumQueries(2):
            prefetched = [
                list(b.members.all())
                for b in Band.objects.prefetch_related("members")
            ]
        plain = [list(b.members.all()) for b in Band.objects.all()]
        self.assertEqual(plain, prefetched)

    def test_prefetch_parental_m2m(self):
        """prefetch_related on a ParentalManyToManyField fetches all related rows
        in a fixed number of queries."""
        authors = Author.objects.bulk_create(Author(id=i, name=str(i)) for i in range(5))
        for i in range(5):
            article = Article(title=str(i))
            article.authors = Author.objects.all()
            article.save()

        def names(articles):
            return [a.name for art in articles for a in art.authors.all()]

        plain = names(Article.objects.all())
        with self.assertNumQueries(2):
            prefetched = names(Article.objects.prefetch_related("authors"))
        self.assertEqual(plain, prefetched)

    def test_prefetch_tags(self):
        """prefetch_related('tags') over ClusterTaggableManager fetches tags for
        all instances in a fixed number of queries."""
        burrito = Place(name="Mission Burrito")
        burrito.tags.add("mexican", "burrito")
        burrito.save()
        burger = Place(name="Atomic Burger")
        burger.tags.add("burger")
        burger.save()

        with self.assertNumQueries(2):
            places = list(Place.objects.order_by("name").prefetch_related("tags"))
            self.assertCountEqual([t.name for t in places[0].tags.all()], ["burger"])
            self.assertCountEqual(
                [t.name for t in places[1].tags.all()], ["mexican", "burrito"]
            )
