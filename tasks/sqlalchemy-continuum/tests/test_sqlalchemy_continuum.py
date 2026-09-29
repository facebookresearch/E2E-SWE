"""End-to-end test suite for the sqlalchemy-continuum WRG task.

Deterministic, sqlite :memory: only. Every test mirrors a realistic user
workflow: define ORM models with __versioned__, make_versioned(), commit
changes, then assert the resulting version history / relationship reflection /
revert / plugin behavior with exact values.
"""
from copy import copy
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import close_all_sessions, declarative_base, sessionmaker

from sqlalchemy_continuum import (
    ClassNotVersioned,
    make_versioned,
    remove_versioning,
    version_class,
    count_versions,
    changeset,
    versioning_manager,
)
from sqlalchemy_continuum.transaction import TransactionFactory
from sqlalchemy_continuum.reverter import ReverterException
from sqlalchemy_continuum.plugins import (
    NullDeletePlugin,
    PropertyModTrackerPlugin,
    TransactionChangesPlugin,
    TransactionMetaPlugin,
)


class BaseTestCase:
    """Canonical isolation harness (validity strategy = library default)."""

    versioning_strategy = 'validity'
    plugins = []

    @property
    def options(self):
        return {'base_classes': (self.Model,), 'strategy': self.versioning_strategy}

    def setup_method(self, method):
        self.Model = declarative_base()
        make_versioned(options=self.options)
        versioning_manager.plugins = self.plugins
        versioning_manager.transaction_cls = TransactionFactory()
        versioning_manager.user_cls = None
        self.create_models()
        sa.orm.configure_mappers()
        if hasattr(self, 'Article'):
            try:
                self.ArticleVersion = version_class(self.Article)
            except ClassNotVersioned:
                pass
        if hasattr(self, 'Tag'):
            try:
                self.TagVersion = version_class(self.Tag)
            except ClassNotVersioned:
                pass
        self.engine = create_engine('sqlite:///:memory:')
        self.connection = self.engine.connect()
        Session = sessionmaker(bind=self.connection)
        self.session = Session(autoflush=False)
        self.Model.metadata.create_all(self.engine)

    def teardown_method(self, method):
        self.session.rollback()
        remove_versioning()
        versioning_manager.reset()
        try:
            close_all_sessions()
        except Exception:
            pass
        self.Model.metadata.drop_all(self.engine)
        self.connection.close()
        self.engine.dispose()

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)
            content = sa.Column(sa.UnicodeText)

        class Tag(self.Model):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
            article = sa.orm.relationship(Article, backref='tags')

        self.Article = Article
        self.Tag = Tag



# === CORE (insert/update/delete, changeset) ===


class TestUpdate(BaseTestCase):
    def test_update_creates_second_version_mirroring_new_state(self):
        """A user updates two columns of a committed Article and commits. A
        second version row is created reflecting the new values and carrying
        operation_type UPDATE (1); the first version still holds the old state."""
        article = self.Article(name='Some article', content='Some content')
        self.session.add(article)
        self.session.commit()

        article.name = 'Updated name'
        article.content = 'Updated content'
        self.session.commit()

        assert count_versions(article) == 2
        first, second = article.versions[0], article.versions[1]
        assert first.name == 'Some article'
        assert first.content == 'Some content'
        assert first.operation_type == 0
        assert second.name == 'Updated name'
        assert second.content == 'Updated content'
        assert second.operation_type == 1

class TestDelete(BaseTestCase):
    def test_delete_creates_version_with_delete_operation_type(self):
        """A user deletes a committed Article. A second version row records the
        deletion with operation_type DELETE (2), preserving the last-known
        column values of the row."""
        article = self.Article(name='Some article', content='Some content')
        self.session.add(article)
        self.session.commit()
        self.session.delete(article)
        self.session.commit()

        ArticleVersion = version_class(self.Article)
        versions = self.session.query(ArticleVersion).order_by(
            ArticleVersion.transaction_id
        ).all()
        assert len(versions) == 2
        assert versions[0].operation_type == 0
        assert versions[1].operation_type == 2
        assert versions[1].name == 'Some article'
        assert versions[1].content == 'Some content'

class TestVersionObjectChangeset(BaseTestCase):
    def test_changeset_property_for_insert_and_update(self):
        """A user inspects `.changeset` on version objects. For the initial
        insert it reports every column going from None to its inserted value
        (including the primary key); for a subsequent update it reports only the
        columns that changed, as [old, new] pairs. Internal columns
        (transaction_id/operation_type) never appear."""
        article = self.Article(name='Some article', content='Some content')
        self.session.add(article)
        self.session.commit()

        assert article.versions[0].changeset == {
            'id': [None, 1],
            'name': [None, 'Some article'],
            'content': [None, 'Some content'],
        }

        article.name = 'Updated name'
        article.content = 'Updated content'
        self.session.commit()

        assert article.versions[1].changeset == {
            'name': ['Some article', 'Updated name'],
            'content': ['Some content', 'Updated content'],
        }

class TestChangesetUtil(BaseTestCase):
    def test_changeset_util_for_pending_new_update_and_delete(self):
        """A user calls the `changeset()` helper on a live ORM object to preview
        the pending change in the current transaction. For a brand-new object it
        reports [new, None]; for a dirty (modified) object it reports [new, old]
        and only for the columns actually being changed; for an object marked for
        deletion it reports [None, old] for each non-None non-pk column."""
        # New (transient) object: pending value with no prior value.
        article = self.Article(name='Some article')
        assert changeset(article) == {'name': ['Some article', None]}

        # Persisted then modified: pending new value vs committed old value.
        # `content` holds a committed non-None value that is NOT being modified,
        # so it is not a pending change and must not appear.
        article.content = 'Some content'
        self.session.add(article)
        self.session.commit()
        article.name = 'Updated article'
        assert changeset(article) == {'name': ['Updated article', 'Some article']}

        # Marked for deletion: reports the values being removed.
        self.session.commit()
        self.session.delete(article)
        assert changeset(article) == {
            'name': [None, 'Updated article'],
            'content': [None, 'Some content'],
        }


# === STRATEGIES & TRAVERSAL (validity vs subquery) ===

STRATEGIES = ['validity', 'subquery']


class StrategyHarness:
    def __init__(self, strategy):
        self.strategy = strategy
        self.Model = declarative_base()
        self.options = {'base_classes': (self.Model,), 'strategy': strategy}
        make_versioned(options=self.options)
        versioning_manager.plugins = []
        versioning_manager.transaction_cls = TransactionFactory()
        versioning_manager.user_cls = None

        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = copy(self.options)
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            content = sa.Column(sa.UnicodeText)

        self.Article = Article
        sa.orm.configure_mappers()
        self.ArticleVersion = version_class(Article)
        self.engine = create_engine('sqlite:///:memory:')
        self.connection = self.engine.connect()
        Session = sessionmaker(bind=self.connection)
        self.session = Session()
        self.Model.metadata.create_all(self.connection)
        self.connection.commit()

    def teardown(self):
        self.session.rollback()
        remove_versioning()
        versioning_manager.reset()
        try:
            close_all_sessions()
        except Exception:
            pass
        self.Model.metadata.drop_all(self.connection)
        self.connection.close()
        self.engine.dispose()

    def make_four_versions(self):
        names = ['v0', 'v1', 'v2', 'v3']
        a = self.Article(name=names[0], content='c0')
        self.session.add(a)
        self.session.commit()
        for n in names[1:]:
            a.name = n
            self.session.commit()
        return a, names




