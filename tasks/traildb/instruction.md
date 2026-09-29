# traildb

`traildb` is a compact, columnar event store for behavioral / time-series
data. It stores an ordered set of *trails* — one per user, session, or
device — where each trail is a sequence of *events* stamped with a
`uint64_t` timestamp and a variable-arity list of `(field, value)` items.
The on-disk format is a single self-contained package (or an equivalent
directory) built once with a *constructor* API and read back many times
with cheap random access.

The deliverable is a C99 library plus a companion command-line tool:

* **`libtraildb.so`** and **`libtraildb.a`** installed under a standard
  prefix (`/usr/local/lib` is fine), such that
  `gcc driver.c -ltraildb -o driver` (no extra `-L` / `-I` / `-l` flags)
  links a driver against the library. Refresh the linker cache
  (`ldconfig`) after install so the shared object is discoverable at
  runtime.
* Public headers under the same prefix's `include/` directory
  (`traildb.h`, `tdb_types.h`, `tdb_error.h`, `tdb_limits.h`) so
  `#include <traildb.h>` alone resolves the full public surface.
* A **`tdb`** binary installed on `PATH` (again, `/usr/local/bin` is
  fine) implementing the `tdb make | dump | merge` subcommands
  described below.

An offline **`setup.sh`** in the workspace root builds and installs all
of the above. No Internet is available while `setup.sh` runs; every
system dependency you rely on is already baked into the environment.

## Performance contract

The TDB output format must apply general-purpose compression to field
values such that the on-disk size grows sublinearly with the number
of stored events (given repetitive input — clickstream data is the
canonical case). A fixed per-TDB overhead is expected (a codebook or
schema block whose size does not depend on event count); once that
overhead is amortised, per-event blowup must be a small fraction of
the raw field byte count.

Trail lookup by UUID must use an index — hash-based, tree-based,
trie-based, or equivalent — such that `tdb_get_trail_id(uuid)`
completes in **sublinear time relative to the total trail count**. A
linear scan over all trails is not acceptable and will not meet the
lookup-latency contract on realistic reader workloads.

## System dependencies (pre-installed)

The following are already installed on the image; do not attempt to
fetch or build them from source:

* **`libjudy-dev`** — headers and static/shared libraries for Judy
  sparse arrays (`<Judy.h>`, `-lJudy`).
* **`libarchive-dev`** — headers and libraries for reading/writing tar
  archives (`<archive.h>`, `-larchive`); the package output format is a
  tar stream.
* **`pkg-config`** — used by the `libarchive` autodetection.
* **`gcc`** with the standard `build-essential` toolchain, plus
  `autoconf`, `automake`, `libtool`, `m4`, and `make` if you prefer
  autotools. Python 3 and `python3-pip` are also present.

## `tdb` command-line tool

The `tdb` binary accepts one of three subcommands: `make`, `dump`,
`merge`. Two — `make` and `dump` — form the primary
input/output pipeline; `merge` combines multiple existing `traildb`
files into one. Every subcommand takes flags with **`getopt_long`-style
parsing**: short options may be spelled `-c`, `-i FILE`, `-o FILE`;
long options may be spelled `--csv`, `--no-bigrams`, `--tdb-format=pkg`
(with an `=`) or `--tdb-format pkg` (separated by whitespace).

### Common flags

| Flag                       | Meaning                                                    |
| -------------------------- | ---------------------------------------------------------- |
| `-c`, `--csv`              | Read or write CSV (default; whitespace-separated by default). |
| `-j`, `--json`             | Read or write JSON — one JSON object per line.             |
| `-i FILE`, `--input FILE`  | Input source. For `make` the events; for `dump` the `traildb` to read. Default: stdin for `make`, `a` for `dump`. |
| `-o FILE`, `--output FILE` | Output destination. For `make` the `traildb` to create; for `dump` the events. Default: `a` for `make`, stdout for `dump`. |
| `-f LIST`, `--fields LIST` | Field specification (comma-separated). See below.          |
| `-F EXPR`, `--filter EXPR` | Event filter, applied on `dump` and `merge`. See below.    |
| `--csv-header`             | On `make -c`, read field names from the first CSV row.     |
| `--tdb-format=pkg\|dir`    | Output format for `make`: `pkg` (default, a single tar file) or `dir` (a directory of files). |
| `--no-bigrams`             | On `make`, disable the bigram encoding pass.               |
| `--no-index`               | On `dump -F`, ignore any persisted `-F` index and match by scanning trails directly. |

