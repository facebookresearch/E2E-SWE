# stylesheet-tree — a CSS parser, generator, traversal and validation toolkit

Implement a JavaScript library for working with CSS as an abstract syntax tree (AST). The library
parses CSS text into a detailed AST, serializes an AST back to CSS, traverses and searches the tree,
and validates CSS values against W3C value-definition grammars. It is the kind of toolkit a CSS
minifier, linter, or transformer is built on.

## Build and packaging

The library is written as native **ECMAScript modules** (`"type": "module"`) and runs on Node.js 20
with **no build/transpile step**. Provide an executable **`setup.sh`** at the repository root; its
only required job is to make the runtime dependencies resolvable (they are pre-installed — see
below). The package entry point is **`src/index.js`**.

The library is imported under the package name **`stylesheet-tree`** (resolved to `src/index.js`).
All examples below use a namespace import:

```js
import * as sst from "stylesheet-tree";
```

Every symbol documented here is a **named export** of the package
(`sst.parse`, `sst.generate`, `sst.walk`, `sst.lexer`, …).

### Pre-installed dependencies (do not reimplement or vendor)

Two third-party packages are already installed and importable by bare specifier:

- **`mdn-data`** — MDN's machine-readable CSS dictionaries (`mdn-data/css/properties.json`,
  `mdn-data/css/at-rules.json`, `mdn-data/css/syntaxes.json`). These supply the property/type
  **value-definition grammars** the validation lexer checks against. Load them and build the
  lexer's dictionaries from them.
- **`source-map-js`** — provides `SourceMapGenerator` (import from
  `source-map-js/lib/source-map-generator.js`); used only to build a source map in
  `generate(ast, { sourceMap: true })`.

`mdn-data` is the only grammar source that is pre-installed. It does not cover every syntax
(vendor-prefixed and legacy grammars, corrections), so the library may layer a supplementary
dictionary of CSS syntax patches on top of it and merge that into the lexer's grammars at load time;
if you ship one, keep it at **`data/patch.json`** at the repository root next to `src/`.

## AST overview

`parse` produces a tree of **nodes**. Every node has a string `type` field and a `loc` field (source
location, `null` unless positions are requested). Node types referenced in this spec:

- **Rootsheet** `{ type, children }` — the root; `children` is a List (see below) of rules,
  at-rules and raw nodes.
- **Rule** `{ type, prelude, block }` — `prelude` is a MatchGroup (or Raw), `block` is a Block.
- **Atrule** `{ type, name, prelude, block }` — `name` is the at-rule keyword (e.g. `"media"`);
  `prelude` is an AtruleHead (or Raw or `null`); `block` is a Block or `null`.
- **AtruleHead** `{ type, children }`, **Block** `{ type, children }`.
- **MatchGroup** `{ type, children }` — a List of MatchSeq nodes.
- **MatchSeq** `{ type, children }` — a List of simple-selector / combinator nodes.
- **TypeMatch** `{ type, name }` (`a`), **IdMatch** `{ type, name }` (`#id`),
  **ClassMatch** `{ type, name }` (`.cls`).
- **AttrMatch** `{ type, name, matcher, value, flags }` — `name` is an Identifier node,
  `matcher` is a string like `"^="` (or `null`), `value` is a String or Identifier node (or `null`).
- **Joiner** `{ type, name }` — `name` is `">"`, `"+"`, `"~"`, or `" "` (descendant).
- **PseudoClassMatch** `{ type, name, children }` (`:hover`, `:nth-child(...)`),
  **PseudoElemMatch** `{ type, name, children }` (`::before`).
- **Nth** — the parsed `An+B` argument of a structural pseudo-class; its `nth` field is an
  **AnPlusB** node `{ type: "AnPlusB", a, b }` where `a` and `b` are the coefficient strings (e.g.
  `:nth-child(2n+1)` → `Nth.nth = { type: "AnPlusB", a: "2", b: "1" }`).
