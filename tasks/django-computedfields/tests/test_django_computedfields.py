"""Hidden end-to-end test suite for the django-computedfields WRG task.

Each test exercises a distinct implementation component of the library the way a
real user would: declaring computed fields with @computed / ComputedField across
self, FK, reverse-FK, M2M, O2O, multi-hop and inheritance relations; relying on
automatic updates through Django's save/delete/m2m signals; and driving bulk
updates, previews, contexts, signals, helpers and management commands explicitly.

The models under ``tests_app`` form the fixture; they are hidden from the agent.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from computedfields.models import (
    active_resolver,
    compute,
    get_computedfields,
    get_contributing_fks,
    has_computedfields,
    is_computedfield,
    not_computed,
    preupdate_dependent,
    update_dependent,
)
from computedfields.resolver import ResolverException
from computedfields.signals import resolver_exit, resolver_start, resolver_update

from tests_app.models import (
    Account,
    ArticlePage,
    Article,
    Author,
    BasePage,
    Blog,
    BlogProxy,
    City,
    ConcreteSum,
    Continent,
    Country,
    Department,
    Employee,
    Entry,
    PlainReceipt,
    Profile,
    Receipt,
    Rectangle,
    Shipment,
    SkipReceipt,
    Tag,
    Warehouse,
)


# --------------------------------------------------------------------------- #
# 1. Local / self dependencies + local MRO + update_fields expansion
# --------------------------------------------------------------------------- #
class LocalComputedFieldTests(TestCase):
    def test_local_save_mro_and_update_fields(self):
        """Local CFs compute on save respecting MRO, and update_fields is expanded."""
        a = Author.objects.create(forename="John", surname="Doe")
        a.refresh_from_db()
        self.assertEqual(a.full_name, "Doe, John")
        self.assertEqual(a.label, "Author: Doe, John")

        # edit and re-save: chained CF (label depends on full_name) must follow MRO
        a.surname = "Smith"
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.full_name, "Smith, John")
        self.assertEqual(a.label, "Author: Smith, John")

        # save(update_fields=[...]) still recomputes dependent local CFs
        a.surname = "Park"
        a.save(update_fields=["surname"])
        a.refresh_from_db()
        self.assertEqual(a.full_name, "Park, John")
        self.assertEqual(a.label, "Author: Park, John")


# --------------------------------------------------------------------------- #
# 2. Forward FK + multi-hop relation path + nullable FK
# --------------------------------------------------------------------------- #
class ForwardFkTests(TestCase):
    def test_multihop_propagation_and_nullable_fallback(self):
        """FK chain computes, upstream edits propagate, nullable FK falls back."""
        cont = Continent.objects.create(name="Europe")
        country = Country.objects.create(name="France", continent=cont)
        city = City.objects.create(name="Paris", country=country)
        city.refresh_from_db()
        self.assertEqual(city.location, "Paris, France, Europe")

        # upstream change propagates down the multi-hop chain
        cont.name = "EU"
        cont.save()
        city.refresh_from_db()
        self.assertEqual(city.location, "Paris, France, EU")

        # nullable FK cleared -> fallback branch
        country.delete()
        city.refresh_from_db()
        self.assertEqual(city.location, "Paris")


# --------------------------------------------------------------------------- #
# 3. Reverse FK aggregation (create / edit / delete / update_fields awareness)
# --------------------------------------------------------------------------- #
class ReverseFkTests(TestCase):
    def test_reverse_fk_lifecycle_and_update_fields(self):
        """Reverse FK aggregates update on child create, edit, delete;
        save(update_fields) outside the dependency does not reflow."""
        blog = Blog.objects.create(title="b")

        # child create updates parent aggregate
        e1 = Entry.objects.create(headline="first", blog=blog)
        e2 = Entry.objects.create(headline="second", blog=blog)
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "first, second")
        self.assertEqual(blog.entry_count, 2)

        # child edit reflows into parent aggregate
        e1.headline = "updated"
        e1.save()
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "updated, second")

        # child delete updates parent aggregate (post_delete)
        e1.delete()
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "second")
        self.assertEqual(blog.entry_count, 1)

        # update_fields outside dependency does not trigger parent recompute
        e2.headline = "changed"
        e2.views = 99
        e2.save(update_fields=["views"])
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "second")


# --------------------------------------------------------------------------- #
# 4. M2M both directions (add / remove / clear / edit propagation)
# --------------------------------------------------------------------------- #
class M2MTests(TestCase):
    def test_m2m_lifecycle(self):
        """M2M add/remove/clear/edit propagate to computed fields on both sides."""
        art = Article.objects.create(title="A1")
        t1 = Tag.objects.create(label="python")
        t2 = Tag.objects.create(label="django")

        # add updates both sides
        art.tags.add(t1, t2)
        art.refresh_from_db()
        t1.refresh_from_db()
        self.assertEqual(art.tag_labels, "python,django")
        self.assertEqual(t1.article_titles, "A1")

        # remove + clear
        art.tags.remove(t1)
        art.refresh_from_db()
        self.assertEqual(art.tag_labels, "django")
        art.tags.clear()
        art.refresh_from_db()
        self.assertEqual(art.tag_labels, "")

        # editing a related field propagates through M2M
        art.tags.add(t1)
        t1.label = "py3"
        t1.save()
        art.refresh_from_db()
        self.assertEqual(art.tag_labels, "py3")


# --------------------------------------------------------------------------- #
# 5. O2O forward + reverse (create / missing / edit)
# --------------------------------------------------------------------------- #
class OneToOneTests(TestCase):
    def test_o2o_lifecycle(self):
        """O2O forward + reverse deps compute, handle missing, and propagate edits."""
        acc = Account.objects.create(username="neo")
        acc.refresh_from_db()
        # missing reverse O2O falls back gracefully
        self.assertEqual(acc.profile_summary, "neo")

        # create the reverse side
        prof = Profile.objects.create(bio="hacker", account=acc)
        acc.refresh_from_db()
        prof.refresh_from_db()
        self.assertEqual(prof.owner, "profile of neo")
        self.assertEqual(acc.profile_summary, "neo: hacker")

        # editing one side propagates to the other
        acc.username = "mr_anderson"
        acc.save()
        prof = Profile.objects.get(account=acc)
        self.assertEqual(prof.owner, "profile of mr_anderson")


# --------------------------------------------------------------------------- #
# 6. ComputedField declarative + default_on_create
# --------------------------------------------------------------------------- #
class DeclarativeAndDefaultTests(TestCase):
    def test_declarative_form_and_default_on_create(self):
        """ComputedField(...) works like @computed; default_on_create uses the
        field default on INSERT and computes on subsequent saves."""
        r = Rectangle.objects.create(width=3, height=4)
        r.refresh_from_db()
        self.assertEqual(r.area, 12)
        self.assertEqual(r.status, "NEW")  # default_on_create: field default on INSERT

        r.width = 5
        r.save()
        r.refresh_from_db()
        self.assertEqual(r.area, 20)
        self.assertEqual(r.status, "5x4")  # computed on subsequent update


# --------------------------------------------------------------------------- #
# 7. @precomputed (with / without / skip_after / error)
# --------------------------------------------------------------------------- #
class PrecomputedTests(TestCase):
    def test_precomputed_behaviour(self):
        """@precomputed syncs CFs before save body; without it they're stale;
        skip_after freezes the pre-body value; bad usage raises ResolverException."""
        from computedfields.models import precomputed

        # @precomputed: CF available during save body
        r = Receipt.objects.create(amount=5)
        r.refresh_from_db()
        self.assertEqual(r.doubled, 10)
        self.assertEqual(r.seen_during_save, 10)

        # without @precomputed: CF still at default during save body
        p = PlainReceipt.objects.create(amount=5)
        p.refresh_from_db()
        self.assertEqual(p.doubled, 10)
        self.assertEqual(p.seen_during_save, 0)

        # skip_after=True: post-save recompute is skipped
        s = SkipReceipt.objects.create(amount=5)
        s.refresh_from_db()
        self.assertEqual(s.amount, 6)   # body bumped 5 -> 6
        self.assertEqual(s.doubled, 10) # frozen at pre-bump (5*2)

        # bad declaration raises ResolverException
        with self.assertRaises(ResolverException):
            precomputed(2, 3)


# --------------------------------------------------------------------------- #
# 8. compute() non-destructive preview
# --------------------------------------------------------------------------- #
class ComputePreviewTests(TestCase):
    def test_compute_previews_without_mutating(self):
        """compute() returns the prospective value without altering or saving it."""
        a = Author.objects.create(forename="John", surname="Doe")
        a.surname = "Roe"
        preview = compute(a, "full_name")
        self.assertEqual(preview, "Roe, John")
        # instance attribute and DB remain at the old value until save
        self.assertEqual(a.full_name, "Doe, John")
        a.refresh_from_db()
        self.assertEqual(a.full_name, "Doe, John")


# --------------------------------------------------------------------------- #
# 9. update_dependent / preupdate_dependent for bulk actions
# --------------------------------------------------------------------------- #
class BulkUpdateTests(TestCase):
    def test_bulk_update_and_fk_reassignment(self):
        """update_dependent() reflows after bulk update; preupdate_dependent()
        captures old relations so both old and new parents are resynced."""
        blog = Blog.objects.create(title="b")
        Entry.objects.create(headline="x", blog=blog)
        Entry.objects.create(headline="y", blog=blog)

        # bulk update bypasses signals; aggregate is stale until update_dependent
        Entry.objects.filter(blog=blog).update(headline="z")
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "x, y")
        update_dependent(Entry.objects.filter(blog=blog), update_fields=["headline"])
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "z, z")

        # bulk FK reassignment: preupdate_dependent captures old parent
        old_blog = Blog.objects.create(title="old")
        new_blog = Blog.objects.create(title="new")
        Entry.objects.create(headline="a", blog=old_blog)
        Entry.objects.create(headline="b", blog=old_blog)
        qs = Entry.objects.filter(blog=old_blog)
        old = preupdate_dependent(qs)
        qs.update(blog=new_blog)
        update_dependent(Entry.objects.filter(blog=new_blog), old=old)
        old_blog.refresh_from_db()
        new_blog.refresh_from_db()
        self.assertEqual(old_blog.headlines, "")
        self.assertEqual(old_blog.entry_count, 0)
        self.assertEqual(new_blog.headlines, "a, b")
        self.assertEqual(new_blog.entry_count, 2)


# --------------------------------------------------------------------------- #
# 10. not_computed context (presence / suppression / recover)
# --------------------------------------------------------------------------- #
class NotComputedContextTests(TestCase):
    def test_not_computed_context(self):
        """not_computed() suppresses updates; recover=True replays suppressed changes
        on exit; nesting shares one context so only the outermost exit replays."""
        # suppression: dependent updates are skipped
        blog = Blog.objects.create(title="b")
        with not_computed():
            Entry.objects.create(headline="x", blog=blog)
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "")

        # recover=True replays suppressed updates on exit
        blog2 = Blog.objects.create(title="b2")
        with not_computed(recover=True):
            Entry.objects.create(headline="x", blog=blog2)
            Entry.objects.create(headline="y", blog=blog2)
        blog2.refresh_from_db()
        self.assertEqual(blog2.headlines, "x, y")
        self.assertEqual(blog2.entry_count, 2)

        # nesting shares a single context: leaving an inner block replays nothing,
        # only the outermost exit recovers the whole suppressed set
        blog3 = Blog.objects.create(title="b3")
        with not_computed(recover=True):
            Entry.objects.create(headline="x", blog=blog3)
            with not_computed(recover=True):
                Entry.objects.create(headline="y", blog=blog3)
            # inner block exited, but recovery is deferred to the outermost context
            blog3.refresh_from_db()
            self.assertEqual(blog3.headlines, "")
        blog3.refresh_from_db()
        self.assertEqual(blog3.headlines, "x, y")
        self.assertEqual(blog3.entry_count, 2)


# --------------------------------------------------------------------------- #
# 11. Resolver signals
# --------------------------------------------------------------------------- #
class SignalTests(TestCase):
    def test_resolver_signals_emitted(self):
        """A tree update is bracketed by start/exit with update payloads between."""
        events = []
        updates = []

        def on_start(sender, **kw):
            events.append("start")

        def on_exit(sender, **kw):
            events.append("exit")

        def on_update(sender, model, fields, pks, **kw):
            updates.append((model, set(fields), list(pks)))

        resolver_start.connect(on_start)
        resolver_exit.connect(on_exit)
        resolver_update.connect(on_update)
        try:
            blog = Blog.objects.create(title="b")
            Entry.objects.create(headline="x", blog=blog)
        finally:
            resolver_start.disconnect(on_start)
            resolver_exit.disconnect(on_exit)
            resolver_update.disconnect(on_update)

        self.assertEqual(events[0], "start")
        self.assertEqual(events[-1], "exit")
        blog_updates = [u for u in updates if u[0] is Blog]
        self.assertTrue(blog_updates)
        model, fields, pks = blog_updates[0]
        self.assertIn("headlines", fields)
        self.assertEqual(pks, [blog.pk])


# --------------------------------------------------------------------------- #
# 12. Helper APIs
# --------------------------------------------------------------------------- #
class HelperApiTests(TestCase):
    def test_resolver_helpers(self):
        """has/get/is_computedfield introspection and get_contributing_fks."""
        self.assertTrue(has_computedfields(Author))
        self.assertFalse(has_computedfields(Continent))
        self.assertEqual(set(get_computedfields(Author)), {"full_name", "label"})
        self.assertTrue(is_computedfield(Author, "full_name"))
        self.assertFalse(is_computedfield(Author, "forename"))

        fks = get_contributing_fks()
        self.assertIn(Entry, fks)
        self.assertIn("blog", fks[Entry])


# --------------------------------------------------------------------------- #
# 13. Inheritance: abstract / multi-table / proxy
# --------------------------------------------------------------------------- #
class InheritanceTests(TestCase):
    def test_inheritance_strategies(self):
        """Abstract base CFs apply to concrete subclasses; MTI children can depend
        on parent CFs; proxy models are recognised as having computed fields."""
        # abstract base
        c = ConcreteSum.objects.create(a=3, b=4)
        c.refresh_from_db()
        self.assertEqual(c.total, 7)

        # MTI: child CF depends on parent's computed field (slug)
        p = ArticlePage.objects.create(title="Hello World", body="text")
        p.refresh_from_db()
        self.assertEqual(p.slug, "hello-world")
        self.assertEqual(p.summary, "hello-world: text")
        p.title = "Second Post"
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.slug, "second-post")
        self.assertEqual(p.summary, "second-post: text")

        # proxy model is recognised
        self.assertTrue(has_computedfields(BlogProxy))
        blog = BlogProxy.objects.create(title="b")
        Entry.objects.create(headline="x", blog=blog)
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "x")


# --------------------------------------------------------------------------- #
# 14. Computed foreign key field
# --------------------------------------------------------------------------- #
class ComputedForeignKeyTests(TestCase):
    def test_computed_fk(self):
        """A computed FK stores the resolved instance; cascade delete applies."""
        w = Warehouse.objects.create(code="W1")
        s = Shipment.objects.create(code="W1")
        s.refresh_from_db()
        self.assertEqual(s.warehouse, w)

        # cascade delete on the computed FK target
        self.assertEqual(Shipment.objects.count(), 1)
        w.delete()
        self.assertEqual(Shipment.objects.count(), 0)


# --------------------------------------------------------------------------- #
# 15. Optimization rules (select_related / prefetch_related / querysize)
# --------------------------------------------------------------------------- #
class OptimizationTests(TestCase):
    def test_optimization_rules(self):
        """The resolver aggregates the declared optimization rules per model, and a
        prefetch_related/querysize-optimized reverse-FK aggregate computes the full
        roster across more rows than the per-field querysize, so the sliced
        batched-queryset path is exercised end to end."""
        # per-model aggregation of the rules declared on the model's computed fields:
        # a list for prefetch_related, a set for select_related (empty when none), and
        # the minimum of the per-field querysize values and the global default
        self.assertEqual(active_resolver.get_prefetch_related(Department), ["employees"])
        self.assertEqual(active_resolver.get_select_related(Department), set())
        self.assertEqual(active_resolver.get_querysize(Department), 5)
        # a model whose computed fields declare no querysize falls back to the global
        # COMPUTEDFIELDS_QUERYSIZE default
        self.assertEqual(active_resolver.get_querysize(Blog), 10000)

        dept = Department.objects.create(name="eng")
        # querysize=5 on Department.roster: insert more than 5 employees so the
        # resolver's sliced/batched queryset path is traversed, not just the
        # single-batch case. A correct prefetch + slice + compute must still
        # produce the complete pk-ordered roster.
        for name in ["a", "b", "c", "d", "e", "f"]:
            Employee.objects.create(name=name, department=dept)
        dept.refresh_from_db()
        self.assertEqual(dept.roster, "a,b,c,d,e,f")

        # editing one employee reflows the whole optimized aggregate
        first = Employee.objects.order_by("pk").first()
        first.name = "z"
        first.save()
        dept.refresh_from_db()
        self.assertEqual(dept.roster, "z,b,c,d,e,f")


# --------------------------------------------------------------------------- #
# 16. Cyclic computed-field dependencies are rejected at resolver map-building
# --------------------------------------------------------------------------- #
class GraphTests(TestCase):
    def test_cyclic_dependency_rejected(self):
        """The real (acyclic) computed-field configuration yields cycle-free dependency
        graphs, while a cyclic configuration is rejected by the cycle checker.

        Driven entirely through the public surface: the live configuration's graphs come
        from active_resolver.get_graphs() (each exposes is_cyclefree), and the rejection of
        a cycle is asserted on the public computedfields.graph directed-graph primitives that
        the resolver's map-building cycle check relies on."""
        from computedfields.graph import CycleEdgeException, Edge, Graph, Node

        # the real configuration the suite declares builds cycle-free dependency graphs
        intermodel, modelgraphs, union = active_resolver.get_graphs()
        self.assertTrue(intermodel.is_cyclefree)
        self.assertTrue(union.is_cyclefree)
        self.assertTrue(all(g.is_cyclefree for g in modelgraphs.values()))

        # an acyclic chain is cycle-free ...
        g = Graph()
        g.add_edge(Edge(Node("cyc_a"), Node("cyc_b")))
        g.add_edge(Edge(Node("cyc_b"), Node("cyc_c")))
        self.assertTrue(g.is_cyclefree)

        # ... and closing the loop on the same graph flips the property (it reflects the
        # edges currently present) and makes path linearization -- what map-building does --
        # raise the edge-flavoured CycleException
        g.add_edge(Edge(Node("cyc_c"), Node("cyc_a")))
        self.assertFalse(g.is_cyclefree)
        with self.assertRaises(CycleEdgeException):
            g.get_edgepaths()


