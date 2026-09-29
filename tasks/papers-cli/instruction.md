# papers — a CLI for managing a BibTeX library and the PDFs it points to

Build `papers`, a command-line bibliography manager. It maintains a BibTeX
file and (optionally) a directory of attached PDFs, with duplicate
detection, file renaming from BibTeX fields, LaTeX↔Unicode field
conversion, crossref metadata lookup, and optional git-tracked backup of
every mutation.

Internal organisation is at your discretion. The tests pin only the
public CLI surface and the import paths listed under **Library
interfaces**.

## Dependencies

**The environment is fully offline. Every dependency below is already
installed — do NOT install anything (no `pip install`, no network access).**
The project is installed for you by a `setup.sh` that runs offline
(`pip install -e . --no-build-isolation`), so just declare your dependencies
and package metadata in `pyproject.toml` as usual.

- Python ≥ 3.9.
- Pre-installed and importable: `PyMuPDF` (`import fitz`),
  `bibtexparser>=2.0.0b2`, `unidecode`, `python-slugify` (`import slugify`),
  `rapidfuzz`, and `requests` (use it as the HTTP client for the crossref
  calls).
- `git` (already installed at runtime; do not install it).
- Declare a `papers` console entry point in `pyproject.toml` so
  `papers` is on PATH and `python -m papers ...` also works.

## Configuration

JSON config in two flavours:

- **Global** (default): `$XDG_CONFIG_HOME/papersconfig.json`.
- **Local** (`install --local`): `.papersconfig.json` in cwd. Walks up
  from cwd to root to find it; takes priority over the global file.

Other XDG paths:
- Cache: `$XDG_CACHE_HOME/papers` (crossref response cache).
- Backup: `$XDG_DATA_HOME/papers/backups/<bibname>` (git-tracked when
  `--git` install).

When `--bibtex` / `--filesdir` aren't passed, every subcommand reads
them from the active config.

## CLI

### `papers install [--local] [--force] [--git] --bibtex PATH --filesdir PATH`

Create or update the configuration. `--force` skips prompts. `--local`
writes `.papersconfig.json` to cwd. `--git` initialises a backup repo
under `$XDG_DATA_HOME/papers/backups/<bibname>/`, makes a baseline
commit, and from then on each mutating command commits to that repo so
`undo`/`redo` can walk arbitrarily many steps.

### `papers status [-v]`

Print the active configuration. Verbose mode includes the bibtex and
files-dir paths.

### `papers add SOURCE [--bibtex PATH] [--mode {i,u,U,o,s,r,a}]`

`SOURCE` may be a `.bib` file (entries inserted directly) or a `.pdf`
(DOI parsed from the PDF, then fetched from crossref — see **Metadata
fetch**). Duplicate detection runs before insertion at PARTIAL
similarity (default).

`--mode` controls conflict resolution. Default `i` is interactive. The
non-interactive modes the tests exercise are `u` (update missing fields
on the existing entry, preserve conflicts) and `s` (skip the new
entry). Other modes (`U`, `o`, `r`, `a`) match standard
overwrite/raise/append-anyway semantics.

If the new entry has the same bibtex key as an existing one but
different content, raise `DuplicateKeyError`.

### `papers extract PDF`

Parse `PDF` for a DOI, fetch the bibtex from crossref, and print it to
stdout. Does not modify the library.

### `papers list [--bibtex PATH] [filters...] [output flags] [actions...]`

The search/edit command. `--bibtex PATH` overrides the active config's
bibtex file (falling back to it when omitted), exactly as `check` /
`filecheck` do.

Filters (all AND-combined):
- `-a/--author A ...`: any author matches (substring).
- `-y/--year Y ...`: year in the given list.
- `--key K ...`: bibtex key in the given list.
- `--tag K ...` (also `--keywords`): any matching keyword.
- `--duplicates`: only entries that are duplicates (per active
  similarity) of some other entry.
- `--invert`: negate the active filters — list the entries that do *not*
  match (e.g. `--author perrette --invert` lists every entry whose
  authors do not include "perrette").

Output flags (mutually exclusive — default is a one-liner per entry):
- default: one summary line per entry, beginning with the entry's bibtex
  key, followed by the title and a `doi:<doi>` marker — e.g.
  `perrette_yool2011: Near-ubiquity of ice-edge blooms... (doi:10.5194/bg-8-515-2011)`.
- `--plain`: raw bibtex blocks.
- `--key-only`: just the bibtex key, one per line.