def _body_test_previous_next_index_traversal(env):
    """A user navigates version history forward and backward using
    .previous, .next and .index across the full chain, and on the
    boundary versions."""
    a, names = env.make_four_versions()
    versions = list(a.versions)

    # boundaries
    assert versions[0].previous is None
    assert versions[-1].next is None

    # forward chaining
    assert versions[0].next == versions[1]
    assert versions[0].next.next == versions[2]
    # backward chaining
    assert versions[3].previous == versions[2]
    assert versions[3].previous.previous == versions[1]

    # cross-check next/previous are inverses
    for i in range(1, 4):
        assert versions[i].previous == versions[i - 1]
        assert versions[i - 1].next == versions[i]

    # index is 0-based position in history
    assert [v.index for v in versions] == [0, 1, 2, 3]

def _body_test_traversal_after_delete(env):
    """After deleting a versioned object, a delete-version row is recorded;
    its .previous still points at the last live version and that version's
    .next points at the delete row."""
    a = env.Article(name='alive')
    env.session.add(a)
    env.session.commit()
    a.name = 'updated'
    env.session.commit()
    env.session.delete(a)
    env.session.commit()

    versions = (
        env.session.query(env.ArticleVersion)
        .order_by(env.ArticleVersion.transaction_id)
        .all()
    )
    assert len(versions) == 3
    # operation_type: INSERT=0, UPDATE=1, DELETE=2
    assert [v.operation_type for v in versions] == [0, 1, 2]
    delete_version = versions[-1]
    assert delete_version.previous == versions[1]
    assert versions[1].next == delete_version
    assert delete_version.next is None

def test_validity_end_transaction_id_bookkeeping():
    """Under the validity strategy each version row gets its
    end_transaction_id set to the transaction_id of the *next* version of
    the same entity; the latest live version has end_transaction_id == None.
    Verified across insert -> update -> update -> delete."""
    h = StrategyHarness('validity')
    try:
        a = h.Article(name='n0')
        h.session.add(a)
        h.session.commit()
        a.name = 'n1'
        h.session.commit()
        a.name = 'n2'
        h.session.commit()

        versions = list(a.versions)
        assert len(versions) == 3
        txs = [v.transaction_id for v in versions]
        # each end_transaction_id == next row's transaction_id; last is None
        assert versions[0].end_transaction_id == txs[1]
        assert versions[1].end_transaction_id == txs[2]
        assert versions[2].end_transaction_id is None

        # delete closes the last open range
        h.session.delete(a)
        h.session.commit()
        all_versions = (
            h.session.query(h.ArticleVersion)
            .order_by(h.ArticleVersion.transaction_id)
            .all()
        )
        assert len(all_versions) == 4
        del_tx = all_versions[-1].transaction_id
        # the previously-open update row now closes at the delete tx
        assert all_versions[2].end_transaction_id == del_tx
        # the delete row itself has no successor -> None
        assert all_versions[3].end_transaction_id is None
    finally:
        h.teardown()

def test_subquery_strategy_has_no_end_transaction_column():
    """Under the subquery strategy the version table must NOT carry an
    end_transaction_id column (neighbors are computed by correlated
    subqueries instead of stored validity ranges), yet traversal still
    yields the correct neighbors."""
    h = StrategyHarness('subquery')
    try:
        assert 'end_transaction_id' not in h.ArticleVersion.__table__.c

        a = h.Article(name='s0')
        h.session.add(a)
        h.session.commit()
        a.name = 's1'
        h.session.commit()
        versions = list(a.versions)
        assert len(versions) == 2
        assert versions[0].next == versions[1]
        assert versions[1].previous == versions[0]
        assert versions[0].previous is None
        assert versions[1].next is None
    finally:
        h.teardown()

def _body_test_version_at_point_in_time(env):
    """A user asks 'which version was active at transaction T?' via
    version_at. Querying at each version's own tx returns that version;
    querying between two versions returns the earlier one; querying before
    the first version returns None; an unknown primary key returns None."""
    a, names = env.make_four_versions()
    versions = list(a.versions)
    txs = [v.transaction_id for v in versions]

    # exact tx of each version -> that version
    for v, tx in zip(versions, txs):
        result = env.ArticleVersion.version_at(
            env.session, {'id': a.id}, transaction_id=tx
        )
        assert result is not None
        assert result.transaction_id == tx
        assert result.name == v.name

    # a tx strictly between v1 and v2 (txs are spaced by transaction rows)
    # use last_tx + something guaranteed in-range: pick midpoint logic on ids
    # Query at a tx after the last version -> still the last (validity: open
    # range; subquery: highest <= target).
    later = txs[-1] + 10
    result = env.ArticleVersion.version_at(
        env.session, {'id': a.id}, transaction_id=later
    )
    assert result is not None
    assert result.name == names[-1]

    # before the first version -> None
    result = env.ArticleVersion.version_at(
        env.session, {'id': a.id}, transaction_id=txs[0] - 1
    )
    assert result is None

    # unknown primary key -> None
    result = env.ArticleVersion.version_at(
        env.session, {'id': 99999}, transaction_id=txs[-1]
    )
    assert result is None


# === RELATIONSHIP VERSIONING ===


class TestOneToMany(BaseTestCase):
    """A versioned parent's one-to-many collection, reflected onto the version
    class, returns the *version* objects of the children that were current at
    that parent version's transaction (latest child version with tx <= parent
    version tx, excluding deletes), ordered by child primary key."""

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)

        class Tag(self.Model):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
            article = sa.orm.relationship(Article, backref='tags')

        self.Article = Article
        self.Tag = Tag

    def test_one_to_many_reflection_as_of_transaction(self):
        article = self.Article(name='Some article')
        tag1 = self.Tag(name='some tag')
        article.tags.append(tag1)
        self.session.add(article)
        self.session.commit()  # tx1: article v0, tag1 v0

        # tx2: rename article+tag1, add tag2
        article.name = 'Updated article'
        tag1.name = 'updated tag'
        tag2 = self.Tag(name='other tag', article=article)
        self.session.add(tag2)
        self.session.commit()

        # tx3: rename article + tag1 again
        article.name = 'Updated again'
        tag1.name = 'updated again tag'
        self.session.commit()

        TagVersion = version_class(self.Tag)

        v0_tags = article.versions[0].tags
        assert isinstance(v0_tags, list)
        assert len(v0_tags) == 1
        assert all(isinstance(t, TagVersion) for t in v0_tags)
        assert v0_tags[0] is tag1.versions[0]
        assert v0_tags[0].name == 'some tag'

        v1_tags = article.versions[1].tags
        assert len(v1_tags) == 2
        assert tag1.versions[1] in v1_tags
        assert tag2.versions[0] in v1_tags
        assert sorted(t.name for t in v1_tags) == ['other tag', 'updated tag']

        v2_tags = article.versions[2].tags
        assert len(v2_tags) == 2
        assert tag1.versions[2] in v2_tags
        assert tag2.versions[0] in v2_tags

    def test_one_to_many_delete_excluded(self):
        article = self.Article(name='Some article')
        tag = self.Tag(name='some tag')
        article.tags.append(tag)
        self.session.add(article)
        self.session.commit()
        self.session.delete(tag)
        article.name = 'Updated article'
        self.session.commit()
        assert len(article.versions[0].tags) == 1
        assert len(article.versions[1].tags) == 0

