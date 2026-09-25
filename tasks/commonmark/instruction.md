# `mdcore` — a Markdown processing library

## Overview

Implement `mdcore`, a Java library that parses **Markdown** text into an abstract syntax tree (AST),
lets callers inspect and modify that tree, and renders the tree to **HTML**, back to **Markdown**, or
to **plain text**. The Markdown dialect to implement is the widely-used **CommonMark** specification
(version 0.31.2): https://spec.commonmark.org/0.31.2/ . When any behavior below is unstated, follow
the CommonMark spec exactly — the reference test cases in this document are drawn from it.

The library must be organized under the root package **`org.mdcore`** with the exact sub-packages and
public types described below. Import paths are part of the contract: callers (and the graders) import
these exact fully-qualified names, so they must resolve. You are free to organize internal
(implementation) classes however you like, in whatever packages you like — only the public types named
here are fixed.

### Runtime environment and dependencies

- Pure Java, targeting **Java 11** or later. **No external libraries** — implement everything on the
  standard JDK. Do not attempt to download anything; the environment is offline.
- Build your sources into `/app/out` and provide an executable **`/app/setup.sh`** that performs the
  offline build (e.g. `find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out`). The grader
  runs `bash ./setup.sh` before compiling and running the tests against your compiled classes.
- **HTML entity data file.** Decoding of *named* HTML character references (e.g. `&copy;` → `©`)
  requires a lookup table of entity names. This table is provided to you as a data file at
  **`/app/entities.txt`** — you do not need to hand-write it. Load it at runtime. Its format is one
  entry per line, `name=value`, where `name` is the entity name **without** the leading `&` or
  trailing `;`, and `value` is the literal replacement string (UTF-8), for example:

  ```
  copy=©
  amp=&
  frac34=¾
  Aacute=Á
  ```

  Lines are UTF-8. The name `NewLine` maps to a newline character. There are ~2,100 entries. If you
  place a copy of this table on your runtime classpath instead of reading the file directly, that is
  fine — but the data itself must come from `/app/entities.txt` (do not hard-code it).

---

## 1. Parsing: `org.mdcore.parser.Parser`

`Parser` is the entry point for turning Markdown source into an AST. It is created through a builder
and is safe to reuse across calls/threads.

```java
Parser parser = Parser.builder().build();
Node document = parser.parse("This is *Markdown*");
```

- `static Parser.Builder builder()` — returns a new builder.
- `Node parse(String input)` — parse a complete Markdown document, returning the root `Document` node.
- `Node parseReader(java.io.Reader input) throws java.io.IOException` — parse from a `Reader`; behaves
  identically to reading the reader fully and calling `parse`.

`Parser.Builder` supports (at least) these configuration methods, each returning the builder (`this`)
for chaining, plus `Parser build()`:

- `includeSourceSpans(IncludeSourceSpans includeSourceSpans)` — control whether the parser records
  the source position of each node (see §5). Default is `IncludeSourceSpans.NONE`.

(Other builder methods used only for extensions are not required for this task.)

### 1.1 What to parse — the block and inline grammar

Implement the full CommonMark block and inline grammar. The distinct constructs the graders rely on:

**Blocks (container and leaf):**
- **Thematic breaks** — a line of three or more matching `*`, `-`, or `_` (optionally separated by
  spaces) → a thematic-break node.
- **ATX headings** — 1–6 leading `#` followed by a space (or end of line) → heading of that level. A
  run of 7+ `#` is *not* a heading. An optional closing run of `#` is stripped. Up to 3 leading spaces
  of indentation are allowed. The heading text is the inline content between the markers.
- **Setext headings** — a paragraph line followed by a line of `=` (level 1) or `-` (level 2).
- **Indented code blocks** — lines indented with 4+ spaces (or a tab). Content is literal (inline
  parsing is *not* applied); it is HTML-escaped on rendering.
- **Fenced code blocks** — opened by 3+ backticks or 3+ tildes; closed by a matching fence of the same
  character and at least the same length. An optional **info string** follows the opening fence
  (its first word becomes the code language). Content is literal.
- **HTML blocks** — block-level raw HTML is passed through verbatim (subject to the `escapeHtml`
  option, §3).
- **Link reference definitions** — see §6.
- **Paragraphs** — consecutive non-blank lines; blank lines separate blocks.
- **Block quotes** — lines beginning with `>` (with optional following space). Support **lazy
  continuation** (a paragraph continuation line inside a quote need not repeat `>`), nesting, and
  containing other blocks (lists, headings, code).
