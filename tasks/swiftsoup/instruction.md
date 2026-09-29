# SwiftSoup — an HTML parser & manipulation library for Swift

Build a **pure‑Swift, dependency‑free** library that parses, traverses, manipulates,
sanitizes and re‑serializes HTML. It parses HTML the way modern browsers do — following
the **WHATWG HTML5** tree‑construction rules so that even malformed “tag soup” yields a
sane document tree.

The library exposes five capabilities, all reachable from `import SwiftSoup`:

1. **Parsing** — turn an HTML (or XML) string into a `Document` DOM tree.
2. **Traversal & selection** — navigate the tree and query it with **CSS selectors**.
3. **Manipulation** — read/modify text, attributes, classes and structure.
4. **Output** — serialize back to HTML with configurable pretty‑printing & escaping.
5. **Sanitization** — clean untrusted HTML against a `Whitelist`, plus an `Entities` codec.

Everything below is the public contract your implementation must satisfy. *How* you build
the tokenizer, tree builder, selector engine and serializer is entirely up to you.

---

## Packaging & build requirements

* Ship a **Swift Package Manager** package whose library code is a single module named
  **`SwiftSoup`**, importable with `import SwiftSoup`. Put all library sources under
  `Sources/` (a single module/target). Everything the contract describes must be `public`
  (or `open`).
* **No third‑party dependencies.** Foundation is allowed.
* The package must build offline with `swift build`.

The grading harness compiles every `*.swift` under your `Sources/` into a module named
`SwiftSoup` and runs hidden XCTest suites that `import SwiftSoup` and exercise only the
public API described here.

> **Note on the API style.** SwiftSoup follows jsoup’s naming closely, so most methods read
> like the Java originals (`getElementById`, `outerHtml`, `attr`, …). Many mutating methods
> **return the receiver** so calls can be chained (`el.attr("id","x").addClass("y")`). Methods
> that touch the parser/serializer are `throws`. **Argument labels matter in Swift** — use
> exactly the labels shown in the signature blocks below.

---

# Part 1 — Parsing (top‑level functions)

These are **module‑level functions** in the `SwiftSoup` module (call them as
`SwiftSoup.parse(...)`):

```swift
// Parse markup into a Document. Auto-detects XML: if the input (after leading whitespace)
// starts with "<?xml", the XML parser is used; otherwise the HTML5 parser is applied.
public func parse(_ html: String) throws -> Document
public func parse(_ html: String, _ baseUri: String) throws -> Document
public func parse(_ html: String, _ baseUri: String, _ parser: Parser) throws -> Document

// Force a specific parser regardless of content.
public func parseHTML(_ html: String, _ baseUri: String = "") throws -> Document
public func parseXML(_ xml: String, _ baseUri: String = "") throws -> Document

// Parse a fragment assumed to be the contents of <body>.
public func parseBodyFragment(_ bodyHtml: String) throws -> Document
public func parseBodyFragment(_ bodyHtml: String, _ baseUri: String) throws -> Document

// Sanitize untrusted HTML (see Part 5). Returns the cleaned <body> inner HTML.
public func clean(_ bodyHtml: String, _ whitelist: Whitelist) throws -> String?
public func clean(_ bodyHtml: String, _ baseUri: String, _ whitelist: Whitelist) throws -> String?
public func clean(_ bodyHtml: String, _ baseUri: String, _ whitelist: Whitelist,
                  _ outputSettings: OutputSettings) throws -> String?

// True iff the input contains only tags/attributes the whitelist permits.
public func isValid(_ bodyHtml: String, _ whitelist: Whitelist) throws -> Bool
```

`baseUri` is the URL the markup came from; it is used to resolve relative URLs (see
`absUrl` / the `abs:` attribute prefix below). It defaults to `""`.

## HTML5 tree construction (what a correct parse produces)

The HTML parser must normalize input into a well‑formed document following the HTML5
algorithm. The key observable behaviors (standard HTML5 except where a deviation is called out
below — reproduce them faithfully):

