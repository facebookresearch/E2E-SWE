# Plot — a type-safe HTML/XML/RSS DSL for Swift

Build a Swift library called **Plot**: a domain-specific language (DSL) for writing type-safe
**HTML, XML, RSS, podcast feeds and site maps** in Swift, and rendering them to strings. A user
constructs a document with a lightweight DSL — either a tree of `Node` factory calls or a set of
SwiftUI-like `Component` values — and then calls `render()` to turn it into a string.

```swift
let html = HTML(
    .head(
        .title("My website"),
        .stylesheet("styles.css")
    ),
    .body(
        .div(
            .h1("My website"),
            .p("Writing HTML in Swift is pretty great!")
        )
    )
)

html.render() // "<!DOCTYPE html><html><head>…</head><body>…</body></html>"
```

## Deliverable & environment

- A **Swift Package Manager** package that produces a single library target/module named **`Plot`**,
  importable as `import Plot`. Put the library sources under `Sources/`. The grader compiles every
  `*.swift` file it finds under `Sources/` into the `Plot` module, so keep all library code there
  (you may organise it into any sub-folders you like).
- **No third-party dependencies** — only the Swift standard library and **Foundation** (used for
  `Date`/`DateFormatter`/`TimeZone`, and JSON where noted). The package must build offline.
- Build offline with `swift build`. Do not attempt to fetch anything from the network.

## The core model

Everything Plot renders is a **node**. The four core public types are generic over a *context*:

- `public struct Node<Context>` — the core building block: an element, an attribute, text, a group
  of nodes, or a wrapped component.
- `public struct Element<Context>` — a named element (an HTML/XML tag).
- `public struct Attribute<Context>` — a name/value attribute attached to an element.
- `public struct Document<Format: DocumentFormat>` — the root of a document of a given format.

`Context` is a **phantom type**: it never carries a runtime value; it exists so the DSL can, at
compile time, restrict which factories are available inside which parent (e.g. only `<li>` inside a
list, `href` only on linkable elements). How you model and enforce that type-safety internally is
up to you, but the generic *shapes* must be preserved so that user code compiles — in particular:

- `Node`, `Element`, `Attribute` are generic over a free `Context` (users write `Node<Any>`,
  `Attribute<String>`, etc.).
- `Node<Any>` is the context-free node used for standalone rendering and for wrapping components.
- A factory reference is enough on its own to fix `Context`: a bare `Node.<tag>(…)` call — written
  with no explicit context argument and nothing around it to pin one — must compile, resolving to
  the context in which that tag is valid, and is usable anywhere a node or `Component` is expected
  (including chained with component modifiers, or as a member of a `Node.group(…)`).

`render` is available on documents, nodes and components:

```swift
func render() -> String
func render(indentedBy indentationKind: Indentation.Kind?) -> String
```

`render()` produces output with no indentation and no separating whitespace between elements — this
is the primary contract the rest of this document specifies.

### Node factories

`Node` exposes (at least) these static factories:

- `.text(_ text: String)` — free-form text, **escaped** (see *Escaping*).
- `.raw(_ text: String)` — pre-rendered text, emitted **verbatim** (not escaped).
- `.element(_ element: Element<Context>)`.
- `.element(named: String)`, `.element(named: String, nodes: [Node])`,
  `.element(named: String, text: String)`, `.element(named: String, attributes: [Attribute])`.
- `.selfClosedElement(named: String)`, `.selfClosedElement(named: String, attributes: [Attribute])`.
- `.attribute(_ attribute: Attribute<Context>)`, `.attribute(named: String, value: String?)`.
- `.group(_ members: [Node])` and `.group(_ members: Node...)` — a flat group of sibling nodes.
- `.component(_ component: Component)` and `.components(@ComponentBuilder …)` — embed component(s)
  into a node hierarchy.
- `.empty` — renders nothing.

`Node` also conforms to `Component` (its `body` is itself) and is `ExpressibleByStringLiteral`
(a string literal becomes a `.text` node), so a bare `"string"` may be used where a `Node` or
`Component` is expected.

### Element & Attribute

`Element<Context>` has a `name`, a `closingMode`, its child nodes, and (internally) an optional
padding character used for declarations. Public helpers used by callers:

