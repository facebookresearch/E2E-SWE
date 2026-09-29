# reader

Build `reader`, a Python feed-reader library. A user creates a `Reader` against a
local SQLite database, adds RSS/Atom/JSON feeds, updates them, and then queries
entries (read/unread, important, tagged, by feed, etc.). Opt-in full-text search
indexes entries for query. A CLI invoked as `python -m reader` exposes the core
workflows and is part of the required public surface. A built-in plugin system
lets users hook into update lifecycle events.

## Dependencies (offline environment)

The environment is **fully offline — there is no network access, and every
dependency you need is already installed.** Do not run `pip install` or try to
fetch anything; it will fail. Just `import` the libraries you need.

The grader installs your package with `pip install -e ".[cli]"
--no-build-isolation`, so your `pyproject.toml` (or `setup.py`) must:

- expose a `cli` extra that provides `click` (what the CLI needs), and
- list your runtime dependencies **without pinning versions that differ from the
  ones already installed** — an unsatisfiable pin cannot be resolved offline.

The following packages are pre-installed and are the only third-party libraries
available to your implementation:

- **feedparser** — RSS/Atom parsing.
- **requests** — feed retrieval over HTTP(S).
- **werkzeug** — HTTP utilities (e.g. header/URL parsing).
- **beautifulsoup4** — HTML handling for full-text search indexing.
- **structlog** — structured logging.
- **typing-extensions** — typing backports.
- **click** — the CLI framework (exposed via the `cli` extra).

Everything else must be built on the Python standard library (notably `sqlite3`
for storage and search, and `xml` for OPML).

## Package layout

Public imports come from `reader`, `reader.types`, `reader.exceptions`,
`reader.opml`, and `reader.plugins`. 

## API: top-level (`reader`)

### Constructing a Reader

```python
make_reader(
    url: str,
    *,
    feed_root: str | None = None,
    read_only: bool = False,
    plugins: Iterable[str | Callable[[Reader], None]] = (),
    search_enabled: bool | None | Literal['auto'] = 'auto',
) -> Reader
```

- `url` — path to the SQLite database file (created if missing).
- `feed_root` — `None` disables local-file feeds (`add_feed` of a path or
  `file:` URI raises `InvalidFeedURLError` immediately, not at update time);
  `''` allows any absolute path / `file:` URI; a non-empty absolute path
  restricts file feeds to that root.
- `search_enabled` — `'auto'` (enable on first `update_search()`), `True`
  (enable now), `False` (disable now), `None` (leave as-is). Any other value
  raises `ValueError`.

### Feed URL validity

`add_feed` and `change_feed_url` validate the feed value up front — raising
immediately, not at update time — and raise `InvalidFeedURLError` (a subclass of
`ValueError`) for any value that is not retrievable under the current
`feed_root`:

- `http` / `https` web URLs are always valid.
- A `file:` URI, a filesystem path, or any other scheme-less / bare token names
  a **local file**, so it is valid only when `feed_root` allows local-file
  feeds. Under the default `feed_root=None`, local files are disabled, so every
  non-`http(s)` value is rejected.

`allow_invalid_url=True` bypasses this validation and stores the value verbatim,
so it round-trips through `get_feeds` unchanged (useful for user-entry feeds).

### `Reader` instance

Methods (most are obvious from the name):

- `close()`; usable as a context manager (`with make_reader(...) as r:`).
- Feed CRUD: `add_feed(feed, /, exist_ok=False, *, allow_invalid_url=False)`,
  `delete_feed(feed, /, missing_ok=False)`,
  `change_feed_url(old, new, /, *, allow_invalid_url=False)`,
  `get_feed(feed, /[, default])` (raises `FeedNotFoundError` if missing and
  no default), `get_feeds(*, feed=None, tags=None, broken=None,
  updates_enabled=None, new=None, scheduled=False, sort=FeedSort.TITLE,
  limit=None, starting_after=None)`, `get_feed_counts(...)`,
  `set_feed_user_title(feed, title, /)`, `enable_feed_updates(feed, /)`,
  `disable_feed_updates(feed, /)`.
- Feed updates: `update_feed(feed, /) -> UpdatedFeed | None`,
  `update_feeds(*, feed=None, ...workers=1)`,
  `update_feeds_iter(...) -> Iterable[UpdateResult]`.
- Entry retrieval: `get_entry(entry, /[, default])`,
  `get_entries(*, feed=None, entry=None, read=None, important=None,
  has_enclosures=None, source=None, tags=None, feed_tags=None,
  sort=EntrySort.RECENT, limit=None, starting_after=None)`,
  `get_entry_counts(...)`.