- **Decl** `{ type, important, property, value }` — `important` is a boolean;
  `property` is the property-name string; `value` is a Value or Raw node. The important flag belongs
  to the **declaration** production, not to the value: a `!` inside a declaration always ends the
  value and starts the flag (it is never a value component) and must be followed by an identifier, so
  a `!` with no identifier after it is a span the declaration cannot consume (see `onParseError`).
- **Value** `{ type, children }` — a List of value component nodes. Insignificant whitespace between
  components is **not** represented in the tree: `children` holds the component nodes only, and the
  serializer re-inserts separating whitespace where needed (see `generate`).
- **Identifier** `{ type, name }`, **Hash** `{ type, value }` (a `#rrggbb`; `value` excludes `#`),
  **Dimension** `{ type, value, unit }` (`10px` → `value: "10"`, `unit: "px"`),
  **Number** `{ type, value }` (a bare number, `3` → `value: "3"`),
  **Percentage** `{ type, value }` (`50%` → `value: "50"` — a percentage is its **own** node type,
  not a Dimension with unit `"%"`),
  **String** `{ type, value }` — a quoted string; `value` is the **decoded** inner text, with the
  surrounding quotes removed and escape sequences resolved (i.e. `string.decode` applied, e.g. a
  `"foo bar"` token → `value: "foo bar"`). The generator re-adds the quotes on serialization, so the
  string round-trips.
- **Function** `{ type, name, children }` — a functional value such as `calc(...)` or `var(...)`;
  `name` is the function keyword (e.g. `"calc"`) and `children` is a List of the argument value nodes.
- **Url** `{ type, value }` — a `url(...)` value; `value` is the **inner URL string only**, with the
  `url(` / `)` wrapper and any surrounding quotes removed (e.g. `url(foo.jpg)` → `value: "foo.jpg"`).
- **UnicodeRange** `{ type, value }` — a `U+...` unicode-range token; `value` is the full token text
  (e.g. `U+0-7F` → `value: "U+0-7F"`).
- **Raw** `{ type, value }` — an unparsed span of text (used for tolerant recovery and for parts
  left unparsed by detail options).

The `children` of container nodes is always a **List** instance (see the List section), not a plain
array.

## parse(source[, options])

Parses CSS text into an AST and returns the root node.

```js
const ast = sst.parse(".a { color: red; }"); // ast.type === "Rootsheet"
```

The parser is **tolerant**: malformed input never throws. Content that cannot be parsed is wrapped
in a **Raw** node and, if an `onParseError` handler is supplied, the handler is called once per
error.

Options:

- **context** (string, default `"stylesheet"`) — which CSS production to parse the source as. The
  returned root node type depends on the context. Supported contexts include: `"stylesheet"` →
  Rootsheet, `"selector"` → MatchSeq, `"selectorList"` → MatchGroup, `"declaration"` →
  Decl, `"value"` → Value.
- **positions** (boolean, default `false`) — when `true`, every node's `loc` is populated with
  `{ source, start, end }`, where `start`/`end` are `{ offset, line, column }`. `offset` is
  0-based; `line` and `column` are **1-based**. When `false`, every node's `loc` is `null`.
- **filename** (string, default `"<unknown>"`) — stored as `loc.source` and used as the source name
  in generated source maps.
- **onParseError** (function `(error) => void`) — called for each recovered parse error. Each error
  exposes a `rawMessage` (e.g. `"Colon is expected"`, `"Identifier is expected"`). Recovery is never
  silent: every span of input the parser cannot consume as part of the production it is parsing is
  both wrapped in a Raw node and reported through this handler exactly once.
- **onComment** (function `(value, loc) => void`) — called for each comment; `value` is the comment
  body **without** the surrounding `/*` and `*/`.