- `Element.named(_ name: String, nodes: [Node<Any>]) -> Element`
- `Element.selfClosed(named: String, attributes: [Attribute<Any>]) -> Element`
- When `Context == Any`, `Element` is a `Component` and has an initializer
  `Element(name: String, @ComponentBuilder content: …)`.

`ElementClosingMode` (aliased as `Element.ClosingMode`) has three cases:

- `.standard` — rendered as `<name…>children</name>`.
- `.selfClosing` — rendered as `<name…/>` **when it has no child elements**; if a self-closing
  element ends up containing child elements it is rendered as a standard open/close pair instead.
- `.neverClosed` — rendered as `<name…>` with no closing tag (used for declarations).

`Attribute<Context>` is:

```swift
public struct Attribute<Context> {
    public var name: String
    public var value: String?
    public var replaceExisting: Bool      // default true
    public var ignoreIfValueIsEmpty: Bool // default true
    public init(name: String, value: String?,
                replaceExisting: Bool = true,
                ignoreIfValueIsEmpty: Bool = true)
}
```

Also: `Attribute.empty` (a no-op attribute) and `Attribute.attribute(named:value:)`.

### Attribute rendering & merging

- An attribute renders as `name="value"`.
- If its value is `nil`/empty and `ignoreIfValueIsEmpty` is `true`, it renders as the **empty
  string** (it disappears). If the value is empty and `ignoreIfValueIsEmpty` is `false`, it renders
  as just the bare `name` (a valueless/boolean attribute, e.g. `hidden`, `checked`).
- When two attributes with the **same name** are added to one element, they are merged:
  - `replaceExisting == true` (the default): the later value **replaces** the earlier one.
  - `replaceExisting == false`: the later non-empty value is **appended** to the existing one,
    separated by a single space (empty values are skipped). This appending mode is how the
    component `.class` modifier accumulates multiple CSS classes (see *Component modifiers*); the
    element-level attribute factories (below) instead use the `replaceExisting: true` default.

### Escaping

`.text` content is HTML-escaped, but **existing character/entity references are never
double-escaped**:

- `<` → `&lt;`, `>` → `&gt;`.
- A `&` that begins a valid reference — `&` optionally followed by `#`, then letters/digits, then
  `;` (e.g. `&amp;`, `&#160;`, `&lt;`) — is left **unchanged**.
- Any other `&` (not forming such a reference) becomes `&amp;`.
- `.raw` text is emitted verbatim with no escaping.

Examples (`Node<Any>.text(x).render()`):

| input | output |
|-------|--------|
| `Hello & welcome to <Plot>!;` | `Hello &amp; welcome to &lt;Plot&gt;!;` |
| `&&` | `&amp;&amp;` |
| `&< &>` | `&amp;&lt; &amp;&gt;` |
| `Hello &amp; welcome&#160;to &lt;Plot&gt;!&text` | `Hello &amp; welcome&#160;to &lt;Plot&gt;!&amp;text` |

### Inline control flow

`Node` provides commands for inlining logic when building a node tree:

- `.if(_ condition: Bool, _ node: Node, else fallback: Node? = nil)` — returns `node` when the
  condition holds, otherwise the fallback (or `.empty`).
- `.unwrap(_ optional: T?, _ transform: (T) -> Node, else fallback: Node = .empty)` — maps a
  non-`nil` optional through `transform`, else returns the fallback.
- `.forEach(_ sequence: S, _ transform: (S.Element) -> Node)` — maps a sequence into a group of
  nodes (empty sequence → renders nothing).

(`Attribute` also has an `.unwrap` variant.)

### Indentation

`Indentation.Kind` is an enum with `.tabs(Int)` and `.spaces(Int)`. When a non-`nil` kind is passed
to `render(indentedBy:)`, the document is pretty-printed: each nesting level is prefixed with the
indentation unit, each element/text/component sibling is placed on its own line, and a standard
element that contains child elements gets its closing tag on its own indented line. A self-closing
element renders on one line (`<three/>`). Text that directly follows an element stays on the same
line as that element's closing tag. Example:

```
<one>
    <two>
        <three/>
    </two>four five
    <six>seven</six>
    <eight>nine</eight>
</one>
<ten key="value"/>
```

