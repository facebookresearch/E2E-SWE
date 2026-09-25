# SEC filing parser

Build a Python library that reads the HTML of a U.S. SEC EDGAR filing (quarterly
"10-Q" and annual "10-K" reports) and turns it into a structured, labeled
representation of the document.

A filing is one large HTML page. Visually it is a sequence of headings, body
paragraphs, tables, images, page headers/numbers, and so on. The library's job
is to look at the raw HTML and decide, for each top-level piece of the document,
what kind of content it is — a title, a section heading, a paragraph, a table,
etc. — and then optionally arrange those pieces into a tree that mirrors the
document's section structure.

The package must be importable as `sec_parser`.

## Dependencies

The environment is **offline**: every dependency you need is **already installed**,
and you **must not install anything** (there is no network). The project is
installed for you by a `setup.sh` that runs `pip install -e . --no-build-isolation`
against the pre-installed packages, so simply declare your dependencies in the
project metadata (`pyproject.toml` / `setup.py`) — do not attempt to fetch them.

The implementation parses HTML and inspects inline CSS styling, and it can render
tables. The following libraries are available for this and should be used: an HTML
parsing library (`beautifulsoup4` with the `lxml` parser), a CSS-style parsing
helper (`cssutils`), and a data/table library (`pandas`). The Python standard
library (e.g. `hashlib` for the element hash in §7) is also available.

---

## 1. Public API surface

These names must be importable directly from the top-level package, e.g.
`from sec_parser import Edgar10QParser, TitleElement`:

- Parsers: `Edgar10QParser`, `Edgar10KParser`
- Tree: `TreeBuilder`, `SemanticTree`, `TreeNode`
- Low-level HTML wrapper: `HtmlTag`
- Element types: `TextElement`, `TitleElement`, `TopSectionTitle`,
  `TableElement`, `SupplementaryText`, `ImageElement`, `EmptyElement`,
  `PageNumberElement`, `PageHeaderElement`, `CompositeSemanticElement`
- Extensibility base classes: `AbstractProcessingStep`, `AbstractNestingRule`
  (see §9)
- Errors: `SecParserValueError`, `SecParserRuntimeError`

Two more element types are produced by the parser but do not need to be importable
from the top level; they only need to exist with these exact class names:
`TableOfContentsElement` and `IntroductorySectionElement`.

---

## 2. Parsing a document

Both `Edgar10QParser` and `Edgar10KParser` expose the same method:

```
parser.parse(html, *, unwrap_elements=None, include_containers=None,
             include_irrelevant_elements=None) -> list of elements
```

- `html` is the filing HTML as a string.
- The return value is a flat list of element objects, in the order they appear
  in the document.
- The two parsers behave the same way except for how they recognize the
  standard top-level sections of a filing (see §4).

### Output options and their defaults

- **Irrelevant content is dropped by default.** Some elements represent
  document "furniture" rather than content: empty elements, page numbers, page
  headers, and introductory-section elements (see §3). By default these are
  removed from the returned list. Pass `include_irrelevant_elements=True` to keep
  them.
- **Container elements are flattened by default.** When one HTML tag actually
  holds several distinct pieces of content, the parser groups them inside a
  single container element (see §3, "Composite elements"). By default the result
  is flattened so you get the individual inner pieces and not the container.
  - `include_containers=True` keeps the container element *in addition to* its
    inner pieces. The container appears immediately **before** its inner pieces
    in the list. This applies to **every** container: when a container is itself
    an inner piece of another container (nested containers), each container still
    appears immediately before its own inner pieces, so both the outer and the
    nested container — and all their pieces — are surfaced into the same flat
    top-level list, in document order.
  - `unwrap_elements=False` turns flattening off entirely, so a container is
    returned whole and its inner pieces are not listed separately.

---

## 3. The element types and how each is recognized

Each piece of the document is represented by one element object. Every element
exposes:

- `.text` — the element's visible text, with leading and trailing whitespace
  stripped. (Interior whitespace is left as-is; HTML entities are decoded by the
  HTML parser as usual.)
- `.to_dict(...)` — a serializable summary (see §7).

The parser decides each element's type using the rules below. Apply them so that
a given input produces exactly one resulting type.

### Body text — `TextElement`
Ordinary paragraph text that isn't something more specific.

### Titles / headings — `TitleElement`
A short run of text that is visually emphasized is treated as a heading. Treat
text as emphasized if **any** of the following hold:

- It is **bold**. Bold means the CSS `font-weight` is the keyword `bold`, or a
  numeric weight of **600 or greater**. (Weights below 600 are not bold.)
- It is **italic** (`font-style: italic`).
- It is **centered** (`text-align: center`).
- It is **underlined** (`text-decoration: underline`).
- Its text is **overwhelmingly uppercase** — i.e. the large majority of its
  letters are capitals. (A normal sentence with ordinary capitalization is not.)