class TestManyToOne(BaseTestCase):
    """The 'many' side's reflected many-to-one accessor returns a single parent
    *version* object: the parent version with the highest transaction id that is
    <= the child version's transaction id (or None)."""

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)

        class Tag(self.Model):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
            article = sa.orm.relationship(Article, backref='tags')

        self.Article = Article
        self.Tag = Tag

    def test_many_to_one_picks_latest_parent_version_at_or_before_tx(self):
        article = self.Article(name='Original')
        tag = self.Tag(name='some tag', article=article)
        self.session.add(article)
        self.session.commit()  # tx1: article v0, tag v0

        article.name = 'Renamed'
        self.session.commit()  # tx2: article v1

        tag.name = 'updated tag'
        self.session.commit()  # tx3: tag v1

        ArticleVersion = version_class(self.Article)

        # tag v0 (tx1) should point at article v0 (the only parent version <= tx1)
        a_for_tag_v0 = tag.versions[0].article
        assert isinstance(a_for_tag_v0, ArticleVersion)
        assert a_for_tag_v0 is article.versions[0]
        assert a_for_tag_v0.name == 'Original'

        # tag v1 (tx3) should point at the latest article version <= tx3 = v1
        a_for_tag_v1 = tag.versions[1].article
        assert a_for_tag_v1 is article.versions[1]
        assert a_for_tag_v1.name == 'Renamed'

class TestOneToOne(BaseTestCase):
    """A one-to-one (uselist=False) reflected relationship returns a single
    version object (not a list), tracking replacement across transactions."""

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)

        class Category(self.Model):
            __tablename__ = 'category'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
            article = sa.orm.relationship(
                Article, backref=sa.orm.backref('category', uselist=False)
            )

        self.Article = Article
        self.Category = Category

    def test_one_to_one_returns_single_version(self):
        article = self.Article(name='Some article')
        cat = self.Category(name='some category')
        article.category = cat
        self.session.add(article)
        self.session.commit()

        CategoryVersion = version_class(self.Category)
        reflected = article.versions[0].category
        assert isinstance(reflected, CategoryVersion)
        assert reflected == cat.versions[0]
        assert reflected.name == 'some category'

class TestManyToMany(BaseTestCase):
    """Many-to-many reflected onto version classes uses an association *version*
    table. article_version.tags returns the tag versions linked at that
    transaction; removing an association drops the tag from later versions."""

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        article_tag = sa.Table(
            'article_tag',
            self.Model.metadata,
            sa.Column('article_id', sa.Integer,
                      sa.ForeignKey('article.id'), primary_key=True),
            sa.Column('tag_id', sa.Integer,
                      sa.ForeignKey('tag.id'), primary_key=True),
        )

        class Tag(self.Model):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        Tag.articles = sa.orm.relationship(
            Article, secondary=article_tag, backref='tags'
        )

        self.Article = Article
        self.Tag = Tag
        self.article_tag = article_tag

    def test_many_to_many_reflection_and_removal(self):
        article = self.Article(name='Some article')
        tag1 = self.Tag(name='some tag')
        article.tags.append(tag1)
        self.session.add(article)
        self.session.commit()  # tx1

        # tx2: rename article + tag1, add tag2
        tag2 = self.Tag(name='other tag')
        article.tags.append(tag2)
        tag1.name = 'updated tag1'
        article.name = 'updated article'
        self.session.commit()

        # tx3: remove tag1 association, rename article
        article.tags.remove(tag1)
        article.name = 'updated again'
        self.session.commit()

        TagVersion = version_class(self.Tag)

        v0 = article.versions[0].tags
        assert len(v0) == 1
        assert all(isinstance(t, TagVersion) for t in v0)
        assert v0[0] is tag1.versions[0]

        v1 = article.versions[1].tags
        assert len(v1) == 2
        assert tag1.versions[1] in v1
        assert tag2.versions[0] in v1

        v2 = article.versions[2].tags
        assert len(v2) == 1
        assert v2[0] is tag2.versions[0]

class TestManyToManySelfReferential(BaseTestCase):
    """Self-referential many-to-many with explicit primaryjoin/secondaryjoin:
    both the forward (references) and backref (cited_by) reflected accessors
    return the correct version objects."""

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        article_references = sa.Table(
            'article_references',
            self.Model.metadata,
            sa.Column('referring_id', sa.Integer,
                      sa.ForeignKey('article.id'), primary_key=True),
            sa.Column('referred_id', sa.Integer,
                      sa.ForeignKey('article.id'), primary_key=True),
        )

        Article.references = sa.orm.relationship(
            Article,
            secondary=article_references,
            primaryjoin=Article.id == article_references.c.referring_id,
            secondaryjoin=Article.id == article_references.c.referred_id,
            backref='cited_by',
        )

        self.Article = Article

    def test_self_referential_m2m_both_directions(self):
        article = self.Article(name='article')
        reference1 = self.Article(name='referred article 1')
        article.references.append(reference1)
        self.session.add(article)
        self.session.commit()

        ArticleVersion = version_class(self.Article)

        refs = article.versions[0].references
        assert len(refs) == 1
        assert isinstance(refs[0], ArticleVersion)
        assert reference1.versions[0] in refs

        cited = reference1.versions[0].cited_by
        assert len(cited) == 1
        assert article.versions[0] in cited

class TestCustomConditionRelations(BaseTestCase):
    """Relationships with a custom primaryjoin containing an extra filter
    (Tag.category == 'primary') are reflected with that filter preserved, so
    the version accessor returns only the matching child versions."""

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        class Tag(self.Model):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
            category = sa.Column(sa.Unicode(20))

        Article.primary_tags = sa.orm.relationship(
            Tag,
            primaryjoin=sa.and_(
                Tag.article_id == Article.id, Tag.category == 'primary'
            ),
            overlaps='secondary_tags',
        )
        Article.secondary_tags = sa.orm.relationship(
            Tag,
            primaryjoin=sa.and_(
                Tag.article_id == Article.id, Tag.category == 'secondary'
            ),
            overlaps='primary_tags',
        )

        self.Article = Article
        self.Tag = Tag

    def test_custom_condition_filters_reflected_relationship(self):
        article = self.Article(name='Some article')
        ptag = self.Tag(name='tag #1', category='primary')
        stag = self.Tag(name='tag #2', category='secondary')
        article.primary_tags.append(ptag)
        article.secondary_tags.append(stag)
        self.session.add(article)
        self.session.commit()

        TagVersion = version_class(self.Tag)

        primary = article.versions[0].primary_tags
        secondary = article.versions[0].secondary_tags
        assert len(primary) == 1
        assert len(secondary) == 1
        assert all(isinstance(t, TagVersion) for t in primary + secondary)
        assert primary[0] is ptag.versions[0]
        assert primary[0].category == 'primary'
        assert secondary[0] is stag.versions[0]
        assert secondary[0].category == 'secondary'

class TestDynamicRelationship(BaseTestCase):
    """A lazy='dynamic' relationship is reflected as a *Query* object (not a
    materialized list), which can be further filtered/counted and yields child
    version objects when iterated."""

    def create_models(self):
        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)

        class Tag(self.Model):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
            article = sa.orm.relationship(
                Article, backref=sa.orm.backref('tags', lazy='dynamic')
            )

        self.Article = Article
        self.Tag = Tag

    def test_dynamic_relationship_returns_query(self):
        article = self.Article(name='Some article')
        article.tags.append(self.Tag(name='some tag'))
        article.tags.append(self.Tag(name='other tag'))
        self.session.add(article)
        self.session.commit()

        TagVersion = version_class(self.Tag)
        reflected = article.versions[0].tags
        # Reflected dynamic relationship is a Query, not a list.
        assert isinstance(reflected, sa.orm.Query)
        results = reflected.all()
        assert len(results) == 2
        assert all(isinstance(t, TagVersion) for t in results)
        assert sorted(t.name for t in results) == ['other tag', 'some tag']
        # The Query supports further refinement.
        assert reflected.count() == 2