- **Lists** — bullet lists (`-`, `+`, `*`) and ordered lists (`1.`, `1)`), with nesting. A list is
  **tight** if there are no blank lines between its items (and within items); otherwise **loose**.
  Tight vs loose changes rendering (§2). Ordered lists track a **start number** and a **delimiter**
  (`.` or `)`).

**Inlines:**
- **Backslash escapes** — a backslash before an ASCII punctuation character produces that literal
  character; before any other character the backslash is literal.
- **Entity and numeric character references** — named (`&copy;`, using `/app/entities.txt`), decimal
  (`&#35;`), and hexadecimal (`&#x41;`, `&#Xe9;`). An invalid or unknown reference is left as literal
  text. The numeric reference `&#0;` (and out-of-range code points) decode to U+FFFD.
- **Code spans** — backtick-delimited; the number of opening backticks must match the closing run.
  A single leading and single trailing space is stripped **iff** the content is not all spaces. Content
  is literal and HTML-escaped.
- **Emphasis and strong emphasis** — `*`/`_` for emphasis, `**`/`__` for strong. Implement the full
  CommonMark delimiter-run algorithm: left/right-flanking runs, the "rule of 3" (a multiple-of-3
  constraint on run lengths), the rule that `_` does not create intraword emphasis while `*` does, and
  correct nesting.
- **Links** — inline (`[text](/url "title")`), and reference links (full `[text][label]`, collapsed
  `[label][]`, shortcut `[label]`) resolved against link reference definitions. Destinations may be
  wrapped in `<...>`. Titles are optional.
- **Images** — `![alt](/url "title")` and the reference forms. The alt text is the plain textual
  content of the image's children.
- **Autolinks** — `<absolute-URI>` and `<email@example.com>` in angle brackets. Emails render with a
  `mailto:` destination.
- **Raw inline HTML** — open tags (with attributes), closing tags, self-closing tags, HTML comments,
  processing instructions, CDATA sections, and declarations pass through. Text that only *looks* like a
  tag but is not valid HTML is treated as literal (escaped) text.
- **Hard line breaks** — a line ending in two or more spaces, or in a backslash, becomes a hard break.
- **Soft line breaks** — a single newline within a paragraph.

---

## 2. Rendering to HTML: `org.mdcore.renderer.html.HtmlRenderer`

```java
HtmlRenderer renderer = HtmlRenderer.builder().build();
String html = renderer.render(document);   // e.g. "<p>This is <em>Markdown</em></p>\n"
```

- `static HtmlRenderer.Builder builder()`.
- `String render(Node node)` — render the node (usually a `Document`) to an HTML string.

The default renderer must reproduce standard CommonMark HTML output exactly, including trailing
newlines. Worked examples (input on the left, exact `render` output on the right):

| Markdown input | HTML output |
|---|---|
| `# h1` then `## h2` … `###### h6` then `####### not` | `<h1>h1</h1>\n<h2>h2</h2>\n…<h6>h6</h6>\n<p>####### not</p>\n` |
| `***` | `<hr />\n` |
| `` `foo *bar* baz` `` | `<p><code>foo *bar* baz</code></p>\n` |
| `    <a> & "q"` (indented code) | `<pre><code>&lt;a&gt; &amp; &quot;q&quot;\n</code></pre>\n` |
| ` ```ruby `\n`def foo`\n` ``` ` | `<pre><code class="language-ruby">def foo\n</code></pre>\n` |
| `- a`\n`- b` (tight) | `<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n` |
| `- a`\n\n`- b` (loose) | `<ul>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n</ul>\n` |
| `5. five`\n`6. six` | `<ol start="5">\n<li>five</li>\n<li>six</li>\n</ol>\n` |
| `[text](/url "a title")` | `<p><a href="/url" title="a title">text</a></p>\n` |
| `![alt text](/img.png "ttl")` | `<p><img src="/img.png" alt="alt text" title="ttl" /></p>\n` |
| `<http://example.com/a?b=c>` | `<p><a href="http://example.com/a?b=c">http://example.com/a?b=c</a></p>\n` |
| `<foo@bar.example.com>` | `<p><a href="mailto:foo@bar.example.com">foo@bar.example.com</a></p>\n` |
| `&copy; &amp; &lt;` | `<p>© &amp; &lt;</p>\n` |
| `&#35; &#x41;` | `<p># A</p>\n` |
| `foo  ` (2 trailing spaces) `\nbar` | `<p>foo<br />\nbar</p>\n` |

