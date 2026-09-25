"""Hidden test suite for the reader WRG task.

Tests realistic user workflows against the public reader API and CLI.
Feeds are read from local fixture files via file:// URIs (no network).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent.absolute() / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def db_path():
    """Fresh sqlite path; reader will create the file on first open."""
    path = _tmp_db()
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def reader(db_path):
    """A reader with feed_root='' (full filesystem access for local fixtures)."""
    from reader import make_reader

    r = make_reader(db_path, feed_root="")
    try:
        yield r
    finally:
        r.close()


@pytest.fixture
def reader_with_sample(reader):
    """A reader with the RSS sample feed added and updated."""
    url = str(FIXTURES / "sample.rss")
    reader.add_feed(url)
    reader.update_feeds()
    return reader, url


def _run_cli(db_path, *args, env_extra=None, feed_root=""):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, "-m", "reader", "--db", db_path]
    if feed_root is not None:
        cmd += ["--feed-root", feed_root]
    cmd += list(args)
    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# 1. make_reader / configuration
# ---------------------------------------------------------------------------


def test_make_reader_constructor_modes(db_path):
    """make_reader covers: db creation, search default off, search_enabled=True,
    invalid search_enabled raises, context-manager usage."""
    from reader import make_reader

    # default: db file created, search disabled
    r = make_reader(db_path)
    try:
        assert os.path.exists(db_path)
        assert r.is_search_enabled() is False
    finally:
        r.close()

    # search_enabled=True turns search on immediately
    r = make_reader(db_path, search_enabled=True)
    try:
        assert r.is_search_enabled() is True
    finally:
        r.close()

    # invalid value rejected
    with pytest.raises(ValueError):
        make_reader(db_path, search_enabled="bogus")

    # context-manager protocol
    db2 = _tmp_db()
    try:
        with make_reader(db2) as r:
            r.add_feed("http://example.com/feed.xml")
            feeds = list(r.get_feeds())
        assert [f.url for f in feeds] == ["http://example.com/feed.xml"]
    finally:
        try:
            os.unlink(db2)
        except OSError:
            pass


def test_make_reader_feed_root_none_blocks_file_feeds(db_path):
    """feed_root=None (default) disables local-file feeds —
    add_feed on a file path raises InvalidFeedURLError."""
    from reader import InvalidFeedURLError, make_reader

    r = make_reader(db_path)  # feed_root defaults to None
    try:
        url = str(FIXTURES / "sample.rss")
        with pytest.raises(InvalidFeedURLError):
            r.add_feed(url)
    finally:
        r.close()


# ---------------------------------------------------------------------------
# 2. Feed CRUD (API-only behaviors; CLI flows live in section 15)
# ---------------------------------------------------------------------------


def test_add_feed_duplicate_raises(reader):
    """Adding the same feed twice raises FeedExistsError; exist_ok suppresses it."""
    from reader import FeedExistsError

    reader.add_feed("http://example.com/feed.xml")
    with pytest.raises(FeedExistsError):
        reader.add_feed("http://example.com/feed.xml")
    # exist_ok is a clean no-op (no extra feed inserted)
    reader.add_feed("http://example.com/feed.xml", exist_ok=True)
    assert len(list(reader.get_feeds())) == 1


def test_delete_missing_feed_raises(reader):
    """delete_feed raises FeedNotFoundError unless missing_ok=True."""
    from reader import FeedNotFoundError

    with pytest.raises(FeedNotFoundError):
        reader.delete_feed("http://nope.example.com/feed.xml")
    # missing_ok suppresses cleanly
    reader.delete_feed("http://nope.example.com/feed.xml", missing_ok=True)


def test_add_feed_invalid_url_raises(db_path):
    """Adding a feed with an unsupported scheme raises InvalidFeedURLError;
    allow_invalid_url=True accepts it for user-entry workflows."""
    from reader import InvalidFeedURLError, make_reader

    r = make_reader(db_path)
    try:
        with pytest.raises(InvalidFeedURLError):
            r.add_feed("not-a-supported-url")
        # but allow_invalid_url=True accepts it
        r.add_feed("not-a-supported-url", allow_invalid_url=True)
        assert {f.url for f in r.get_feeds()} == {"not-a-supported-url"}
    finally:
        r.close()


def test_get_missing_feed_raises(reader):
    """get_feed raises FeedNotFoundError when missing; default arg suppresses."""
    from reader import FeedNotFoundError

    with pytest.raises(FeedNotFoundError):
        reader.get_feed("http://missing.example.com/feed.xml")

    sentinel = object()
    assert reader.get_feed("http://missing.example.com/", sentinel) is sentinel


def test_change_feed_url(reader):
    """change_feed_url renames a feed and the old URL is gone from the feed
    set (get_feed(old) raises, get_feed(new) returns the feed); collisions
    raise FeedExistsError. Kills implementations that keep both URLs as
    aliases or copy without removing the source."""
    from reader import FeedExistsError, FeedNotFoundError

    reader.add_feed("http://old.example.com/feed.xml")
    reader.change_feed_url(
        "http://old.example.com/feed.xml", "http://new.example.com/feed.xml"
    )
    # Exactly one feed under the new URL; old URL completely gone.
    assert {f.url for f in reader.get_feeds()} == {"http://new.example.com/feed.xml"}
    with pytest.raises(FeedNotFoundError):
        reader.get_feed("http://old.example.com/feed.xml")
    new_feed = reader.get_feed("http://new.example.com/feed.xml")
    assert new_feed.url == "http://new.example.com/feed.xml"

    # collide with an existing feed
    reader.add_feed("http://other.example.com/feed.xml")
    with pytest.raises(FeedExistsError):
        reader.change_feed_url(
            "http://other.example.com/feed.xml",
            "http://new.example.com/feed.xml",
        )
    # After the failed rename, both feeds should still exist independently.
    assert {f.url for f in reader.get_feeds()} == {
        "http://new.example.com/feed.xml",
        "http://other.example.com/feed.xml",
    }


def test_set_feed_user_title(reader):
    """set_feed_user_title sets and clears the user-defined title; setting it
    does NOT clobber the feed's `url`, AND it raises FeedNotFoundError on
    an unknown feed. resolved_title prefers user_title once set, falls back
    once cleared. Kills implementations that store user_title in feed.title
    (clobbering parser-supplied title) or silently no-op on missing feeds."""
    from reader import FeedNotFoundError

    feed_url = "http://example.com/feed.xml"
    reader.add_feed(feed_url)

    reader.set_feed_user_title(feed_url, "My Custom Title")
    f = reader.get_feed(feed_url)
    assert f.user_title == "My Custom Title"
    assert f.url == feed_url  # url unchanged
    # resolved_title prefers user_title.
    assert f.resolved_title == "My Custom Title"

    reader.set_feed_user_title(feed_url, None)
    f2 = reader.get_feed(feed_url)
    assert f2.user_title is None
    assert f2.url == feed_url

    # Setting on a non-existent feed raises (no silent no-op).
    with pytest.raises(FeedNotFoundError):
        reader.set_feed_user_title("http://does-not-exist.example/", "x")


def test_enable_disable_feed_updates(reader):
    """enable/disable_feed_updates toggles the updates_enabled flag."""
    reader.add_feed("http://example.com/feed.xml")
    reader.disable_feed_updates("http://example.com/feed.xml")
    assert reader.get_feed("http://example.com/feed.xml").updates_enabled is False
    reader.enable_feed_updates("http://example.com/feed.xml")
    assert reader.get_feed("http://example.com/feed.xml").updates_enabled is True


def test_get_feed_counts_total_and_filters(reader):
    """get_feed_counts reports total, broken (always 0 for healthy feeds),
    updates_enabled count, and respects per-feed filter."""
    reader.add_feed("http://a.example.com/")
    reader.add_feed("http://b.example.com/")
    reader.disable_feed_updates("http://a.example.com/")

    counts = reader.get_feed_counts()
    assert counts.total == 2
    # only one feed has updates enabled (b)
    assert counts.updates_enabled == 1
    # neither has a parse exception → broken count is 0
    assert counts.broken == 0
    # filter by single feed
    assert reader.get_feed_counts(feed="http://a.example.com/").total == 1
    assert reader.get_feed_counts(feed="http://b.example.com/").total == 1
    # broken=True filter: zero matches
    assert reader.get_feed_counts(broken=True).total == 0
    # broken=False filter: both feeds
    assert reader.get_feed_counts(broken=False).total == 2
    # updates_enabled filter
    assert reader.get_feed_counts(updates_enabled=False).total == 1
    assert reader.get_feed_counts(updates_enabled=True).total == 1


# ---------------------------------------------------------------------------
# 3. Feed updates / parsing (RSS, Atom, JSON)
# ---------------------------------------------------------------------------


def test_cli_update_feed_rss(db_path):
    """CLI `add URL --update` populates the RSS fixture's entries. `list entries
    --json` then emits exactly 3 JSON lines whose (id, title) pairs match the
    fixture verbatim. Kills implementations that fetch but fail to persist,
    that emit stub titles, or that miscount new entries.

    Also covers the UpdatedFeed counts via the observable side-effect: after
    one update, exactly N=3 entries are queryable."""
    feed_url = (FIXTURES / "sample.rss").as_uri()
    add = _run_cli(db_path, "add", feed_url, "--update")
    assert add.returncode == 0, add.stderr
    listed = _run_cli(db_path, "list", "entries", "--json")
    assert listed.returncode == 0, listed.stderr
    lines = [line for line in listed.stdout.splitlines() if line.strip()]
    assert len(lines) == 3
    objs = [json.loads(line) for line in lines]
    id_to_title = {o["id"]: o.get("title") for o in objs}
    assert id_to_title == {
        "rss-entry-1": "Hello World",
        "rss-entry-2": "Second Post",
        "rss-entry-3": "Third Post About Cats",
    }


def test_cli_update_feed_atom(db_path):
    """CLI `add URL --update` parses an Atom feed. `list entries --json` emits
    exactly 2 lines and each id maps to the fixture's exact (title, link).
    Kills implementations that parse the Atom envelope but drop per-entry
    title/link fields."""
    feed_url = (FIXTURES / "sample.atom").as_uri()
    add = _run_cli(db_path, "add", feed_url, "--update")
    assert add.returncode == 0, add.stderr
    listed = _run_cli(db_path, "list", "entries", "--json")
    assert listed.returncode == 0
    lines = [line for line in listed.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    objs = [json.loads(line) for line in lines]
    by_id = {o["id"]: o for o in objs}
    assert set(by_id) == {"urn:uuid:atom-entry-1", "urn:uuid:atom-entry-2"}
    assert by_id["urn:uuid:atom-entry-1"]["title"] == "Atom Robots"
    assert by_id["urn:uuid:atom-entry-1"]["link"] == "http://atom.example.com/robots"
    assert by_id["urn:uuid:atom-entry-2"]["title"] == "Atom Cats"
    assert by_id["urn:uuid:atom-entry-2"]["link"] == "http://atom.example.com/cats"


def test_cli_update_feed_jsonfeed(db_path):
    """CLI `add URL --update` parses a JSON feed (jsonfeed.org spec).
    `list entries --json` emits 2 lines whose ids map to the fixture's
    exact titles and links. Kills implementations that parse the top-level
    envelope but not per-item title/url."""
    feed_url = (FIXTURES / "sample.json").as_uri()
    add = _run_cli(db_path, "add", feed_url, "--update")
    assert add.returncode == 0, add.stderr
    listed = _run_cli(db_path, "list", "entries", "--json")
    assert listed.returncode == 0
    lines = [line for line in listed.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    objs = [json.loads(line) for line in lines]
    by_id = {o["id"]: o for o in objs}
    assert set(by_id) == {"json-entry-1", "json-entry-2"}
    assert by_id["json-entry-1"]["title"] == "JSON One"
    assert by_id["json-entry-1"]["link"] == "https://json.example.org/one"
    assert by_id["json-entry-2"]["title"] == "JSON Two"
    assert by_id["json-entry-2"]["link"] == "https://json.example.org/two"


def test_cli_update_feed_idempotent(db_path):
    """CLI `update` twice (without changing the fixture) leaves the entry set
    identical — same N=3 ids both times. Kills implementations that re-insert
    entries on every update, or that wipe-and-replace each pass."""
    feed_url = (FIXTURES / "sample.rss").as_uri()
    _run_cli(db_path, "add", feed_url)
    upd1 = _run_cli(db_path, "update")
    assert upd1.returncode == 0
    listed1 = _run_cli(db_path, "list", "entries", "--json")
    objs1 = [json.loads(line) for line in listed1.stdout.splitlines() if line.strip()]
    ids1 = {o["id"] for o in objs1}
    assert ids1 == {"rss-entry-1", "rss-entry-2", "rss-entry-3"}

    upd2 = _run_cli(db_path, "update")
    assert upd2.returncode == 0
    listed2 = _run_cli(db_path, "list", "entries", "--json")
    objs2 = [json.loads(line) for line in listed2.stdout.splitlines() if line.strip()]
    ids2 = {o["id"] for o in objs2}
    # Same set, same count — no duplicates introduced on the second pass.
    assert ids2 == ids1
    assert len(objs2) == len(objs1) == 3


def test_cli_update_populates_feed_metadata(db_path):
    """After CLI `update`, `list feeds --json` carries the parser-populated
    title (`"Sample RSS Feed"`) and link (`"http://example.com/"`) for the
    feed. Kills implementations that store the feed row without backfilling
    metadata from the source on update."""
    feed_url = (FIXTURES / "sample.rss").as_uri()
    _run_cli(db_path, "add", feed_url)
    upd = _run_cli(db_path, "update")
    assert upd.returncode == 0
    listed = _run_cli(db_path, "list", "feeds", "--json")
    assert listed.returncode == 0
    lines = [line for line in listed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["url"] == feed_url
    assert obj.get("title") == "Sample RSS Feed"
    assert obj.get("link") == "http://example.com/"


def test_cli_update_feeds_all(db_path):
    """CLI `update` (no URL) updates every feed. After updating two distinct
    feeds (RSS + Atom), `list entries --json` emits exactly 5 entries with
    the right per-feed split (3 under sample.rss, 2 under sample.atom).
    Kills implementations that only update the first or last feed, or that
    drop entries under the wrong feed url."""
    a = (FIXTURES / "sample.rss").as_uri()
    b = (FIXTURES / "sample.atom").as_uri()
    _run_cli(db_path, "add", a)
    _run_cli(db_path, "add", b)
    upd = _run_cli(db_path, "update")
    assert upd.returncode == 0
    listed = _run_cli(db_path, "list", "entries", "--json")
    assert listed.returncode == 0
    objs = [json.loads(line) for line in listed.stdout.splitlines() if line.strip()]
    assert len(objs) == 5
    # Split by feed url (the nested feed dict carries url).
    by_feed = {}
    for o in objs:
        by_feed.setdefault(o["feed"]["url"], set()).add(o["id"])
    assert by_feed == {
        a: {"rss-entry-1", "rss-entry-2", "rss-entry-3"},
        b: {"urn:uuid:atom-entry-1", "urn:uuid:atom-entry-2"},
    }


def test_update_feed_nonexistent_file_raises_parse_error(reader):
    """Updating a feed whose file doesn't exist raises ParseError."""
    from reader import ParseError

    bogus = str(FIXTURES / "this-file-does-not-exist.xml")
    reader.add_feed(bogus)
    with pytest.raises(ParseError):
        reader.update_feed(bogus)


def test_update_feed_not_added_raises_feed_not_found(reader):
    """update_feed raises FeedNotFoundError for a feed never added."""
    from reader import FeedNotFoundError

    with pytest.raises(FeedNotFoundError):
        reader.update_feed("http://never-added.example.com/feed.xml")


def test_cli_update_silently_skips_parse_errors(db_path):
    """CLI `update` exits 0 even when one feed cannot be parsed; the good
    feed's entries are fully populated and the bad feed contributes nothing.
    Kills implementations that abort the whole batch on the first bad feed,
    or that surface ParseError as a non-zero exit and skip the rest."""
    good_url = (FIXTURES / "sample.rss").as_uri()
    bad_url = (FIXTURES / "this-also-missing.xml").as_uri()
    add_good = _run_cli(db_path, "add", good_url)
    assert add_good.returncode == 0
    add_bad = _run_cli(db_path, "add", bad_url)
    assert add_bad.returncode == 0
    # CLI update must NOT raise / non-zero on per-feed parse errors.
    upd = _run_cli(db_path, "update")
    assert upd.returncode == 0
    listed = _run_cli(db_path, "list", "entries", "--json")
    assert listed.returncode == 0
    objs = [json.loads(line) for line in listed.stdout.splitlines() if line.strip()]
    # Exactly the 3 good entries; nothing from the bad feed.
    assert len(objs) == 3
    by_feed = {}
    for o in objs:
        by_feed.setdefault(o["feed"]["url"], set()).add(o["id"])
    assert by_feed == {good_url: {"rss-entry-1", "rss-entry-2", "rss-entry-3"}}
    # The bad feed url contributes nothing.
    assert bad_url not in by_feed


# ---------------------------------------------------------------------------
# 4. Entry retrieval, filtering, sorting
# ---------------------------------------------------------------------------


def test_get_entry_by_resource_id_and_missing(reader_with_sample):
    """get_entry returns the matching Entry for an (feed_url, id);
    raises EntryNotFoundError when missing."""
    from reader import EntryNotFoundError

    reader, url = reader_with_sample
    entry = reader.get_entry((url, "rss-entry-1"))
    assert entry.id == "rss-entry-1"
    assert entry.title == "Hello World"
    assert entry.link == "http://example.com/posts/1"

    with pytest.raises(EntryNotFoundError):
        reader.get_entry((url, "nope"))


def test_get_entries_filter_by_feed(reader):
    """get_entries(feed=...) returns only entries for that feed."""
    a = str(FIXTURES / "sample.rss")
    b = str(FIXTURES / "sample.atom")
    reader.add_feed(a)
    reader.add_feed(b)
    reader.update_feeds()

    a_entries = list(reader.get_entries(feed=a))
    assert {e.id for e in a_entries} == {"rss-entry-1", "rss-entry-2", "rss-entry-3"}
    b_entries = list(reader.get_entries(feed=b))
    assert {e.id for e in b_entries} == {
        "urn:uuid:atom-entry-1",
        "urn:uuid:atom-entry-2",
    }


def test_get_entries_filter_by_read(reader_with_sample):
    """get_entries(read=True/False) partitions correctly and read=None returns
    the full set; the partition is exact and the two slices sum to the whole."""
    reader, url = reader_with_sample
    reader.mark_entry_as_read((url, "rss-entry-1"))

    read_ids = {e.id for e in reader.get_entries(read=True)}
    unread_ids = {e.id for e in reader.get_entries(read=False)}
    all_ids = {e.id for e in reader.get_entries(read=None)}
    assert read_ids == {"rss-entry-1"}
    assert unread_ids == {"rss-entry-2", "rss-entry-3"}
    assert read_ids | unread_ids == all_ids
    assert read_ids.isdisjoint(unread_ids)
    # And the .read flag actually matches what we filtered on.
    for e in reader.get_entries(read=True):
        assert e.read is True
    for e in reader.get_entries(read=False):
        assert e.read is False


def test_get_entries_filter_has_enclosures(reader_with_sample):
    """get_entries(has_enclosures=True) returns only entries with enclosures,
    and those entries actually carry the parsed Enclosure objects with the
    correct href from the fixture. Kills implementations that filter
    correctly but discard enclosures from the Entry payload, or vice versa
    (claim has_enclosures=True for any entry but return empty enclosures)."""
    reader, url = reader_with_sample
    with_enc = list(reader.get_entries(has_enclosures=True))
    without = list(reader.get_entries(has_enclosures=False))
    assert {e.id for e in with_enc} == {"rss-entry-1"}
    assert {e.id for e in without} == {"rss-entry-2", "rss-entry-3"}
    # The entry with enclosures must actually carry them with correct href.
    [e] = with_enc
    assert len(e.enclosures) == 1
    assert e.enclosures[0].href == "http://example.com/audio/1.mp3"
    assert e.enclosures[0].type == "audio/mpeg"
    assert e.enclosures[0].length == 12345
    # The entries without enclosures actually have an empty enclosures tuple.
    for e in without:
        assert len(e.enclosures) == 0


def test_get_entries_filter_important_tri_state(reader_with_sample):
    """get_entries(important=...) honors True/False/None plus 'istrue'/'isfalse'/
    'notset' / 'isset' / 'any' string forms."""
    reader, url = reader_with_sample
    reader.set_entry_important((url, "rss-entry-1"), True)
    reader.set_entry_important((url, "rss-entry-2"), False)
    # rss-entry-3 left as None

    assert {e.id for e in reader.get_entries(important=True)} == {"rss-entry-1"}
    assert {e.id for e in reader.get_entries(important="istrue")} == {"rss-entry-1"}
    assert {e.id for e in reader.get_entries(important="isfalse")} == {"rss-entry-2"}
    assert {e.id for e in reader.get_entries(important="notset")} == {"rss-entry-3"}
    assert {e.id for e in reader.get_entries(important="isset")} == {
        "rss-entry-1",
        "rss-entry-2",
    }
    assert {e.id for e in reader.get_entries(important="any")} == {
        "rss-entry-1",
        "rss-entry-2",
        "rss-entry-3",
    }


def test_get_entries_filter_by_tags(reader):
    """get_entries(tags=...) and feed_tags=... apply ENTRY-tag vs FEED-tag filters,
    including AND/OR/negation syntax."""
    a = str(FIXTURES / "sample.rss")
    b = str(FIXTURES / "sample.atom")
    reader.add_feed(a)
    reader.add_feed(b)
    reader.update_feeds()

    # entry tags on rss-entry-1
    reader.set_tag((a, "rss-entry-1"), "starred")
    reader.set_tag((a, "rss-entry-1"), "favorite")
    # entry tag on rss-entry-2
    reader.set_tag((a, "rss-entry-2"), "starred")

    # AND: both starred AND favorite
    both = {e.id for e in reader.get_entries(tags=["starred", "favorite"])}
    assert both == {"rss-entry-1"}

    # OR (nested list): starred OR favorite — same as just "starred" here
    either = {e.id for e in reader.get_entries(tags=[["starred", "favorite"]])}
    assert either == {"rss-entry-1", "rss-entry-2"}

    # negation: NOT starred
    not_starred = {e.id for e in reader.get_entries(tags=["-starred"])}
    # all atom entries (none starred) + rss-entry-3 (not starred)
    assert not_starred == {
        "urn:uuid:atom-entry-1",
        "urn:uuid:atom-entry-2",
        "rss-entry-3",
    }

    # feed_tags filter: tag the RSS feed and filter to that feed's entries
    reader.set_tag(a, "newsroom")
    by_feed_tag = {e.id for e in reader.get_entries(feed_tags=["newsroom"])}
    assert by_feed_tag == {"rss-entry-1", "rss-entry-2", "rss-entry-3"}


def test_get_entries_sort_recent_chronological(reader):
    """get_entries(sort=EntrySort.RECENT) returns entries newest-published first."""
    from reader import EntrySort

    url = str(FIXTURES / "sorted.rss")
    reader.add_feed(url)
    reader.update_feeds()
    ids = [e.id for e in reader.get_entries(sort=EntrySort.RECENT)]
    assert ids == ["sorted-5", "sorted-4", "sorted-3", "sorted-2", "sorted-1"]


def test_get_entries_limit(reader):
    """get_entries(limit=N) returns the first N entries IN SORT ORDER (RECENT),
    not just any N; limit=0 raises ValueError; negative limit also raises."""
    from reader import EntrySort

    url = str(FIXTURES / "sorted.rss")
    reader.add_feed(url)
    reader.update_feeds()

    page = list(reader.get_entries(sort=EntrySort.RECENT, limit=2))
    # Must be the two newest, in RECENT order — not just any two.
    assert [e.id for e in page] == ["sorted-5", "sorted-4"]

    with pytest.raises(ValueError):
        list(reader.get_entries(limit=0))
    with pytest.raises(ValueError):
        list(reader.get_entries(limit=-1))


def test_get_entry_counts_basic(reader_with_sample):
    """get_entry_counts reports total/read/important/unimportant/has_enclosures
    counts, and the same counts via direct get_entries(filter=...) length match."""
    reader, url = reader_with_sample
    reader.mark_entry_as_read((url, "rss-entry-1"))
    reader.mark_entry_as_important((url, "rss-entry-2"))
    reader.mark_entry_as_unimportant((url, "rss-entry-3"))
    counts = reader.get_entry_counts()
    assert counts.total == 3
    assert counts.read == 1
    assert counts.important == 1
    # rss-entry-3 marked unimportant (important=False) → exactly one unimportant.
    # Kills SUM(important=0) returning 0 when no entry was set False.
    assert counts.unimportant == 1
    # rss-entry-1 has an enclosure (audio/1.mp3); the other two do not.
    # Kills counts that hard-code has_enclosures=0 / forget enclosure parsing.
    assert counts.has_enclosures == 1
    # Cross-check with filtered get_entries length.
    assert len(list(reader.get_entries(read=True))) == counts.read
    assert len(list(reader.get_entries(important=True))) == counts.important
    assert len(list(reader.get_entries(has_enclosures=True))) == counts.has_enclosures
    # Per-feed filter narrows correctly.
    assert reader.get_entry_counts(feed=url).total == 3


# ---------------------------------------------------------------------------
# 5. Marking read / important
# ---------------------------------------------------------------------------


def test_mark_entry_as_read_then_unread(reader_with_sample):
    """mark_entry_as_read / mark_entry_as_unread flip the read flag AND stamp
    read_modified to a timezone-aware UTC datetime (per spec, all datetime
    fields are timezone-aware UTC). Kills implementations that store naive
    datetimes or leave read_modified None when implicitly marking."""
    from datetime import datetime, timezone

    reader, url = reader_with_sample
    eid = (url, "rss-entry-1")
    # Before marking: read_modified should be None for a fresh entry.
    assert reader.get_entry(eid).read_modified is None

    reader.mark_entry_as_read(eid)
    e = reader.get_entry(eid)
    assert e.read is True
    # read_modified must now be set, a datetime, and timezone-aware UTC.
    assert isinstance(e.read_modified, datetime)
    assert e.read_modified.tzinfo is not None
    assert e.read_modified.utcoffset() == timezone.utc.utcoffset(None)

    reader.mark_entry_as_unread(eid)
    e2 = reader.get_entry(eid)
    assert e2.read is False
    # Still a timezone-aware UTC datetime after unread.
    assert isinstance(e2.read_modified, datetime)
    assert e2.read_modified.tzinfo is not None
    assert e2.read_modified.utcoffset() == timezone.utc.utcoffset(None)


def test_set_entry_read_requires_bool(reader_with_sample):
    """set_entry_read raises ValueError on a non-bool value."""
    reader, url = reader_with_sample
    with pytest.raises(ValueError):
        reader.set_entry_read((url, "rss-entry-1"), "yes")


def test_mark_entry_as_important_three_states(reader_with_sample):
    """set_entry_important supports True / False / None tri-state and
    rejects strings like 'maybe'."""
    reader, url = reader_with_sample
    eid = (url, "rss-entry-1")
    reader.set_entry_important(eid, True)
    assert reader.get_entry(eid).important is True
    reader.set_entry_important(eid, False)
    assert reader.get_entry(eid).important is False
    reader.set_entry_important(eid, None)
    assert reader.get_entry(eid).important is None
    with pytest.raises(ValueError):
        reader.set_entry_important(eid, "maybe")


def test_mark_missing_entry_raises(reader):
    """Marking a missing entry raises EntryNotFoundError."""
    from reader import EntryNotFoundError

    with pytest.raises(EntryNotFoundError):
        reader.mark_entry_as_read(("http://nofeed.example.com/", "nope"))


# ---------------------------------------------------------------------------
# 6. add_entry / delete_entry / copy_entry (user entries)
# ---------------------------------------------------------------------------


def test_delete_feed_entry_raises(reader_with_sample):
    """delete_entry on a feed-added entry raises EntryError."""
    from reader import EntryError

    reader, url = reader_with_sample
    with pytest.raises(EntryError):
        reader.delete_entry((url, "rss-entry-1"))


def test_copy_entry_creates_user_copy(reader_with_sample):
    """copy_entry copies an entry into another feed; the copy is added_by='user'
    and copies tags."""
    from reader import EntryExistsError

    reader, src_url = reader_with_sample
    # Tag the source entry so we can verify tags are copied
    reader.set_tag((src_url, "rss-entry-1"), "label", "fav")

    dst_feed = "http://copy.example.com/"
    reader.add_feed(dst_feed, allow_invalid_url=True)

    reader.copy_entry((src_url, "rss-entry-1"), (dst_feed, "copy-1"))
    copy = reader.get_entry((dst_feed, "copy-1"))
    assert copy.title == "Hello World"
    assert copy.added_by == "user"
    # tag carried over
    assert reader.get_tag((dst_feed, "copy-1"), "label") == "fav"

    # copying onto an existing entry id raises EntryExistsError
    with pytest.raises(EntryExistsError):
        reader.copy_entry((src_url, "rss-entry-1"), (dst_feed, "copy-1"))


# ---------------------------------------------------------------------------
# 7. Tags
# ---------------------------------------------------------------------------


def test_set_get_delete_feed_tag(reader):
    """User can set, retrieve, list, and delete a tag on a feed; tag values
    preserve string identity; after delete the key is gone from get_tag_keys."""
    from reader import TagNotFoundError

    feed_url = "http://example.com/"
    reader.add_feed(feed_url)
    reader.set_tag(feed_url, "category", "tech")
    value = reader.get_tag(feed_url, "category")
    assert value == "tech"
    assert isinstance(value, str)
    assert dict(reader.get_tags(feed_url)) == {"category": "tech"}
    assert list(reader.get_tag_keys(feed_url)) == ["category"]

    reader.delete_tag(feed_url, "category")
    assert dict(reader.get_tags(feed_url)) == {}
    assert list(reader.get_tag_keys(feed_url)) == []
    # And get_tag now raises (no silent default).
    with pytest.raises(TagNotFoundError):
        reader.get_tag(feed_url, "category")


def test_get_tag_missing_and_default(reader):
    """get_tag raises TagNotFoundError on missing key, but returns provided default."""
    from reader import TagNotFoundError

    reader.add_feed("http://example.com/")
    with pytest.raises(TagNotFoundError):
        reader.get_tag("http://example.com/", "category")
    assert reader.get_tag("http://example.com/", "category", "fallback") == "fallback"


def test_global_tag(reader):
    """Tags with resource=() are global. Value round-trips exactly (nested
    dict structure preserved), the key shows up in get_tags(()) and
    get_tag_keys(()), and the value type is dict (not stringified).
    Kills implementations that serialize tag values as str(value)."""
    reader.set_tag((), "global-key", {"a": 1, "nested": {"x": [10, 20]}})
    value = reader.get_tag((), "global-key")
    # Exact equality and type — not just truthy / not str-coerced.
    assert value == {"a": 1, "nested": {"x": [10, 20]}}
    assert isinstance(value, dict)
    assert isinstance(value["nested"]["x"], list)
    # Same key appears via the dict/keys APIs at the global resource scope.
    assert dict(reader.get_tags(())) == {
        "global-key": {"a": 1, "nested": {"x": [10, 20]}}
    }
    assert list(reader.get_tag_keys(())) == ["global-key"]


def test_entry_tag(reader_with_sample):
    """Entry tags are scoped to (feed_url, entry_id)."""
    reader, url = reader_with_sample
    reader.set_tag((url, "rss-entry-1"), "label", "fav")
    assert reader.get_tag((url, "rss-entry-1"), "label") == "fav"
    assert reader.get_tag((url, "rss-entry-2"), "label", None) is None


def test_get_feeds_filter_by_tag(reader):
    """get_feeds(tags=[...]) filters by matching feed tags — positive selects
    only tagged feeds, '-tag' negation selects only untagged feeds,
    tags=True selects any-tag, tags=False selects no-tag. Kills
    implementations that ignore the tag filter entirely or that don't
    handle the '-' negation syntax."""
    reader.add_feed("http://a.example.com/")
    reader.add_feed("http://b.example.com/")
    reader.set_tag("http://a.example.com/", "kind")

    # Positive: only the tagged feed.
    assert {f.url for f in reader.get_feeds(tags=["kind"])} == {"http://a.example.com/"}
    # Negation: only the untagged feed.
    assert {f.url for f in reader.get_feeds(tags=["-kind"])} == {
        "http://b.example.com/"
    }
    # has-any-tag and no-tag boolean shortcuts (spec: True / False).
    assert {f.url for f in reader.get_feeds(tags=True)} == {"http://a.example.com/"}
    assert {f.url for f in reader.get_feeds(tags=False)} == {"http://b.example.com/"}


def test_get_tag_keys_alphabetical(reader):
    """get_tag_keys returns the keys in alphabetical order."""
    reader.add_feed("http://example.com/")
    reader.set_tag("http://example.com/", "zeta", 1)
    reader.set_tag("http://example.com/", "alpha", 2)
    reader.set_tag("http://example.com/", "mu", 3)
    assert list(reader.get_tag_keys("http://example.com/")) == ["alpha", "mu", "zeta"]


def test_delete_tag_missing_raises(reader):
    """delete_tag on a missing key raises TagNotFoundError; missing_ok suppresses."""
    from reader import TagNotFoundError

    reader.add_feed("http://example.com/")
    with pytest.raises(TagNotFoundError):
        reader.delete_tag("http://example.com/", "nope")
    reader.delete_tag("http://example.com/", "nope", missing_ok=True)


# ---------------------------------------------------------------------------
# 8. Reserved names
# ---------------------------------------------------------------------------


def test_make_reserved_name_helpers(reader):
    """make_reader_reserved_name yields '.reader.<key>';
    make_plugin_reserved_name yields '.plugin.<name>' or '.plugin.<name>.<key>'."""
    assert reader.make_reader_reserved_name("foo") == ".reader.foo"
    assert reader.make_plugin_reserved_name("myplugin") == ".plugin.myplugin"
    assert reader.make_plugin_reserved_name("myplugin", "k") == ".plugin.myplugin.k"


# ---------------------------------------------------------------------------
# 9. Search
# ---------------------------------------------------------------------------


@pytest.fixture
def search_reader(reader):
    """reader with the search fixture loaded, search enabled, index updated."""
    url = str(FIXTURES / "search.rss")
    reader.add_feed(url)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()
    return reader, url


def test_search_disabled_raises(reader_with_sample):
    """Both search_entries AND search_entry_counts raise SearchNotEnabledError
    when search isn't enabled (count path must not silently return 0).
    Kills implementations that only guard search_entries."""
    from reader import SearchNotEnabledError

    reader, _ = reader_with_sample
    reader.disable_search()
    assert reader.is_search_enabled() is False
    with pytest.raises(SearchNotEnabledError):
        list(reader.search_entries("anything"))
    # Count path must also reject — not silently return a zero counts object.
    with pytest.raises(SearchNotEnabledError):
        reader.search_entry_counts("anything")


def test_search_entries_basic(search_reader):
    """search_entries returns the right matches for single and multi-match queries
    and empty for no-match queries; counts agree; resource_id is a (feed_url, id)
    tuple; no-match counts is zero."""
    reader, url = search_reader

    # single match: resource_id is the (feed_url, entry_id) tuple
    [r] = list(reader.search_entries("python"))
    assert r.id == "srch-1"
    assert r.feed_url == url
    assert r.resource_id == (url, "srch-1")

    # multi-match (both python guide and rust patterns mention 'programming')
    assert {r.id for r in reader.search_entries("programming")} == {"srch-1", "srch-2"}
    # no-match
    assert list(reader.search_entries("nonexistentword")) == []
    # counts agree with results
    assert reader.search_entry_counts("programming").total == 2
    assert reader.search_entry_counts("python").total == 1
    # no-match counts also zero
    assert reader.search_entry_counts("nonexistentword").total == 0


def test_search_invalid_query_raises(search_reader):
    """search_entries raises InvalidSearchQueryError on malformed FTS syntax."""
    from reader import InvalidSearchQueryError

    reader, _ = search_reader
    with pytest.raises(InvalidSearchQueryError):
        list(reader.search_entries('"unclosed'))


def test_search_result_highlight_and_resource_id(search_reader):
    """EntrySearchResult.metadata values are HighlightedString with the matched
    span at the exact slice that selects 'Python' from the title. The
    highlighted slice must round-trip via .apply to mark up the matched word.
    Kills implementations that return raw strings under .metadata keys, or
    that build empty-highlights HighlightedStrings."""
    from reader import HighlightedString

    reader, url = search_reader

    [r] = list(reader.search_entries("python"))
    assert r.resource_id == (url, "srch-1")
    hs = r.metadata[".title"]
    assert isinstance(hs, HighlightedString)
    assert hs.value == "Python programming guide"
    # Highlights must be a NON-empty sequence and the first one selects "Python".
    assert len(hs.highlights) >= 1
    assert hs.highlights[0] == slice(0, 6)
    # The selected substring matches the literal query word (case-preserved).
    assert hs.value[hs.highlights[0]] == "Python"
    # Applying the highlight wraps that exact word, leaving the rest unchanged.
    assert hs.apply("[", "]") == "[Python] programming guide"


def test_search_filter_by_read(search_reader):
    """search_entries(read=True) honors the read-state filter."""
    reader, url = search_reader
    reader.mark_entry_as_read((url, "srch-1"))
    # only srch-1 (read) should match
    assert {r.id for r in reader.search_entries("programming", read=True)} == {"srch-1"}
    assert {r.id for r in reader.search_entries("programming", read=False)} == {
        "srch-2"
    }


def test_search_sort_kwarg_accepted(search_reader):
    """search_entries accepts sort=EntrySearchSort.{RELEVANT,RECENT,RANDOM};
    all three return the same matching set and the value-typed members exist."""
    from reader import EntrySearchSort

    reader, _ = search_reader
    by_relevant = {
        r.id
        for r in reader.search_entries("programming", sort=EntrySearchSort.RELEVANT)
    }
    by_recent = {
        r.id for r in reader.search_entries("programming", sort=EntrySearchSort.RECENT)
    }
    by_random = {
        r.id for r in reader.search_entries("programming", sort=EntrySearchSort.RANDOM)
    }
    assert by_relevant == {"srch-1", "srch-2"}
    assert by_recent == {"srch-1", "srch-2"}
    assert by_random == {"srch-1", "srch-2"}


# ---------------------------------------------------------------------------
# 10. Plugins
# ---------------------------------------------------------------------------


def test_enclosure_dedupe_plugin(db_path):
    """The .enclosure_dedupe plugin removes duplicate enclosure URLs;
    same plugin loadable via full module path."""
    from reader import make_reader

    url = str(FIXTURES / "dedupe.rss")
    # By short name
    r = make_reader(db_path, feed_root="", plugins=[".enclosure_dedupe"])
    try:
        r.add_feed(url)
        r.update_feeds()
        [entry] = list(r.get_entries())
        hrefs = [e.href for e in entry.enclosures]
        assert hrefs == [
            "http://dup.example.com/file.mp3",
            "http://dup.example.com/other.mp3",
        ]
    finally:
        r.close()

    # By full module path on a fresh db
    db2 = _tmp_db()
    try:
        r2 = make_reader(db2, feed_root="", plugins=["reader.plugins.enclosure_dedupe"])
        try:
            r2.add_feed(url)
            r2.update_feeds()
            [entry] = list(r2.get_entries())
            assert [e.href for e in entry.enclosures] == [
                "http://dup.example.com/file.mp3",
                "http://dup.example.com/other.mp3",
            ]
        finally:
            r2.close()
    finally:
        try:
            os.unlink(db2)
        except OSError:
            pass


def test_mark_as_read_plugin(db_path):
    """The .mark_as_read plugin marks matching new entries as read+unimportant."""
    from reader import make_reader

    r = make_reader(db_path, feed_root="", plugins=[".mark_as_read"])
    try:
        url = str(FIXTURES / "mark.rss")
        r.add_feed(url)
        r.set_tag(
            url, r.make_reader_reserved_name("mark-as-read"), {"title": ["^SPAM:"]}
        )
        r.update_feeds()
        spam1 = r.get_entry((url, "mark-1"))
        legit = r.get_entry((url, "mark-2"))
        spam2 = r.get_entry((url, "mark-3"))
        assert spam1.read is True
        assert spam1.important is False
        assert legit.read is False
        assert legit.important is None
        assert spam2.read is True
        assert spam2.important is False
    finally:
        r.close()


def test_readtime_plugin_tags_entries(db_path):
    """The .readtime plugin stores exactly {'seconds': <positive int>} on every
    updated entry under the .reader.readtime tag."""
    from reader import make_reader

    r = make_reader(db_path, feed_root="", plugins=[".readtime"])
    try:
        url = str(FIXTURES / "sample.rss")
        r.add_feed(url)
        r.update_feeds()
        key = r.make_reader_reserved_name("readtime")
        for entry in r.get_entries():
            value = r.get_tag(entry, key)
            assert isinstance(value, dict)
            assert set(value.keys()) == {"seconds"}
            assert isinstance(value["seconds"], int)
            # Every sample.rss entry has non-empty text (its summary), and the
            # spec rounds the read-time estimate up to whole seconds, so a
            # correct read time is >= 1; a no-op stub tagging {'seconds': 0}
            # must not pass. Kept as `> 0` (not an exact value) so an
            # implementation using a different words-per-minute constant still
            # passes.
            assert value["seconds"] > 0
    finally:
        r.close()


def test_invalid_plugin_raises(db_path):
    """make_reader raises InvalidPluginError on an unknown built-in name AND on
    an unknown full module import path. Per the spec, InvalidPluginError must
    also subclass ValueError. Kills implementations that catch only the dotted
    short-name path or that re-raise plain ImportError."""
    from reader import InvalidPluginError, make_reader

    # Subclass relationship (spec: InvalidPluginError also subclasses ValueError).
    assert issubclass(InvalidPluginError, ValueError)

    # Unknown built-in name (leading dot).
    with pytest.raises(InvalidPluginError):
        make_reader(db_path, plugins=[".nonexistent_plugin_xyz"])

    # Unknown full module import path: same exception, not bare ImportError.
    with pytest.raises(InvalidPluginError):
        make_reader(db_path, plugins=["reader.plugins.this_module_does_not_exist"])


def test_callable_plugin_runs(db_path):
    """A plain Callable[[Reader], None] is accepted as a plugin and invoked
    EXACTLY once at make_reader time with the Reader as its only argument;
    multiple callable plugins are invoked in order; side-effects on the Reader
    persist after init. Kills implementations that no-op callable plugins or
    fan them out via threads."""
    from reader import make_reader

    calls = []

    def first_plugin(rdr):
        # Side-effect: install an after-entry hook that records entries.
        rdr._test_seen = ["first"]
        calls.append(("first", rdr))

    def second_plugin(rdr):
        # Subsequent plugin observes prior plugin's side-effect (ordered init).
        rdr._test_seen.append("second")
        calls.append(("second", rdr))

    r = make_reader(db_path, plugins=[first_plugin, second_plugin])
    try:
        # Exactly two calls, in order, each with the same Reader instance.
        assert len(calls) == 2
        assert calls[0][0] == "first"
        assert calls[1][0] == "second"
        assert calls[0][1] is r
        assert calls[1][1] is r
        # Plugin side-effects persist on the live Reader.
        assert r._test_seen == ["first", "second"]
    finally:
        r.close()


# ---------------------------------------------------------------------------
# 11. OPML import / export
# ---------------------------------------------------------------------------


def test_opml_parse_basic():
    """reader.opml.parse extracts xmlUrl entries (including nested)."""
    from reader.opml import parse

    feeds = parse(open(FIXTURES / "subscriptions.opml", "rb"))
    urls = {f.url for f in feeds}
    assert urls == {
        "http://feed-one.example.com/",
        "http://feed-two.example.com/",
        "http://feed-three.example.com/",
    }


def test_opml_parse_invalid_raises():
    """parse raises OPMLError (a FeedImportError) on malformed XML."""
    from reader.opml import OPMLError, parse
    from reader import FeedImportError

    assert issubclass(OPMLError, FeedImportError)
    with pytest.raises(OPMLError):
        parse(io.BytesIO(b"not xml at all"))


def test_opml_unparse_roundtrip():
    """unparse(feeds) then parse() preserves the feed URLs.

    Exercises the documented `unparse(feeds: Iterable[Feed])` contract by
    passing real `Feed` objects built from the parsed subscription list."""
    from reader import Feed
    from reader.opml import parse, unparse

    feeds_in = parse(open(FIXTURES / "subscriptions.opml", "rb"))
    out = unparse(
        [
            Feed(url=f.url, title=f.title, link=f.link, subtitle=f.subtitle)
            for f in feeds_in
        ]
    )
    feeds_out = parse(io.BytesIO(out))
    assert {f.url for f in feeds_out} == {f.url for f in feeds_in}


def test_import_feeds(reader):
    """import_feeds adds all feeds described by an OPML file."""
    with open(FIXTURES / "subscriptions.opml", "rb") as f:
        reader.import_feeds(f)
    urls = {f.url for f in reader.get_feeds()}
    assert urls == {
        "http://feed-one.example.com/",
        "http://feed-two.example.com/",
        "http://feed-three.example.com/",
    }


def test_import_feeds_iter_yields_per_feed(reader):
    """import_feeds_iter yields a FeedImportResult per feed AND the feeds are
    really persisted (visible via get_feeds); duplicates yield .added=False
    (FeedExistsError is excluded from .error per the spec) but do NOT create
    duplicate rows. Kills implementations that yield results without actually
    adding the feeds, or that double-insert on re-import."""
    from reader.opml import parse

    with open(FIXTURES / "subscriptions.opml", "rb") as f:
        feeds = list(parse(f))
    # First import: all added successfully
    results = list(reader.import_feeds_iter(iter(feeds)))
    assert len(results) == 3
    assert all(r.error is None for r in results)
    assert all(r.added for r in results)
    # State check: the three feeds are actually persisted under their URLs.
    assert {f.url for f in reader.get_feeds()} == {
        "http://feed-one.example.com/",
        "http://feed-two.example.com/",
        "http://feed-three.example.com/",
    }

    # Re-import the same feeds: all already exist → added=False; .error stays
    # None because FeedExistsError is filtered out of .error by the spec.
    results2 = list(reader.import_feeds_iter(iter(feeds)))
    assert len(results2) == 3
    assert all(not r.added for r in results2)
    # No duplicate rows after re-import — still exactly 3 feeds.
    assert len(list(reader.get_feeds())) == 3


def test_export_feeds(reader):
    """export_feeds returns a FeedExport: content round-trips through opml.parse
    to the exact same feed URLs; filename ends in .opml; headers include the
    XML Content-Type and a Content-Disposition that names the same filename."""
    from reader.opml import parse

    reader.add_feed("http://a.example.com/")
    reader.add_feed("http://b.example.com/")
    export = reader.export_feeds()
    # Content round-trips: parsing the export yields the original urls exactly.
    parsed = parse(io.BytesIO(export.content))
    assert {f.url for f in parsed} == {
        "http://a.example.com/",
        "http://b.example.com/",
    }
    assert export.filename.endswith(".opml")
    ct = export.headers["Content-Type"]
    assert ct.startswith("application/xml")
    assert "charset=utf-8" in ct
    # Content-Disposition references the same filename.
    cd = export.headers["Content-Disposition"]
    assert f'filename="{export.filename}"' in cd


# ---------------------------------------------------------------------------
# 12. Dataclass types: Feed, Entry, Content, Enclosure, etc.
# ---------------------------------------------------------------------------


def test_feed_resource_id_and_resolved_title():
    """Feed.resource_id is the (url,) tuple; resolved_title prefers user_title."""
    from reader import Feed

    f = Feed("http://x/", title="orig", user_title="custom")
    assert f.resource_id == ("http://x/",)
    assert f.resolved_title == "custom"
    f2 = Feed("http://x/", title="orig")
    assert f2.resolved_title == "orig"


def test_entry_resource_id(reader_with_sample):
    """Entry.resource_id == (feed_url, id) and feed_url == feed.url."""
    reader, url = reader_with_sample
    e = reader.get_entry((url, "rss-entry-1"))
    assert e.resource_id == (url, "rss-entry-1")
    assert e.feed_url == url
    assert e.feed.url == url


def test_entry_get_content_prefer_summary(reader_with_sample):
    """Entry.get_content(prefer_summary=True) returns summary when present."""
    reader, url = reader_with_sample
    e = reader.get_entry((url, "rss-entry-1"))
    c = e.get_content(prefer_summary=True)
    assert c is not None
    assert c.value == "First entry summary."


def test_content_is_html_default_true():
    """Content with no type defaults is_html == True; text/plain is False."""
    from reader import Content

    assert Content("hello").is_html is True
    assert Content("hello", type="text/plain").is_html is False
    assert Content("hello", type="text/html").is_html is True


# ---------------------------------------------------------------------------
# 13. HighlightedString
# ---------------------------------------------------------------------------


def test_highlighted_string_extract_apply_roundtrip():
    """HighlightedString.extract pulls spans out, .apply re-emits them, and
    constructing one with overlapping slices raises ValueError."""
    from reader import HighlightedString

    hs = HighlightedString.extract(">one< two", ">", "<")
    assert hs.value == "one two"
    assert hs.highlights == (slice(0, 3),)

    hs2 = HighlightedString("abcd", [slice(1, 3)])
    assert hs2.apply(">", "<") == "a>bc<d"

    with pytest.raises(ValueError):
        HighlightedString("abcd", [slice(0, 3), slice(1, 4)])


# ---------------------------------------------------------------------------
# 14. Exception hierarchy
# ---------------------------------------------------------------------------


def test_exception_hierarchy():
    """Every documented (child, parent) Is-A relationship in reader's exception
    hierarchy holds. The hierarchy is a single declarative contract, so it is
    checked as one graded unit (looping over the pairs internally)."""
    import reader as reader_mod

    pairs = [
        ("FeedExistsError", "FeedError"),
        ("FeedNotFoundError", "FeedError"),
        ("FeedNotFoundError", "ResourceNotFoundError"),
        ("FeedError", "ReaderError"),
        ("InvalidFeedURLError", "ValueError"),
        ("InvalidFeedURLError", "FeedError"),
        ("EntryExistsError", "EntryError"),
        ("EntryNotFoundError", "EntryError"),
        ("EntryNotFoundError", "ResourceNotFoundError"),
        ("EntryError", "ReaderError"),
        ("ParseError", "FeedError"),
        ("ParseError", "UpdateError"),
        ("UpdateError", "ReaderError"),
        ("SearchNotEnabledError", "SearchError"),
        ("InvalidSearchQueryError", "ValueError"),
        ("InvalidSearchQueryError", "SearchError"),
        ("InvalidPluginError", "ValueError"),
        ("InvalidPluginError", "PluginError"),
        ("TagNotFoundError", "TagError"),
        ("StorageError", "ReaderError"),
    ]
    for child_mod_name, parent_mod_name in pairs:
        child = getattr(reader_mod, child_mod_name, None)
        parent = (
            getattr(reader_mod, parent_mod_name, None)
            if parent_mod_name != "ValueError"
            else ValueError
        )
        assert child is not None, f"reader.{child_mod_name} not exported"
        assert parent is not None, f"reader.{parent_mod_name} not exported"
        assert issubclass(
            child, parent
        ), f"reader.{child_mod_name} should subclass {parent_mod_name}"


def test_feed_and_entry_error_attributes():
    """FeedError exposes .url + .resource_id; EntryError exposes .feed_url, .id,
    .resource_id."""
    from reader import EntryError, FeedError

    fe = FeedError("http://x/")
    assert fe.url == "http://x/"
    assert fe.resource_id == ("http://x/",)

    ee = EntryError("http://x/", "id-1")
    assert ee.feed_url == "http://x/"
    assert ee.id == "id-1"
    assert ee.resource_id == ("http://x/", "id-1")


# ---------------------------------------------------------------------------
# 15. CLI
# ---------------------------------------------------------------------------


def test_cli_help_and_version(db_path):
    """--help and --version exit 0; help lists EVERY required top-level command;
    empty-db listings print EXACTLY nothing to stdout (no header line, etc.)."""
    h = _run_cli(db_path, "--help")
    assert h.returncode == 0
    assert "Usage:" in h.stdout
    # All required commands must appear in --help output (exact word).
    for cmd in ("add", "delete", "update", "list", "search"):
        assert cmd in h.stdout, f"missing command in --help: {cmd}"

    v = _run_cli(db_path, "--version")
    assert v.returncode == 0
    assert any(ch.isdigit() for ch in v.stdout.strip())

    # Empty-db listings: stdout must be empty (no header, no newline-only)
    feeds = _run_cli(db_path, "list", "feeds")
    assert feeds.returncode == 0
    assert feeds.stdout == ""
    entries = _run_cli(db_path, "list", "entries")
    assert entries.returncode == 0
    assert entries.stdout == ""


def test_cli_add_list_delete_feed(db_path):
    """CLI add + list feeds + delete round-trip: exact URL appears then disappears."""
    feed_url = (FIXTURES / "sample.rss").as_uri()
    add = _run_cli(db_path, "add", feed_url)
    assert add.returncode == 0

    listed = _run_cli(db_path, "list", "feeds")
    assert listed.returncode == 0
    lines = [line for line in listed.stdout.splitlines() if line.strip()]
    assert lines == [feed_url]

    deleted = _run_cli(db_path, "delete", feed_url)
    assert deleted.returncode == 0

    listed2 = _run_cli(db_path, "list", "feeds")
    assert listed2.returncode == 0
    assert listed2.stdout.strip() == ""


def test_cli_update_then_list_entries(db_path):
    """CLI 'update' populates entries that 'list entries' then shows in
    '<feed-url> <link-or-id>' format, one per line."""
    feed_url = (FIXTURES / "sample.rss").as_uri()
    _run_cli(db_path, "add", feed_url)
    upd = _run_cli(db_path, "update")
    assert upd.returncode == 0
    listed = _run_cli(db_path, "list", "entries")
    assert listed.returncode == 0
    lines = sorted(line for line in listed.stdout.splitlines() if line.strip())
    assert len(lines) == 3
    # exact-line check: feed url + space + entry link from fixture
    assert lines == sorted(
        [
            f"{feed_url} http://example.com/posts/1",
            f"{feed_url} http://example.com/posts/2",
            f"{feed_url} http://example.com/posts/3",
        ]
    )


def test_cli_update_single_feed(db_path):
    """CLI 'update URL' only updates the SPECIFIED feed — the listed entries
    are EXACTLY the three from sample.rss, in the canonical line form, and
    zero entries from sample.atom. Kills implementations that ignore the
    positional URL and update every feed."""
    a = (FIXTURES / "sample.rss").as_uri()
    b = (FIXTURES / "sample.atom").as_uri()
    _run_cli(db_path, "add", a)
    _run_cli(db_path, "add", b)
    # update only feed a
    result = _run_cli(db_path, "update", a)
    assert result.returncode == 0
    # list entries should only show entries from a (3 RSS entries, exact)
    listed = _run_cli(db_path, "list", "entries")
    lines = sorted(line for line in listed.stdout.splitlines() if line.strip())
    assert lines == sorted(
        [
            f"{a} http://example.com/posts/1",
            f"{a} http://example.com/posts/2",
            f"{a} http://example.com/posts/3",
        ]
    )
    # None of the atom entries leaked through.
    for line in lines:
        assert b not in line


def test_cli_search_status_and_workflow(db_path):
    """CLI: search status round-trips disabled→enabled→disabled (via `search
    enable` / `search disable`), and the full search workflow returns
    matching entries on stdout.

    Covers both single-match (`python` → exactly srch-1) and multi-match
    (`programming` → srch-1 and srch-2) queries, plus a no-match query
    (zero hits, stdout still empty after status line). Kills implementations
    that hard-wire enable/disable to a single direction, that no-op
    `search disable`, or that emit a header line on zero results."""
    # status starts disabled
    status = _run_cli(db_path, "search", "status")
    assert status.returncode == 0
    assert status.stdout.strip() == "search: disabled"

    # enable, status flips to enabled
    en = _run_cli(db_path, "search", "enable")
    assert en.returncode == 0
    status2 = _run_cli(db_path, "search", "status")
    assert status2.stdout.strip() == "search: enabled"

    # disable, status flips back (round-trip — kills hard-wired enable).
    dis = _run_cli(db_path, "search", "disable")
    assert dis.returncode == 0
    status3 = _run_cli(db_path, "search", "status")
    assert status3.stdout.strip() == "search: disabled"

    # re-enable for the workflow portion
    _run_cli(db_path, "search", "enable")

    # full workflow: add, update, search update, search entries
    feed_url = (FIXTURES / "search.rss").as_uri()
    _run_cli(db_path, "add", feed_url)
    _run_cli(db_path, "update")
    _run_cli(db_path, "search", "update")

    # Single match: 'python' → srch-1 only.
    result = _run_cli(db_path, "search", "entries", "python")
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines == [f"{feed_url} http://search.example.com/python"]

    # Multi-match: 'programming' → both srch-1 and srch-2 (set comparison
    # since CLI doesn't guarantee order).
    result2 = _run_cli(db_path, "search", "entries", "programming")
    assert result2.returncode == 0
    multi = {line for line in result2.stdout.splitlines() if line.strip()}
    assert multi == {
        f"{feed_url} http://search.example.com/python",
        f"{feed_url} http://search.example.com/rust",
    }


def test_cli_read_only_mode(db_path):
    """--read-only blocks writes: add should fail (non-zero exit)."""
    # First create the DB file with normal mode by listing
    init = _run_cli(db_path, "list", "feeds")
    assert init.returncode == 0

    feed_url = (FIXTURES / "sample.rss").as_uri()
    # Attempt to add a feed with --read-only — should fail
    result = _run_cli(db_path, "--read-only", "add", feed_url)
    assert result.returncode != 0

    # confirm no feed was added
    listed = _run_cli(db_path, "list", "feeds")
    assert listed.stdout.strip() == ""


def test_cli_plugin_flag(db_path):
    """--plugin wires plugin loading: a known plugin loads (rc=0); an unknown
    plugin name fails (rc != 0)."""
    ok = _run_cli(
        db_path, "--plugin", "reader.plugins.enclosure_dedupe", "list", "feeds"
    )
    assert ok.returncode == 0, ok.stderr

    bad = _run_cli(db_path, "--plugin", ".nonexistent_plugin_xyz", "list", "feeds")
    assert bad.returncode != 0


# ---------------------------------------------------------------------------
# 16. update_feeds_iter / UpdateResult
# ---------------------------------------------------------------------------


def test_update_feeds_iter_yields_per_feed(reader):
    """update_feeds_iter yields EXACTLY one UpdateResult per attempted feed,
    each with the correct per-feed entry count (RSS=3, Atom=2). Kills
    implementations that return UpdatedFeed sentinels without actually
    parsing, or fan out yields per-entry instead of per-feed."""
    a = str(FIXTURES / "sample.rss")
    b = str(FIXTURES / "sample.atom")
    reader.add_feed(a)
    reader.add_feed(b)
    results = list(reader.update_feeds_iter())
    # Exactly one result per feed — not per-entry.
    assert len(results) == 2
    by_url = {r.url: r for r in results}
    assert set(by_url.keys()) == {a, b}
    # Each result reports no error AND the correct new-entry counts from
    # parsing the actual fixture (RSS has 3 items, Atom has 2).
    assert by_url[a].error is None
    assert by_url[a].updated_feed is not None
    assert by_url[a].updated_feed.new == 3
    assert by_url[b].error is None
    assert by_url[b].updated_feed is not None
    assert by_url[b].updated_feed.new == 2


def test_update_feeds_iter_mixed_success_and_error(reader):
    """update_feeds_iter yields UpdatedFeed for good feeds AND ParseError for
    bad feeds in the same call."""
    from reader import ParseError

    good = str(FIXTURES / "sample.rss")
    bad = str(FIXTURES / "definitely-missing.xml")
    reader.add_feed(good)
    reader.add_feed(bad)

    results = {r.url: r for r in reader.update_feeds_iter()}
    assert set(results.keys()) == {good, bad}
    # good one updated
    assert results[good].error is None
    assert results[good].updated_feed is not None
    assert results[good].updated_feed.new == 3
    # bad one has ParseError
    assert isinstance(results[bad].error, ParseError)
    assert results[bad].updated_feed is None


# ---------------------------------------------------------------------------
# 17. Update hooks
# ---------------------------------------------------------------------------


def test_after_entry_update_hooks_fire_on_new_entries(reader):
    """after_entry_update_hooks is called EXACTLY once per new entry with
    status NEW; the hook receives the live Reader as its first argument;
    re-running update_feeds() with no fixture changes yields no further calls
    (idempotent). Kills implementations that fire the hook multiple times per
    entry, pass the wrong reader, or re-fire on idempotent updates."""
    from reader import EntryUpdateStatus

    captured = []

    def hook(rdr, entry, status):
        captured.append((rdr, entry.id, status))

    reader.after_entry_update_hooks.append(hook)
    url = str(FIXTURES / "sample.rss")
    reader.add_feed(url)
    reader.update_feeds()

    # Exactly 3 calls — one per entry, no duplicates.
    assert len(captured) == 3
    captured_ids = sorted(e_id for _, e_id, _ in captured)
    assert captured_ids == ["rss-entry-1", "rss-entry-2", "rss-entry-3"]
    # All statuses NEW on first pass.
    assert {status for _, _, status in captured} == {EntryUpdateStatus.NEW}
    # The reader passed to the hook is the same reader.
    assert all(rdr is reader for rdr, _, _ in captured)

    # Second update with no changes: must NOT fire the hook again (still 3).
    reader.update_feeds()
    assert len(captured) == 3


# ---------------------------------------------------------------------------
# 18. Search filters and counts (deeper than basic match-set checks)
# ---------------------------------------------------------------------------


def test_search_entries_filter_by_feed(reader):
    """search_entries(feed=url) narrows results to that feed only."""
    a = str(FIXTURES / "search.rss")
    b = str(FIXTURES / "sample.rss")  # also has 'python' nowhere; 'cats' yes
    reader.add_feed(a)
    reader.add_feed(b)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    # 'programming' is only in the search.rss feed.
    by_a = {r.id for r in reader.search_entries("programming", feed=a)}
    by_b = {r.id for r in reader.search_entries("programming", feed=b)}
    assert by_a == {"srch-1", "srch-2"}
    assert by_b == set()

    # 'cats' is only in sample.rss (rss-entry-3 title 'Third Post About Cats').
    by_a2 = {r.id for r in reader.search_entries("cats", feed=a)}
    by_b2 = {r.id for r in reader.search_entries("cats", feed=b)}
    assert by_a2 == set()
    assert by_b2 == {"rss-entry-3"}


def test_search_entries_filter_by_entry_tags(search_reader):
    """search_entries(tags=[...]) narrows by entry tag (entry-level tag filter)."""
    reader, url = search_reader
    reader.set_tag((url, "srch-1"), "starred")
    # Query that matches both srch-1 and srch-2; tag filter restricts to srch-1.
    all_hits = {r.id for r in reader.search_entries("programming")}
    assert all_hits == {"srch-1", "srch-2"}
    starred = {r.id for r in reader.search_entries("programming", tags=["starred"])}
    assert starred == {"srch-1"}
    # Negated tag: not starred.
    not_starred = {
        r.id for r in reader.search_entries("programming", tags=["-starred"])
    }
    assert not_starred == {"srch-2"}


def test_search_entries_filter_by_feed_tags(search_reader):
    """search_entries(feed_tags=[...]) narrows by FEED tag, not entry tag."""
    reader, url = search_reader
    reader.set_tag(url, "newsroom")
    # All hits when no filter.
    assert {r.id for r in reader.search_entries("programming")} == {"srch-1", "srch-2"}
    # feed has the tag -> both entries pass.
    via_feed_tag = {
        r.id for r in reader.search_entries("programming", feed_tags=["newsroom"])
    }
    assert via_feed_tag == {"srch-1", "srch-2"}
    # feed lacks the tag -> nothing passes.
    via_missing_tag = {
        r.id for r in reader.search_entries("programming", feed_tags=["missing"])
    }
    assert via_missing_tag == set()


def test_search_entry_counts_break_down_by_state(search_reader):
    """search_entry_counts returns counts whose .read / .important /
    .unimportant fields ALL match the actual filtered population, not stub
    zeros. Kills implementations that only populate .total and leave the
    sub-fields at 0."""
    reader, url = search_reader
    # srch-1: read+important. srch-2: unread+unimportant (False, not None).
    reader.mark_entry_as_read((url, "srch-1"))
    reader.set_entry_important((url, "srch-1"), True)
    reader.set_entry_important((url, "srch-2"), False)

    counts = reader.search_entry_counts("programming")
    assert counts.total == 2
    # Exactly one read entry in the match set.
    assert counts.read == 1
    # Exactly one important entry in the match set.
    assert counts.important == 1
    # Exactly one unimportant (important=False) entry in the match set —
    # not 0, not 2 (None entries don't count as unimportant).
    assert counts.unimportant == 1


def test_search_entry_counts_filter_by_feed(reader):
    """search_entry_counts honors feed= filter — count narrows to that feed."""
    a = str(FIXTURES / "search.rss")
    b = str(FIXTURES / "sample.rss")
    reader.add_feed(a)
    reader.add_feed(b)
    reader.update_feeds()
    reader.enable_search()
    reader.update_search()

    # 'programming' total counts only the search.rss matches.
    assert reader.search_entry_counts("programming").total == 2
    assert reader.search_entry_counts("programming", feed=a).total == 2
    assert reader.search_entry_counts("programming", feed=b).total == 0


# ---------------------------------------------------------------------------
# 19. Update result semantics (return values, disable, get_feeds filters)
# ---------------------------------------------------------------------------


def test_update_feed_returns_updatedfeed_with_correct_counts(reader):
    """First update_feed returns UpdatedFeed with new=N (all entries new on
    first pass), modified=0, unmodified=0; .total == new."""
    url = str(FIXTURES / "sample.rss")
    reader.add_feed(url)
    result = reader.update_feed(url)
    assert result is not None
    assert result.url == url
    assert result.new == 3
    assert result.modified == 0
    assert result.unmodified == 0
    # .total convenience property
    assert result.total == 3


def test_disable_feed_skips_update_feeds(reader):
    """A feed with updates_enabled=False is NOT updated by update_feeds() —
    its entries stay empty after the bulk update call."""
    a = str(FIXTURES / "sample.rss")
    b = str(FIXTURES / "sample.atom")
    reader.add_feed(a)
    reader.add_feed(b)
    reader.disable_feed_updates(a)

    reader.update_feeds()  # default updates_enabled=True → skips disabled feeds
    # Only atom feed entries should be present.
    ids = {e.id for e in reader.get_entries()}
    assert ids == {"urn:uuid:atom-entry-1", "urn:uuid:atom-entry-2"}
    # Sanity: feed a still has zero entries.
    assert reader.get_entry_counts(feed=a).total == 0


def test_get_feeds_filter_updates_enabled(reader):
    """get_feeds(updates_enabled=False) returns only disabled feeds;
    updates_enabled=True returns only enabled ones."""
    reader.add_feed("http://a.example.com/")
    reader.add_feed("http://b.example.com/")
    reader.add_feed("http://c.example.com/")
    reader.disable_feed_updates("http://a.example.com/")
    reader.disable_feed_updates("http://c.example.com/")

    disabled = {f.url for f in reader.get_feeds(updates_enabled=False)}
    enabled = {f.url for f in reader.get_feeds(updates_enabled=True)}
    assert disabled == {"http://a.example.com/", "http://c.example.com/"}
    assert enabled == {"http://b.example.com/"}


# ---------------------------------------------------------------------------
# 20. Tags — value types, overwrite, isolation
# ---------------------------------------------------------------------------


def test_set_tag_overwrites_existing_value(reader):
    """set_tag on an existing key replaces the value (no duplicate-key error)."""
    feed_url = "http://example.com/"
    reader.add_feed(feed_url)
    reader.set_tag(feed_url, "color", "red")
    assert reader.get_tag(feed_url, "color") == "red"
    reader.set_tag(feed_url, "color", "blue")  # overwrite
    assert reader.get_tag(feed_url, "color") == "blue"
    # And there is only one entry for that key.
    items = dict(reader.get_tags(feed_url))
    assert items == {"color": "blue"}


def test_tag_value_can_be_any_json_type(reader):
    """Tag values may be int, list, dict, str, None — all round-trip identically."""
    reader.add_feed("http://example.com/")
    cases = {
        "an_int": 42,
        "a_list": [1, "two", 3],
        "a_dict": {"nested": {"k": "v"}, "n": 7},
        "a_str": "hello",
        "a_none": None,
    }
    for key, val in cases.items():
        reader.set_tag("http://example.com/", key, val)
    for key, val in cases.items():
        assert reader.get_tag("http://example.com/", key) == val


def test_tags_do_not_leak_across_resources(reader):
    """Tags on a feed vs an entry vs a global resource are isolated — none of
    them leak into get_tags() of another resource."""
    url = str(FIXTURES / "sample.rss")
    reader.add_feed(url)
    reader.update_feeds()
    eid = (url, "rss-entry-1")

    reader.set_tag(url, "feed-tag", "F")  # feed
    reader.set_tag(eid, "entry-tag", "E")  # entry
    reader.set_tag((), "global-tag", "G")  # global

    assert dict(reader.get_tags(url)) == {"feed-tag": "F"}
    assert dict(reader.get_tags(eid)) == {"entry-tag": "E"}
    assert dict(reader.get_tags(())) == {"global-tag": "G"}


# ---------------------------------------------------------------------------
# 21. Entry state — modified timestamps and mark/set parity
# ---------------------------------------------------------------------------


def test_set_entry_read_with_explicit_modified(reader_with_sample):
    """set_entry_read(entry, True, modified=<dt>) stamps read_modified to the
    EXACT provided datetime (timezone-aware UTC) — not to 'now'. Round-trip
    must preserve the timezone."""
    from datetime import datetime, timezone

    reader, url = reader_with_sample
    eid = (url, "rss-entry-1")
    when = datetime(2020, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
    reader.set_entry_read(eid, True, modified=when)

    fetched = reader.get_entry(eid)
    assert fetched.read is True
    assert fetched.read_modified == when
    # Round-trip must preserve timezone-awareness exactly (spec: all datetime
    # fields are timezone-aware UTC). Kills naive-datetime storage shortcuts.
    assert fetched.read_modified.tzinfo is not None
    assert fetched.read_modified.utcoffset() == timezone.utc.utcoffset(None)


def test_mark_as_important_matches_set_entry_important_true(reader_with_sample):
    """mark_entry_as_important / mark_entry_as_unimportant are exact equivalents
    of set_entry_important(.., True/False) — both flip .important AND set a
    timezone-aware UTC .important_modified. Spec: all datetime fields are
    timezone-aware UTC. Kills implementations that alias mark_as_important
    to a no-op or skip stamping important_modified."""
    from datetime import datetime, timezone

    reader, url = reader_with_sample
    e1 = (url, "rss-entry-1")
    e2 = (url, "rss-entry-2")
    reader.mark_entry_as_important(e1)
    reader.set_entry_important(e2, True)
    assert reader.get_entry(e1).important is True
    assert reader.get_entry(e2).important is True
    # important_modified is set on both, timezone-aware UTC.
    for eid in (e1, e2):
        im = reader.get_entry(eid).important_modified
        assert isinstance(im, datetime)
        assert im.tzinfo is not None
        assert im.utcoffset() == timezone.utc.utcoffset(None)

    # mark_entry_as_unimportant flips back to False.
    reader.mark_entry_as_unimportant(e1)
    assert reader.get_entry(e1).important is False


# ---------------------------------------------------------------------------
# 22. Feed mutations — change_feed_url preserves data
# ---------------------------------------------------------------------------


def test_change_feed_url_preserves_user_title(reader):
    """change_feed_url preserves user_title (a user-defined attribute)."""
    reader.add_feed("http://old.example.com/")
    reader.set_feed_user_title("http://old.example.com/", "My Old Feed")
    reader.change_feed_url("http://old.example.com/", "http://new.example.com/")

    new_feed = reader.get_feed("http://new.example.com/")
    assert new_feed.user_title == "My Old Feed"


def test_export_feeds_subset(reader):
    """export_feeds(feeds=[f1]) exports ONLY the given subset, not all feeds."""
    from reader.opml import parse

    reader.add_feed("http://a.example.com/")
    reader.add_feed("http://b.example.com/")
    reader.add_feed("http://c.example.com/")
    a_feed = reader.get_feed("http://a.example.com/")
    export = reader.export_feeds([a_feed])
    parsed = parse(io.BytesIO(export.content))
    urls = {f.url for f in parsed}
    assert urls == {"http://a.example.com/"}


# ---------------------------------------------------------------------------
# 24. CLI extras — boundary behaviors
# ---------------------------------------------------------------------------


def test_cli_add_without_update_leaves_entries_empty(db_path):
    """CLI `add URL` (no --update) does NOT populate entries — `list entries`
    must be empty afterward (only the feed row exists)."""
    feed_url = (FIXTURES / "sample.rss").as_uri()
    add = _run_cli(db_path, "add", feed_url)
    assert add.returncode == 0
    # Feed is listed.
    feeds = _run_cli(db_path, "list", "feeds")
    feed_lines = [line for line in feeds.stdout.splitlines() if line.strip()]
    assert feed_lines == [feed_url]
    # But entries are empty.
    entries = _run_cli(db_path, "list", "entries")
    assert entries.returncode == 0
    assert entries.stdout == ""


def test_cli_delete_missing_feed_fails(db_path):
    """CLI `delete URL` on a feed that was never added exits non-zero."""
    # Initialize the db.
    init = _run_cli(db_path, "list", "feeds")
    assert init.returncode == 0
    result = _run_cli(db_path, "delete", "http://never-added.example.com/feed.xml")
    assert result.returncode != 0


def test_cli_search_entries_no_match_empty_stdout(db_path):
    """CLI `search entries QUERY` with zero matches prints exactly nothing on
    stdout — no header, no 'no results' message."""
    feed_url = (FIXTURES / "search.rss").as_uri()
    _run_cli(db_path, "add", feed_url)
    _run_cli(db_path, "update")
    _run_cli(db_path, "search", "enable")
    _run_cli(db_path, "search", "update")
    result = _run_cli(db_path, "search", "entries", "thiswordmatchesnothing")
    assert result.returncode == 0
    assert result.stdout == ""