A style only makes an element a heading if it applies to **most of the
element's text**. If only a small fragment of a paragraph is bold (and the rest
is normal), the paragraph stays body text.

**Heading levels.** Titles carry a 0-based `.level` indicating heading depth.
Levels are assigned by the order in which *distinct* emphasis styles first appear
in the document: the first style seen becomes level 0, the next new (different)
style becomes level 1, and so on. A style that appears again reuses the level it
was first given.

A "style" here is the specific combination of the emphasis signals listed above
(bold / italic / centered / underlined / uppercase) that the element carries.
Only those signals distinguish one style from another — other CSS such as font
size, font family, or color does **not** make two otherwise-equally-emphasized
headings count as different styles.

Only title elements take part in this level numbering. Standard section headings
(§4) are a different kind of element, not titles, and do **not** affect title
levels — so the first ordinary title in a document is level 0 even if section
headings (which may also be bold) appeared before it.

### Top-level section headings — `TopSectionTitle`
SEC filings are divided into standard top-level sections such as "Part I" and
"Item 2. Management's Discussion and Analysis". When a heading names one of these
standard sections, it becomes a `TopSectionTitle` instead of a plain title.
These carry both a `.level` and a `.section_type` (see §4).

A heading is recognized as a section by the **leading** "Part …" or "Item …"
designation at the start of its text; any descriptive title that follows on the
same line (e.g. the "Financial Information" in "PART I — FINANCIAL INFORMATION",
or the rest of "Item 2. Management's Discussion and Analysis") is part of the
same heading and does not prevent recognition. Section recognition is based on
this leading designation regardless of how the heading is styled (bold,
centered, uppercase, etc.).

### Tables — `TableElement` and `TableOfContentsElement`
- An HTML table with **more than one row** becomes a `TableElement`. A table
  with only a single row is not treated as a table (it falls through to ordinary
  text).
- A table that is actually a **table of contents** becomes a
  `TableOfContentsElement`. Recognize this by the table containing a header data
  cell whose text is exactly "Page" (case-insensitive; also accept "Page No." and
  "Page number"). This check runs on something already recognized as a table.

### Images — `ImageElement`
An image (`<img>`) on its own becomes an `ImageElement`. If a single tag holds
both an image and text, it is split (see "Composite elements") into an image
element and a separate text element.

### Recurring page furniture — `PageNumberElement` and `PageHeaderElement`
Short lines that recur many times across the document are page furniture, not
content. A short line is treated as recurring furniture when the same line
appears **five or more times**:

- If the recurring line is a **page number** — i.e. short text with a **varying
  numeric marker**: the **digit portion changes** from one occurrence to the next
  while a short non-digit frame stays constant (e.g. "Page 1", "Page 2", … or
  "- 12 -", "- 13 -", …) — it becomes a `PageNumberElement`. What repeats across
  occurrences is the non-digit frame, not the digits.
- If the recurring line is **running-header text repeated verbatim** — i.e. the
  **whole line, including any digits it contains, is identical every time** (e.g.
  a company name or report title repeated at the top of every page) — it becomes a
  `PageHeaderElement`. "Non-numeric" here means "not a varying numeric marker": a
  verbatim-repeating header is a page header even when it happens to contain
  constant, incidental digits. The deciding factor between the two is whether the
  digits **vary** across occurrences (page number) or **repeat unchanged** with the
  rest of the line (page header) — not merely whether a digit character is present.

Both of these are "irrelevant" (dropped by default; see §2). Recurring-furniture
detection is based on the line's text repeating; it applies even when the line is
styled (for example a centered or bold running header that repeats on every page
is still a page header, not a title). Section headings (above) are the exception —
a line that names a standard Part/Item section is treated as a section even if its
text happens to repeat.

### Supplementary text — `SupplementaryText`
Short qualifying or pointer lines that aren't really body content. Treat a line
as supplementary if any of these hold:

- It is fully wrapped in parentheses, e.g.
  "(In millions, except per share amounts)".
- It is italic and ends with a period (a short italic note).
- It points the reader to the accompanying notes to the financial statements,
  e.g. "See accompanying Notes to Condensed Consolidated Financial Statements."

### Empty elements — `EmptyElement`
A tag with no real text (no letters or digits) is an `EmptyElement` (irrelevant;
dropped by default).

### Introductory section — `IntroductorySectionElement`
Everything that appears **before the first standard section begins** (i.e. before
"Part I") in a filing that does have a Part I is introductory matter — cover
page, forward-looking-statements notices, and the like. Mark each such element as
an `IntroductorySectionElement` (irrelevant; dropped by default). If the document
has no Part I at all, nothing is reclassified this way. This takes precedence over
page-furniture detection: a line before Part I is introductory even if the same
text also recurs later as a running header (only the later occurrences, from
Part I onward, become page headers).