- **parseRulePrelude** (boolean, default `true`) — when `false`, a rule's selector prelude is kept
  as a single **Raw** node (`{ type: "Raw", value: ".foo" }`) instead of a MatchGroup.
- **parseAtrulePrelude** (boolean, default `true`) — when `false`, an at-rule's prelude is kept as a
  **Raw** node instead of being parsed in detail.
- **parseValue** (boolean, default `true`) — when `false`, a declaration's value is kept as a
  **Raw** node instead of a Value.
- **parseCustomProperty** (boolean, default `false`) — custom-property (`--*`) values and `var()`
  fallbacks are kept as **Raw** by default; when `true`, they are parsed in detail as a Value.

Worked example — detail options change one field:

```js
sst.parse("color:#aabbcc", { context: "declaration" }).value.type            // "Value"
sst.parse("color:#aabbcc", { context: "declaration", parseValue: false }).value.type // "Raw"
```

## generate(ast[, options])

Serializes an AST back to a CSS string. Output is **compact** (no insignificant whitespace):
`sst.generate(sst.parse(".a { color: red }"))` → `".a{color:red}"`.

Serialization must **round-trip with parsing** for every construct — including at-rules and their
nested rules. In particular, `@keyframes` (and `@media`/`@supports`) blocks contain nested rules
whose preludes must be preserved: a keyframe rule is keyed by a percentage or the keywords
`from`/`to`, e.g. `generate(parse("@keyframes spin{0%{opacity:0}100%{opacity:1}}"))` →
`"@keyframes spin{0%{opacity:0}100%{opacity:1}}"` (the `0%` / `100%` selectors are not dropped).

Comments are normally dropped by the parser, but a top-level **exclamation comment** (`/*! … */`)
is retained and re-emitted by the generator, e.g.
`generate(parse("/*! keep */ .a{color:red}"))` → `"/*! keep */.a{color:red}"`.

- The serializer **auto-inserts whitespace only where needed** to prevent adjacent tokens from
  merging into a different token. Example: the value `1%var(--a)#ff0000` serializes as
  `1% var(--a) #ff0000`. Raw values are emitted verbatim (no auto-spacing).
- Whitespace around the `+` and `-` operators inside a math function such as `calc()` is
  **significant**: it is not insignificant whitespace the compact-output rule may drop, and it is
  preserved through a parse/generate round-trip. This follows the CSS rule that `+`/`-` in a
  `calc()` expression must be surrounded by whitespace so they are not read as the sign of the
  following number (`*` and `/` need no surrounding space).
- **mode** (`"safe"` default, or `"spec"`): `safe` inserts an extra separating space in a few edge
  cases so older browsers still tokenize the result; `spec` follows the CSS serialization spec
  exactly. For `a { border: calc(1px) solid #ff0000 }`: safe →
  `a{border:calc(1px) solid #ff0000}`, spec → `a{border:calc(1px)solid#ff0000}`.
- **sourceMap** (boolean, default `false`): when `true`, `generate` returns an object
  `{ css, map }` instead of a string, where `map` is a `SourceMapGenerator` (nodes must carry
  positions). For `parse(".a {\n  color: red;\n}\n", { filename: "test.css", positions: true })`
  then `generate(ast, { sourceMap: true })`:
  - `result.css` === `".a{color:red}"`
  - `result.map.toString()` ===
    `'{"version":3,"sources":["test.css"],"names":[],"mappings":"AAAA,E,CACE,S"}'`
- Passing a node with an unrecognized `type` **throws** an error whose message contains
  `Unknown node type`.

Serialization must **round-trip** with parsing: `generate(parse(x))` re-parses to an equivalent AST.

## Traversal: walk(ast, options)

Visits every node of the tree. `options` may be a function (shorthand for `{ enter: fn }`) or an
object with `enter` and/or `leave` handlers.