* **Document shell.** A parsed `Document` always has an `<html>` root containing a `<head>`
  and a `<body>`. Stray text/elements are moved into the right place
  (`parse("")` ⇒ `<html><head></head><body></body></html>`; loose text before `<body>` is
  relocated into the body). The `<html>`/`<head>`/`<body>` wrappers are created implicitly
  when missing.
* **Head vs body.** While the parser is still in head context, `<title>`, `<meta>`, `<link>`,
  `<style>`, `<script>`, `<base>` go to `<head>`; flow content (or any other non‑whitespace
  content) ends the head and goes to `<body>`. Once the body has been opened, one of those
  head‑only tags encountered later is inserted where it appears and is **not** hoisted back
  into `<head>`. Content after a closed body is merged back into the body.
* **Void / empty elements.** Void tags (`area base br col embed hr img input link meta param
  source track wbr`) never have children and serialize self‑closed (`<br />`). A **known**
  non‑void tag written self‑closed (`<div id=1 />`) is still given a proper end tag
  (`<div id="1"></div>`); an **unknown** tag may remain self‑closed (`<foo />`). The
  self‑closing `/>` marker is honoured on **every** tag — unlike WHATWG, which ignores it on
  non‑void HTML elements, a self‑closed start tag is closed immediately and never becomes an
  open element, so whatever follows it is a **sibling**, not a child.
* **Tables.** Implicitly insert `<tbody>` around `<tr>` rows; rows/cells written loosely are
  fostered into a valid `table > tbody > tr > td` structure. Content that cannot live in a
  table (text, mis‑placed elements) is *foster‑parented* out before/around the table.
  `<td>`s with no enclosing `<table>` are **not** wrapped in an implicit table (browsers emit
  the text run instead). Likewise `<li>`/`<dt>`/`<dd>` are **not** auto‑wrapped in
  `<ul>`/`<dl>`.
* **Formatting elements.** Implement the *adoption agency* behavior: mis‑nested inline
  formatting tags are re‑balanced and reconstructed. For example
  `<p>1<b>2<i>3</b>4</i>5</p>` parses to `<p>1<b>2<i>3</i></b><i>4</i>5</p>`, and an unclosed
  `<b>` spanning a `<p>` boundary is reopened in the following paragraph.
* **Comments / doctype / CDATA.** `<!-- … -->` becomes a `Comment` node; `<!doctype …>` is
  preserved (and lower‑cased to `<!doctype html>` on output); bogus/unterminated comments are
  recovered without crashing.
* **Raw‑text / data elements.** `<script>` and `<style>` contents are stored verbatim as a
  **data node** (not parsed as HTML, not a `TextNode`); `<textarea>`/`<title>` hold RCDATA.
  An end tag inside such an element is matched case‑insensitively.
* **Entities.** Character references in text and attribute values are decoded during parsing
  (`&amp;` ⇒ `&`); see Part 6 for the exact unescape rules.
* **Robustness.** Parsing must never crash and never throw on malformed input — truncated
  tags, attributes, entities or multi‑byte sequences (e.g. `"<a href=\""`, `"&amp"`, `"<"`)
  must each produce *some* document with a non‑nil `body()`.

---

# Part 2 — The DOM model

A node hierarchy rooted at `Node`:

```swift
open class Node: Equatable, Hashable {
    open func nodeName() -> String                      // e.g. "div", "#text", "#comment", "#document"
    open func parent() -> Node?
    open func ownerDocument() -> Document?
    open func childNode(_ index: Int) -> Node
    open func getChildNodes() -> [Node]
    public func childNodeSize() -> Int
    public func hasChildNodes() -> Bool
    open func attr(_ key: String) throws -> String       // "" if absent; "abs:href" resolves absolute
    open func attr(_ key: String, _ value: String) throws -> Node
    open func hasAttr(_ key: String) -> Bool             // also true for "abs:x" when resolvable
    open func removeAttr(_ key: String) throws -> Node
    open func getAttributes() -> Attributes?
    open func absUrl(_ key: String) throws -> String     // resolve attr value against base URI
    open func setBaseUri(_ baseUri: String) throws       // recursive
    open func getBaseUri() -> String
    open func remove() throws
    open func before(_ html: String) throws -> Node
    open func before(_ node: Node) throws -> Node
    open func after(_ html: String) throws -> Node
    open func after(_ node: Node) throws -> Node
    open func wrap(_ html: String) throws -> Node?
    open func unwrap() throws -> Node?                    // remove this node, keep children; returns first child
    public func replaceWith(_ input: Node) throws
    open func siblingNodes() -> [Node]
    open func nextSibling() -> Node?
    open func previousSibling() -> Node?
    public var siblingIndex: Int { get }
    open func traverse(_ visitor: NodeVisitor) throws -> Node
    open func outerHtml() throws -> String
}
```

Concrete node types:

```swift
open class Element: Node { … }            // a tag, e.g. <p>; see Part 3
open class Document: Element { … }         // the whole document; see Part 4
open class TextNode: Node {
    open func text() -> String             // normalized text
    public func text(_ text: String) -> TextNode
    open func getWholeText() -> String     // raw, un-normalized
    open func isBlank() -> Bool
    open func splitText(_ offset: Int) throws -> TextNode
    public static func createFromEncoded(_ encodedText: String, _ baseUri: String) throws -> TextNode
}
public class Comment: Node { public func getData() -> String }       // text between <!-- -->
open class DataNode: Node { open func getWholeData() -> String }      // <script>/<style> contents
```

`Node` is `Equatable`/`Hashable` by **identity** (two distinct nodes with equal content are
not `==`). `Document` additionally offers value comparison via `hasSameValue(_:)`.

## `Elements` — a list of elements

`select(...)` and the bulk accessors return `Elements`, an ordered collection of `Element`
with list helpers **and** bulk operations that fan out to every member:

```swift
open class Elements: Sequence {
    public init(); public init(_ a: [Element])
    open func size() -> Int
    open func get(_ i: Int) -> Element
    open func first() -> Element?
    open func last() -> Element?
    open func isEmpty() -> Bool
    open func array() -> [Element]
    open func eq(_ index: Int) -> Elements
    // bulk getters/setters across all members:
    open func text(trimAndNormaliseWhitespace: Bool = true) throws -> String  // joined with " "
    open func html() throws -> String                  // joined inner html
    open func outerHtml() throws -> String
    open func attr(_ key: String) throws -> String     // first member that has the attr
    open func attr(_ key: String, _ value: String) throws -> Elements
    open func hasClass(_ name: String) -> Bool
    open func addClass(_ name: String) throws -> Elements
    open func removeClass(_ name: String) throws -> Elements
    open func val() throws -> String
    open func select(_ query: String) throws -> Elements   // search WITHIN these elements
    open func not(_ query: String) throws -> Elements
    open func eachText() throws -> [String]
    // …plus append/prepend/before/after/wrap/remove/empty mirroring Element
    public var count: Int { get }
    public static func == (lhs: Elements, rhs: Elements) -> Bool   // element-wise identity
}
```

`Elements` is iterable (`for el in elements { … }`) and indexable enough to support the
above; equality is element‑wise identity.

---

# Part 3 — `Element` (traversal, accessors, manipulation)