class TestRelationshipToNonVersioned(BaseTestCase):
    """When the related class is NOT versioned, the reflected relationship
    falls back to returning the live *original* objects (not version objects):
    one for many-to-one, a list for many-to-many."""

    def create_models(self):
        class User(self.Model):
            __tablename__ = 'user'
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        class Article(self.Model):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)
            author_id = sa.Column(sa.Integer, sa.ForeignKey(User.id))
            author = sa.orm.relationship(User)

        article_tag = sa.Table(
            'article_tag',
            self.Model.metadata,
            sa.Column('article_id', sa.Integer,
                      sa.ForeignKey('article.id'), primary_key=True),
            sa.Column('tag_id', sa.Integer,
                      sa.ForeignKey('tag.id'), primary_key=True),
        )

        class Tag(self.Model):
            __tablename__ = 'tag'
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        Tag.articles = sa.orm.relationship(
            Article, secondary=article_tag, backref='tags'
        )

        self.User = User
        self.Article = Article
        self.Tag = Tag

    def test_non_versioned_many_to_one_returns_original(self):
        user = self.User(name='Some user')
        article = self.Article(name='Some article', author=user)
        self.session.add(article)
        self.session.commit()

        reflected = article.versions[0].author
        assert isinstance(reflected, self.User)
        assert reflected is user
        assert reflected.name == 'Some user'

    def test_non_versioned_many_to_many_returns_originals(self):
        article = self.Article(name='Some article')
        tag = self.Tag(name='some tag')
        article.tags.append(tag)
        self.session.add(article)
        self.session.commit()

        reflected = article.versions[0].tags
        assert len(reflected) == 1
        assert isinstance(reflected[0], self.Tag)
        assert reflected[0] is tag
        assert reflected[0].name == 'some tag'


# === REVERT, CONFIG, INHERITANCE ===

class VersioningFixture:
    options = {}

    def setup(self, build):
        self.Model = declarative_base()
        opts = {'strategy': 'validity'}
        opts.update(self.options)
        make_versioned(user_cls=None, options=opts)
        versioning_manager.plugins = []
        versioning_manager.transaction_cls = TransactionFactory()
        versioning_manager.user_cls = None
        self.models = build(self.Model)
        sa.orm.configure_mappers()
        self.engine = sa.create_engine('sqlite:///:memory:')
        self.Model.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        return self.models

    def teardown(self):
        try:
            self.session.rollback()
            self.session.close()
        except Exception:
            pass
        remove_versioning()
        versioning_manager.reset()
        try:
            self.engine.dispose()
        except Exception:
            pass


@pytest.fixture
def vf():
    f = VersioningFixture()
    yield f
    f.teardown()


def build_article_tag(Base):
    class Article(Base):
        __tablename__ = 'article'
        __versioned__ = {}
        id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
        name = sa.Column(sa.Unicode(255), nullable=False)
        content = sa.Column(sa.UnicodeText)

    class Tag(Base):
        __tablename__ = 'tag'
        __versioned__ = {}
        id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
        name = sa.Column(sa.Unicode(255))
        article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
        article = sa.orm.relationship(Article, backref='tags')

    return {'Article': Article, 'Tag': Tag}


def test_revert_deletion_resurrects_then_redeletes(vf):
    """Reverting the INSERT version of a deleted object resurrects it with its
    original pk + columns; reverting the DELETE version removes it again."""
    m = vf.setup(build_article_tag)
    Article = m['Article']
    a = Article(name='Some article', content='Some content')
    vf.session.add(a)
    vf.session.commit()
    old_id = a.id
    insert_version = a.versions[0]

    vf.session.delete(a)
    vf.session.commit()
    # two version rows: the insert and the delete
    assert vf.session.query(version_class(Article)).count() == 2

    insert_version.revert()
    vf.session.commit()
    assert vf.session.query(Article).count() == 1
    restored = vf.session.get(Article, old_id)
    assert restored.id == old_id
    assert restored.name == 'Some article'
    assert restored.content == 'Some content'

    # reverting the DELETE version removes the object again
    insert_version.next.revert()
    vf.session.commit()
    assert vf.session.get(Article, old_id) is None
    assert vf.session.query(Article).count() == 0

def test_revert_one_to_many_resurrects_and_prunes_children(vf):
    """Deep revert with relations=['tags']: a removed child is resurrected and
    a child added after the reverted version is pruned, leaving exactly the
    children present at the reverted version."""
    m = vf.setup(build_article_tag)
    Article, Tag = m['Article'], m['Tag']
    a = Article(name='Some article', content='Some content')
    keep = Tag(name='keep tag')
    drop = Tag(name='drop tag')
    a.tags.append(keep)
    a.tags.append(drop)
    vf.session.add(a)
    vf.session.commit()

    # mutate: remove 'drop', add a brand-new tag, change name
    a.name = 'Updated name'
    a.tags.remove(drop)
    a.tags.append(Tag(name='new tag'))
    vf.session.commit()
    vf.session.refresh(a)
    assert {t.name for t in a.tags} == {'keep tag', 'new tag'}
    assert len(a.versions[0].tags) == 2

    a.versions[0].revert(relations=['tags'])
    vf.session.commit()
    vf.session.refresh(a)

    assert a.name == 'Some article'
    # exactly the two children that existed at version 0; 'new tag' pruned
    assert {t.name for t in a.tags} == {'keep tag', 'drop tag'}

def test_revert_deep_nested_relations(vf):
    """Recursive reification across two relationship levels: reverting a
    Category with relations=['articles', 'articles.tags'] restores the removed
    article AND its removed tag."""

    def build(Base):
        class Category(Base):
            __tablename__ = 'category'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        class Article(Base):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            category_id = sa.Column(sa.Integer, sa.ForeignKey(Category.id))
            category = sa.orm.relationship(Category, backref='articles')

        class Tag(Base):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            article_id = sa.Column(sa.Integer, sa.ForeignKey(Article.id))
            article = sa.orm.relationship(Article, backref='tags')

        return {'Category': Category, 'Article': Article, 'Tag': Tag}

    m = vf.setup(build)
    Category, Article, Tag = m['Category'], m['Article'], m['Tag']

    category = Category(name='Some category')
    article = Article(name='Some article')
    category.articles.append(article)
    tag = Tag(name='some tag')
    article.tags.append(tag)
    vf.session.add(article)
    vf.session.commit()
    assert len(article.versions[0].tags) == 1

    article.tags.remove(tag)
    category.articles.remove(article)
    vf.session.commit()
    vf.session.refresh(article)
    assert article.tags == []
    assert article.category is None

    category.versions[0].revert(relations=['articles', 'articles.tags'])
    vf.session.commit()
    vf.session.refresh(category)

    assert len(category.articles) == 1
    restored = category.articles[0]
    assert restored.name == 'Some article'
    assert len(restored.tags) == 1
    assert restored.tags[0].name == 'some tag'

def test_revert_one_to_one_relationship(vf):
    """Reverting a scalar (uselist=False) relationship re-links the previously
    detached related object."""

    def build(Base):
        class Category(Base):
            __tablename__ = 'category'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        class Article(Base):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)
            category_id = sa.Column(sa.Integer, sa.ForeignKey(Category.id))
            category = sa.orm.relationship(
                Category, backref=sa.orm.backref('article', uselist=False)
            )

        return {'Category': Category, 'Article': Article}

    m = vf.setup(build)
    Category, Article = m['Category'], m['Article']

    a = Article(name='Some article')
    cat = Category(name='some category')
    a.category = cat
    vf.session.add(a)
    vf.session.commit()
    assert a.versions[0].category == cat.versions[0]

    a.category = None
    vf.session.commit()
    vf.session.refresh(a)
    assert a.category is None

    a.versions[0].revert(relations=['category'])
    vf.session.commit()
    assert a.category == cat
    assert a.category.name == 'some category'