- **Natural order**: `enter` fires in document order (a node before its children); `leave` fires
  after all of a node's children. For `.a { color: red; }` the enter order is
  `Rootsheet, Rule, MatchGroup, MatchSeq, ClassMatch, Block, Decl, Value, Identifier`
  and the leave order is the reverse-ish post-order
  (`ClassMatch, MatchSeq, MatchGroup, Identifier, Value, Decl, Block, Rule, Rootsheet`).
- **visit** (string): restrict the handler to a single node type (e.g. `{ visit: "ClassMatch" }`).
- **reverse** (boolean): iterate a node's properties and children last-to-first.
- **Control flow** from an `enter`/`leave` handler:
  - returning `this.skip` (or `sst.walk.skip`) from `enter` prevents descent into the current
    node's subtree (the node itself is still visited);
  - returning `this.break` (or `sst.walk.break`) stops the entire traversal immediately.
- **Handler arguments** `(node, item, list)`: when the node is inside a List, `item` is its List
  wrapper and `list` is the containing List (usable for mutation such as `list.remove(item)`);
  otherwise `item`/`list` are absent.
- **Handler context** (`this`) exposes the closest ancestor of interest, or `null`: `this.root`,
  `this.stylesheet`, `this.atrule`, `this.atrulePrelude`, `this.rule`, `this.selector`,
  `this.block`, `this.declaration`, `this.function`. (For example, inside an `@import url(...)` the
  `Url` node has `this.declaration === null`; inside `background: url(...)` it is non-null.)

Removing nodes during a walk via `list.remove(item)` and re-serializing reflects the deletion:
walking `.a { foo: 1; bar: 2; } .b { bar: 3; baz: 4; }` and removing every `bar` declaration yields
`.a{foo:1}.b{baz:4}`.

## Searching: find / findLast / findAll

- **find(ast, fn)** — the first node (natural order) for which `fn(node, item, list)` is truthy.
- **findLast(ast, fn)** — the first match in reverse order.
- **findAll(ast, fn)** — an array of all matches in natural order.

For `.a { color: red } .b { color: green }`, finding `Decl` nodes with `property === "color"`
gives `find` → `color:red`, `findLast` → `color:green`, `findAll` → two nodes.

## Value validation: the lexer

`sst.lexer` validates CSS against W3C value-definition grammars built from `mdn-data` (plus any
patches layered on top). A **match result** is an object `{ matched, error, ... }`:

- on success, `matched` is a non-`null` match node and `error` is `null`;
- on failure, `matched` is `null` and `error` is an `Error` (see the specific error names below).

Match-result objects also expose helper methods `getTrace(node)`, `isType(node, name)`,
`isProperty(node, name)`, `isKeyword(node)`.

Methods:

- **matchProperty(propertyName, value)** — validate a value against a property's grammar. `value`
  may be a CSS string or a parsed Value node. Behaviors:
  - a valid value matches (`.matched !== null`, `.error === null`);
  - an invalid value fails with `error.name === "SyntaxMatchError"` and `error.rawMessage ===
    "Mismatch"`;
  - the four **CSS-wide keywords** `inherit`, `initial`, `unset`, `revert` match **any** property;
  - a **custom property** (name starting with `--`) is not validated: `matched` is `null` and
    `error.message` is exactly ``Lexer matching doesn't applicable for custom properties``.
- **matchType(typeName, value)** — validate against a named type grammar (e.g. `"length"`,
  `"color"`). An unknown type name fails with `error.name === "SyntaxReferenceError"` and a message
  containing `Unknown type`.
- **matchDeclaration(declarationNode)** — validate a parsed Decl node against its property.
- **match(syntax, value)** — validate against an **arbitrary value-definition syntax string**
  supplied by the caller. This is where the value-definition **matching engine** is exercised
  directly; it must correctly implement at least:
  - **combinators**: ` ` (juxtaposition), `|` (exactly one alternative), `||` (one or more, any
    order), `&&` (all, any order);
  - **multipliers**: `?` (0–1), `*` (0+), `+` (1+), `#` (comma-separated list, 1+),
    `{min,max}` (occurrence range), and their comma variants.
  - Examples: `match("<number>{2,3}", "1")` fails; `"1 2"` and `"1 2 3"` match; `"1 2 3 4"` fails.
    `match("<number>#", "1, 2, 3")` matches; `match("<number>#", "1, 2,")` fails (trailing comma).