- Entry state: `set_entry_read(entry, read, /, modified=MISSING)` (only
  accepts `True`/`False`, else raises `ValueError`),
  `mark_entry_as_read(entry, /)`, `mark_entry_as_unread(entry, /)`,
  `set_entry_important(entry, important, /, modified=MISSING)` (only
  accepts `True`/`False`/`None`, else `ValueError`),
  `mark_entry_as_important(entry, /)`, `mark_entry_as_unimportant(entry, /)`.
- User entries: `add_entry(entry, /, *, overwrite=False)`,
  `delete_entry(entry, /, missing_ok=False)` (deleting an entry that was
  added by a feed rather than the user raises `EntryError`),
  `copy_entry(src, dst, /)` — creates the destination as a user entry and
  copies the source entry's tags onto it; it raises `EntryExistsError` if an
  entry already exists at the destination id and never overwrites it (there is
  no `overwrite` option). Entries created via `add_entry` /
  `copy_entry` have `added_by == 'user'`; entries ingested from a feed have
  `added_by == 'feed'`.
- Search: `enable_search()`, `disable_search()`, `is_search_enabled() -> bool`,
  `update_search()`, `search_entries(query, /, **filters) ->
  Iterable[EntrySearchResult]`, `search_entry_counts(query, /, **filters)`.
  `query` is an SQLite FTS5 full-text query string; a query the FTS5 query
  parser cannot parse raises `InvalidSearchQueryError`.
- Tags: `get_tags(resource, /, *, key=None) -> Iterable[tuple[str, value]]`,
  `get_tag_keys(resource=None, /) -> Iterable[str]` (alphabetical order),
  `get_tag(resource, key, /[, default])`,
  `set_tag(resource, key, /[, value])`,
  `delete_tag(resource, key, /, missing_ok=False)`.
- Reserved names: `make_reader_reserved_name(key, /) -> str` (default scheme
  yields `'.reader.<key>'`), `make_plugin_reserved_name(name, /[, key])`
  (yields `'.plugin.<name>'` or `'.plugin.<name>.<key>'`).
- OPML: `import_feeds(file, /)`, `import_feeds_iter(feeds, /) ->
  Iterable[FeedImportResult]`, `export_feeds(feeds=None, /) -> FeedExport`.
- Update hooks (lists of callables, appended to):
  `before_feeds_update_hooks`, `before_feed_update_hooks`,
  `after_entry_update_hooks(reader, entry, status)`,
  `after_feed_update_hooks(reader, feed_url)`,
  `after_feeds_update_hooks`.

`resource` arguments to tag methods are:

- a feed URL `str`, a one-tuple `(url,)`, or a `Feed` object → feed tag
- `(feed_url, entry_id)` or an `Entry` object → entry tag
- `()` (empty tuple) → global tag

`feed` arguments accept `str`, one-tuple `(url,)`, or a `Feed` object.
`entry` arguments accept `(feed_url, entry_id)` or an `Entry` object.

### `tags=` filter syntax

Used by `get_feeds`, `get_entries`, `search_entries`, and counts variants.

- `None` — no filter.
- `True` / `False` — has any tag / has no tag.
- `['tag1', 'tag2']` — AND of all listed tags.
- `[['tag1', 'tag2']]` — nested list is OR.
- A leading `'-'` negates: `['-tag1']` means "not tagged tag1".

### `important=` filter

`get_entries`/`get_entry_counts`/`search_entries` accept:

- `None` — no filter.
- `True` — `important == True`.
- `False` — `important is None or False` (i.e. "not true").
- One of the strings `'istrue'`, `'isfalse'`, `'notset'`, `'nottrue'`,
  `'notfalse'`, `'isset'`, `'any'` for precise tri-state filtering.

### Feed formats

Feeds are parsed according to their content:

- **RSS / Atom** — parsed with `feedparser`.
- **JSON Feed** (the [jsonfeed.org](https://www.jsonfeed.org/) v1 / v1.1
  standard) — parsed with the standard-library `json` module, since
  `feedparser` handles only RSS/Atom. A feed is treated as JSON Feed when its
  content is JSON (e.g. a `.json` feed). Its feed-level fields and each of its
  `items[]` populate the documented `Feed` / `Entry` / `Content` /
  `Enclosure` fields according to their jsonfeed.org meanings.

### Update results

- `update_feed(url)` returns an `UpdatedFeed` on success, `None` when nothing
  changed; raises `FeedNotFoundError` if the feed wasn't added,
  `ParseError` if retrieval/parse failed.
- `update_feeds()` silently skips per-feed `ParseError`s but re-raises hook
  errors via `UpdateHookErrorGroup`.
- `update_feeds_iter()` yields `UpdateResult(url, value)` per feed; `value`
  is `UpdatedFeed | None | UpdateError`. Convenience: `result.updated_feed`,
  `result.error`, `result.not_modified`.

### Limits / ordering errors

`limit` must be a positive integer; otherwise `ValueError`.

## Types (`reader.types`)

All re-exported from `reader`. All datetime fields are timezone-aware UTC.

- `Feed(url, updated=None, title=None, link=None, authors=(), subtitle=None,
  version=None, user_title=None, added=None, last_updated=None,
  last_exception=None, updates_enabled=True, update_after=None,
  last_retrieved=None)`; properties: `resource_id` (= `(url,)`),
  `resolved_title` (= `user_title or title`).
- `Entry(id, updated=None, title=None, link=None, authors=(), published=None,
  summary=None, content=(), enclosures=(), source=None, read=False,
  read_modified=None, important=None, important_modified=None, added=None,
  added_by=None, last_updated=None, original_feed_url=None, feed=None)`;
  properties: `feed_url` (= `feed.url`), `resource_id` (= `(feed_url, id)`);
  method `get_content(*, prefer_summary=False) -> Content | None`.
- `Content(value, type=None, language=None)`; property `is_html` — `True` if
  `type in {'text/html', 'text/xhtml'}` OR `type is None`.
- `Enclosure(href, type=None, length=None)` — `length` is `int | None` (the
  file size in bytes; coerced to an integer from the parsed feed value when
  present, so a numeric enclosure length surfaces as an `int`, not a `str`).
- `EntrySource(url=None, updated=None, title=None, link=None, authors=(),
  subtitle=None)`.
- `Author(name=None, href=None, email=None)`.
- `HighlightedString(value='', highlights=())` — `highlights` is a sequence of
  non-overlapping `slice` objects with `start <= stop` within `0..len(value)`;
  invalid or overlapping slices raise `ValueError`. Methods: `split()`,
  `apply(before, after, func=None)`, classmethod `extract(text, before, after)`.
- `EntrySearchResult(feed_url, id, metadata={}, content={})`; values are
  `HighlightedString`s. `metadata` keys are dotted paths like `.title`,
  `.feed.title`, `.feed.user_title`. `content` keys are e.g. `.summary` or
  `.content[N].value`. Property `resource_id`.
- `FeedCounts(total, broken, updates_enabled)`.
- `EntryCounts(total, read, important, unimportant, has_enclosures, averages)`.
- `EntrySearchCounts(total, read, important, unimportant, has_enclosures,
  averages)`.
- `UpdatedFeed(url, new=0, modified=0, unmodified=0)`; property `total`.
- `UpdateResult(url, value)` — a `NamedTuple`; properties `updated_feed`,
  `error`, `not_modified`.
- `EntryUpdateStatus` enum: `NEW`, `MODIFIED`.
- `FeedSort` `StrEnum`: `TITLE`, `ADDED`.
- `EntrySort` `StrEnum`: `RECENT` (newest `published` first), `RANDOM`.
- `EntrySearchSort` `StrEnum`: `RELEVANT`, `RECENT`, `RANDOM`.
- `FeedToImport(url, *, title=None, link=None, subtitle=None)`.
- `FeedImportResult(feed, exception=None)`; properties `added`, `error`.
  `import_feeds_iter` yields one result per input feed, and `added` reports
  whether that call actually added the feed.
- `FeedExport(content: bytes, filename: str)`; property `headers` returns
  `{'Content-Type': 'application/xml; charset=utf-8',
  'Content-Disposition': f'attachment; filename="<filename>"'}`.

## Exceptions (`reader.exceptions`, re-exported from `reader`)

Hierarchy (each child Is-A its parent):

- `ReaderError(Exception)`
  - `ResourceNotFoundError`
  - `FeedError(url, /, message='')` — exposes `.url` and `.resource_id`.
    - `FeedExistsError`
    - `FeedNotFoundError` (also subclasses `ResourceNotFoundError`)
    - `InvalidFeedURLError` (also subclasses `ValueError`)
  - `EntryError(feed_url, id, /, message='')` — exposes `.feed_url`, `.id`,
    `.resource_id`.
    - `EntryExistsError`
    - `EntryNotFoundError` (also subclasses `ResourceNotFoundError`)
  - `UpdateError`
    - `ParseError` (also subclasses `FeedError`)
    - `UpdateHookError`
      - `SingleUpdateHookError`
      - `UpdateHookErrorGroup` — an `ExceptionGroup[UpdateHookError]`.
  - `StorageError`
  - `SearchError`
    - `SearchNotEnabledError`
    - `InvalidSearchQueryError` (also subclasses `ValueError`)
  - `TagError(resource_id, key, /, message='')`
    - `TagNotFoundError`
  - `PluginError`
    - `InvalidPluginError` (also subclasses `ValueError`)
    - `PluginInitError`
  - `FeedImportError`
  - `ReaderWarning(UserWarning)`

## OPML (`reader.opml`)

- `parse(file: IO[bytes], max_depth: int = 10) -> list[FeedToImport]`. Only
  `<outline type="rss" xmlUrl="...">` entries are extracted (case-insensitive).
  Nested outlines are walked. Raises `OPMLError` on malformed XML / missing
  `<opml>` root / exceeded depth.
- `unparse(feeds: Iterable[Feed], *, title=None, created=None,
  generator=SOURCE_URL) -> bytes` — emits an OPML 2.0 document.
- `OPMLError(FeedImportError)`.

## Plugins (`reader.plugins`)

- Plugin entries passed to `make_reader(plugins=...)` are either built-in
  names like `'.enclosure_dedupe'` (resolved against `reader.plugins`),
  full import paths like `'reader.plugins.enclosure_dedupe'`, or arbitrary
  `Callable[[Reader], None]` objects.
- Any plugin reference that cannot be resolved or imported raises
  `InvalidPluginError` at `make_reader` time.

Built-in plugins that must be present:

- `reader.plugins.enclosure_dedupe` (built-in name `.enclosure_dedupe`):
  deduplicates each entry's `enclosures` sequence by `href` (first
  occurrence wins; insertion order preserved).