```swift
open class Element: Node {
    public init(_ tag: Tag, _ baseUri: String)
    public init(_ tag: Tag, _ baseUri: String, _ attributes: Attributes)

    // identity / tag
    open func tagName() -> String                       // lower-cased normal name? NO — original case is kept (see below)
    public func tagName(_ tagName: String) throws -> Element
    open func tag() -> Tag
    open func id() -> String                            // value of the id attribute, or ""
    open func isBlock() -> Bool

    // navigation
    open override func parent() -> Element?
    open func parents() -> Elements                     // ancestors, nearest first, up to <html>
    open func children() -> Elements                    // child *elements* (no text nodes)
    open func child(_ index: Int) -> Element
    open func textNodes() -> [TextNode]
    open func dataNodes() -> [DataNode]
    public func siblingElements() -> Elements
    public func nextElementSibling() throws -> Element?
    public func previousElementSibling() throws -> Element?
    public func firstElementSibling() -> Element?
    public func lastElementSibling() -> Element?
    public func elementSiblingIndex() throws -> Int     // 0-based position among sibling elements

    // search (rooted at this element)
    public func select(_ cssQuery: String) throws -> Elements
    public func iS(_ cssQuery: String) throws -> Bool   // does THIS element match the selector?
    public func getElementById(_ id: String) throws -> Element?
    public func getElementsByTag(_ tagName: String) throws -> Elements         // case-insensitive
    public func getElementsByClass(_ className: String) throws -> Elements
    public func getElementsByAttribute(_ key: String) throws -> Elements
    public func getElementsByAttributeValue(_ key: String, _ value: String) throws -> Elements
    public func getAllElements() throws -> Elements

    // text
    public func text() throws -> String                 // normalized text of this element + descendants
    public func text(_ text: String) throws -> Element  // set: removes children, adds one text node
    public func ownText() -> String                     // text of direct child text nodes only
    public func hasText() -> Bool
    public func data() -> String                        // combined data-node content (script/style)
    public func val() throws -> String                  // form value: textarea text, else "value" attr
    public func val(_ value: String) throws -> Element

    // attributes
    open override func attr(_ key: String) throws -> String
    open override func attr(_ key: String, _ value: String) throws -> Element
    open func attr(_ key: String, _ value: Bool) throws -> Element   // boolean attribute; true stores an empty value
    open func dataset() -> [String: String]             // data-* attributes (without the data- prefix)

    // classes
    public func className() throws -> String            // the class attribute, whitespace-collapsed
    public func classNames() throws -> OrderedSet<String>
    public func hasClass(_ className: String) -> Bool   // case-insensitive, whitespace-aware
    public func addClass(_ className: String) throws -> Element
    public func removeClass(_ className: String) throws -> Element
    public func toggleClass(_ className: String) throws -> Element

    // structure mutation
    public func append(_ html: String) throws -> Element     // parse html, add to end of children
    public func prepend(_ html: String) throws -> Element
    public func appendChild(_ child: Node) throws -> Element
    public func appendElement(_ tagName: String) throws -> Element  // create+append, return the NEW element
    public func prependElement(_ tagName: String) throws -> Element
    public func appendText(_ text: String) throws -> Element
    public func prependText(_ text: String) throws -> Element
    public func insertChildren(_ index: Int, _ children: [Node]) throws -> Element  // index -1 == append
    public func empty() -> Element                            // remove all children
    open override func before(_ html: String) throws -> Element
    open override func after(_ html: String) throws -> Element
    open override func wrap(_ html: String) throws -> Element

    // output
    public func html() throws -> String                 // inner HTML
    public func html(_ html: String) throws -> Element  // set inner HTML
    open override func outerHtml() throws -> String
    public func cssSelector() throws -> String          // a unique selector path to this element
}
```

### Important accessor semantics

* **`tagName()` preserves original case for elements you create** (`appendElement("P")` →
  tag name `P`), but the HTML parser lower‑cases known tags during parsing. Selection by tag
  is **case‑insensitive** regardless.
* **`text()`** returns the element’s combined, whitespace‑**normalized** text: runs of
  whitespace collapse to a single space, the result is trimmed, `<br>` and block boundaries
  introduce a space, and `&nbsp;` (U+00A0) normalizes to a regular space. **Exception:**
  whitespace **inside `<pre>`/`<textarea>`** is preserved.
* **`ownText()`** is the same normalization but only over this element’s *direct* text nodes
  (children’s text excluded).
* **`html()` setter / `text()` setter** replace existing children. `text(_:)` HTML‑escapes
  its argument (`appendText("a & b")` → serializes as `a &amp; b`).