### `tdb make`

```
tdb make [-c|-j] [-i FILE] [-o OUTPUT] [-f LIST] [--csv-header]
         [--tdb-format=pkg|dir] [--no-bigrams]
```

Reads a stream of events (from `-i FILE`, or stdin if unspecified) and
produces a new `traildb` at `OUTPUT` (default `a`). Every input event
must carry exactly two mandatory columns — `uuid` (a 32-character
hex-encoded 16-byte identifier of the trail the event belongs to) and
`time` (a `uint64_t` timestamp) — plus any number of additional
user-defined string fields.

**Field spec (`-f`).** Names are comma-separated. `uuid` and `time` are
mandatory and must be present exactly once each; the remaining names
become the trail's user fields in the given order. For example
`-f uuid,time,action,country` declares two user fields `action` and
`country`.

**`--csv-header`.** If given, `tdb make -c` skips `-f` and instead
reads the field names from the first row of the input, treating them
exactly as `-f` would have.

**Formats.**

* `-j` (JSON): each input line is a JSON object; keys map directly to
  field names. Extra keys not listed in the schema are ignored.
* `-c` (CSV, the default): each input line is delimiter-separated in
  the order given by `-f` (or by the header row when `--csv-header`).
  The default delimiter is a single space character; column count must
  equal the field count.

**Output format (`--tdb-format`).** With `--tdb-format=pkg` (the
default), `tdb make -o NAME` produces a single file `NAME.tdb` — a tar
archive that packages every internal section together. With
`--tdb-format=dir`, `tdb make -o NAME` produces a directory `NAME/`
containing individual per-section files. In `dir` form the directory
must, at minimum, contain the files `info`, `fields`, `version`,
`uuids`, and `trails.data` (plus any other internal sections your
implementation writes such as a lexicon, codebook, or table of
contents).

**`--no-bigrams`.** Skips the bigram-selection pass of the encoding
pipeline. Output must still be a valid `traildb` that dumps back
byte-for-byte identically at the event level; the flag only affects
the compression path.

### `tdb dump`

```
tdb dump [-c|-j] [-i INPUT] [-o FILE] [-f LIST] [-F EXPR] [--no-index]
```

Opens the `traildb` at `INPUT` (default `a`) and writes every event to
stdout (or to `-o FILE`), one event per line. Trails are dumped one at
a time; within each trail events are yielded in ascending timestamp
order.

**Path resolution.** `-i NAME` opens either `NAME.tdb` (package format)
or `NAME/` (directory format) transparently — the caller passes the
same base name regardless of the format chosen at `make` time.

**Output formats.**

* `-j` (JSON): one JSON object per line, with keys in the field-schema
  order. Every value is serialised as a JSON **string** (including
  `time`). Formatting is exact:
  `{"uuid": "0000…0001", "time": "10", "action": "click"}` — one space
  after each `:`, `", "` between successive key/value pairs, and a
  single trailing newline per event.
* `-c` (CSV, the default): one delimiter-joined line per event, in the
  field-schema order. Default delimiter is a single space.

**`-F EXPR` filter.** Selects a subset of events. Grammar:

* A **term** is one of `field=value` (equals), `field!=value` (not
  equals), or `field=` (equals empty).
* Terms separated by **whitespace** form an OR clause (the *disjunction*
  of the terms) — an event matches the clause if any of its terms
  matches.
* Clauses separated by **`&`** form the AND of the clauses (the
  *conjunction*) — an event matches the filter if it matches every
  clause.

Example: `-F "country=US action=view & price!="` selects events whose
country is US OR action is view, **and** whose price is not empty.

**`--no-index`.** By default `dump -F` may consult a pre-built filter
index, if one exists next to the input. `--no-index` disables that
optimization and forces a plain trail scan; both paths must return the
same events.

### `tdb merge`

```
tdb merge [-o OUTPUT] TDB1 TDB2 [TDB3 …]
```