# --------------------------------------------------------------------------- #
# 17. Admin helper proxy models
# --------------------------------------------------------------------------- #
class AdminHelperTests(TestCase):
    def test_admin_helper_querysets(self):
        """The admin proxy managers list CF models and contributing-FK models."""
        from computedfields.models import ComputedFieldsAdminModel, ContributingModelsModel

        cf_models = {ct.model_class() for ct in ComputedFieldsAdminModel.objects.all()}
        self.assertIn(Author, cf_models)
        self.assertNotIn(Continent, cf_models)

        contributing = {ct.model_class() for ct in ContributingModelsModel.objects.all()}
        self.assertIn(Entry, contributing)


# --------------------------------------------------------------------------- #
# 18. Management commands
# --------------------------------------------------------------------------- #
class ManagementCommandTests(TestCase):
    def test_management_commands(self):
        """updatedata resyncs desynced rows; checkdata detects desync and passes
        when synced; showdependencies prints dependency edges."""
        import contextlib

        blog = Blog.objects.create(title="b")
        with not_computed():
            Entry.objects.create(headline="x", blog=blog)
            Entry.objects.create(headline="y", blog=blog)

        # checkdata detects desync
        with self.assertRaises(CommandError):
            call_command("checkdata", "tests_app.Blog", stderr=StringIO())

        # updatedata resyncs
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "")
        call_command("updatedata", "tests_app.Blog", stdout=StringIO())
        blog.refresh_from_db()
        self.assertEqual(blog.headlines, "x, y")

        # checkdata passes when synced
        call_command("checkdata", "tests_app.Blog", stderr=StringIO())

        # showdependencies prints edges keyed by the contributing source model:
        # Entry.blog (the FK) and Entry.headline are dependency sources for Blog's
        # computed fields, each rendered with the concrete source field and the
        # lowercased app.model target. (The bracketed target-field set is printed
        # from an unordered set, so its ordering is not asserted here.)
        out = StringIO()
        with contextlib.redirect_stdout(out):
            call_command("showdependencies", "tests_app")
        rendered = out.getvalue()
        self.assertIn("blog -> tests_app.blog", rendered)
        self.assertIn("headline -> tests_app.blog", rendered)