(rendered from a two-root document with `.spaces(4)`; with `.tabs(1)` the unit is a tab).

---

## HTML documents (Node-based API)

`HTML` is a `DocumentFormat`. Its initializer takes the document's root nodes and wraps them in the
standard skeleton:

```swift
public init(_ nodes: Node<HTML.DocumentContext>...)
```

`HTML().render()` → `<!DOCTYPE html><html></html>`. The doctype is `<!DOCTYPE html>` (a
never-closed element) and the content is wrapped in `<html>…</html>`.

- `.lang(_:)` on the document sets the `lang` attribute on `<html>` (e.g. `.lang(.english)` →
  `<html lang="en">`). `Language` is an enum of language codes; its raw values are the codes
  (`.english` → `en`, `.usEnglish` → `en-us`, …).
- `.dir(_:)` sets text direction. `Directionality` has `.leftToRight` (`ltr`), `.rightToLeft`
  (`rtl`), `.auto` (`auto`). At document level it applies to `<html>`; on an element it applies to
  that element.
- `.comment(_ text: String)` renders an HTML comment `<!--text-->`. It is available in any HTML
  context — at document level and inside element content (e.g. within `<body>`).
- `.head(_:)` and `.body(_:)` create the `<head>` and `<body>` elements.

### `<head>` metadata expansion

Several head factories expand into **multiple ordered tags** — this is a core Plot behaviour. Each
of the following shows the exact expansion (in order):

- `.encoding(.utf8)` → `<meta charset="UTF-8"/>`.
- `.title("Title")` →
  `<title>Title</title>` · `<meta name="twitter:title" content="Title"/>` ·
  `<meta property="og:title" content="Title"/>`.
- `.description("D")` →
  `<meta name="description" content="D"/>` · `<meta name="twitter:description" content="D"/>` ·
  `<meta property="og:description" content="D"/>`.
- `.url("url.com")` →
  `<link rel="canonical" href="url.com"/>` · `<meta name="twitter:url" content="url.com"/>` ·
  `<meta property="og:url" content="url.com"/>`.
- `.siteName("MySite")` → `<meta property="og:site_name" content="MySite"/>`.
- `.socialImageLink("url.png")` →
  `<meta name="twitter:image" content="url.png"/>` · `<meta property="og:image" content="url.png"/>`.
- `.twitterCardType(_:)` → `<meta name="twitter:card" content="…"/>` where the value is the card
  type's raw value (`.summaryLargeImage` → `summary_large_image`).
- `.twitterUsername("@x")` → `<meta name="twitter:site" content="@x"/>`.
- `.viewport(_ width, fit:)` → `<meta name="viewport" content="…"/>`. The content is
  `width=<W>, initial-scale=1.0` where `<W>` is `device-width` for `.accordingToDevice` or the
  number for `.constant(n)`; if a `fit:` (`HTMLViewportFitMode`, e.g. `.cover`) is supplied,
  `, viewport-fit=<fit>` is appended.
- `.stylesheet("styles.css")` → `<link rel="stylesheet" href="styles.css" type="text/css"/>`. An
  optional `integrity:` argument appends an `integrity="…"` attribute.
- `.favicon("icon.png")` → `<link rel="shortcut icon" href="icon.png" type="image/png"/>`.
- `.rssFeedLink("feed.rss", title: "RSS")` →
  `<link rel="alternate" href="feed.rss" type="application/rss+xml" title="RSS"/>`.
- `.style("css")` (in `<head>`) → `<style>css</style>`.
- `.script(…)` in `<head>` renders a `<script>` element (see scripts below).

`.link(…)` builds a `<link>` from its attributes, e.g. `.rel(_:)` (`HTMLLinkRelationship`, whose
cases render their raw values — `.alternate` → `alternate`, `.appleTouchIcon` → `apple-touch-icon`,
`.preconnect` → `preconnect`, `.manifest` → `manifest`, `.maskIcon` → `mask-icon`,
`.stylesheet` → `stylesheet`, `.canonical` → `canonical`, `.shortcutIcon` → `shortcut icon`),
`.href(_:)`, `.hreflang(_:)` (a `Language`), `.sizes(_:)`, `.color(_:)`, `.type(_:)`,
`.integrity(_:)`, `.crossorigin(_ enabled: Bool)` (renders bare `crossorigin` when `true`, omitted
when `false`), `.title(_:)`.