Combines two or more existing `traildb` inputs (given as positional
arguments after the options) into a new `traildb` at `OUTPUT`. Every
event from every input appears in the result; trails with the same
UUID across inputs are concatenated in timestamp order; the field
schema of every input must match.

### Error behaviour

Every failure — missing input file, malformed input line, unknown
subcommand, bad flag — must exit with a **non-zero** status and print
a human-readable diagnostic. The diagnostic for a missing / unreadable
`traildb` should surface the underlying error name (e.g. the string
`TDB_ERR_IO_OPEN`, or the same text `tdb_error_str` would return for
that code).

## Public C API (`traildb.h`)

Everything below lives in the single public header `<traildb.h>` (which
in turn drags in `<tdb_types.h>`, `<tdb_error.h>`, and `<tdb_limits.h>`
for the associated types, error codes, and limit constants). The
implementation of every symbol is compiled into `libtraildb.{so,a}` and
callable by any C driver linked with `-ltraildb`.

The API is arranged in seven groups: constructor, reader, lexicon,
UUID helpers, cursor, event filter, and multi-cursor.

### Types

```c
typedef struct _tdb_cons  tdb_cons;   /* opaque -- constructor handle    */
typedef struct _tdb       tdb;        /* opaque -- reader handle         */

typedef uint32_t tdb_field;           /* dense field id, 0 = "time"      */
typedef uint64_t tdb_val;             /* dense value id within a field   */
typedef uint64_t tdb_item;            /* packed (field, val) pair        */

typedef struct __attribute__((packed)) {
    uint64_t         timestamp;
    uint64_t         num_items;
    const tdb_item   items[0];
} tdb_event;

typedef struct {
    const tdb        *db;
    const tdb_event  *event;
    uint64_t          cursor_idx;     /* index of the source cursor      */
} tdb_multi_event;

typedef struct {
    struct tdb_decode_state *state;
    const char              *next_event;
    uint64_t                 num_events_left;
} tdb_cursor;

typedef struct tdb_multi_cursor tdb_multi_cursor;    /* opaque           */

struct tdb_event_filter;                             /* opaque           */

typedef enum {
    TDB_EVENT_FILTER_UNKNOWN_TERM    = 0,
    TDB_EVENT_FILTER_MATCH_TERM      = 1,
    TDB_EVENT_FILTER_TIME_RANGE_TERM = 2,
} tdb_event_filter_term_type;

typedef enum { /* option keys, see "Options" below */ } tdb_opt_key;

typedef union {
    const void *ptr;
    uint64_t    value;
} tdb_opt_value;
```

The two "cursor" structs (`tdb_cursor`, `tdb_multi_cursor`) are
allocated and freed only through the API — treat their layout as
implementation-owned; consumers only touch `tdb_event` (via `items` /
`timestamp` / `num_items`) and `tdb_multi_event` (via `db` / `event` /
`cursor_idx`).

Return values of type `tdb_error` are `TDB_ERR_OK` (`0`) on success
and a negative error code on failure.

### Constructor path

Build a `traildb` in five phases: allocate → open → add events →
finalize → close.

```c
tdb_cons  *tdb_cons_init  (void);
tdb_error  tdb_cons_open  (tdb_cons *cons,
                           const char *root,
                           const char **ofield_names,
                           uint64_t     num_ofields);
tdb_error  tdb_cons_add   (tdb_cons     *cons,
                           const uint8_t uuid[16],
                           uint64_t      timestamp,
                           const char  **values,
                           const uint64_t *value_lengths);
tdb_error  tdb_cons_append(tdb_cons *cons, const tdb *db);
tdb_error  tdb_cons_finalize(tdb_cons *cons);
void       tdb_cons_close (tdb_cons *cons);

tdb_error  tdb_cons_set_opt(tdb_cons     *cons,
                            tdb_opt_key   key,
                            tdb_opt_value value);
```

* **`tdb_cons_init`** allocates a fresh constructor handle. Return
  `NULL` on out-of-memory.
* **`tdb_cons_open`** binds the constructor to the output path `root`
  (the constructor decides whether it becomes a package file or a
  directory based on the current
  `TDB_OPT_CONS_OUTPUT_FORMAT` option, see below) and declares the
  user fields. `ofield_names` is `num_ofields` pointers to
  null-terminated ASCII names; the implicit "time" field is not
  included in this list.