def test_revert_many_to_many_relationship(vf):
    """Reverting a many-to-many (secondary table) relationship re-creates a
    removed association link."""

    def build(Base):
        class Article(Base):
            __tablename__ = 'article'
            __versioned__ = {'base_classes': (Base,)}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        article_tag = sa.Table(
            'article_tag',
            Base.metadata,
            sa.Column('article_id', sa.Integer,
                      sa.ForeignKey('article.id', ondelete='CASCADE'),
                      primary_key=True),
            sa.Column('tag_id', sa.Integer,
                      sa.ForeignKey('tag.id', ondelete='CASCADE'),
                      primary_key=True),
        )

        class Tag(Base):
            __tablename__ = 'tag'
            __versioned__ = {'base_classes': (Base,)}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        Tag.articles = sa.orm.relationship(Article, secondary=article_tag,
                                           backref='tags')
        return {'Article': Article, 'Tag': Tag}

    m = vf.setup(build)
    Article, Tag = m['Article'], m['Tag']

    a = Article(name='Some article')
    tag = Tag(name='some tag')
    a.tags.append(tag)
    vf.session.add(a)
    vf.session.commit()
    assert len(a.versions[0].tags) == 1

    a.tags.remove(tag)
    vf.session.commit()
    vf.session.refresh(a)
    assert a.tags == []

    a.versions[0].revert(relations=['tags'])
    vf.session.commit()
    assert a.name == 'Some article'
    assert len(a.tags) == 1
    assert a.tags[0].name == 'some tag'

def test_reverter_rejects_unknown_relation(vf):
    """Calling revert() with a relation name that is not a relationship on the
    parent class raises ReverterException before any revert is performed."""
    m = vf.setup(build_article_tag)
    Article = m['Article']
    a = Article(name='Some article', content='Some content')
    vf.session.add(a)
    vf.session.commit()
    version = a.versions[0]

    with pytest.raises(ReverterException):
        version.revert(relations=['unknown_relation'])

def test_column_exclusion(vf):
    """__versioned__={'exclude': [...]}: excluded column is absent from the
    version class and updating ONLY the excluded column creates no new version.
    """

    def build(Base):
        class TextItem(Base):
            __tablename__ = 'text_item'
            __versioned__ = {'exclude': ['content']}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            content = sa.Column(sa.UnicodeText)

        return {'TextItem': TextItem}

    m = vf.setup(build)
    TextItem = m['TextItem']
    TextItemVersion = version_class(TextItem)
    assert 'content' not in TextItemVersion._sa_class_manager.keys()

    item = TextItem(name='Some textitem')
    vf.session.add(item)
    vf.session.commit()
    assert item.versions[0].name == 'Some textitem'
    assert item.versions.count() == 1

    # updating only the excluded column -> no new version row
    item.content = 'Some content'
    vf.session.commit()
    assert item.versions.count() == 1

    # updating a versioned column -> new version row
    item.name = 'Renamed'
    vf.session.commit()
    assert item.versions.count() == 2

def test_custom_transaction_and_operation_column_names(vf):
    """transaction_column_name / end_transaction_column_name options rename the
    internal version-table columns; under the validity strategy the renamed
    end-transaction column still closes the previous version's range, and
    operation_type values remain correct."""

    def build(Base):
        class Article(Base):
            __tablename__ = 'article'
            __versioned__ = {
                'transaction_column_name': 'tx_id',
                'end_transaction_column_name': 'end_tx_id',
            }
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255), nullable=False)

        return {'Article': Article}

    m = vf.setup(build)
    Article = m['Article']
    ArticleVersion = version_class(Article)

    cols = ArticleVersion.__table__.c
    assert 'tx_id' in cols
    assert 'end_tx_id' in cols
    # the defaults must NOT be present once renamed
    assert 'transaction_id' not in cols
    assert 'end_transaction_id' not in cols

    a = Article(name='Some article')
    vf.session.add(a)
    vf.session.commit()
    a.name = 'Updated'
    vf.session.commit()
    vf.session.refresh(a)

    v0 = a.versions[0]
    v1 = a.versions[1]
    # operation_type keeps its default name and correct values
    assert v0.operation_type == 0
    assert v1.operation_type == 1
    # the renamed transaction column is populated; validity range is closed
    assert getattr(v0, 'tx_id') > 0
    assert getattr(v0, 'end_tx_id') == getattr(v1, 'tx_id')
    assert getattr(v1, 'end_tx_id') is None

def test_composite_primary_key_version_table(vf):
    """A model with a composite pk produces a version table whose pk is the
    original pk columns PLUS the transaction column, and the original pk columns
    stay NOT NULL on the version table."""

    def build(Base):
        class TeamMember(Base):
            __tablename__ = 'team_member'
            __versioned__ = {}
            user_id = sa.Column(sa.Integer, primary_key=True, nullable=False)
            team_id = sa.Column(sa.Integer, primary_key=True, nullable=False)
            role = sa.Column(sa.Unicode(255))

        return {'TeamMember': TeamMember}

    m = vf.setup(build)
    TeamMember = m['TeamMember']
    TeamMemberVersion = version_class(TeamMember)

    pk_cols = TeamMemberVersion.__table__.primary_key.columns
    assert len(pk_cols) == 3
    assert {'user_id', 'team_id', 'transaction_id'} == set(pk_cols.keys())
    # original composite-pk columns must remain NOT NULL on version table
    assert not TeamMemberVersion.__table__.c.user_id.nullable
    assert not TeamMemberVersion.__table__.c.team_id.nullable

def test_single_table_inheritance(vf):
    """Single-table inheritance: all version classes share ONE version table,
    the version-class hierarchy mirrors the model hierarchy, each object gets
    its concrete version subclass, and each model in the hierarchy has its
    own version class."""

    def build(Base):
        class TextItem(Base):
            __tablename__ = 'text_item'
            __versioned__ = {'base_classes': (Base,)}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            discriminator = sa.Column(sa.Unicode(100))
            __mapper_args__ = {
                'polymorphic_on': discriminator,
                'polymorphic_identity': 'base',
                'with_polymorphic': '*',
            }

        class Article(TextItem):
            __mapper_args__ = {'polymorphic_identity': 'article'}
            name = sa.Column(sa.Unicode(255))

        class BlogPost(TextItem):
            __mapper_args__ = {'polymorphic_identity': 'blog_post'}
            title = sa.Column(sa.Unicode(255))

        return {'TextItem': TextItem, 'Article': Article, 'BlogPost': BlogPost}

    m = vf.setup(build)
    TIV = version_class(m['TextItem'])
    AV = version_class(m['Article'])
    BPV = version_class(m['BlogPost'])

    assert issubclass(AV, TIV)
    assert issubclass(BPV, TIV)
    # all three share the single version table (checked through the mapper for
    # the two children, which add no table of their own)
    assert TIV.__table__.name == 'text_item_version'
    assert sa.inspect(AV).local_table.name == 'text_item_version'
    assert sa.inspect(BPV).local_table.name == 'text_item_version'

    # three distinct version classes mirror the three-model hierarchy
    assert len({TIV, AV, BPV}) == 3

    article = m['Article'](name='Text 1')
    blog = m['BlogPost'](title='Blog 1')
    base = m['TextItem']()
    vf.session.add_all([article, blog, base])
    vf.session.commit()
    assert isinstance(base.versions[0], TIV)
    assert isinstance(article.versions[0], AV)
    assert isinstance(blog.versions[0], BPV)