* **`attr("abs:href")`** returns the value of `href` resolved to an absolute URL against the
  base URI (empty string if it cannot be made absolute); `hasAttr("abs:href")` reflects
  whether such resolution succeeds. A *literal* attribute named `abs:href` is returned as‑is.
* `getElementById` returns the **first** matching element in document order; called on a
  sub‑element it searches that subtree only.

### CSS selector syntax

`select(_:)` / `iS(_:)` accept a **jsoup‑style** CSS query: the standard **CSS Selectors
Level 3** grammar, with the semantics that standard specifies, plus the jsoup deviations and
extensions below. Tag names and `.class` tokens are matched **case‑insensitively**, and —
unlike standard CSS — so are attribute **names and values**. The deviations and extensions:

* **Attributes:** `[attr]` (present), `[attr=val]`, `[attr!=val]` (not equal — **also matches
  elements that do not have the attribute**), `[attr^=val]` (value starts with), `[attr$=val]`
  (value ends with), `[attr*=val]` (value contains), and `[^prefix]` (has any attribute whose
  **name** starts with `prefix`). Attribute name and value comparisons are case‑insensitive.
* **Indexed pseudo‑classes (jsoup):** `:lt(n)`, `:gt(n)`, `:eq(n)` keep elements whose
  **0‑based sibling index** (position among their sibling elements, relative to their parent)
  is `< n`, `> n`, or `== n`; they may be chained (`p:gt(0):lt(2)`).
* **Text / predicate pseudo‑classes (jsoup):** `:contains(text)` / `:containsOwn(text)` match
  when the element's text (or its **own** direct text) contains `text`
  **case‑insensitively, with whitespace normalized**; `:matches(regex)` / `:matchesOwn(regex)`
  match when a **case‑sensitive** regular expression (honoring inline flags such as `(?i)`) is
  found in that text; `:has(selector)` matches when a descendant matches `selector`; and
  `:not(selector)` matches when the element does not match `selector`.

---

# Part 4 — `Document` & output

```swift
open class Document: Element {
    public init(_ baseUri: String)
    public func head() -> Element?
    public func body() -> Element?
    public func title() throws -> String                // normalized text of <title>, or ""
    public func title(_ title: String) throws           // set/create <title>
    public func location() -> String
    public func createElement(_ tagName: String) throws -> Element
    public func normalise() throws -> Document
    public func outputSettings() -> OutputSettings
    public func outputSettings(_ outputSettings: OutputSettings) -> Document
    open override func outerHtml() throws -> String      // the whole document
    public override func text(_ text: String) throws -> Element
}
```

`Document` inherits `html()` (whole‑document inner HTML) and `outerHtml()` from `Element`.

## `OutputSettings` — serialization control

```swift
public class OutputSettings {
    public enum Syntax { case html, xml }
    public init()
    public func prettyPrint() -> Bool
    public func prettyPrint(pretty: Bool) -> OutputSettings           // default true
    public func indentAmount() -> UInt
    public func indentAmount(indentAmount: UInt) -> OutputSettings     // default 1
    public func outline() -> Bool
    public func outline(outlineMode: Bool) -> OutputSettings           // default false
    public func escapeMode() -> Entities.EscapeMode
    public func escapeMode(_ mode: Entities.EscapeMode) -> OutputSettings   // default .base
    public func charset() -> String.Encoding
    public func charset(_ e: String.Encoding) -> OutputSettings        // default .utf8
    public func encoder(_ e: String.Encoding) -> OutputSettings        // alias for charset
    public func syntax() -> Syntax
    public func syntax(syntax: Syntax) -> OutputSettings               // default .html
}
```

### Pretty‑printing rules (the default)

With `prettyPrint == true` (default `indentAmount == 1`):

* Block‑level elements are placed on their own line and indented by `indentAmount` spaces per
  ancestor depth; inline content and inline elements stay on the same line as their text.