Actions:
- `--delete`: remove the filtered subset from the library file
  (non-interactive — no prompt, no `--force` needed).
- `--add-tag K ...` (also `--add-keywords`): append K to the entries'
  `keywords` field. `--tag` searches over the same field.

### `papers check [--bibtex PATH] [-f/--force] [--format-name] [--fix-doi] [--encoding {latex,unicode}]`

Walk the library and fix entries. `--force` skips prompts. `--bibtex PATH`
overrides the active config's bibtex file (falling back to it when omitted).

- `--format-name`: normalise the `author` field so each name is
  `"Family, Given"` joined by `" and "`. E.g.
  `"John Smith and Jane Doe"` → `"Smith, John and Doe, Jane"`.
- `--fix-doi`: strip leading `"DOI:"` from `doi` fields.
- `--encoding {latex,unicode}`: convert all field values to the chosen
  encoding (LaTeX escapes ↔ Unicode characters).

### `papers filecheck [--bibtex PATH] [--filesdir PATH] [--rename] [--delete-broken] [--force]`

`--bibtex PATH` / `--filesdir PATH` override the active config's bibtex file
and files directory respectively (falling back to it when omitted).

- `--rename`: rename each attached file using the active name format
  (and move it to `--filesdir` if that differs from the file's current
  location).
- `--delete-broken`: drop `file=` entries whose target does not exist.
- `--force`: skip prompts.

The bibtex `file` field uses the JabRef triple form
`<basename>:<path>:<type>` (the `<basename>` and `<type>` components are
usually empty, e.g. `file = {:/abs/path/paper.pdf:pdf}`); the middle
`<path>` component is the attached file's location and is what `filecheck`
reads and rewrites. Multiple attachments are `;`-separated. A bare path
with no `:` is also accepted (then `<path>` is the whole value).

### `papers undo` / `papers redo`

Revert / replay the last mutation. With `--git` install the history is
unbounded, walked across the backup repo; without `--git`, only the
single previous state is remembered.

### `papers git ARGS...`

Pass-through to `git` running inside the backup repository. E.g.
`papers git log --oneline` lists every backup commit.

## Filename / key templates

Both the bibtex key (`KEYFORMAT`) and the attached-filename
(`NAMEFORMAT`) are produced by the same template engine. Defaults:

- `KEYFORMAT`: template `"{author}{year}"`, `author_num=2`,
  `author_sep="_"`.
- `NAMEFORMAT`: template `"{authorX}_{year}_{title}"`, `author_sep="_"`,
  `title_sep="-"`.

Template fields (case matters):

- `{author}`: slugified, lowercase, `author_sep`-joined family names of
  the first `author_num` authors. `{Author}` is the same with each name
  title-cased; `{AUTHOR}` uppercased.
- `{authorX}`: lowercased — `"first"` for one author,
  `"first and second"` for two, `"first et al"` for three or more
  (spaces replaced by `author_sep`). `{AuthorX}` is the title-cased
  variant.
- `{year}`: the `year` field (default `"0000"`).
- `{title}`: slugified title, joined by `title_sep`, truncated by
  `title_word_num` / `title_word_size` / `title_length`. `{Title}`
  capitalises each word.
- `{ID}`, `{doi}`, `{doi_or_id}`, `{journal}`: the corresponding entry
  field (slugified for `doi_or_id`).

`author_sep` and `title_sep` may be any string including `""`.

## Duplicate detection

`papers.bib` exposes five integer constants:

| Constant             | Value | Two entries match when…                          |
|----------------------|-------|--------------------------------------------------|
| `EXACT_DUPLICATES`   | 104   | every field value is identical                   |
| `GOOD_DUPLICATES`    | 103   | same DOI AND same author+title identifier        |
| `FAIR_DUPLICATES`    | 102   | same DOI (whatever author/title)                 |
| `PARTIAL_DUPLICATES` | 101   | same DOI OR same author+title identifier         |
| `FUZZY_DUPLICATES`   | 100   | fuzzy author+title score ≥ `fuzzy_ratio` (80)    |

The "author+title identifier" is the lowercased, ASCII-only
concatenation of family names + title. Default similarity for `add` and
`Biblio` is `PARTIAL`.

## Metadata fetch (crossref)

For commands that fetch metadata, the pipeline is:
1. If a PDF was given, parse the DOI from it (checking the PDF's embedded
   metadata first, then falling back to a plain-text DOI regex over the first
   few pages).
