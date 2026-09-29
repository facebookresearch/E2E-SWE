"""Model fixtures for the django-computedfields hidden test suite.

Every model derives from ``ComputedFieldsModel`` and wires computed fields across
the relation kinds the library supports (self/local, forward FK, reverse FK,
M2M + back, O2O + back, multi-hop paths, inheritance, computed FK). These models
are the fixture the tests drive; they are hidden from the agent.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from computedfields.models import ComputedField, ComputedFieldsModel, computed, precomputed


# --------------------------------------------------------------------------- #
# 1. Local / self-dependent computed fields + local MRO of chained CFs
# --------------------------------------------------------------------------- #
class Author(ComputedFieldsModel):
    forename = models.CharField(max_length=64)
    surname = models.CharField(max_length=64)

    @computed(models.CharField(max_length=130, default=""), depends=[("self", ["forename", "surname"])])
    def full_name(self):
        return f"{self.surname}, {self.forename}"

    # depends on another *local* computed field -> must be computed after full_name
    @computed(models.CharField(max_length=160, default=""), depends=[("self", ["full_name"])])
    def label(self):
        return f"Author: {self.full_name}"


# --------------------------------------------------------------------------- #
# 2. Forward FK + multi-hop relation path
# --------------------------------------------------------------------------- #
class Continent(ComputedFieldsModel):
    name = models.CharField(max_length=64)


class Country(ComputedFieldsModel):
    name = models.CharField(max_length=64)
    continent = models.ForeignKey(Continent, related_name="countries", on_delete=models.CASCADE)


class City(ComputedFieldsModel):
    name = models.CharField(max_length=64)
    country = models.ForeignKey(
        Country, related_name="cities", null=True, on_delete=models.SET_NULL
    )

    @computed(
        models.CharField(max_length=200, default=""),
        depends=[("country", ["name"]), ("country.continent", ["name"])],
    )
    def location(self):
        if not self.country:
            return self.name
        return f"{self.name}, {self.country.name}, {self.country.continent.name}"


# --------------------------------------------------------------------------- #
# 3. Reverse FK aggregation (+ dependency-aware update_fields)
# --------------------------------------------------------------------------- #
class Blog(ComputedFieldsModel):
    title = models.CharField(max_length=64)

    @computed(models.CharField(max_length=255, default=""), depends=[("entries", ["headline"])])
    def headlines(self):
        if not self.pk:
            return ""
        return ", ".join(self.entries.order_by("pk").values_list("headline", flat=True))

    @computed(models.IntegerField(default=0), depends=[("entries", ["headline"])])
    def entry_count(self):
        if not self.pk:
            return 0
        return self.entries.count()


class Entry(ComputedFieldsModel):
    headline = models.CharField(max_length=64)
    views = models.IntegerField(default=0)
    blog = models.ForeignKey(Blog, related_name="entries", on_delete=models.CASCADE)


class BlogProxy(Blog):
    class Meta:
        proxy = True


# --------------------------------------------------------------------------- #
# 4. M2M both directions
# --------------------------------------------------------------------------- #
class Tag(ComputedFieldsModel):
    label = models.CharField(max_length=32)

    @computed(models.CharField(max_length=255, default=""), depends=[("articles", ["title"])])
    def article_titles(self):
        if not self.pk:
            return ""
        return ",".join(self.articles.order_by("pk").values_list("title", flat=True))


class Article(ComputedFieldsModel):
    title = models.CharField(max_length=64)
    tags = models.ManyToManyField(Tag, related_name="articles")

    @computed(models.CharField(max_length=255, default=""), depends=[("tags", ["label"])])
    def tag_labels(self):
        if not self.pk:
            return ""
        return ",".join(self.tags.order_by("pk").values_list("label", flat=True))


# --------------------------------------------------------------------------- #
# 5. O2O forward + reverse
# --------------------------------------------------------------------------- #
class Account(ComputedFieldsModel):
    username = models.CharField(max_length=32)

    @computed(models.CharField(max_length=128, default=""), depends=[("profile", ["bio"])])
    def profile_summary(self):
        try:
            return f"{self.username}: {self.profile.bio}"
        except ObjectDoesNotExist:
            return self.username


class Profile(ComputedFieldsModel):
    bio = models.CharField(max_length=64)
    account = models.OneToOneField(Account, related_name="profile", on_delete=models.CASCADE)

    @computed(models.CharField(max_length=128, default=""), depends=[("account", ["username"])])
    def owner(self):
        return f"profile of {self.account.username}"


# --------------------------------------------------------------------------- #
# 6. ComputedField declarative syntax + default_on_create
# --------------------------------------------------------------------------- #
def _compute_area(inst):
    return inst.width * inst.height


class Rectangle(ComputedFieldsModel):
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)

    # declarative ComputedField with a named compute function
    area = ComputedField(
        models.IntegerField(default=0),
        depends=[("self", ["width", "height"])],
        compute=_compute_area,
    )

    # default_on_create: on INSERT the field default is used instead of computing
    @computed(
        models.CharField(max_length=32, default="NEW"),
        depends=[("self", ["width", "height"])],
        default_on_create=True,
    )
    def status(self):
        return f"{self.width}x{self.height}"


# --------------------------------------------------------------------------- #
# 7. @precomputed custom save behaviour
# --------------------------------------------------------------------------- #
class Receipt(ComputedFieldsModel):
    amount = models.IntegerField(default=0)
    seen_during_save = models.IntegerField(default=-1)

    @computed(models.IntegerField(default=0), depends=[("self", ["amount"])])
    def doubled(self):
        return self.amount * 2

    @precomputed
    def save(self, *args, **kwargs):
        # @precomputed updates local CFs *before* this body runs, so self.doubled
        # already reflects the current amount here.
        self.seen_during_save = self.doubled
        return super().save(*args, **kwargs)


class PlainReceipt(ComputedFieldsModel):
    amount = models.IntegerField(default=0)
    seen_during_save = models.IntegerField(default=-1)

    @computed(models.IntegerField(default=0), depends=[("self", ["amount"])])
    def doubled(self):
        return self.amount * 2

    def save(self, *args, **kwargs):
        # No @precomputed: doubled is still stale (its default) during the body.
        self.seen_during_save = self.doubled
        return super().save(*args, **kwargs)


class SkipReceipt(ComputedFieldsModel):
    amount = models.IntegerField(default=0)

    @computed(models.IntegerField(default=0), depends=[("self", ["amount"])])
    def doubled(self):
        return self.amount * 2

    @precomputed(skip_after=True)
    def save(self, *args, **kwargs):
        # doubled was synced before this body (for the original amount). We bump
        # amount afterwards; skip_after=True means the post-save recompute is
        # skipped, so stored doubled stays at the pre-bump value.
        self.amount += 1
        return super().save(*args, **kwargs)


# --------------------------------------------------------------------------- #
# 8. Inheritance: abstract / multi-table / (proxy is BlogProxy above)
# --------------------------------------------------------------------------- #
class AbstractSum(ComputedFieldsModel):
    a = models.IntegerField(default=0)
    b = models.IntegerField(default=0)

    @computed(models.IntegerField(default=0), depends=[("self", ["a", "b"])])
    def total(self):
        return self.a + self.b

    class Meta:
        abstract = True


class ConcreteSum(AbstractSum):
    note = models.CharField(max_length=32, default="")


class BasePage(ComputedFieldsModel):
    title = models.CharField(max_length=64)

    @computed(models.CharField(max_length=80, default=""), depends=[("self", ["title"])])
    def slug(self):
        return self.title.lower().replace(" ", "-")


class ArticlePage(BasePage):
    body = models.CharField(max_length=64, default="")

    # depends on the parent's computed `slug` (inherited into this model's CF set),
    # ordered before `summary` by the local MRO
    @computed(
        models.CharField(max_length=160, default=""),
        depends=[("self", ["body", "slug"])],
    )
    def summary(self):
        return f"{self.slug}: {self.body}"


# --------------------------------------------------------------------------- #
# 9. Computed foreign key field (a CF that is itself a ForeignKey)
# --------------------------------------------------------------------------- #
class Warehouse(ComputedFieldsModel):
    code = models.CharField(max_length=16)


class Shipment(ComputedFieldsModel):
    code = models.CharField(max_length=16)

    @computed(
        models.ForeignKey(
            Warehouse, null=True, on_delete=models.CASCADE, related_name="shipments"
        ),
        depends=[("self", ["code"])],
    )
    def warehouse(self):
        return Warehouse.objects.filter(code=self.code).first()


# --------------------------------------------------------------------------- #
# 10. Optimization rules: select_related / prefetch_related / querysize
# --------------------------------------------------------------------------- #
class Department(ComputedFieldsModel):
    name = models.CharField(max_length=32)

    @computed(
        models.CharField(max_length=255, default=""),
        depends=[("employees", ["name"])],
        prefetch_related=["employees"],
        querysize=5,
    )
    def roster(self):
        if not self.pk:
            return ""
        employees = sorted(self.employees.all(), key=lambda e: e.pk)
        return ",".join(e.name for e in employees)


class Employee(ComputedFieldsModel):
    name = models.CharField(max_length=32)
    department = models.ForeignKey(Department, related_name="employees", on_delete=models.CASCADE)
