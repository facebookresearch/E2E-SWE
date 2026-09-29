# `html2markdown` — an HTML → Markdown converter CLI

Build a command-line program named `html2markdown` that reads an HTML document from **stdin** and
writes a **CommonMark Markdown** rendering of it to **stdout**. The conversion must reproduce the
exact byte-for-byte behavior described below (the hidden test-suite compares stdout with exact-string
equality).

## Language, dependencies, and build

- Implement in **Go**.
- You may use **only the Go standard library plus `golang.org/x/net/html`** (and its subpackages such
  as `golang.org/x/net/html/atom`). `golang.org/x/net/html` is available in the offline build
  environment; no other third-party module is available. Use it to parse the input HTML into a node
  tree; implement all rendering, escaping, whitespace, and table logic yourself.
- The build environment is **offline**. Put a `go.mod` at the repo root (module name of your choice,
  `go 1.25`) declaring the single dependency `golang.org/x/net v0.55.0`.
- Provide an executable **`setup.sh`** at the repo root containing exactly:
  ```sh
  go build -o /app/html2markdown .
  ```
  `package main` must live at the repo root. After `setup.sh` runs, `/app/html2markdown` must exist.

## Invocation and I/O

```
html2markdown [FLAGS] < input.html > output.md
```

- Read the entire HTML document from stdin, convert, write Markdown to stdout, exit `0`.
- The output always ends with exactly one trailing newline (`\n`).
- On a usage error (see "Flag validation") write a diagnostic to **stderr**, write nothing to stdout,
  and exit with a **non-zero** status.

### Flags

| Flag | Arg | Meaning |
|---|---|---|
| `--domain` | URL string | Resolve root-relative link/image URLs against this base (see Links). Default: empty (no resolution). |
| `--opt-strong-delimiter` | `**` or `__` | Delimiter used for `<strong>`/`<b>`. Default `**`. |
| `--plugin-strikethrough` | (bool) | Enable `<del>`/`<s>`/`<strike>` → `~~…~~`. Default off. |
| `--plugin-table` | (bool) | Enable `<table>` rendering (see Tables). Default off. |
| `--opt-table-header-promotion` | (bool) | Treat the first row as a header even without `<thead>`/`<th>`. |
| `--opt-table-span-cell-behavior` | `empty` or `mirror` | How to fill `colspan`/`rowspan` extra cells. |
| `--opt-table-cell-padding-behavior` | `aligned`, `minimal`, or `none` | Cell padding style. |
| `--opt-table-skip-empty-rows` | (bool) | Omit rows whose cells are all empty. |
| `--opt-table-newline-behavior` | `skip` or `preserve` | Handling of tables whose cells contain a hard break / block content. Default `skip`. |

Flags may appear in any order and use either `--flag value` or `--flag=value` form.

### Flag validation

Each `--opt-table-*` flag **requires** `--plugin-table` to also be set; if a `--opt-table-*` flag is
given without `--plugin-table`, exit non-zero with a stderr diagnostic and no stdout. `--domain` and
`--opt-strong-delimiter` are always valid.

## HTML parsing

Parse stdin as an HTML fragment/document with `golang.org/x/net/html`. Convert the element tree.
Ignore `<head>` content; render the document body. Unknown/inline-neutral wrapper elements
(`<span>`, `<div>` — see below) contribute their children. HTML comments (`<!-- … -->`) produce no
output.

## Block elements

Blocks are separated from adjacent blocks by a blank line (i.e. `\n\n` between them). The final block
is followed by the single trailing `\n`. A block whose rendered inline content is empty (e.g.
`<p></p>`) produces no output at all — it is omitted entirely and contributes no blank-line separator
between its neighbours.

- **`<p>`** → its inline content.
- **`<h1>`…`<h6>`** → `#`×level, a space, then inline content. E.g. `<h2>Hi</h2>` → `## Hi`.
- **`<blockquote>`** → each output line of the inner content is prefixed with `> ` (a blank inner line
  becomes `>` followed by a space, i.e. `> `). Nested blockquotes stack the prefixes: an inner
  blockquote line becomes `> > …`.