### `<body>` and other elements

For the vast majority of HTML elements, there is a `Node` factory **named after the tag** that
renders `<tag>…children…</tag>`, taking a variadic list of child nodes/attributes/strings. This
includes at least:

- Sectioning/content: `.div`, `.span`, `.p`, `.h1`–`.h6`, `.article`, `.section`, `.nav`,
  `.aside`, `.main`, `.header`, `.footer`, `.blockquote`, `.pre`, `.code`, `.abbr`, `.noscript`,
  `.details`, `.summary`, `.time`.
- Inline text styling: `.b`, `.strong`, `.i`, `.em`, `.u`, `.s`, `.ins`, `.del`, `.small`.
- Lists: `.ul`, `.ol`, `.li`; description lists `.dl`, `.dt`, `.dd`.
- Tables: `.table`, `.caption`, `.thead`, `.tbody`, `.tfoot`, `.tr`, `.th`, `.td`.
- Forms: `.form`, `.fieldset`, `.label`, `.input`, `.textarea`, `.button`, `.select`, `.datalist`,
  `.option`.
- Media/embeds: `.img`, `.audio`, `.video`, `.source`, `.picture`, `.iframe`, `.embed`, `.object`,
  `.data`, `.script`.
- Void/self-closing elements render with a trailing slash: `.br` → `<br/>`, `.hr` → `<hr/>`,
  `.img` → `<img …/>`, `.input` → `<input …/>`, `.source` → `<source …/>`, `.meta`, `.link`. That
  enumeration is illustrative, not exhaustive: apart from the exception below, an HTML element
  factory takes the closing mode its tag has in standard HTML — the elements that are void in HTML
  self-close, every other element renders as an open/close pair.
- `.option` uses the `.selfClosing` closing mode: an `<option>` with no child content renders
  self-closed (e.g. `<option value="x"/>`, `<option value="y" selected/>`), falling back to
  `<option …>…</option>` only when it is given child elements.

Passing a bare string to an element factory (e.g. `.p("Text")`) is shorthand for an escaped text
child. `.a(…)` renders an `<a>` anchor.

### HTML attributes