* **`tdb_cons_add`** appends one event to the trail identified by
  `uuid`, at the given `timestamp`, with `num_ofields` string values
  and matching `value_lengths`. Passing an empty string (length `0`)
  is legal and produces the "empty value" for that field.
* **`tdb_cons_append`** ingests every trail and event of an already-
  opened `tdb` into the current constructor. Returns
  `TDB_ERR_APPEND_FIELDS_MISMATCH` if the source `tdb`'s field schema
  does not match the constructor's.
* **`tdb_cons_finalize`** seals the constructor: writes headers,
  compresses trails, and flushes the output to disk. Must be called
  exactly once per successful `tdb_cons_open`.
* **`tdb_cons_close`** frees the handle. Always safe to call, even
  after `tdb_cons_finalize`.

### Reader path

```c
tdb       *tdb_init         (void);
tdb_error  tdb_open         (tdb *db, const char *root);
void       tdb_close        (tdb *db);

uint64_t   tdb_num_events   (const tdb *db);

tdb_error  tdb_set_opt      (tdb *db, tdb_opt_key key, tdb_opt_value  value);
tdb_error  tdb_get_opt      (tdb *db, tdb_opt_key key, tdb_opt_value *value);
```

* **`tdb_init`** allocates a fresh reader handle; `tdb_open` binds it
  to `root` and loads the on-disk structure. `root` may point at
  either a package file (`root.tdb`) or a directory (`root/`); both
  cases must resolve transparently. Returns non-zero on any I/O or
  format error (e.g. path missing, invalid header).
* **`tdb_close`** frees the handle.
* **`tdb_num_events`** returns the total number of events across all
  trails.
* **`tdb_set_opt` / `tdb_get_opt`** manipulate reader-level options
  (see the Options section).

### Lexicon

Each user field has a *lexicon* — the dense set of distinct string
values ever written into that field, indexed by a per-field `tdb_val`.

```c
tdb_error   tdb_get_field     (const tdb *db,
                               const char *field_name,
                               tdb_field  *field);
uint64_t    tdb_lexicon_size  (const tdb *db, tdb_field field);
tdb_item    tdb_get_item      (const tdb *db,
                               tdb_field   field,
                               const char *value,
                               uint64_t    value_length);
const char *tdb_get_item_value(const tdb *db,
                               tdb_item    item,
                               uint64_t   *value_length);
```

* **`tdb_get_field`** resolves a field name to its dense `tdb_field`
  id. Returns `TDB_ERR_UNKNOWN_FIELD` if the name is not in the
  schema.
* **`tdb_lexicon_size(db, field)`** returns the number of distinct
  values in the given field's lexicon **including the implicit empty
  value slot**, so a field with three distinct non-empty values has
  `tdb_lexicon_size == 4`.
* **`tdb_get_item`** looks up a `(field, value_bytes, value_length)`
  triple in the lexicon and returns the packed `tdb_item`. If the
  value is not present the return value is `0` — the sentinel for
  "empty value / not found".
* **`tdb_get_item_value`** does the reverse: given a `tdb_item`, it
  returns a pointer to the value's bytes and writes the byte length
  to `*value_length`. The returned pointer is owned by the reader and
  is valid until `tdb_close`.

### UUID helpers

Trails are keyed by raw 16-byte UUIDs but often exchanged as 32-char
hex strings.

```c
tdb_error       tdb_get_trail_id(const tdb *db,
                                 const uint8_t uuid[16],
                                 uint64_t     *trail_id);
void            tdb_uuid_hex    (const uint8_t uuid[16],
                                 uint8_t       hexuuid[32]);
tdb_error       tdb_uuid_raw    (const uint8_t hexuuid[32],
                                 uint8_t       uuid[16]);
```

* **`tdb_get_trail_id`** maps a raw UUID to the dense `trail_id` used
  by cursors. Returns `TDB_ERR_UNKNOWN_UUID` when the UUID is not
  present in the reader.
* **`tdb_uuid_hex`** writes the 32-char **lowercase** hex encoding of
  `uuid` into `hexuuid` (no null terminator).