def test_joined_table_inheritance(vf):
    """Joined-table inheritance: each model gets its OWN version table named
    '<table>_version'; the version-class hierarchy mirrors the models; each
    version table carries the transaction column and 'id' in its pk; an insert
    writes a row to every level's version table."""

    def build(Base):
        class TextItem(Base):
            __tablename__ = 'text_item'
            __versioned__ = {'base_classes': (Base,)}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            discriminator = sa.Column(sa.Unicode(100))
            __mapper_args__ = {'polymorphic_on': discriminator,
                               'with_polymorphic': '*'}

        class Article(TextItem):
            __tablename__ = 'article'
            __mapper_args__ = {'polymorphic_identity': 'article'}
            id = sa.Column(sa.Integer, sa.ForeignKey(TextItem.id),
                           primary_key=True)
            byline = sa.Column(sa.Unicode(255))

        return {'TextItem': TextItem, 'Article': Article}

    m = vf.setup(build)
    TIV = version_class(m['TextItem'])
    AV = version_class(m['Article'])

    assert TIV.__table__.name == 'text_item_version'
    assert AV.__table__.name == 'article_version'
    assert issubclass(AV, TIV)

    for table in (TIV.__table__, AV.__table__):
        assert 'transaction_id' in table.c
        assert 'id' in table.primary_key.columns
        assert 'transaction_id' in table.primary_key.columns

    article = m['Article'](name='Some article', byline='by me')
    vf.session.add(article)
    vf.session.commit()
    assert vf.session.execute(
        sa.text('SELECT COUNT(1) FROM article_version')).scalar() == 1
    assert vf.session.execute(
        sa.text('SELECT COUNT(1) FROM text_item_version')).scalar() == 1
    # polymorphic load of base version table yields the concrete subclass
    assert isinstance(article.versions[0], AV)

def test_concrete_table_inheritance(vf):
    """Concrete-table inheritance: each concrete model gets its OWN version
    table; the version-class hierarchy still mirrors the models."""

    def build(Base):
        class TextItem(Base):
            __tablename__ = 'text_item'
            __versioned__ = {'base_classes': (Base,)}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            discriminator = sa.Column(sa.Unicode(100))
            __mapper_args__ = {'polymorphic_on': discriminator}

        class Article(TextItem):
            __tablename__ = 'article'
            __mapper_args__ = {'polymorphic_identity': 'article',
                               'concrete': True}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        class BlogPost(TextItem):
            __tablename__ = 'blog_post'
            __mapper_args__ = {'polymorphic_identity': 'blog_post',
                               'concrete': True}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            title = sa.Column(sa.Unicode(255))

        return {'TextItem': TextItem, 'Article': Article, 'BlogPost': BlogPost}

    m = vf.setup(build)
    TIV = version_class(m['TextItem'])
    AV = version_class(m['Article'])
    BPV = version_class(m['BlogPost'])

    assert issubclass(AV, TIV)
    assert issubclass(BPV, TIV)
    assert TIV.__table__.name == 'text_item_version'
    assert AV.__table__.name == 'article_version'
    assert BPV.__table__.name == 'blog_post_version'

    # three distinct version classes mirror the three-model hierarchy
    assert len({TIV, AV, BPV}) == 3

    # version data round-trips per concrete subclass (a column mismap would fail).
    # Concrete mappers don't inherit the `.versions` accessor, so query the
    # version class directly.
    a = m['Article'](name='Hello')
    bp = m['BlogPost'](title='World')
    vf.session.add_all([a, bp])
    vf.session.commit()
    av = vf.session.query(AV).filter(AV.id == a.id).one()
    bpv = vf.session.query(BPV).filter(BPV.id == bp.id).one()
    assert av.name == 'Hello'
    assert bpv.title == 'World'

def test_multi_level_inheritance_shared_table(vf):
    """A 3-level joined hierarchy where the deepest level adds NO own table:
    the version class name is '<Model>Version' and a level with no distinct
    table shares its parent's version table name."""

    def build(Base):
        class BaseModel(Base):
            __tablename__ = 'base_model'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            discriminator = sa.Column(sa.String(50), index=True)
            __mapper_args__ = {'polymorphic_on': discriminator,
                               'polymorphic_identity': 'product'}

        class FirstLevel(BaseModel):
            __tablename__ = 'first_level'
            id = sa.Column(sa.Integer, sa.ForeignKey('base_model.id'),
                           primary_key=True)
            __mapper_args__ = {'polymorphic_identity': 'first_level'}

        class SecondLevel(FirstLevel):
            __mapper_args__ = {'polymorphic_identity': 'second_level'}

        return {'BaseModel': BaseModel, 'FirstLevel': FirstLevel,
                'SecondLevel': SecondLevel}

    m = vf.setup(build)
    bm = version_class(m['BaseModel'])
    fl = version_class(m['FirstLevel'])
    sl = version_class(m['SecondLevel'])

    assert bm.__name__ == 'BaseModelVersion'
    assert bm.__table__.name == 'base_model_version'
    assert fl.__name__ == 'FirstLevelVersion'
    assert fl.__table__.name == 'first_level_version'
    # SecondLevel adds no own table -> shares FirstLevel's version table.
    # Checked through the mapper: a version class that adds no table of its own
    # need not expose it as __table__ (imperative mapping sets that to None).
    assert sl.__name__ == 'SecondLevelVersion'
    assert sa.inspect(sl).local_table.name == 'first_level_version'

    # a SecondLevel instance versions correctly and round-trips its pk/identity
    obj = m['SecondLevel']()
    vf.session.add(obj)
    vf.session.commit()
    assert obj.versions.count() == 1
    assert isinstance(obj.versions[0], sl)
    assert obj.versions[0].id == obj.id


# === TRANSACTION, PLUGINS, SAVEPOINTS ===


class TestTransactionModel(BaseTestCase):
    """One Transaction row per commit linking all version rows from that commit;
    issued_at populated, repr format, version.transaction accessor, and the
    'no actual change -> no transaction' rule."""

    plugins = [TransactionChangesPlugin(), TransactionMetaPlugin()]

    def test_transaction_links_versions_and_dedupes_noop_commits(self):
        from datetime import datetime

        article = self.Article(name='Some article', content='Some content')
        article.tags.append(self.Tag(name='Some tag'))
        self.session.add(article)
        self.session.commit()

        Transaction = versioning_manager.transaction_cls

        # Exactly one transaction created for the single commit.
        assert self.session.query(Transaction).count() == 1
        tx = self.session.query(Transaction).one()

        # The version row of every entity created in that commit points at it.
        article_v0 = article.versions[0]
        tag_v0 = article.tags[0].versions[0]
        assert article_v0.transaction is tx
        assert tag_v0.transaction is tx
        assert article_v0.transaction_id == tx.id
        assert tag_v0.transaction_id == tx.id

        # issued_at is auto-populated with a datetime default.
        assert isinstance(tx.issued_at, datetime)

        # repr format (no user_cls configured -> only id + issued_at).
        assert repr(tx) == (
            f'<Transaction id={tx.id}, issued_at={tx.issued_at!r}>'
        )

        # Re-assigning identical values produces no real modification -> no new
        # transaction rows are written across two further commits.
        article.name = 'Some article'
        self.session.commit()
        article.name = 'Some article'
        self.session.commit()
        assert self.session.query(Transaction).count() == 1

    def test_changed_entities_groups_versions_by_version_class(self):
        article = self.Article(name='Some article', content='Some content')
        article.tags.append(self.Tag(name='Some tag'))
        self.session.add(article)
        self.session.commit()

        article_v0 = article.versions[0]
        tag_v0 = article.tags[0].versions[0]
        tx = article_v0.transaction

        assert tx.changed_entities == {
            self.ArticleVersion: [article_v0],
            self.TagVersion: [tag_v0],
        }

    def test_transaction_ids_strictly_increase(self):
        """Each commit allocates a transaction whose id is strictly greater than
        the previous commit's."""
        a = self.Article(name='a')
        self.session.add(a)
        self.session.commit()
        b = self.Article(name='b')
        self.session.add(b)
        self.session.commit()
        c = self.Article(name='c')
        self.session.add(c)
        self.session.commit()
        ids = [a.versions[0].transaction_id,
               b.versions[0].transaction_id,
               c.versions[0].transaction_id]
        assert ids[0] < ids[1] < ids[2]