### Composite elements — `CompositeSemanticElement`
Usually one top-level HTML tag corresponds to one piece of content. But sometimes
a single tag wraps several distinct pieces — for example a `<div>` containing
both a table and a separate paragraph, or a tag containing both an image and
text. In that case the tag is split: each inner piece is classified on its own,
and they are grouped under a `CompositeSemanticElement` container.

- The container exposes its inner pieces via `.inner_elements` (a sequence of
  the inner element objects).
- As described in §2, containers are flattened away by default, so callers
  normally just see the inner pieces.

### Merging split-up text
Filings sometimes break a single sentence across several adjacent tags. Adjacent
body-text elements that sit next to each other should be **merged into a single
`TextElement`**. An irrelevant element sitting between two text runs does not
break the run (the text on both sides still merges); but a non-text content
element (such as a heading) does separate one run from the next.

### Classification precedence
A single line can match more than one of the rules above (for example a
parenthetical that also repeats, or a centered running header). Resolve such
overlaps in this order, highest priority first:

1. **Standard section headings** (`TopSectionTitle`) win over everything.
2. **Supplementary text** wins over page furniture — a repeated parenthetical or
   a repeated italic note is `SupplementaryText`, not a page number/header.
3. **Page furniture** (page numbers / page headers) wins over plain emphasis — a
   repeated centered or bold running header is a `PageHeaderElement`, not a
   title.

---

## 4. Standard sections (`TopSectionTitle` details)

A `TopSectionTitle` has:

- `.level` — `0` for a Part heading, `1` for an Item heading.
- `.section_type` — an object describing which standard section it is. It has an
  `.identifier` attribute: a lowercase string with no spaces, built as the part
  and (optionally) item it represents.

**Identifier format.** Part headings use the Part number with Roman numerals
converted to Arabic. Item headings are scoped to the most recently seen Part, and
append the item number with any trailing letter lowercased. For example, an
"Item 7A" heading appearing after "Part II" has the identifier `part2item7a`.

**10-Q vs 10-K.** The two filing types have different sets of standard sections,
which is the only behavioral difference between the two parsers. `Edgar10QParser`
recognizes the 10-Q section scheme; `Edgar10KParser` recognizes the 10-K scheme.
Resolve each heading against the appropriate filing's sections.

**Each section appears once, in order.** The standard sections have a natural
order (by part, then item). A section is only promoted to a `TopSectionTitle` the
first time it legitimately appears and only if it comes *after* the
most-recently-accepted section in that order. A heading that names a section
which has already been passed (for example a second "Item 1." appearing after
"Item 2.") is **not** promoted again — it falls through and is treated as an
ordinary title instead.

---

## 5. Building the section tree

`TreeBuilder().build(elements)` takes the flat list of elements and returns a
`SemanticTree` that nests them according to the document's heading structure.

Nesting rules (observable behavior):

- Content that follows a heading nests **underneath** that heading.
- A top-level section heading and a title act as parents for the elements that
  come after them.
- Among headings of the same kind, a higher-rank heading (a smaller `.level`
  number) becomes the parent of the lower-rank headings (larger `.level`) that
  follow it. A heading closes when another heading of equal or higher rank
  begins.

So, for a document like: title A (level 0), title A1 (level 1), a paragraph,
title B (level 0), a paragraph — the tree has two top-level nodes (A and B); A
contains A1; A1 contains the first paragraph; B contains the second paragraph.

### `SemanticTree`
- Iterable: iterating it (or `list(tree)`) yields the top-level (root) nodes.
- `.nodes` — yields **every** node in the tree (roots and all descendants).
- `.render(*, pretty=True, ignored_types=None) -> str` — see §6.

### `TreeNode`
- `.semantic_element` — the element this node holds.
- `.text` — convenience pass-through to the element's text.
- `.children` — the node's child nodes (returns a list you can read without
  mutating the node's internal state).
- `.parent` — the parent node (or `None` for a root).
- `.add_child(node)` — attach a child.
- Re-parenting consistency: setting `node.parent = other` (or adding a node as a
  child of a new parent) must detach the node from its previous parent
  automatically, so a node is only ever in one parent's children list.
- `.get_descendants()` — yields all descendants of the node.

---

## 6. Rendering a tree

`tree.render(pretty=False)` returns a plain-text outline of the tree, one line
per node, indented to show nesting. In plain (non-pretty) form, each line shows
the element's **type name**, then a colon and a space, then the element's text —
for example:

```
TitleElement: Section A Title
TextElement: Body text under A.
```