* **`tdb_uuid_raw`** parses `hexuuid` into `uuid`. Returns
  `TDB_ERR_INVALID_UUID` if any character is outside the hex alphabet.

### Cursor

A cursor is a stateful iterator over a single trail's events.

```c
tdb_cursor       *tdb_cursor_new       (const tdb *db);
void              tdb_cursor_free      (tdb_cursor *cursor);
tdb_error         tdb_get_trail        (tdb_cursor *cursor, uint64_t trail_id);
uint64_t          tdb_get_trail_length (tdb_cursor *cursor);
const tdb_event  *tdb_cursor_next      (tdb_cursor *cursor);
const tdb_event  *tdb_cursor_peek      (tdb_cursor *cursor);
tdb_error         tdb_cursor_set_event_filter(tdb_cursor *cursor,
                                              const struct tdb_event_filter *filter);
```

* **`tdb_cursor_new`** allocates a cursor bound to the reader `db`.
  Free with `tdb_cursor_free`.
* **`tdb_get_trail(cursor, trail_id)`** re-positions the cursor at
  the start of `trail_id`, discarding any prior state.
* **`tdb_get_trail_length`** returns the count of events remaining on
  the cursor and, as a side effect, **advances the cursor to
  completion** — after the call returns, `tdb_cursor_next` yields
  `NULL` immediately. This is intentional (the count is produced by
  the same walk that would iterate the trail), not a bug: a naive
  "peek at internal state and return length without advancing"
  implementation does NOT satisfy this contract. Callers who want to
  iterate the trail *after* asking for its length MUST call
  `tdb_get_trail(cursor, trail_id)` again to reset the cursor.
* **`tdb_cursor_next`** advances the cursor and returns a pointer to
  the next event, or `NULL` at end-of-trail. The returned pointer is
  valid until the *next* call to `tdb_cursor_next` / `_peek` on the
  same cursor.
* **`tdb_cursor_peek`** returns a pointer to the next event **without
  advancing**. Repeated `tdb_cursor_peek` calls return the same event;
  a subsequent `tdb_cursor_next` returns that same event and only then
  advances.
* **`tdb_cursor_set_event_filter`** attaches a filter to the cursor;
  from then on `tdb_cursor_next` / `_peek` skip events that do not
  match. The filter is *not* copied — its lifetime must exceed the
  cursor's use of it.

Within a single trail events are yielded in **ascending timestamp
order** regardless of the order they were `tdb_cons_add`-ed at
construction time.

### Event filter

An event filter is a boolean expression over `(field, value)` items
and time ranges, in conjunctive normal form: it is a conjunction (AND)
of clauses, each of which is a disjunction (OR) of terms.

```c
struct tdb_event_filter *tdb_event_filter_new           (void);
struct tdb_event_filter *tdb_event_filter_new_match_all (void);
struct tdb_event_filter *tdb_event_filter_new_match_none(void);
void                     tdb_event_filter_free (struct tdb_event_filter *filter);

tdb_error tdb_event_filter_add_term      (struct tdb_event_filter *filter,
                                          tdb_item                 term,
                                          int                      is_negative);
tdb_error tdb_event_filter_add_time_range(struct tdb_event_filter *filter,
                                          uint64_t                 start_time,
                                          uint64_t                 end_time);
tdb_error tdb_event_filter_new_clause    (struct tdb_event_filter *filter);

uint64_t  tdb_event_filter_num_clauses(const struct tdb_event_filter *filter);
tdb_error tdb_event_filter_num_terms  (const struct tdb_event_filter *filter,
                                       uint64_t  clause_index,
                                       uint64_t *num_terms);
tdb_error tdb_event_filter_get_item   (const struct tdb_event_filter *filter,
                                       uint64_t  clause_index,
                                       uint64_t  item_index,
                                       tdb_item *item,
                                       int      *is_negative);
tdb_error tdb_event_filter_get_term_type(const struct tdb_event_filter *filter,
                                         uint64_t  clause_index,
                                         uint64_t  term_index,
                                         tdb_event_filter_term_type *term_type);
tdb_error tdb_event_filter_get_time_range(const struct tdb_event_filter *filter,
                                          uint64_t  clause_index,
                                          uint64_t  term_index,
                                          uint64_t *start_time,
                                          uint64_t *end_time);
```