class TestTransactionChangesPlugin(BaseTestCase):
    """transaction_changes table records one (transaction_id, entity_name) row
    per changed entity class; tx.changes / tx.entity_names reflect it; noop
    commits add no rows."""

    plugins = [TransactionChangesPlugin()]

    def test_records_changed_entity_class_names_per_transaction(self):
        article = self.Article(name='Some article', content='Some content')
        article.tags.append(self.Tag(name='Some tag'))
        self.session.add(article)
        self.session.commit()

        tx = article.versions[0].transaction
        TransactionChanges = self.Article.__versioned__['transaction_changes']

        # Two distinct entity classes changed in this commit.
        assert self.session.query(TransactionChanges).count() == 2
        assert sorted(tx.entity_names) == ['Article', 'Tag']
        assert sorted(c.entity_name for c in tx.changes) == ['Article', 'Tag']

        # A noop commit (re-assign identical value) writes no new change rows.
        article.name = 'Some article'
        self.session.commit()
        assert self.session.query(TransactionChanges).count() == 2

class TestTransactionMetaPlugin(BaseTestCase):
    """Transaction.meta association proxy: empty dict by default, settable to
    key/value pairs persisted in transaction_meta and queryable back as a dict."""

    plugins = [TransactionMetaPlugin()]

    def test_meta_is_dict_proxy_persisted_per_transaction(self):
        article = self.Article(name='Some article', content='Some content')
        self.session.add(article)
        self.session.commit()

        tx = article.versions[0].transaction
        assert tx.meta == {}

        tx.meta = {'some key': 'some value'}
        self.session.commit()
        self.session.refresh(tx)
        assert tx.meta == {'some key': 'some value'}
        assert tx.meta['some key'] == 'some value'

        TransactionMeta = versioning_manager.transaction_meta_cls
        rows = self.session.query(TransactionMeta).all()
        assert len(rows) == 1
        assert rows[0].transaction_id == tx.id
        assert rows[0].key == 'some key'
        assert rows[0].value == 'some value'

        # in-place mutation on a later transaction's meta also persists
        article.name = 'Renamed'
        self.session.commit()
        tx2 = article.versions[1].transaction
        tx2.meta['k2'] = 'v2'
        self.session.commit()
        self.session.refresh(tx2)
        assert tx2.meta == {'k2': 'v2'}

class TestPropertyModTrackerPlugin(BaseTestCase):
    """Adds a non-nullable Boolean `<col>_mod` column per versioned non-PK
    column; sets it True for inserts/changed columns/deletes and False for
    untouched columns; primary keys excluded; *_mod stripped from changeset."""

    plugins = [PropertyModTrackerPlugin()]

    def test_mod_columns_schema_and_per_operation_flags(self):
        ArticleVersion = version_class(self.Article)

        # Schema: name_mod exists, is non-nullable Boolean; id_mod (PK) absent.
        assert 'name_mod' in ArticleVersion.__table__.c
        assert 'id_mod' not in ArticleVersion.__table__.c
        col = ArticleVersion.__table__.c['name_mod']
        assert isinstance(col.type, sa.Boolean)
        assert col.nullable is False

        # Insert: only the columns that received values are flagged True.
        article = self.Article(name='John')
        self.session.add(article)
        self.session.commit()
        v0 = list(article.versions)[-1]
        assert v0.name_mod is True
        assert v0.content_mod is False

        # Update one column: that column True, untouched ones False.
        article.content = 'Some content'
        self.session.commit()
        v1 = list(article.versions)[-1]
        assert v1.content_mod is True
        assert v1.name_mod is False

        # Delete: all non-PK mod columns flagged True.
        self.session.delete(article)
        self.session.commit()
        v2 = (
            self.session.query(ArticleVersion)
            .order_by(sa.desc(ArticleVersion.transaction_id))
            .first()
        )
        assert v2.name_mod is True
        assert v2.content_mod is True

class TestNullDeletePlugin(BaseTestCase):
    """On delete, the delete-version row stores NULL for all non-PK columns
    (instead of the deleted object's data), while still recording the delete
    (operation_type == 2) and preserving the primary key."""

    plugins = [NullDeletePlugin()]

    def test_delete_version_nullifies_non_pk_columns(self):
        article = self.Article(name='Some article', content='Some content')
        self.session.add(article)
        self.session.commit()

        self.session.delete(article)
        self.session.commit()

        versions = self.session.query(self.ArticleVersion).order_by(
            self.ArticleVersion.transaction_id
        ).all()
        assert len(versions) == 2
        # Insert version keeps data.
        assert versions[0].operation_type == 0
        assert versions[0].name == 'Some article'
        # Delete version: operation_type DELETE == 2, PK kept, data nulled.
        assert versions[1].operation_type == 2
        assert versions[1].id == versions[0].id
        assert versions[1].name is None
        assert versions[1].content is None

class TestSavepoints(BaseTestCase):
    """Nested transactions (savepoints): a rolled-back savepoint discards its
    changes from version history; committed savepoints fold into the single
    outer transaction (one version reflecting the final state)."""

    plugins = []

    def test_nested_rollback_discards_changes(self):
        article = self.Article(name='Some article')
        self.session.add(article)
        self.session.flush()
        savepoint = self.session.begin_nested()
        self.session.add(self.Article(name='Throwaway'))
        article.name = 'Updated name'
        savepoint.rollback()
        self.session.commit()

        assert article.versions.count() == 1
        assert list(article.versions)[-1].name == 'Some article'

    def test_multiple_savepoints_fold_into_one_version(self):
        article = self.Article(name='Some article')
        self.session.add(article)
        self.session.flush()
        savepoint = self.session.begin_nested()
        article.name = 'Updated name'
        savepoint.commit()
        self.session.begin_nested()
        article.name = 'Another article'
        self.session.commit()

        assert article.versions.count() == 1
        assert list(article.versions)[-1].name == 'Another article'

class TestExoticOperationCombos(BaseTestCase):
    """Deleting an object and inserting a fresh object reusing the same primary
    key inside one commit is recorded as an UPDATE version (operation_type 1)
    on top of the original INSERT (operation_type 0), not a delete row."""

    plugins = []

    def test_insert_over_deleted_object_is_update(self):
        article = self.Article(name='Some article', content='Some content')
        self.session.add(article)
        self.session.commit()
        assert article.versions.count() == 1

        self.session.delete(article)
        self.session.flush()
        article2 = self.Article(id=article.id, name='Some other article')
        self.session.add(article2)
        self.session.commit()

        assert article2.versions.count() == 2
        assert article2.versions[0].operation_type == 0
        assert article2.versions[1].operation_type == 1
        assert article2.versions[1].name == 'Some other article'

    def test_insert_over_deleted_no_flush_is_update(self):
        """The same delete+reinsert-same-PK coalescing, but with NO flush between
        the delete and the re-add (the harder operation-merge path): still one
        INSERT then one UPDATE version, not a delete row."""
        article = self.Article(name='First', content='c')
        self.session.add(article)
        self.session.commit()
        self.session.delete(article)
        article2 = self.Article(id=article.id, name='Second')
        self.session.add(article2)
        self.session.commit()
        assert article2.versions.count() == 2
        assert article2.versions[0].operation_type == 0
        assert article2.versions[1].operation_type == 1
        assert article2.versions[1].name == 'Second'