* Void elements serialize as `<tag />`; non‑void elements always get an explicit end tag.
* Empty block elements render as `<div></div>` (no internal newline).
* Runs of whitespace inside text are collapsed to a single space.
* The contents of `<script>`, `<style>`, `<pre>`, `<textarea>` are emitted verbatim (neither
  re‑indented nor whitespace‑collapsed), and the closing `</script>`/`</style>` is not pushed to
  a new line.
* Attributes serialize as `key="value"`; an attribute whose value is the empty string renders as
  just `key`. The collapse is keyed on the value being empty, whatever the attribute is named —
  there is no fixed list of boolean attribute names. Attribute values are escaped per the current
  escape mode.

For example, `try SwiftSoup.parse("<title>T</title><div><p>Hi <span>there</span></p></div>").html()`
produces:

```
<html>
 <head>
  <title>T</title>
 </head>
 <body>
  <div>
   <p>Hi <span>there</span></p>
  </div>
 </body>
</html>
```

With `prettyPrint(pretty: false)`, output is compact: no added newlines or indentation, and a
freshly parsed document round‑trips its source closely.

With `outline(outlineMode: true)`, inline elements are also broken onto their own indented
lines; however only an element that has **element children** is split across lines — an element
whose content is purely text still renders on a single line, and any text placed on its own line
keeps its surrounding whitespace. With `syntax(syntax: .xml)`, an empty‑valued attribute
serializes as `key=""` and the doctype keeps its given case.

### Escaping on output

Text and attribute values are escaped using the document’s `escapeMode` and `charset`:

* Escaping depends on context: in text, `&`, `<` and `>` are escaped to `&amp;`, `&lt;`,
  `&gt;`; in attribute values, `&` and `"` are escaped to `&amp;` and `&quot;` while `<` and
  `>` are emitted literally. The same split applies under both `.html` and `.xml` syntax.
* With `charset(.utf8)` (default) non‑ASCII characters are emitted literally; with
  `charset(.ascii)` they are emitted as character references — using **named** entities in
  `.base`/`.extended` mode where one exists (e.g. `π` → `&pi;` in extended), else a numeric
  reference. `.xhtml` mode only knows `amp/lt/gt/quot` and uses numeric references for the
  rest. See Part 6.

---

# Part 5 — Sanitization (`Whitelist` + `Cleaner`)

`SwiftSoup.clean(html, whitelist)` parses `html` as a body fragment, keeps only the tags,
attributes, and URL protocols the `Whitelist` permits, drops everything else (including
comments, scripts and unknown tags), and returns the cleaned body’s inner HTML.

```swift
open class Whitelist {
    public enum URLWhitespaceMode { case trim, strict, allow }

    // Prebuilt levels (all throw except none). Start from one of these (e.g. none()) and
    // customise with the builders below.
    public static func none() -> Whitelist          // empty: text only, no tags
    public static func simpleText() throws -> Whitelist   // b, em, i, strong, u
    public static func basic() throws -> Whitelist        // a,b,blockquote,br,cite,code,dd,dl,dt,em,i,
                                                          //   li,ol,p,pre,q,small,span,strike,strong,sub,
                                                          //   sup,u,ul + a[href] (http/https/ftp/mailto)
    public static func basicWithImages() throws -> Whitelist  // basic + img[src,align,alt,height,width,title]
    public static func relaxed() throws -> Whitelist          // a broad set of formatting/table tags

    // Builders (chainable, return self):
    open func addTags(_ tags: String...) throws -> Whitelist
    open func removeTags(_ tags: String...) throws -> Whitelist
    open func addAttributes(_ tag: String, _ keys: String...) throws -> Whitelist        // tag ":all" = any tag
    open func removeAttributes(_ tag: String, _ keys: String...) throws -> Whitelist
    open func addEnforcedAttribute(_ tag: String, _ key: String, _ value: String) throws -> Whitelist
    open func removeEnforcedAttribute(_ tag: String, _ key: String) throws -> Whitelist
    open func addProtocols(_ tag: String, _ key: String, _ protocols: String...) throws -> Whitelist
    open func removeProtocols(_ tag: String, _ key: String, _ protocols: String...) throws -> Whitelist
    open func addCSSProperties(_ tag: String, _ properties: String...) throws -> Whitelist
    open func removeCSSProperties(_ tag: String, _ properties: String...) throws -> Whitelist
    open func preserveRelativeLinks(_ preserve: Bool) -> Whitelist     // default false
    open func urlWhitespace(_ mode: URLWhitespaceMode) -> Whitelist
}

public class Cleaner {
    public init(_ whitelist: Whitelist)
    public init(headWhitelist: Whitelist, bodyWhitelist: Whitelist)
    public func clean(_ dirtyDocument: Document) throws -> Document
    public func isValid(_ dirtyDocument: Document) throws -> Bool
}
```