* **`tdb_event_filter_new`** returns a fresh, empty filter with a
  single empty clause.
* **`tdb_event_filter_new_match_all`** / **`_new_match_none`** return
  pre-built filters that always / never match; useful as neutral
  elements for cursor attachment.
* **`tdb_event_filter_add_term(filter, item, is_negative)`** adds an
  item term to the **current clause** (the last one added). `item` is
  a packed `tdb_item` from `tdb_get_item`. `is_negative = 0` means the
  event's `(field, value)` must equal `item`; `is_negative = 1` means
  it must *not* equal `item`. Within a clause, terms combine with OR.
* **`tdb_event_filter_add_time_range(filter, start, end)`** adds a
  time-range term to the current clause. The range is **half-open**:
  an event's timestamp `t` matches iff `start <= t < end`.
* **`tdb_event_filter_new_clause`** closes the current clause and
  opens a new empty one. Between-clause combination is AND.
* The `get_*` / `num_*` accessors let a caller reflect on an
  already-built filter:
  * `num_clauses` counts clauses.
  * `num_terms(f, i, &n)` counts terms in clause `i`.
  * `get_term_type(f, i, j, &t)` returns
    `TDB_EVENT_FILTER_MATCH_TERM` (`= 1`) for item terms or
    `TDB_EVENT_FILTER_TIME_RANGE_TERM` (`= 2`) for time-range terms.
  * `get_item(f, i, j, &item, &neg)` reads back the `item` and
    negation flag of an item term.
  * `get_time_range(f, i, j, &start, &end)` reads back the `[start,
    end)` bounds of a time-range term.

### Multi-cursor

A multi-cursor merges N single-trail cursors into one stream, yielding
their events globally sorted by timestamp.

```c
tdb_multi_cursor       *tdb_multi_cursor_new (tdb_cursor **cursors,
                                              uint64_t     num_cursors);
void                    tdb_multi_cursor_free(tdb_multi_cursor *mc);
void                    tdb_multi_cursor_reset(tdb_multi_cursor *mc);
const tdb_multi_event  *tdb_multi_cursor_next (tdb_multi_cursor *mc);
const tdb_multi_event  *tdb_multi_cursor_peek (tdb_multi_cursor *mc);
```

* **`tdb_multi_cursor_new`** takes an array of already-positioned
  single cursors and returns a merged view. The multi-cursor does not
  take ownership — callers must keep each `tdb_cursor` alive for the
  multi-cursor's lifetime, and free everything themselves.