# Explicit per-strategy wrappers (parametrized names collapse under CTRF, so we
# expand them into uniquely-named tests that the grader counts individually).
def _run_for_strategy(body, strategy):
    h = StrategyHarness(strategy)
    try:
        body(h)
    finally:
        h.teardown()


def test_previous_next_index_traversal_validity():
    """previous/next/index traversal under the validity strategy."""
    _run_for_strategy(_body_test_previous_next_index_traversal, 'validity')


def test_previous_next_index_traversal_subquery():
    """previous/next/index traversal under the subquery strategy."""
    _run_for_strategy(_body_test_previous_next_index_traversal, 'subquery')


def test_traversal_after_delete_validity():
    """delete-version traversal neighbors under the validity strategy."""
    _run_for_strategy(_body_test_traversal_after_delete, 'validity')


def test_traversal_after_delete_subquery():
    """delete-version traversal neighbors under the subquery strategy."""
    _run_for_strategy(_body_test_traversal_after_delete, 'subquery')


def test_version_at_point_in_time_validity():
    """version_at point-in-time lookup under the validity strategy."""
    _run_for_strategy(_body_test_version_at_point_in_time, 'validity')


def test_version_at_point_in_time_subquery():
    """version_at point-in-time lookup under the subquery strategy."""
    _run_for_strategy(_body_test_version_at_point_in_time, 'subquery')



class TestJoinedInheritanceValidityBookkeeping(BaseTestCase):
    """Joined-table inheritance under the validity strategy: every commit writes a
    version row to BOTH the base and child version tables, and end_transaction_id
    is closed (set to the next version's transaction) independently per table."""

    versioning_strategy = 'validity'

    def create_models(self):
        class TextItem(self.Model):
            __tablename__ = 'text_item'
            __versioned__ = {}
            id = sa.Column(sa.Integer, primary_key=True)
            name = sa.Column(sa.Unicode(255))
            discriminator = sa.Column(sa.Unicode(100))
            __mapper_args__ = {'polymorphic_on': discriminator,
                               'with_polymorphic': '*'}

        class Article(TextItem):
            __tablename__ = 'article'
            __mapper_args__ = {'polymorphic_identity': 'article'}
            id = sa.Column(sa.Integer, sa.ForeignKey('text_item.id'),
                           primary_key=True)
            byline = sa.Column(sa.Unicode(255))

        self.TextItem = TextItem
        self.Article = Article

    def test_validity_end_tx_closed_across_inherited_tables(self):
        a = self.Article(name='n0', byline='b0')
        self.session.add(a)
        self.session.commit()          # tx1
        a.name = 'n1'
        self.session.commit()          # tx2 (changes a base-table column)
        a.byline = 'b1'
        self.session.commit()          # tx3 (changes a child-table column)

        TIV = version_class(self.TextItem)
        base_rows = self.session.query(TIV).order_by(TIV.transaction_id).all()
        assert len(base_rows) == 3
        btx = [r.transaction_id for r in base_rows]
        assert [r.end_transaction_id for r in base_rows] == [btx[1], btx[2], None]
        assert base_rows[2].name == 'n1'

        # the child version table closes end_transaction_id independently
        child = self.session.execute(sa.text(
            'SELECT transaction_id, end_transaction_id, byline '
            'FROM article_version ORDER BY transaction_id'
        )).fetchall()
        assert len(child) == 3
        ctx = [r[0] for r in child]
        assert [r[1] for r in child] == [ctx[1], ctx[2], None]
        assert child[1][2] == 'b0'   # byline carried forward at tx2
        assert child[2][2] == 'b1'   # byline updated at tx3


class TestVersionParent(BaseTestCase):
    """version.version_parent is a viewonly relationship (joined on the primary
    key) returning the live parent object, or None once the parent is deleted."""

    def test_version_parent_resolves_live_parent_then_none_after_delete(self):
        article = self.Article(name='Some article', content='c')
        self.session.add(article)
        self.session.commit()
        assert article.versions[0].version_parent is article

        self.session.delete(article)
        self.session.commit()
        ArticleVersion = version_class(self.Article)
        last = (
            self.session.query(ArticleVersion)
            .order_by(ArticleVersion.transaction_id)
            .all()[-1]
        )
        assert last.operation_type == 2
        assert last.version_parent is None


# === ADDITIONAL EDGE-CASE TESTS ===


def test_noop_reassign_same_value_creates_no_version(vf):
    """Re-assigning a versioned column to its current value is NOT a change
    (§3): no new version row and no new transaction should be created."""

    def build(Base):
        class Article(Base):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        return {'Article': Article}

    m = vf.setup(build)
    Article = m['Article']
    a = Article(name='hello')
    vf.session.add(a)
    vf.session.commit()
    assert count_versions(a) == 1

    a.name = 'hello'
    vf.session.commit()
    assert count_versions(a) == 1

    Transaction = versioning_manager.transaction_cls
    assert vf.session.query(Transaction).count() == 1


def test_m2m_association_version_records_insert_row(vf):
    """When a M2M link is added and committed, the association version table
    (§8) must contain a row recording that INSERT with operation_type 0 and
    the correct foreign-key values."""

    def build(Base):
        class Article(Base):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        article_tag = sa.Table(
            'article_tag', Base.metadata,
            sa.Column('article_id', sa.Integer,
                      sa.ForeignKey('article.id'), primary_key=True),
            sa.Column('tag_id', sa.Integer,
                      sa.ForeignKey('tag.id'), primary_key=True),
        )

        class Tag(Base):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        Tag.articles = sa.orm.relationship(
            Article, secondary=article_tag, backref='tags')

        return {'Article': Article, 'Tag': Tag}

    m = vf.setup(build)
    Article, Tag = m['Article'], m['Tag']
    a = Article(name='post')
    t = Tag(name='python')
    a.tags.append(t)
    vf.session.add(a)
    vf.session.commit()

    from sqlalchemy import text
    rows = vf.session.execute(
        text("SELECT article_id, tag_id, operation_type FROM article_tag_version")
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == a.id
    assert row[1] == t.id
    assert row[2] == 0


def test_m2m_association_version_records_delete_on_unlink(vf):
    """Removing a M2M link and committing must produce a DELETE row
    (operation_type 2) in the association version table (§8)."""

    def build(Base):
        class Article(Base):
            __tablename__ = 'article'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        article_tag = sa.Table(
            'article_tag', Base.metadata,
            sa.Column('article_id', sa.Integer,
                      sa.ForeignKey('article.id'), primary_key=True),
            sa.Column('tag_id', sa.Integer,
                      sa.ForeignKey('tag.id'), primary_key=True),
        )

        class Tag(Base):
            __tablename__ = 'tag'
            __versioned__ = {}
            id = sa.Column(sa.Integer, autoincrement=True, primary_key=True)
            name = sa.Column(sa.Unicode(255))

        Tag.articles = sa.orm.relationship(
            Article, secondary=article_tag, backref='tags')

        return {'Article': Article, 'Tag': Tag}

    m = vf.setup(build)
    Article, Tag = m['Article'], m['Tag']
    a = Article(name='post')
    t = Tag(name='python')
    a.tags.append(t)
    vf.session.add(a)
    vf.session.commit()

    a.tags.remove(t)
    vf.session.commit()

    from sqlalchemy import text
    ops = [
        r[0] for r in vf.session.execute(
            text("SELECT operation_type FROM article_tag_version")
        ).fetchall()
    ]
    assert 0 in ops, 'expected INSERT (0) in association version'
    assert 2 in ops, 'expected DELETE (2) in association version'