Key rules the examples pin down:
- Special HTML characters in text/code are escaped: `<`→`&lt;`, `>`→`&gt;`, `&`→`&amp;`,
  `"`→`&quot;`. In text, a literal `&` that does not begin a valid entity is escaped to `&amp;`.
- A fenced code block's info-string first word becomes `class="language-<word>"` on the `<code>`.
- Tight list items render their content inline inside `<li>`; loose list items wrap block content in
  `<p>`.
- Ordered lists render a `start` attribute only when the start number is not 1.
- A soft line break renders as the configured softbreak string (default `"\n"`).

### 2.1 `HtmlRenderer.Builder` options

Each returns the builder (`this`) for chaining; `HtmlRenderer build()` finishes.

- `escapeHtml(boolean)` — default `false`. When `true`, raw inline HTML and HTML blocks are
  HTML-escaped instead of passed through. Example: with `escapeHtml(true)`, `foo <span>bar</span>`
  → `<p>foo &lt;span&gt;bar&lt;/span&gt;</p>\n`. A block-level HTML block, when escaped this way, has
  its escaped text wrapped in a `<p>` element — e.g. a `<section>x</section>` block →
  `<p>&lt;section&gt;x&lt;/section&gt;</p>\n`.
- `softbreak(String)` — default `"\n"`. The string emitted for a soft line break. Example: with
  `softbreak("<br>")`, `foo\nbar` → `<p>foo<br>bar</p>\n`; with `softbreak(" ")`, → `<p>foo bar</p>\n`.
- `sanitizeUrls(boolean)` — default `false`. When `true`, link/image destinations whose URL scheme is
  not one of `http`, `https`, `mailto`, `data` are replaced with an empty destination, and every
  rendered `<a>` (link) element additionally gets a `rel="nofollow"` attribute, emitted **before** the
  `href` attribute. (Images get the sanitized `src` but no `rel`.) A URL with no scheme (relative, or
  starting with `/`, `#`, `?`) is allowed. Example: with `sanitizeUrls(true)`,
  `[a](javascript:alert(1)) [b](http://ok.example/)` →
  `<p><a rel="nofollow" href="">a</a> <a rel="nofollow" href="http://ok.example/">b</a></p>\n`.
- `percentEncodeUrls(boolean)` — default `false`. When `true`, characters unsafe in a URL are
  percent-encoded in link/image destinations (e.g. a space → `%20`, non-ASCII → its UTF-8 percent
  encoding), while already-valid percent-escapes and reserved URL characters are preserved.
- `omitSingleParagraphP(boolean)` — default `false`. When `true`, if the document is a single
  top-level paragraph, render its inline content **without** the wrapping `<p>`/`</p>` — and with **no
  trailing newline** either, so the output is exactly the paragraph's inline content (e.g.
  `hello there` renders to `hello there`, with no trailing `\n`). Documents with more than one block
  are unaffected.

---

## 3. Rendering back to Markdown: `org.mdcore.renderer.markdown.MarkdownRenderer`

```java
MarkdownRenderer renderer = MarkdownRenderer.builder().build();
String markdown = renderer.render(document);
```

- `static MarkdownRenderer.Builder builder()` and `MarkdownRenderer build()`.
- `String render(Node node)` — render the AST to CommonMark Markdown text.

The renderer must produce Markdown that, when re-parsed, yields an equivalent document (a stable
round-trip), choosing canonical markers and escaping. Behaviors the graders rely on:
- ATX headings render as `#`×level + space + inline content, followed by a newline. A **setext**
  heading is re-rendered in ATX form **only when its inline content fits on a single line** (e.g.
  `Baz\n---` → `## Baz`); a level-1/2 heading whose content spans multiple lines (it contains a
  soft/hard line break) is kept in **setext** form so the break is preserved. The setext underline
  is a fixed run of exactly three characters — `===` for a level-1 heading, `---` for a level-2
  heading — regardless of the heading's content width.
- Emphasis renders with `*`/`**`; a run needing both renders as `***…***`.
- Links and images render in canonical inline form — `[text](destination "title")` and
  `![alt](destination "title")`, with the `"title"` part omitted when there is no title.
- Fenced code blocks render with a backtick fence; if the content itself contains a run of backticks,
  the fence is widened so it still delimits the content. The info string is preserved.