- **`<pre><code>…</code></pre>`** (code block) → a fenced code block. The fence is a run of backticks
  (`` ` ``). Use **3** backticks normally, but if the code content contains a run of N≥3 backticks,
  use N+1 backticks so the fence is longer than any internal run. The opening fence, the verbatim code
  (its interior newlines preserved, no escaping applied inside code), and the closing fence are each on
  their own line. Text inside code is **not** HTML-escaped or markdown-escaped. A `<pre>` **without** an
  inner `<code>` is treated the same way. If the `<code>` carries a `class="language-XXX"` (or
  `lang-XXX`), the opening fence gets that info string, e.g. ` ```go `.
- **`<ul>` / `<ol>`** → list (see Lists).
- **`<hr>`** → a thematic break rendered as `* * *` (asterisk, space, asterisk, space, asterisk).
- Consecutive top-level blocks are separated by one blank line.

### Lists

- `<ul>` items use `- ` as the marker.
- `<ol>` items use `N. ` where N counts up from the `start` attribute if present (default `1`), so
  `<ol start="5">` yields `5.`, `6.`, ….
- **Nested lists** are indented so their marker aligns under the parent item's text: unordered nesting
  indents by 2 spaces (`- ` width); ordered nesting indents by 3 spaces (`N. ` width). A nested list
  is preceded, within its parent item, by a blank continuation line that carries the parent's
  indentation as trailing spaces. For example
  `<ul><li>a<ul><li>b</li></ul></li></ul>` →
  ```
  - a
    
    - b
  ```
  (the middle line is two spaces). Under an ordered parent the continuation/indent is three spaces.
- A `<li>` containing multiple block children (e.g. two `<p>`s) renders the first block on the marker
  line, then a blank continuation line (indented with trailing spaces), then the next block indented
  to the item's text column.

## Inline elements

- **`<em>`/`<i>`** → `*text*`.
- **`<strong>`/`<b>`** → `**text**` (or `__text__` with `--opt-strong-delimiter=__`).
- **`<code>`** (inline) → the text wrapped in backticks. Use a single backtick normally; if the
  content contains a backtick, wrap with a run of `` `` `` (two backticks). For content `a\`b` the
  result is `` ``a`b`` ``.
- **`<br>`** → a hard line break: two spaces followed by `\n`, continuing the same block.
- **`<a href="URL" title="T">text</a>`** → `[text](URL "T")`; with no title → `[text](URL)`. The link
  text is rendered (and escaped) as inline content. If `--domain=BASE` is set and `URL` is
  root-relative (begins with `/`), output `BASE`+`URL`.
- **`<img src="URL" alt="A" title="T">`** → `![A](URL "T")` (title omitted if absent). `--domain`
  applies to `src` the same way as links.
- **Emphasis wrapping a link/image.** When a `<strong>`/`<em>` (etc.) wraps a link or image, the
  emphasis markers are placed **inside** the link/image text, not around the whole link. E.g.
  `<strong><a href="/x">link</a></strong>` → `[**link**](/x)` (not `**[link](/x)**`). A link wrapping
  an image is the natural nesting: `<a href="/p"><img src="/i" alt="pic"></a>` → `[![pic](/i)](/p)`.
- **`<del>`/`<s>`/`<strike>`** → `~~text~~` only when `--plugin-strikethrough` is set; otherwise the
  element contributes its text with no markers.
- `<span>` contributes its children unchanged.

## Text: entities and whitespace

- **Entity decoding.** Decode HTML entities in text: named (`&amp;`→`&`, `&copy;`→`©`, `&lt;`/`&gt;`),
  decimal (`&#65;`→`A`), and hex (`&#x42;`→`B`). `&nbsp;` decodes to a **non-breaking space (U+00A0)**,
  which is a distinct character from an ASCII space (see Whitespace).
- **Re-encoding on output.** When emitting text, the characters `<` and `>` are always written as the
  entities `&lt;` and `&gt;` (whether they came from raw text or from `&lt;`/`&gt;`). The character
  `&` is written literally as `&` (it is **not** re-encoded to `&amp;`).
- **Whitespace collapsing.** In normal (non-`<pre>`) text, every run of **ASCII** whitespace
  (space, tab, newline) collapses to a single space, and leading/trailing whitespace of a block's
  rendered inline content is stripped. A non-breaking space (U+00A0, from `&nbsp;`) is **not** ASCII
  whitespace: an interior `&nbsp;` is preserved literally (e.g. `<p>a&nbsp;&nbsp;b</p>` → `a  b`),
  but `&nbsp;` at the very start/end of a block is trimmed along with adjacent ASCII whitespace. E.g.
  `<p>a    b\tc\n   d</p>` → `a b c d` and `<p>&nbsp; x &nbsp;</p>` → `x`.

## Smart escaping

The purpose of escaping is to prevent literal text from being mis-parsed as Markdown syntax. Escaping
applies to **normal text content only** — never inside code spans/blocks, and never to markup you
generate (e.g. the `*` you emit for `<em>`).

The candidate characters are:
```
\  *  _  -  +  .  >  |  $  #  =  [  ]  (  )  !  ~  `  "  '
```
Escaping a character means emitting a backslash `\` before it. A candidate character is escaped
**only when, in its output context, it could start (or form) a Markdown construct**, per the following
rules (evaluate against the rendered text of the block; "line start" means preceded only by spaces
since the previous newline):

- **`\`** (backslash): always escaped → `\\`.
- **`*` or `_`** (emphasis): escaped when the **next** character is not whitespace and not
  end-of-text. (So a `*`/`_` that opens emphasis is escaped; a trailing one before space/EOL is not.)
  Example: `_under_` → `\_under_`, `*star*` → `\*star*`, and `**bold**` → `\*\*bold\**`.
- **`-`, `*`, or `+`** (unordered-list marker): escaped when it is at line start (only spaces before
  it on the line) **and** the next character is a space or end-of-text. `<p>- x</p>` → `\- x`;
  `<p>+ item</p>` → `\+ item`.
- **`.` or `)`** (ordered-list marker): escaped when immediately preceded by a digit, everything from
  there back to line start is digits/spaces, and the next character is a space or end-of-text.
  `<p>1. text</p>` → `1\. text`; but `v1.0` and `step2. x` are not escaped.
- **`#`** (ATX heading): escaped when at line start (spaces allowed before) and it is part of a run of
  1–6 `#` followed by a space/tab/newline or end-of-text. `<p># x</p>` → `\# x`.