* **`tdb_multi_cursor_reset`** must be called after any of the
  underlying cursors is repositioned (via `tdb_get_trail` or
  `tdb_cursor_next` outside the multi-cursor's control) so the merge
  heap re-reads their heads.
* **`tdb_multi_cursor_next`** returns the next `tdb_multi_event` in
  global timestamp order, or `NULL` when every underlying cursor is
  exhausted. Each returned event carries a `cursor_idx` pointing at
  the source cursor's position in the `cursors` array passed to
  `_new`, and a `db` pointing at the source cursor's reader.
* **`tdb_multi_cursor_peek`** is the corresponding non-consuming peek.
* **`tdb_multi_cursor_free`** frees the multi-cursor itself.

### Item packing

`tdb_item` packs a `(field, value_id)` pair into a single integer.
Two encodings exist:

* **Narrow (32-bit representation):** the field id fits in 7 bits and
  the value id fits in 24 bits. Used when both fit.
* **Wide (64-bit representation):** used when either the field id or
  the value id does not fit in the narrow layout. In wide form the
  field id can grow to 14 bits and the value id to 40 bits.

Three inline helpers make packing and unpacking free of magic
constants at the call site:

```c
tdb_item  tdb_make_item  (tdb_field field, tdb_val val);
tdb_field tdb_item_field (tdb_item item);
tdb_val   tdb_item_val   (tdb_item item);
int       tdb_item_is32  (tdb_item item);      /* nonzero = narrow */
```

`tdb_make_item(field, val)` chooses the encoding automatically. The
three decoders return the same `field` and `val` you gave to
`tdb_make_item`, regardless of which encoding was used, and
`tdb_item_is32` tells you which one that was.

## Options (`tdb_opt_key`)

`tdb_set_opt` / `tdb_cons_set_opt` accept a `tdb_opt_key` and a
`tdb_opt_value`. The value union is:

```c
typedef union {
    const void *ptr;
    uint64_t    value;
} tdb_opt_value;
```

Constructor keys (used with `tdb_cons_set_opt` **before**
`tdb_cons_open`):

* **`TDB_OPT_CONS_OUTPUT_FORMAT`** — `value.value` selects the
  on-disk layout. Two values are defined:
  * `TDB_OPT_CONS_OUTPUT_FORMAT_DIR`     (= `0`): output is a
    directory.
  * `TDB_OPT_CONS_OUTPUT_FORMAT_PACKAGE` (= `1`): output is a single
    `.tdb` tar file. This is the default.
* **`TDB_OPT_CONS_NO_BIGRAMS`** — when set to `value.value = 1`,
  disables the bigram encoding pass. Same behavioural contract as the
  CLI's `--no-bigrams`.

Reader keys (used with `tdb_set_opt`):

* **`TDB_OPT_ONLY_DIFF_ITEMS`** — when set to `value.value = 1`,
  cursors over the reader switch to **event-diff** mode. Every
  original event is **still yielded** by `tdb_cursor_next` at its
  true timestamp — this option does NOT skip, drop, or filter events.
  What changes is per-event content: the yielded `tdb_event`'s
  `num_items` counts only the items whose `(field, value)` pair
  differs from the previous event on the same trail. Items that
  repeat their previous value are omitted from the `items[]` array;
  an event whose items all repeat the previous event's values
  surfaces with `num_items == 0` (and still appears in the stream).
  **Invariant:** for a given trail, the total number of `tdb_event`s
  yielded by the cursor is identical whether or not this option is
  set; only `num_items` per event, and the contents of `items[]`,
  change.

`tdb_get_opt` on any reader key returns the currently-set value in
`*value` (i.e. the same `.value` a prior `tdb_set_opt` wrote).

Passing an unrecognized `tdb_opt_key` to `tdb_set_opt` or
`tdb_cons_set_opt` must return **`TDB_ERR_UNKNOWN_OPTION`**; the
value must not be applied.

## Errors (`tdb_error`)

Every fallible API returns a `tdb_error` — `TDB_ERR_OK` (= `0`) on
success, or one of the negative codes below on failure. The full list
lives in `tdb_error.h`; the codes the public contract calls out
explicitly are:

| Code                              | Value | When                                                                       |
| --------------------------------- | ----: | -------------------------------------------------------------------------- |
| `TDB_ERR_OK`                      |     0 | Success.                                                                   |
| `TDB_ERR_NOMEM`                   |    -2 | Allocation failed.                                                         |
| `TDB_ERR_UNKNOWN_FIELD`           |    -4 | `tdb_get_field` did not find the requested field name.                     |
| `TDB_ERR_UNKNOWN_UUID`            |    -5 | `tdb_get_trail_id` did not find the requested UUID.                        |
| `TDB_ERR_UNKNOWN_OPTION`          |    -9 | `tdb_set_opt` / `tdb_cons_set_opt` received an unrecognised `tdb_opt_key`. |
| `TDB_ERR_INVALID_UUID`            |   -11 | `tdb_uuid_raw` received a hex string with non-hex characters.              |
| `TDB_ERR_APPEND_FIELDS_MISMATCH`  |  -262 | `tdb_cons_append`'s source `tdb` has a schema incompatible with the constructor's. |
| `TDB_ERR_IO_OPEN`                 |   -65 | Underlying open()/stat() failed for a `traildb` path.                      |

**`tdb_error_str`.**

```c
const char *tdb_error_str(tdb_error errcode);
```

Returns a non-`NULL`, non-empty human-readable string for every
defined error code, **including `TDB_ERR_OK`**. Distinct error codes
map to distinct, code-specific strings, so a caller can tell two
different failures apart from the returned text alone; the pointer is
never `NULL` and the string is never `""`.