- **findAllFragments(ast, type, name)** — collect every value fragment of a given grammar type
  across a stylesheet. Each returned fragment exposes a `nodes` List of the matched value nodes. For
  `.a { color: red; background: url(x) #fff }`, `findAllFragments(ast, "Type", "color")` returns two
  fragments whose nodes generate to `red` and `#fff`.
- **getType(name)** / **getProperty(name)** — return the resolved definition node for a known type
  (`{ type: "Type", ... }`) or property (`{ type: "Property", name }`), or `null` when unknown.
- **checkStructure(ast)** — structural validation of an AST; returns `false` when there are no
  structural errors.

### fork(extension)

**sst.fork(extension)** returns a **new** toolkit instance (`{ lexer, parse, generate, ... }`)
whose lexer is extended with caller-supplied grammars, without mutating the base toolkit. The
`extension` may contain `properties` and/or `types` maps from name → value-definition string:

```js
const custom = sst.fork({ properties: { "stack-count": "<integer>" } });
custom.lexer.matchProperty("stack-count", "42").matched   // non-null (valid)
custom.lexer.matchProperty("stack-count", "red").matched  // null (invalid)
sst.lexer.getProperty("stack-count")                  // null — base toolkit is unaffected
```

## Tokenizer

- **tokenize(source, onToken)** — call `onToken(type, start, end, index)` for every CSS token, where
  `type` is a numeric token type and `start`/`end` are offsets into `source`. For `.a { color: red }`
  the first tokens are `. ` (delim), `a` (ident), ` ` (whitespace), `{`, ` `, `color` (ident), …
  `onToken` is invoked once per concrete token that spans a slice of the source text, in order, and
  stops once the source is exhausted: it is **not** called with a terminal `<EOF-token>` after the
  last token (there is no `eof-token` entry in `tokenNames`).
- **tokenTypes** — an object mapping token names (`Ident`, `Hash`, `Delim`, …) to numeric codes.
- **tokenNames** — the inverse: index by numeric code to get the CSS token name string, e.g.
  `tokenNames[tokenTypes.Ident] === "ident-token"`, and `"hash-token"`, `"dimension-token"`,
  `"number-token"`, `"delim-token"`, `"whitespace-token"`, `"{-token"` for the corresponding tokens.

## List

`sst.List` is a doubly-linked list used for every node's `children`. It provides an Array-like
query API and a mutation API:

- Query: `size`, `isEmpty`, `first`, `last`, `toArray()`, `fromArray(array)` (returns the list),
  `forEach(fn)`, `map(fn)` (returns a new List), `filter(fn)` (returns a new List),
  `reduce(fn, init)`, `some(fn)`.
- Mutation: `appendData(data)`, `prependData(data)`, `push(data)`, `unshift(data)`,
  `shift()`/`pop()` (return the removed **item wrapper**, whose `.data` is the value),
  `insert(item, before)`, `remove(item)`.

`map`/`filter` return List instances (`.toArray()` to compare). `first`/`last` return the data
values directly.

## Value Definition Syntax API: sst.definitionSyntax

Utilities to work with the CSS **value definition** grammar language itself (the `<number>#`,
`foo | bar` mini-language), exposed as `sst.definitionSyntax`:

- **parse(source)** — parse a definition string into a definition-AST. `parse` **always returns a
  top-level `Group` node** whose `terms` array holds the parsed term(s) — even when the definition is
  a single term or a lone multiplier with no combinator — so a parsed term is always reached via
  `.terms[i]`. `parse("foo | bar")` yields a `Group` with `combinator: "|"` and two `Keyword` terms
  (`foo`, `bar`). Multipliers parse to a `Multiplier` node with `comma` (boolean), `min`, `max`
  (numbers; `max: 0` means unbounded) and a `term`; e.g. `parse("<number>#").terms[0]` is a Multiplier
  `{ comma: true, min: 1, max: 0 }` and `parse("<number>{2,4}").terms[0]` is
  `{ comma: false, min: 2, max: 4 }` (each multiplier nested as a term of the enclosing top-level
  Group). Type references parse to a `Type` node `{ type: "Type", name, opts }`.
- **walk(node, options)** — traverse a definition-AST; `options` is a function or
  `{ enter, leave }`. For `foo | bar` the enter order is the Group then each Keyword.
- **generate(node, options)** — serialize a definition-AST back to its string. `generate` of
  `parse("foo && bar || [ baz | qux ]")` reproduces `foo && bar || [ baz | qux ]`. Options:
  `forceBraces` (make every group's brackets explicit — `generate(parse("a b"), { forceBraces:
  true })` → `[ a b ]`), `compact` (omit optional spaces — `foo&&bar||baz`).

## Utility functions

- **property(name)** — analyze a declaration property name, returning
  `{ basename, name, hack, vendor, prefix, custom }`. For `*-vendor-property`:
  `basename: "property"`, `name: "-vendor-property"`, `hack: "*"`, `vendor: "-vendor-"`,
  `prefix: "*-vendor-"`, `custom: false`. For `--test-var`: `custom: true`. Names are normalized to
  lower case (except custom `--*` names, which are case-sensitive), and the function returns the
  **same frozen instance** for equal normalized inputs (`property("name") === property("NAME")`).
- **keyword(name)** — like `property` but without hack detection; returns
  `{ basename, name, vendor, prefix, custom }`. As with `property`, `basename` is the name with any
  vendor prefix removed: `keyword("-vendor-keyword")` → `basename: "keyword"`,
  `name: "-vendor-keyword"`, `vendor: "-vendor-"`, `prefix: "-vendor-"`, `custom: false`.
- **ident** — `{ decode, encode }` for CSS identifier token values.
  `ident.decode("hello\\9 \\ world")` → `"hello\t world"`; `ident.encode("hello\t world")` →
  `"hello\\9 \\ world"`.
- **string** — `{ decode, encode }` for CSS string token values. `string.decode('"hello\\9  \\"world\\""')`
  → `hello\t "world"`; `string.encode('hello\t "world"')` → `"hello\\9  \\"world\\""`; a second
  truthy argument selects single-quote output: `string.encode('hello\t "world"', true)` →
  `'hello\\9  "world"'`.
- **url** — `{ decode, encode }` for CSS url token values. `url.decode("url(file\\ \\(1\\).ext)")` →
  `file (1).ext`; `url.encode("file (1).ext")` → `url(file\\ \\(1\\).ext)`.
- **clone(ast)** — return a deep, independent copy of an AST (mutating the copy leaves the original
  unchanged).
- **fromPlainObject(object)** — convert every `children` array in a tree into a List (returns the
  tree). **toPlainObject(ast)** — the inverse (List children → arrays).

## Summary of the required public API

`parse`, `generate`, `walk` (with `.break`/`.skip`), `find`, `findLast`, `findAll`, `tokenize`,
`tokenTypes`, `tokenNames`, `lexer` (`matchProperty`, `matchType`, `match`, `matchDeclaration`,
`findAllFragments`, `getType`, `getProperty`, `checkStructure`, and match-result helpers), `fork`,
`List`, `definitionSyntax` (`parse`, `walk`, `generate`), `property`, `keyword`, `ident`, `string`,
`url`, `clone`, `fromPlainObject`, `toPlainObject` — all as named exports of `stylesheet-tree`.