- Indented code, block quotes (`> `), and bullet lists (`- `) render in their canonical forms. An
  ordered list renders each item as its number + the delimiter recorded on the list (`.` or `)`) + a
  space, preserving the parsed delimiter and starting number (a `)`-delimited list stays
  `)`-delimited, not normalized to `.`). A thematic break renders as `---`.
- A blank line that separates two blocks **inside** a block quote is not emitted empty: it carries the
  quote prefix as trailing whitespace — `> ` for a single quote, and one `> ` per nesting level (so a
  doubly-nested quote emits `> > `) — mirroring the loose-list-item rule below.
- **Loose lists** (see §1.1) render with a **blank line between items**, and multi-block item content
  (continuation paragraphs, nested blocks) is indented to the width of the item marker (e.g. an
  ordered item `1. ` indents continuations by three spaces); a blank line that separates two blocks
  **within** such an item carries that same indentation as trailing whitespace (e.g. `   `) rather
  than being empty. Tight lists render one item per line with no blank separators.
- A **hard line break** renders as two trailing spaces followed by a newline (not the backslash
  form); a **soft line break** renders as a single newline.
- Characters that would otherwise be parsed as Markdown structure are backslash-escaped so the text
  round-trips as literal. Because the AST does not record whether a character was originally escaped
  in the source, the renderer escapes **conservatively**: the emphasis delimiters `*` and `_` are
  escaped **wherever they occur in text**, so a literal `*` always renders as `\*` — even when it is
  surrounded by spaces and so could not itself open or close emphasis. Characters that are only
  special at the **start of a line** are escaped only there: a `#` renders as `\#` only when it
  begins a line (where it could start a heading), while a `#` in the middle of a line is left
  unescaped; the same start-of-line rule applies to the other line-leading markers. Text inside a
  title/destination is escaped according to that context, not blanket-escaped.
- `render` does not append a trailing newline beyond what the block structure itself produces.

---

## 4. Rendering to plain text: `org.mdcore.renderer.text.TextContentRenderer`

```java
TextContentRenderer renderer = TextContentRenderer.builder()
        .lineBreakRendering(LineBreakRendering.COMPACT)
        .build();
String text = renderer.render(document);
```

- `static TextContentRenderer.Builder builder()` and `TextContentRenderer build()`.
- `String render(Node node)` — render the AST to plain text with minimal markup.
- `Builder lineBreakRendering(LineBreakRendering mode)` — default `LineBreakRendering.COMPACT`.

`org.mdcore.renderer.text.LineBreakRendering` is an enum with exactly these constants:
`STRIP`, `COMPACT`, `SEPARATE_BLOCKS`.
- `COMPACT` (default) — blocks separated by a single newline.
- `SEPARATE_BLOCKS` — top-level blocks separated by a blank line (two newlines). The items of a list
  are **not** blank-separated (they stay on adjacent lines, one newline apart); only the list as a
  whole is separated from its surrounding blocks.
- `STRIP` — everything rendered on a single line; a heading and its following block are joined with
  `": "`, and inter-word spacing is normalized to single spaces.

Element-specific text output (these exact conventions are required):
- **Code span** — rendered wrapped in double quotes: `` `x` `` → `"x"`.
- **Link / Image** — rendered as the (double-quoted) child text, then, if there is a title and/or a
  non-empty destination, a space and the destination in parentheses: `[the site](http://example.com)`
  → `"the site" (http://example.com)`. If a title is present and differs from the destination, the
  parenthesized part is `title: destination`. An image renders the same way from its alt-text
  children. (A link/image whose destination equals its title, or with no destination, renders just
  the quoted text.)
- **Emphasis / strong emphasis** — rendered as their inner text with no markers (`*em*` → `em`).
- **Block quote** — its content is rendered wrapped in `«` … `»` (e.g. `> a` → `«a»`).
- **List item markers are preserved**: a bullet item renders with `- ` (well, the source bullet:
  `* ` or `- `) and an ordered item with `N. `/`N) ` before its content, in COMPACT/SEPARATE modes;
  STRIP drops the markers and joins item text with spaces. A **nested** list item is indented to the
  width of its parent item's marker (two spaces for a `- ` bullet), and nested lists add no
  blank-line separation in any mode.
- **Thematic break** — renders as `***` in COMPACT and SEPARATE_BLOCKS; in **STRIP** mode it is a
  structural-only element and is omitted entirely.