- **`=` or `-`** (setext heading underline): escaped when the character (in a run) sits on a line by
  itself that directly follows a non-empty line. (Rare in inline text; include the rule for
  completeness.)
- **`-`, `_`, or `*`** (thematic break): escaped when at line start and the line consists only of ≥3
  of that same character (spaces allowed between).
- **`` ` `` or `~`** (fenced code): escaped when at line start and it begins a run of ≥3 `` ` ``/`~`.
- **`` ` ``** (inline code): always escaped → `` \` ``. Example: `a\`b` in text → `` a\`b ``.
- **`>`** never needs a backslash because it is emitted as `&gt;` (see Re-encoding) — a `>` at line
  start therefore appears as `&gt;`, not `\>`.
- **`[`** (link/image): escaped when there is a `]` later on the same line. `[link]` → `\[link]`.
- **`!`** (image): the `!` itself is not escaped, but a `[` immediately after a `!` is escaped, so
  `![x]` → `!\[x]`.
- **`.`, `$`, `|`, `]`, `(`, `)`, `=` (standalone), `"`, `'`** in contexts not matched by a rule above
  are **not** escaped. In particular `$5`, `100%`, `a | b`, `"quotes"`, `it's`, and `a = b` are output
  verbatim.

When several rules could apply to the same character, escaping it once (a single leading `\`) is
sufficient.

## Tables (with `--plugin-table`)

Render `<table>` as a GitHub-flavored Markdown pipe table.

- Columns are delimited by `|` with a leading and trailing `|` on every row. A **separator row**
  (`|---|---|…`) follows the header row.
- **Header**: if the table has `<th>` cells or a `<thead>`, that row is the header. With
  `--opt-table-header-promotion`, the first body row is promoted to the header even if it is `<td>`.
  With neither a real header nor promotion, the header cells are **empty** (the separator row still
  appears), e.g. a 2-column table yields a first line `|   |   |`.
- **Cell content** is the inline rendering of the cell (so `<strong>`/`<code>`/etc. inside a cell are
  rendered), with `|` inside a cell escaped as `\|` and newlines handled per `--opt-table-newline-behavior`.
- **Alignment.** A header cell's `align="left"|"center"|"right"` attribute sets the column alignment,
  encoded in the separator row as `:--`, `:-:`, and `--:` respectively (an unaligned column uses `-`
  runs). E.g. left/center/right headers give a separator `|:--|:-:|--:|`.
- **Padding** (`--opt-table-cell-padding-behavior`, default `aligned`):
  - `aligned` — pad every cell so each column is as wide as its widest cell, with one space of padding
    on each side. Cell content is **left-justified** within its column: the fill spaces that widen a
    shorter cell up to the column width are appended **after** the content (before the trailing
    one-space side padding), unless the column carries a right/center alignment. The separator uses
    `-`×(column width). Example:
    ```
    |   |   |
    |---|---|
    | a | b |
    | c | d |
    ```
  - `minimal` — one space of padding on each side of the content, but columns are **not** widened to a
    common width; the separator is always the minimal three dashes `|---|---|`. E.g. rows `aaa`,`b` /
    `c`,`ddd` give `| aaa | b |` and `| c | ddd |` with header `|  |  |` and separator `|---|---|`.
  - `none` — no padding at all: `|a|b|`, and the separator is the minimal `|---|---|` (three dashes
    per column).
- **Span** (`--opt-table-span-cell-behavior`): a `colspan=N`/`rowspan=N` cell occupies N grid cells.
  With `mirror`, the extra cells repeat the same content; with `empty` (the default), the extra cells
  are empty.
- **Newlines** (`--opt-table-newline-behavior`, default `skip`): controls tables whose cells contain a
  hard break / multi-line block content. With `preserve`, a `<br>` inside a cell is rendered inline as
  `  <br />` (the hard break's two spaces, then the literal `<br />`), keeping the cell on one row —
  e.g. a cell `a<br>b` becomes `a  <br />b` (the widest cell still drives column width under `aligned`).
  With `skip` (the default), a table that has any such multi-line cell is **not** rendered as a pipe
  table at all — the whole `<table>` is skipped and falls back to plain rendering (its cell contents
  emitted as inline text, as for a layout table). Tables with no in-cell hard breaks render identically
  under either value.
- With `--opt-table-skip-empty-rows`, a row whose every cell renders empty is omitted.
- **Layout tables:** a `<table role="presentation">` is treated as layout, not a data table — it is
  **not** rendered as a pipe table; its cell contents are emitted as inline text instead. Whenever a
  table is emitted as inline text this way (a layout table, or the `newline=skip` fallback above), its
  rows and cells behave as inline-neutral wrappers that contribute their children directly — like
  `<span>` — so adjacent cells and adjacent rows are concatenated with **no** separator inserted
  between them (no space and no blank line); normal inline whitespace-collapsing still applies to the
  joined run.

Study the exact spacing in the examples above; column widths, the separator dash counts, and the
padding are all significant.