Attributes are added exactly like child nodes (as entries in an element's argument list). Each
attribute has a factory named after it, rendering `name="value"`, available on the elements where
it is valid. These factories build an `Attribute` with the standard defaults (notably
`replaceExisting: true`), so supplying the same attribute twice on one element makes the later
value **replace** the earlier — `.class` included: a second element-level `.class(...)` replaces
the previous class rather than appending. Space-separated class *accumulation* is a feature of the
component `.class` modifier only (default `replaceExisting: false`; see *Component modifiers*).

- Common: `.id`, `.class`, `.style`, `.title`, `.hidden(Bool)` (bare `hidden` when true, else
  omitted), `.dir(_:)`, `.spellcheck(Bool)` (renders `spellcheck="true"`/`"false"`),
  `.onclick(_:)` (an inline event handler → `onclick="…"`).
- Custom data attributes: `.data(named: "x", value: "y")` → `data-x="y"`.
- ARIA: `.ariaLabel` → `aria-label`, `.ariaControls` → `aria-controls`, `.ariaExpanded(Bool)` →
  `aria-expanded="true"`/`"false"`, `.ariaHidden(Bool)` → `aria-hidden="true"`/`"false"`.
- Links/anchors: `.href`, `.rel(_:)` (`HTMLAnchorRelationship` / `HTMLLinkRelationship`, e.g.
  `.nofollow` → `nofollow`, `.noreferrer` → `noreferrer`), `.target(_:)` (`HTMLAnchorTarget`,
  `.blank` → `_blank`), `.hreflang`, `.sizes`, `.color`, `.integrity`, `.crossorigin(Bool)`.
- Media/sources: `.src`, `.srcset`, `.media`, `.alt`, `.width(Int)`, `.height(Int)`,
  `.controls(Bool)` (bare `controls` when true, else omitted), `.type(_:)`, `.frameborder(Bool)`
  (`frameborder="0"` when false), `.allow`, `.allowfullscreen(Bool)` (bare when true),
  `.datetime`, `.data(_:)` (the `<object>` `data` attribute).
- Element type/value: `.type(_:)`, `.value`, `.name`, `.for(_:)` (`<label for>`), `.datetime`.
- Form/inputs: `.action`, `.method(_:)` (`HTMLFormMethod`, `.get`/`.post`),
  `.enctype(_:)` (`HTMLFormContentType`: `.urlEncoded` → `application/x-www-form-urlencoded`,
  `.multipartData` → `multipart/form-data`, `.plainText` → `text/plain`),
  `.novalidate()` (bare `novalidate`), `.placeholder`, `.cols(Int)`, `.rows(Int)`,
  `.required(Bool)`, `.readonly(Bool)`, `.disabled(Bool)`, `.checked(Bool)`, `.multiple(Bool)`,
  `.autofocus(Bool)` (all bare-when-true, omitted-when-false),
  `.autocomplete(Bool)` (renders `autocomplete="on"`/`"off"`),
  `.label(_:)`, `.isSelected(Bool)` (`<option selected>` when true, omitted when false).
- Scripts: `.async()` (bare `async`), `.defer()` (bare `defer`), `.src`, `.integrity`.
- `<input>` `.type(_:)` uses `HTMLInputType` (raw values: `text`, `search`, `email`, `checkbox`,
  `file`, `submit`, `password`, …). `<button>` `.type(_:)` uses `HTMLButtonType` (`button`,
  `submit`). `.open(Bool)` on `<details>` renders bare `open` when true.

**Audio/video sources.** `.source(.src(_), .type(_))` inside `<audio>`/`<video>` uses a format enum
whose raw value is the MIME type: audio — `.mp3` → `audio/mpeg`, `.wav` → `audio/wav`,
`.ogg` → `audio/ogg`; video — `.mp4` → `video/mp4`, `.webM` → `video/webm`, `.ogg` → `video/ogg`.
An `<audio>`/`<video>` renders `controls` (bare) when `.controls(true)`.

**Custom attributes on an element:** `.attribute(named: "x", value: "y")` (a `Node`) or, where a
typed attribute is needed, `.attribute(_ attribute:)` taking an `Attribute` value.

---

## HTML documents (Component API)

Plot also offers a SwiftUI-like component API. `Component` is a protocol:

```swift
public protocol Component: Renderable {
    var body: Component { get }
}
```

Component bodies are built with the **`@ComponentBuilder`** result builder, which supports inlining
Swift control flow — `if`, `if let`, `if/else`, `for` loops, `switch`, and `Optional.map` — and
freely mixing `Component` and `Node` children (a `Node` is a `Component`). Order is preserved.

`HTML` has a component-based initializer:

```swift
public init(head: [Node<HTML.HeadContext>] = [], @ComponentBuilder body: () -> Component)
```

so `HTML { … }` builds a page whose `<body>` is the components in the closure (and a `<head>` only
if head nodes are supplied). `.body { … }` likewise takes a component-builder closure.

### Built-in components

Element-backed components (each renders its corresponding tag; the initializer takes a string, a
`@ComponentBuilder` closure, or no argument at all — yielding the element with empty content):

`Article`, `Button`, `Details`, `Div`, `FieldSet`, `Footer`, `H1`…`H6`, `Header`, `ListItem`,
`Main`, `Navigation`, `Paragraph` (→ `<p>`), `Span`, `Summary`, `TableCaption` (→ `<caption>`),
`TableCell` (→ `<td>`), `TableHeaderCell` (→ `<th>`), `Text` (raw escaped text, no wrapping tag).

Higher-level components:

- `Link(_ title, url:)` → `<a href="url">title</a>`.
- `Image(_ url)` / `Image(url:description:)` → `<img src="…"/>` (with `alt` when a description is
  given).
- `List` — renders `<ul>`/`<ol>` with each element wrapped in `<li>`:
  - `List(_ items: [String])` and `List(_ items:content:)` map a sequence into list items.
  - `List { … }` takes explicit item components; any child that is not already a list item is
    wrapped in `<li>`, an `EmptyComponent()` contributes nothing, and control flow works inside.
  - `.listStyle(_:)` selects the style: `.unordered` (`<ul>`, default) or `.ordered` (`<ol>`);
    `.unordered.withItemClass("item")` adds a `class` to every `<li>`.
  - `ListItem(_:)` is an explicit list item; `.number(_ n: Int)` sets its `value` attribute.
- `Table` — `Table { … }` (rows; non-row children wrapped in `<tr>`, non-cell children in
  `<td>`) and `Table(caption:header:footer:rows:)`, whose optional `caption:` is a `TableCaption`
  and whose `rows:` is a `@ComponentBuilder` closure (so `Table { … }` is that initializer's
  trailing-closure form): it emits the given caption as it stands, then `<thead>` and `<tfoot>`
  around the header and the footer. The `<tbody>` wrapper around the rows appears only when the
  table is grouped, i.e. when at least one of `caption:`, `header:` or `footer:` is supplied; a
  table with none of the three emits its rows directly as children of `<table>`.
  `TableRow { … }` → `<tr>` (cells wrapped in `<td>`). The one exception is the `header:` row of
  `Table(caption:header:footer:rows:)`: its auto-wrapped cells render as `<th>` (header cells),
  while `rows:` and `footer:` cells render as `<td>`.
- `Form(url:method:content:)` → `<form action=… method=…>…</form>`; `Label(_ title){…}`,
  `TextField(name:isRequired:)` (→ `<input type="text">`), `Input(type:name:)`,
  `TextArea(text:name:numberOfRows:numberOfColumns:)`, `SubmitButton(_ title)` (→
  `<input type="submit" value=…>`). `.autoFocused()` and `.autoComplete(_ Bool)` are modifiers on
  form fields.
- `IFrame(url:addBorder:allowFullScreen:enabledFeatureNames:)` → an `<iframe>` (with
  `frameborder="0"` when `addBorder` is false, bare `allowfullscreen`, and an `allow` list joined
  appropriately).
- `AudioPlayer(source:showControls:)` → `<audio>` with a typed `<source>`; `source` is built with
  `.mp3(at:)`, `.wav(at:)`, `.ogg(at:)`.
- `Time(datetime:){…}` → `<time datetime=…>…</time>`.

### Component modifiers

Modifiers return a modified component and can be chained. They apply to the HTML element the
component renders:

- `.class(_ name: String, replaceExisting: Bool = false)` — **appends** the class by default
  (space-separated, empty names skipped); pass `replaceExisting: true` to replace all existing
  classes. `.id(_:)`, `.style(_:)`, `.data(named:value:)`, `.accessibilityLabel(_:)` →
  `aria-label`, `.directionality(_:)` → `dir`.
- `.attribute(named:value:replaceExisting:ignoreValueIfEmpty:)` and `.attribute(_ Attribute)` add
  arbitrary attributes.
- Class/attribute modifiers applied to a **wrapping component** (a component whose body is another
  component) propagate down to the element that is ultimately rendered, and applied to a
  `ComponentGroup` apply to **each** member.
- `Text` styling modifiers wrap the text: `.bold()` → `<b>`, `.italic()` → `<em>`,
  `.underlined()` → `<u>`, `.strikethrough()` → `<s>`, `.addLineBreak()` appends a `<br/>` sibling.
  `Text` values can be concatenated with `+` (e.g. `Text("One") + Text(" ") + Text("Two").bold()`
  → `One <b>Two</b>`).
- `ComponentGroup { … }` groups sibling components with no wrapping element; `EmptyComponent()`
  renders nothing.

### The component environment

Components can pass values down a hierarchy, SwiftUI-style:

- `EnvironmentKey<Value>` identifies a value; construct a custom one with
  `EnvironmentKey(identifier: "…")` (optionally `EnvironmentKey(defaultValue:)`).
- `@EnvironmentValue(_ key:) var x` — a property wrapper that reads the current value for `key`
  inside a component's `body`.
- `.environmentValue(_ value, key:)` — a modifier that sets a value for a subtree (also available
  on the top-level `HTML` document). A value applies to all descendant components until overridden,
  and **does not** leak to siblings.
- Built-in keys/modifiers: `.linkRelationship` (sets the `rel` of descendant `Link`s;
  `.linkRelationship(_:)` modifier), `.linkTarget` (sets `target`; `.linkTarget(_:)`, pass `nil`
  to clear), `.listStyle` (used by `List`).

---

## XML

`XML` is a `DocumentFormat` whose initializer takes free-form nodes:

```swift
public init(_ nodes: Node<XML.DocumentContext>...)
```

`XML().render()` → `<?xml version="1.0" encoding="UTF-8"?>` (the declaration; an empty document is
just the declaration). The declaration is a `neverClosed` element whose tag is padded with `?`.
Build content with the generic `.element(named:…)` / `.selfClosedElement(named:…)` /
`.attribute(named:value:)` factories:

```swift
XML(.element(named: "hello", text: "world!")).render()
// <?xml version="1.0" encoding="UTF-8"?><hello>world!</hello>
XML(.selfClosedElement(named: "element")).render()
// <?xml version="1.0" encoding="UTF-8"?><element/>
```

---

## RSS feeds

`RSS` is an `RSS`-based `DocumentFormat`. Its initializer takes channel-level nodes:

```swift
public init(_ nodes: Node<RSS.ChannelContext>...)
```

Every RSS feed renders the XML declaration, then an `<rss version="2.0" …><channel>…</channel></rss>`
wrapper carrying two namespaces (in this order):

```
<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" \
xmlns:atom="http://www.w3.org/2005/Atom" \
xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>…</channel></rss>
```

Channel-level factories:

- `.title(_:)` → `<title>…</title>`, `.description(_ text:)` → `<description>…</description>`,
  `.link(_:)` → `<link>…</link>`, `.language(_ Language)` → `<language>en-us</language>`,
  `.ttl(_ minutes: Int)` → `<ttl>…</ttl>`.
- `.atomLink(_ href:)` → `<atom:link href="…" rel="self" type="application/rss+xml"/>`.
- `.pubDate(_ date: Date, timeZone: TimeZone = .current)` and
  `.lastBuildDate(_ date:, timeZone:)` → `<pubDate>…</pubDate>` / `<lastBuildDate>…</lastBuildDate>`.
  Dates use the **RFC-822** format `"E, d MMM yyyy HH:mm:ss Z"` with the `en_US_POSIX` locale and
  the given time zone — e.g. a date of 2019-10-17 10:15:05 in `+01:00` renders as
  `Thu, 17 Oct 2019 10:15:05 +0100`.
- `.item(_:)` → an `<item>…</item>`.

Item-level factories:

- `.guid(_:)` → `<guid>…</guid>`; a nested `.isPermaLink(_ Bool)` adds an
  `isPermaLink="true"`/`"false"` attribute (e.g. `<guid isPermaLink="true">url.com</guid>`).
- `.title(_:)`, `.link(_:)`, `.description(_ text:)`, `.pubDate(_:timeZone:)` as above.
- `.content(_ html: String)` → `<content:encoded><![CDATA[…]]></content:encoded>` wrapping the raw
  HTML string in CDATA.
- `.content(_ nodes: Node<HTML.BodyContext>...)` — same, but the CDATA payload is the given HTML
  DSL nodes rendered to a string (no indentation).
- `.description(_ nodes: Node<HTML.BodyContext>...)` (channel or item) →
  `<description><![CDATA[…]]></description>` — a description whose body is CDATA-wrapped
  rendered HTML.

---

## Podcast feeds

`PodcastFeed` is an RSS-based `DocumentFormat` (initializer takes channel nodes). It renders the
same `<rss>/<channel>` wrapper as RSS, plus two extra namespaces after the atom/content ones:

```
… xmlns:atom="…" xmlns:content="…" \
xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" \
xmlns:media="http://www.rssboard.org/media-rss"><channel>…
```

It supports the RSS channel/item factories above **plus** iTunes/media extensions:

- Channel: `.newFeedURL(_:)` → `<itunes:new-feed-url>…`, `.title(_:)` → `<title>…` (plain),
  `.subtitle(_:)` → `<itunes:subtitle>…`, `.summary(_:)` → `<itunes:summary>…`,
  `.author(_:)` → `<itunes:author>…`, `.copyright(_:)` → `<copyright>…`,
  `.owner(.name(_), .email(_))` → `<itunes:owner><itunes:name>…</itunes:name><itunes:email>…</itunes:email></itunes:owner>`,
  `.category(_ name, _ subcategories…)` → `<itunes:category text="News">` (self-closing when no
  subcategory is given; a subcategory is supplied as a nested `.category(_ name)` node — not as a
  string — and renders as a child `<itunes:category text="…"/>`),
  `.image(_ url)` → `<itunes:image href="…"/>`,
  `.explicit(_ Bool)` → `<itunes:explicit>yes</itunes:explicit>` / `…>no<…`,
  `.type(_ PodcastType)` → `<itunes:type>episodic</itunes:type>` / `…serial…`.
- Item (episode): `.title(_:)` renders **both** `<title>…</title>` and `<itunes:title>…</itunes:title>`;
  `.duration(_ string)` → `<itunes:duration>…`, and `.duration(hours:minutes:seconds:)` formats as
  zero-padded `HH:mm:ss`; `.seasonNumber(_ Int)` → `<itunes:season>…`, `.episodeNumber(_ Int)` →
  `<itunes:episode>…`, `.episodeType(_ PodcastEpisodeType)` → `<itunes:episodeType>full|trailer|bonus</…>`.
- `.audio(url:byteSize:type:title:)` (type defaults to `"audio/mpeg"`) expands into an enclosure
  plus a media-content block:
  ```
  <enclosure url="…" length="…" type="…"/>
  <media:content url="…" length="…" type="…" isDefault="true" medium="audio">
  <media:title type="plain">…</media:title></media:content>
  ```
- `.content(_ html:)` → CDATA `<content:encoded>` as in RSS.

---

## Site maps

`SiteMap` is a `DocumentFormat` whose initializer takes URL nodes. It renders the XML declaration
then a `<urlset>` element with two fixed namespaces:

```
<?xml version="1.0" encoding="UTF-8"?>\
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" \
xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">…</urlset>
```

- `.url(_:)` → `<url>…</url>`.
- `.loc(_ url:)` → `<loc>…</loc>`.
- `.changefreq(_ SiteMapChangeFrequency)` → `<changefreq>daily</changefreq>` (raw values such as
  `daily`, `monthly`, …).
- `.priority(_ Double)` → `<priority>1.0</priority>` (the double's default string form).
- `.lastmod(_ date: Date, timeZone: TimeZone = .current)` → `<lastmod>2019-10-17</lastmod>`,
  formatted `yyyy-MM-dd` in the given time zone.

---

## Custom elements, attributes & document formats

`DocumentFormat` is a protocol with an associated `RootContext`:

```swift
public protocol DocumentFormat { associatedtype RootContext }
```

Users can define their own formats and build documents with the generic factories:

```swift
struct MyFormat: DocumentFormat { enum RootContext {} }

let doc = Document.custom(withFormat: MyFormat.self, elements: [
    .named("one", nodes: [
        .element(named: "two", nodes: [.selfClosedElement(named: "three")]),
        .text("four "),
        .component(Text("five"))
    ]),
    .selfClosed(named: "ten", attributes: [Attribute(name: "key", value: "value")])
])
doc.render(indentedBy: .spaces(4))
```

`Document.custom(_ elements: Element<Format.RootContext>...)` and
`Document.custom(withFormat:elements:)` both create a document; `Document`, `Node`, `Element` and
`Attribute` remain usable with any custom context.

---

## Output conventions summary

- `render()` inserts **no** whitespace between sibling elements and no trailing newline.
- Elements are `<name attr="v" …>children</name>`; self-closing `<name …/>`; never-closed
  `<name …>`.
- Boolean attributes render as the bare attribute name when enabled and vanish when disabled,
  except where a specific string is specified above (`autocomplete` → on/off; `spellcheck`,
  `aria-expanded`, `aria-hidden` → true/false; `frameborder` → 0).
- Attribute values are wrapped in double quotes; empty-valued attributes vanish unless configured
  otherwise.
- `.text` is escaped without double-escaping existing references; `.raw` is verbatim; feed HTML
  content is wrapped in `<![CDATA[…]]>`.