- `reader.plugins.mark_as_read` (built-in name `.mark_as_read`):
  for *newly-added* entries (status `NEW`), if the feed's
  `.reader.mark-as-read` tag is `{'title': [regex, ...]}` and any regex
  matches the entry title, mark the entry as `read=True` and
  `important=False`.
- `reader.plugins.readtime` (built-in name `.readtime`): on every entry
  update, stores a `{'seconds': int}` dict under the
  `.reader.readtime` entry tag. `seconds` is the estimated reading time of
  the entry's text — the content returned by `get_content()`, which falls
  back to the `summary` when the entry has no content — rounded **up** to
  whole seconds. An entry with no text stores `{'seconds': 0}`; any entry
  with non-empty text therefore stores `seconds >= 1`. The exact
  words-per-minute constant used for the estimate is unspecified.

## CLI

Invoked as `python -m reader [OPTIONS] COMMAND [ARGS]` — `reader.__main__` is
the only required entry point. Options can also be set via env vars with
prefix `READER_`. Notably `READER_DB` sets `--db` and `READER_FEED_ROOT` sets
`--feed-root`.

Global options:

- `--url` / `--db PATH` — path to the SQLite db.
- `--feed-root PATH` — passed through to `make_reader`.
- `--read-only`/`--no-read-only` — when `--read-only` is set, any command
  that mutates storage (`add`, `delete`, `update`, `search enable/disable/update`)
  exits with non-zero status.
- `--plugin NAME` (repeatable) — feed plugins through to `make_reader`.
- `--cli-plugin NAME` (repeatable).
- `--reserved-name-scheme KEY=VAL,...`.
- `--config PATH`.
- `--version`.

Commands:

- `add URL [--update/--no-update]` — `--update` immediately updates the feed
  after adding (entries become queryable in the same invocation).
- `delete URL`
- `update [URL] [--new/--no-new] [--scheduled/--no-scheduled] [--workers N] [-v]`
- `list feeds [--json]`
- `list entries [--json]`
- `search status`
- `search enable`
- `search disable`
- `search update`
- `search entries QUERY`

Output formats:

- `list feeds` (plain): one feed URL per line.
- `list feeds --json`: one JSON object per line, carrying at least the feed's
  `url`, `title`, and `link` fields.
- `list entries` (plain): one line per entry, `"<feed-url> <entry-link-or-id>"`.
- `list entries --json`: one JSON object per line, carrying at least the entry's
  `id`, `title`, and `link`, plus a nested `feed` object holding at least the
  owning feed's `url`.
- `search status`: prints `search: enabled` or `search: disabled`.
- `search entries QUERY`: like `list entries` but only matching entries.
- `--help` and `--version` exit 0 and print a usage / version line on stdout.