### Sanitizer behaviors

* **Tags:** elements not on the whitelist are unwrapped (children kept, tag removed) unless
  the whole subtree is unsafe (e.g. `<script>`, `<frameset>` produce no output). `addAttributes`
  for a tag implicitly whitelists that tag.
* **Attributes:** attributes not whitelisted for a tag are dropped; an attribute keyed under
  `":all"` is allowed on every tag.
* **Enforced attributes:** `basic()` enforces `rel="nofollow"` on `<a>`, and `basicWithImages()`
  keeps it because it extends `basic()`. `relaxed()` is *not* built from `basic()`: it permits
  `a[href]` with the same protocols but registers **no** enforced attributes. Enforced attributes
  are added to the cleaned output; `removeEnforcedAttribute` disables that.
* **Protocols:** for URL attributes, the value’s scheme must be one of the whitelisted
  protocols, else the attribute is dropped. `#` permits same‑page anchors; a relative URL is
  permitted only if it resolves (or if `preserveRelativeLinks(true)`). With a base URI, URL
  attributes are resolved to absolute (unless preserving relative links). `URLWhitespaceMode`
  controls whether leading/trailing whitespace in a URL is trimmed (`.trim`, default),
  rejected (`.strict`), or kept (`.allow`); a value that is only whitespace drops the attribute.
  The prebuilt `basicWithImages()` and `relaxed()` whitelists register only `http` and
  `https` as permitted protocols for `img[src]`.
* **CSS filtering:** if a tag has `style` whitelisted *and* CSS properties registered via
  `addCSSProperties`, the `style` attribute is filtered to only the whitelisted declarations
  (property names compared case‑insensitively; serialized as `prop:value` joined by `"; "`),
  unsafe declarations (e.g. `url(javascript:…)`, `expression(…)`, `behavior`, `-moz-binding`)
  are dropped, CSS comments are stripped, and quoted `;`/`:` inside values are respected. If no
  whitelisted declarations remain, the `style` attribute is dropped.
* **`Whitelist.none()` entity handling:** with no tags allowed, `&nbsp;`/`&#160;`/`&#xa0;`
  normalize to a regular space in the cleaned text, while other entities (`&amp; &lt; &gt;`)
  stay escaped. Non‑empty whitelists preserve `&nbsp;` as the entity.
* Output is pretty‑printed by default (so multiple block elements appear on separate lines);
  pass an `OutputSettings` to the four‑argument `clean` to override.

A few worked examples (cleaned body inner HTML, newlines stripped for brevity):

```swift
clean("<div><p class=foo><a href='http://e.com'>Hi <b id=bar>there</b>!</a></div>",
      Whitelist.simpleText())              // "Hi <b>there</b>!"
clean("<a href='javascript:x()'>Dodgy</a> <a href='HTTP://nice.com'>Nice</a>",
      Whitelist.basic())                   // "<a rel=\"nofollow\">Dodgy</a> <a href=\"HTTP://nice.com\" rel=\"nofollow\">Nice</a>"
clean("<h1>Head</h1><table><tr><td>One<td>Two</td></tr></table>", Whitelist.relaxed())
      // "<h1>Head</h1><table><tbody><tr><td>One</td><td>Two</td></tr></tbody></table>"
clean("<IMG SRC=\"javascript:alert('XSS')\">", Whitelist.relaxed())   // "<img />"
isValid("<p>Test <b>OK</b></p>", Whitelist.basic())                  // true
isValid("<p align=right>Not <b>OK</b></p>", Whitelist.basic())       // false
```