- **Soft line break** — an intra-paragraph soft break renders as a newline in COMPACT and
  SEPARATE_BLOCKS; **STRIP**, as defined above, joins all content onto a single line.

Worked example for `# Heading\n\nFoo`:
- `COMPACT` → `Heading\nFoo`
- `SEPARATE_BLOCKS` → `Heading\n\nFoo`
- `STRIP` → `Heading: Foo`

---

## 5. The AST: `org.mdcore.node`

`parse` returns a tree of `Node`s rooted at a `Document`. All node classes live in `org.mdcore.node`.

### 5.1 `Node` (base class)

Public API (methods the graders use):
- Traversal: `Node getFirstChild()`, `Node getLastChild()`, `Node getNext()`, `Node getPrevious()`,
  `Node getParent()`.
- Mutation: `void appendChild(Node child)`, `void prependChild(Node child)`,
  `void insertBefore(Node sibling)`, `void insertAfter(Node sibling)`, `void unlink()` (detach this
  node from its parent/siblings).
- Visiting: `void accept(Visitor visitor)`.
- Source spans: `java.util.List<SourceSpan> getSourceSpans()` (see §5.4).

`insertBefore`/`insertAfter` are called on an existing node to place the argument node adjacent to it.
`unlink` removes the receiver from the tree.

### 5.2 Node types

Each concrete node extends `Node` (block nodes extend an intermediate `Block`, but only the concrete
types below are required by name). Constructors: `Text` and `Code` have both a no-arg and a
`(String literal)` constructor; `Link` and `Image` have a no-arg and a `(String destination,
String title)` constructor. All node types have a public no-arg constructor. Every getter listed below
that names a settable property also has the corresponding `set…` setter (e.g. `setLiteral`,
`setDestination`, `setTitle`, `setLevel`), used to build/modify trees programmatically.

- `Document` — the root.
- `Heading` — `int getLevel()`, `void setLevel(int)`.
- `Paragraph`.
- `Text` — `String getLiteral()`, `void setLiteral(String)`.
- `Emphasis`, `StrongEmphasis`.
- `Code` (inline code span) — `String getLiteral()`.
- `FencedCodeBlock` — `String getInfo()`, `String getLiteral()`, `char getFenceChar()`,
  `int getFenceLength()`. `getLiteral()` includes a trailing newline per line of content.
- `IndentedCodeBlock` — `String getLiteral()`.
- `HtmlBlock`, `HtmlInline` — `String getLiteral()`.
- `BlockQuote`.
- `ListBlock` (abstract base of the two list types) — `boolean isTight()`, `void setTight(boolean)`.
- `BulletList extends ListBlock`.
- `OrderedList extends ListBlock` — `Integer getMarkerStartNumber()`, `String getMarkerDelimiter()`
  (the delimiter is `"."` or `")"`).
- `ListItem`.
- `Link` — `String getDestination()`, `String getTitle()`, `void setDestination(String)`,
  `void setTitle(String)`.
- `Image` — `String getDestination()`, `String getTitle()`.
- `ThematicBreak`.
- `HardLineBreak`, `SoftLineBreak`.
- `LinkReferenceDefinition` (see §6) — `String getLabel()`, `String getDestination()`,
  `String getTitle()`.

For a parsed heading like `### Hello *world*`, the `Heading` has `getLevel() == 3` and its children are
the inline nodes (`Text("Hello ")`, `Emphasis` containing `Text("world")`). For `3. a`\n`4. b`, the
`OrderedList` has `getMarkerStartNumber() == 3`, `getMarkerDelimiter() == "."`, and `isTight() == true`.

### 5.3 Visitors: `Visitor` and `AbstractVisitor`

- `org.mdcore.node.Visitor` — an interface with a `void visit(X x)` method for each concrete node type
  above (e.g. `visit(Heading)`, `visit(Text)`, `visit(Emphasis)`, …).
- `org.mdcore.node.AbstractVisitor implements Visitor` — a base class whose default `visit` methods
  recurse into children. Subclass it and override only the methods you care about; call the inherited
  behavior (or iterate children yourself) to descend. Calling `node.accept(visitor)` dispatches to the
  matching `visit` method.

### 5.4 Source spans: `org.mdcore.node.SourceSpan` and `org.mdcore.parser.IncludeSourceSpans`