`render(..., ignored_types=(SomeType, ...))` omits elements of the given types
from the output entirely.

---

## 7. Reading and serializing elements

Beyond `.text`, every element supports `.to_dict(*, include_contents=False,
include_previews=False)`, returning a dictionary describing the element:

- It always includes the element's class name under the key `cls_name`.
- For elements that carry a level (titles, top-section titles), it includes
  `level`.
- For a top-section title, it includes `section_type` set to the section's
  identifier string (e.g. `"part1"`).
- When called with `include_contents=True`, text-bearing elements (such as body
  text, titles, and top-section titles) additionally include `text_content` with
  the element's text.
- When called with `include_previews=True`, every element additionally includes:
  - `tag_name` — the underlying HTML tag name (e.g. `"p"`, `"table"`).
  - `html_preview` — a short preview of the element's HTML *content* (its source
    with the outer opening/closing tag removed). Newlines are turned into spaces
    and the result trimmed; if it is longer than **40** characters it is
    shortened to its first 20 characters, then `...[N]...` where `N` is the
    number of characters omitted (the content length minus 40), then its last 20
    characters.
  - `html_hash` — a hash string of the element's source (any stable hash of the
    source code is acceptable).
  A `TableElement` also adds a `metrics` dict (`{"rows": …, "numbers": …}`) under
  `include_previews=True`.

### Table helpers
`TableElement` additionally provides:

- `.table_to_markdown()` — the table rendered as Markdown text: one line per
  table row, each row's cells wrapped in pipe (`|`) characters, with **no**
  divider/separator line between header and body. (So a three-row table renders
  as three lines.)
- `.get_summary()` — a short human-readable description of the table that
  includes its row count, e.g. "Table with ~3 rows, …".

---

## 8. The `HtmlTag` wrapper and error handling

`HtmlTag` is a small wrapper around a BeautifulSoup4 tag, used as the low-level
handle that element objects are built from.

- `HtmlTag(x)` where `x` is a BeautifulSoup tag/navigable element wraps it.
  Constructing an `HtmlTag` from a value that is not a BeautifulSoup element
  (e.g. an integer) must raise `TypeError`.
- Element objects are constructed from an `HtmlTag`. Title-like elements accept a
  `level` keyword; constructing one with a negative level must raise
  `SecParserValueError`.
- Every element exposes the tag it was built from via a public read-only
  attribute named exactly `.html_tag` (returning that `HtmlTag`). A custom
  processing step (§9) uses it to build replacement elements from existing ones,
  e.g. `TextElement(e.html_tag)`.
- `CompositeSemanticElement` is constructed from an `HtmlTag` plus its inner
  elements; constructing one with no inner elements (e.g. `inner_elements=None`)
  must raise `SecParserValueError`.

`SecParserValueError` is the library's error type for invalid values and must be
importable from the top-level package.

---

## 9. Extensibility (custom steps and rules)

The default parsing pipeline and tree-nesting rules can be replaced by the
caller.

**Custom processing steps.** Both parsers accept a `get_steps` keyword — a
zero-argument callable returning the ordered list of processing steps to run:
`Edgar10QParser(get_steps=lambda: [MyStep(), ...])`. When supplied, exactly those
steps run (the default pipeline is not used). Every input element starts as the
"not yet classified" type and is passed through each step in turn.

All of the per-element behavior in §3 — element-type classification, adjacent
body-text merging ("Merging split-up text"), and recurring-furniture /
introductory-section detection — is performed by the default pipeline steps. So a
custom `get_steps` replaces all of it: with a custom pipeline, the returned list is
exactly what the custom steps produce, with **no** implicit merging or
reclassification unless a supplied step does it. Only the §2 output-stage
transforms — dropping irrelevant elements and container flatten/unwrap — are
applied after the pipeline regardless of which steps ran. (For example, a custom
step that turns two adjacent paragraphs into two `TextElement`s yields two
elements, not one merged element, because the merge step did not run.)

A processing step subclasses `AbstractProcessingStep` and implements the
transform by overriding the method `_process(self, elements) -> list`, which
takes the current list of elements and returns the transformed list. Callers
invoke a step through its public `process(elements)` method (do not override
`process`); `process` runs the step once and returns the result.

A step instance is **single-use**: calling `process()` a second time on the same
instance must raise a `SecParserRuntimeError` (a fresh instance is required per
document).

**Custom nesting rules.** `TreeBuilder` accepts a `get_rules` keyword — a
zero-argument callable returning the list of nesting rules to use:
`TreeBuilder(get_rules=lambda: [MyRule()])`. A rule subclasses
`AbstractNestingRule` and implements `_should_be_nested_under(self, parent, child)
-> bool`, returning whether `child` should nest under `parent`. The builder uses
these rules in place of the defaults to decide the tree structure.