---

# Part 6 — `Entities` (HTML character references)

```swift
public class Entities {
    public class EscapeMode {
        public static var xhtml: EscapeMode       // only amp, lt, gt, quot
        public static var base: EscapeMode        // common named entities
        public static var extended: EscapeMode    // the full HTML5 named-entity set
        public func codepointForName(_ name: String) -> UnicodeScalar?
        public func nameForCodepoint(_ codepoint: UnicodeScalar) -> String?
    }
    public static func escape(_ string: String) -> String                       // utf8 + extended
    public static func escape(_ string: String, _ out: OutputSettings) -> String
    public static func unescape(_ string: String) throws -> String
    public static func unescape(string: String, strict: Bool) throws -> String
    public static func getByName(name: String) -> String?
}
```

### Escape

`escape` replaces characters that need escaping for the given `OutputSettings`:

* `&` always becomes `&amp;`; `<` and `>` become `&lt;`, `&gt;` in text context; `"` (in
  attribute context) becomes `&quot;`. U+00A0 becomes `&nbsp;` in `.base`/`.extended`,
  `&#xa0;` in `.xhtml`.
* When the charset is `.utf8`, other characters pass through literally; when it is `.ascii`,
  every non‑ASCII character is replaced by a **named** reference if the mode defines one
  (`.base`/`.extended`), otherwise a lower‑case hex numeric reference `&#xHH;`. `.xhtml` mode
  only names `amp/lt/gt/quot` and uses numeric references for everything else.

Example (`escape(text, OutputSettings().charset(.ascii).escapeMode(.base))` on
`"Hello &<> Å å π 新 there ¾ © »"`):
`"Hello &amp;&lt;&gt; &Aring; &aring; &#x3c0; &#x65b0; there &frac34; &copy; &raquo;"`.
In `.extended` the same input yields `… &angst; &aring; &pi; &#x65b0; …`; in `.xhtml`,
`… &#xc5; &#xe5; &#x3c0; …`.

### Unescape

`unescape` decodes references in a string:

* Named references with a trailing `;` are decoded (`&AElig;` → `Æ`); a known **base‑form**
  name may be decoded even without the `;` (`&amp` → `&`, `&copy;`/`&COPY;` both → `©`), but
  an unknown bare name is left literal (`&angst` stays `&angst`; `&unknown` stays).
* Numeric references decode in decimal (`&#960;` → `π`, and `&#960` without `;` too) and hex
  (`&#x65B0;` → `新`).
* Multi‑codepoint named entities are supported (`&nparsl;` → `\u{2AFD}\u{20E5}`).
* Anything that does not form a valid reference is preserved verbatim (`&0987654321;`,
  `&!`, a bare `&` in `http://x?a=1&b=2`).
* With `strict: true` (used for attribute values), a named reference without a trailing `;`
  is **not** decoded (`"Hello &amp= &amp;"` → `"Hello &amp= &"`); non‑strict decodes the
  first to `&=`.

Escaping followed by unescaping round‑trips the original text in every mode.

---

## Quick start

```swift
import SwiftSoup

let doc = try SwiftSoup.parse("<html><head><title>Example</title></head><body><p class='m'>Hi</p></body></html>")
try doc.title()                                   // "Example"
try doc.select("p.m").first()?.text()             // "Hi"
let a = try SwiftSoup.parse("<a href='/x'>link</a>", "https://e.com").select("a").first()!
try a.attr("href")                                // "/x"
try a.attr("abs:href")                            // "https://e.com/x"
try SwiftSoup.parse("<div id=c></div>").select("#c").first()?.append("<p>New</p>")
try SwiftSoup.clean("<script>x()</script><b>Hi</b>", Whitelist.basic())   // "<b>Hi</b>"
try Entities.unescape("&copy; 2024")              // "© 2024"
```