`org.mdcore.parser.IncludeSourceSpans` is an enum with constants `NONE`, `BLOCKS`,
`BLOCKS_AND_INLINES`. Configure via `Parser.builder().includeSourceSpans(...)`.

- With `NONE` (default) no source spans are recorded (`getSourceSpans()` is empty).
- With `BLOCKS`, block nodes record one `SourceSpan` per source line they span. A container's own
  line prefix belongs to the container node, not to the blocks nested inside it: a block quote's
  `> ` prefix is part of the `BlockQuote`, so a block nested in a quote records its span starting at
  the content column *after* the `> ` (e.g. the paragraph inside `> hello` starts at column 2, not
  column 0). A list item, by contrast, includes its own `- ` / `N. ` marker in its span (starting at
  column 0).
- With `BLOCKS_AND_INLINES`, inline nodes also record spans.

`org.mdcore.node.SourceSpan`:
- `static SourceSpan of(int lineIndex, int columnIndex, int length)` and
  `static SourceSpan of(int lineIndex, int columnIndex, int inputIndex, int length)`.
- `int getLineIndex()` (0-based line), `int getColumnIndex()` (0-based column),
  `int getInputIndex()` (0-based offset into the whole input), `int getLength()`.
- `SourceSpan subSpan(int beginIndex)` and `SourceSpan subSpan(int beginIndex, int endIndex)` — return
  a span for a sub-range of this span, adjusting `columnIndex`, `inputIndex`, and `length` accordingly
  (a half-open range like `String.substring`).

Worked example: parsing `"foo\n\nbar *baz*"` with `BLOCKS_AND_INLINES`, the emphasis inline
(`doc.getLastChild().getLastChild()`) has a span with `getLineIndex() == 2`, `getColumnIndex() == 4`,
`getInputIndex() == 9`, `getLength() == 5` (covering `*baz*`). For `SourceSpan.of(2, 4, 9, 5)`,
`subSpan(1, 3)` yields `getColumnIndex() == 5`, `getInputIndex() == 10`, `getLength() == 2`.

### 5.5 `org.mdcore.node.Nodes`

- `static Iterable<Node> Nodes.between(Node start, Node end)` — iterate the siblings strictly between
  `start` and `end` (exclusive of both). For siblings `a, b, c, d`, `Nodes.between(a, d)` yields
  `b, c`.

---

## 6. Link reference definitions

A **link reference definition** has the form `[label]: destination "optional title"` on its own. It
produces **no visible output**, but registers a label that reference links/images can resolve — even if
the reference appears **before** the definition in the document. Rules the graders rely on:
- Label matching is **case-insensitive** and collapses internal runs of whitespace (so `[Foo   Bar]`
  resolves against `[foo bar]: …`).
- If a label is defined more than once, the **first** definition wins.
- A `[label]: …` line that is indented as a code block (4+ spaces) is **not** a definition.
- When source spans / AST inspection is used, a definition appears in the tree as a
  `LinkReferenceDefinition` node with `getLabel()` (the normalized-in-appearance label text),
  `getDestination()`, and `getTitle()`.

---

## 7. Summary of required public API (import paths are fixed)

```
org.mdcore.parser.Parser                     (+ Parser.Builder)
org.mdcore.parser.IncludeSourceSpans         (enum: NONE, BLOCKS, BLOCKS_AND_INLINES)
org.mdcore.renderer.html.HtmlRenderer        (+ HtmlRenderer.Builder)
org.mdcore.renderer.markdown.MarkdownRenderer(+ MarkdownRenderer.Builder)
org.mdcore.renderer.text.TextContentRenderer (+ TextContentRenderer.Builder)
org.mdcore.renderer.text.LineBreakRendering  (enum: STRIP, COMPACT, SEPARATE_BLOCKS)
org.mdcore.node.Node, Document, Heading, Paragraph, Text, Emphasis, StrongEmphasis,
  Code, FencedCodeBlock, IndentedCodeBlock, HtmlBlock, HtmlInline, BlockQuote,
  ListBlock, BulletList, OrderedList, ListItem, Link, Image, ThematicBreak,
  HardLineBreak, SoftLineBreak, LinkReferenceDefinition, SourceSpan, Nodes,
  Visitor, AbstractVisitor
```

Anything not listed here is an internal implementation detail and may be organized freely. Match the
CommonMark 0.31.2 behavior for every construct; the worked examples above are exact and must be
reproduced byte-for-byte (including trailing newlines and HTML escaping).