2. `GET <BASE>/works/<DOI>` returns `{"message": {...}}`.
3. Convert that `message` dict to a bibtex string.

`<BASE>` MUST be readable from the `PAPERS_CROSSREF_API` environment
variable, defaulting to `http://api.crossref.org`. (This is the only
test-aware hook the library exposes; expose it for any code path that
talks to crossref.)

## Library interfaces (importable Python API)

These are the only import paths the tests pin.

### `papers.bib`

- `class Biblio` — wraps a `bibtexparser.Library`. Required surface:
  - classmethod `Biblio.load(bibtex_path, filesdir, relative_to=None)`.
  - `dumps() -> str` — serialise back to a bibtex string. Round-trip
    through `bibtexparser` must preserve entries.
  - `entries` — list of bibtex entries.
- `compare_entries(e1, e2, fuzzy=False) -> int` — returns one of the
  duplicate-score constants above, or `0`.
- `are_duplicates(e1, e2, similarity="PARTIAL", fuzzy_ratio=80) -> bool`
  — True iff `compare_entries` reaches the threshold for `similarity
  ∈ {"EXACT","GOOD","FAIR","PARTIAL","FUZZY"}`.
- Entry shape accepted by `compare_entries` / `are_duplicates`: in
  addition to whatever `Biblio.entries` materialises, both must accept a
  bibtex entry given as a **plain mapping** — string keys `"ID"` (bibtex
  key) and `"ENTRYTYPE"` (entry type, e.g. `"article"`) plus lowercase
  field names (`"author"`, `"title"`, `"doi"`, `"year"`, …) mapped to
  string values (the classic bibtexparser dict-entry form). Read fields,
  the DOI, the key, and the entry type through mapping access (subscript
  / `.get()`) so plain-dict entries compare correctly.
- `EXACT_DUPLICATES`, `GOOD_DUPLICATES`, `FAIR_DUPLICATES`,
  `PARTIAL_DUPLICATES`, `FUZZY_DUPLICATES` — the integer constants.

### `papers.extract`

- `parse_doi(text: str) -> str` — extract a DOI from arbitrary text.
  Handles `doi:` prefix, URL form (`https://doi.org/...`, `dx.doi.org/`,
  `www.<pub>.org/.../<doi>`), and DOIs broken by a single newline (with
  optional surrounding whitespace) at either of the two split points
  interior to the DOI, which must be rejoined into the whole DOI:
  immediately after the `10.` prefix and before the registrant digits, or
  after the registrant's slash. Strips trailing `.pdf`, unbalanced `)`, and
  publisher path suffixes (`/-/dcsupplemental`, `preprint`, `received`,
  ...). When the text contains more than one distinct DOI, the **first DOI
  in reading order** wins. Prefers non-supplemental DOIs over `.s<digit>`
  variants. Raises `DOIParsingError` if no valid DOI is found.
- `class DOIParsingError(ValueError)`.
- `crossref_to_bibtex(message: dict) -> str` — convert a crossref
  `message` dict to a bibtex string. Maps `type` to bibtex entry type
  (`journal-article` → `article`, `book` → `book`,
  `proceedings-article` → `inproceedings`, fallback `misc`). Pulls
  `title`, `author` (formatted `"Family, Given"` joined by `" and "`),
  `DOI`, `URL`, `container-title` → `journal`, `volume`, `issue` →
  `number`, `page` → `pages`, year from `published-print` /
  `published-online` / `issued`. Bibtex `ID` is set to the DOI.
- `extract_pdf_doi(pdf_path: str, image: bool = False) -> str` — DOI
  from a PDF (metadata first, text fallback).

### `papers.encoding`

- `standard_name(author: str) -> str` — normalise each name in an
  `" and "`-joined string to `"Family, Given"`. Already-normalised input
  passes through unchanged.
- `family_names(author: str) -> list[str]` — family-name component of
  each author.

### `papers.latexenc`

- `latex_to_unicode(text: str) -> str` — `M\"uller` → `Müller`.
- `string_to_latex(text: str) -> str` — Unicode → LaTeX escapes; spaces
  and braces pass through unchanged.

### `papers.filename`

- `class Format(template, author_num=2, author_sep="_", title_word_num=100,
  title_word_size=1, title_length=100, title_sep="-", ...)` — render
  templates against a bibtex entry via `render(**entry)`. See **Filename
  / key templates** for substitution fields.
