# Splash — a Swift syntax highlighter

Build **Splash**, a fast, lightweight Swift-language syntax highlighter. Given a string of Swift
source code, Splash breaks it into tokens, classifies each token (keyword, type, function call,
string, number, comment, etc.), and renders the result through a pluggable *output format*. The
primary output format produces **HTML** in which every classified token is wrapped in a
`<span>` whose CSS class is the token's type.

```swift
import Splash

let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
let html = highlighter.highlight("func hello(world: String) -> Int")
// <span class="keyword">func</span> hello(world: <span class="type">String</span>) -&gt; <span class="type">Int</span>
```

## Environment & packaging

- **Language / toolchain:** Swift (Swift 5 language mode; the grader builds with a Swift 5.10
  toolchain on Linux). Only the standard library and **Foundation** are available — there are **no
  third-party dependencies** and the build runs fully offline.
- Ship a single Swift Package Manager **library module named `Splash`**, importable as
  `import Splash`. Put all library sources under `Sources/Splash/`. Do not add executable targets.
  Organize files within the module however you like.
- Everything the tests use is imported from the top-level `Splash` module (`import Splash`); do not
  require callers to import any submodule path.
- One platform note for Linux: build the delimiter character set (see *Tokenization*) so that it can
  be mutated after inverting a standard set — on Linux Foundation, calling a mutating method such as
  `remove(_:)` on the result of `CharacterSet.someSet.inverted` traps, so construct the set in a way
  that avoids mutating an inverted set in place.

## Public API

### `SyntaxHighlighter`

```swift
public struct SyntaxHighlighter<Format: OutputFormat> {
    public init(format: Format /*, grammar defaults to Swift */)
    public func highlight(_ code: String) -> Format.Builder.Output
}
```

- Generic over an **output format**. Constructed with a format value; the language grammar defaults
  to Swift (the only grammar the tests use — you do not need to expose others).
- `highlight(_:)` tokenizes the input and returns the format's output. For `HTMLOutputFormat` the
  output type is `String`.
- A single highlighter instance may be reused for many `highlight` calls.
- You are free to model the "output format / output builder" abstraction however you like, as long
  as `SyntaxHighlighter(format:)` and `highlight(_:)` behave as specified and the concrete
  `HTMLOutputFormat` below plugs into it.

### `HTMLOutputFormat`

```swift
public struct HTMLOutputFormat /*: OutputFormat*/ {
    public init(classPrefix: String = "")
}
```

Produces an HTML `String`. The rendering contract:

- Each **classified token** is emitted as `<span class="<classPrefix><type>">TEXT</span>`, where
  `<type>` is the token type's string value (see *Token types*) and `TEXT` is the token's source
  text with HTML entities escaped.
- **Consecutive tokens of the same type** (separated only by whitespace, with no differently-typed
  or plain token between them) are merged into a **single** `<span>`, with the intervening
  whitespace kept *inside* the span. E.g. `public struct` (two keywords) →
  `<span class="keyword">public struct</span>`.
- **Plain text** (source that is not a classified token — identifiers, operators, punctuation, etc.)
  is emitted verbatim (HTML-escaped), with no `<span>`.
- **Whitespace** (spaces, tabs, newlines) is preserved exactly; whitespace that falls between a
  token and following plain text or a differently-typed token is emitted between them.
- **HTML escaping** applies to token text and plain text: `&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;`
  (only these three).
- `classPrefix` (default `""`) is prepended to every generated class name, e.g. with
  `classPrefix: "splash-"` a keyword span is `<span class="splash-keyword">`.

Example:

```
highlight("Array<String>")  ->  <span class="type">Array</span>&lt;<span class="type">String</span>&gt;
```

### `MarkdownDecorator`

```swift
public struct MarkdownDecorator {
    public init(classPrefix: String = "" /*, grammar defaults to Swift */)
    public func decorate(_ markdown: String) -> String
}
```

Decorates fenced code blocks in a Markdown string with Splash-highlighted HTML. The input is split
on the triple-backtack fence ` ``` `; every *odd* segment (i.e. the content between a pair of
fences) is a code block, and every even segment is surrounding Markdown that is passed through
untouched. For each code block:

- Trim leading/trailing whitespace and newlines from the block's contents.
- If the (trimmed) block begins with `no-highlight`, drop that marker line and emit the remaining
  code **HTML-escaped but not highlighted**.
- Otherwise, highlight the code with an `HTMLOutputFormat` (using the decorator's `classPrefix`).
- Wrap the result as: `<pre class="splash"><code>` + code + `</code></pre>`.

Example:

```
Input Markdown:                       Output:
```                                   ```
struct Hello {}                       <pre class="splash"><code><span class="keyword">struct</span> Hello {}</code></pre>
```                                   ```
```

### `TokenType`

```swift
public enum TokenType: Hashable {
    case keyword, string, type, call, number, comment, property, dotAccess, preprocessing
    case custom(String)
    public var string: String { get }
}
```

`string` returns the case name for the built-in cases (`"keyword"`, `"string"`, `"type"`,
`"call"`, `"number"`, `"comment"`, `"property"`, `"dotAccess"`, `"preprocessing"`) and, for
`.custom(value)`, returns the wrapped `value` unchanged. These strings are exactly the CSS class
names used by `HTMLOutputFormat`.

## Tokenization

Break the source into a stream of **tokens** and interleaved **whitespace**:

- **Whitespace** (spaces/tabs) and **newlines** separate tokens and are preserved in the output.
- A set of **delimiter characters** — every non-alphanumeric character *except* `_`, `"`, `#`, `@`
  and `$` — also separates tokens. Two adjacent delimiters are generally emitted as separate
  single-character tokens, but a few specific pairs are merged so that multi-character operators and
  markers form one token, e.g. `//`, `/*`, `*/`, and `\(` (string-interpolation start) merge; a
  closing `)` never merges with a following delimiter; `/` merges with a following `/` or `*` but
  not with most other characters. (This mainly affects how comment markers, interpolation, and
  operators are recognized.)
- A **token** is therefore either a maximal run of "word" characters (alphanumerics plus
  `_ " # @ $`) or a (possibly merged) run of delimiter characters.

Each token is classified by trying an **ordered list of rules** and taking the **first** that
matches. The order is: **preprocessing → comment → raw string → multi-line string → single-line
string → attribute → number → type → call → key-path → property → dot-access → keyword.** A token
that matches no rule is plain text.

The classifier for a token has access to contextual information: the token's text, the previous
token, the next token, all tokens seen so far, the tokens earlier on the same line, and how many
times each token string has occurred so far. Use whatever context you need to implement the rules
below.

## Classification rules

Swift keyword/identifier knowledge is assumed; the rules below define Splash's *specific*
classification decisions (including the deliberate approximations). Worked examples show the exact
expected classification.

### Keywords (`.keyword`)

The keyword set is:

```
final class struct enum protocol extension let var func typealias init guard if else return get
throw throws rethrows for in open weak import mutating nonmutating associatedtype case switch static
do try catch as super self set true false nil override where _ default break required willSet didSet
lazy subscript defer inout while continue fallthrough repeat indirect deinit is dynamic some
convenience unowned async await actor any public internal fileprivate private
#selector #file #line #function #available
```

A keyword token is highlighted **except** in these contexts:

- **Argument labels / parameter names.** A keyword used as an argument label is not highlighted:
  `func a(for b: B)` → `for` is plain. More generally, most keywords immediately preceded by `(`,
  `,` or `>(` are treated as labels and not highlighted (the exceptions that *stay* keywords in that
  position are `self`, `let`, `var`, `true`, `false`, `inout`, `nil`, `try`). (`actor` is governed by
  its own context rule below.)
- **Declaration names.** A keyword used as the name being declared is not highlighted, whether
  escaped or not: `func get()` → `get` plain; `` func `public`() `` → `` `public` `` plain. (A token
  immediately preceded by `func` or `` ` `` is never a keyword.)
- **Optional-binding / assignment names.** `if let override = optional {}` → `override` is plain
  (a non-`self` token preceded by `let`/`var`, when not the first token on the line, is not a
  keyword).
- **Before a colon.** A keyword directly followed by `:` is not highlighted *unless* it is
  `default` (so `default:` in a switch is a keyword) or `nil`.
- **Member access.** A keyword (other than `self`/`super`) directly followed by `.` (with no
  trailing whitespace) is not highlighted.

Special keyword handling:

- `_` on its own is always a keyword (e.g. the wildcard external label in `func a(_ b: B)`, or a
  discarded binding).
- `prefix` is a keyword when immediately followed by `func`.
- `some` and `any` are keywords (opaque/existential types) but **not** when preceded by `case`
  (`case some` → `some` is plain).
- `actor` is a keyword when it declares an actor — including after an access-control keyword or an
  `@`-attribute — but is plain text when used as an ordinary identifier such as a variable name
  (`let actor = Actor()` → `actor` is plain; later `actor.position` treats `actor` as plain).
- `await` is a keyword in expressions and declarations (`await call()`, `for try await …`,
  `async let …`) but is plain text when used as a function name (`func await<T>(…)`).
- **Setter access level:** the `(set)` in `private(set)` is highlighted together with the access
  keyword — `private(set)` renders as one keyword span. (The `(`, `set`, `)` following an
  access-control keyword are keywords.)

### Attributes (`.keyword`)

Tokens beginning with `@` are attributes and are highlighted as **keywords**: `@escaping`,
`@objc`, `@NSApplicationMain`, `@propertyWrapper`. A property-wrapper application is highlighted the
same way, including generic and nested forms: `@Persisted(key: "name")` → `@Persisted` is a keyword;
`@Persisted.InMemory` → both `@Persisted` and `InMemory` are keywords; `@Wrapper<Bool>(…)` →
`@Wrapper` keyword (and `Bool` a type).

### Types (`.type`)

An identifier is a **type** when its first letter (ignoring any leading `_`) is uppercase, e.g.
`String`, `_MyType`. Exceptions — a capitalized token is **not** a type when:

- it is the **name being declared** — i.e. directly preceded by `class`, `struct`, `enum`, `func`,
  `protocol`, `typealias`, `import`, `associatedtype`, `subscript`, `init`, or `actor`
  (`struct MyStruct` → `MyStruct` is plain);
- it is reached through **dot access** (`.Foo`, or ` .Foo` at the start of a member chain);
- it belongs to the **`XCTAssert…` family** (a special case: `XCTAssertTrue` is treated as a call,
  not a type).

**Generics.** Inside a generic *parameter list* at a declaration, only the **constraints** are
highlighted as types, not the parameter names themselves:

```
func hello<A: AnyObject, B: Sequence>(a: A, b: B)
// A, B (the parameters) are plain; AnyObject, Sequence (constraints) and the later A, B used as
// parameter types are types.

struct MyStruct<A: Hello, B> {}      // Hello is a type; A, B are plain
```

Generic arguments used **outside** a parameter list — in return types, superclasses, stored-property
types, subscript key types — are highlighted normally:

```
func array() -> Array<Element> { return [] }         // Array, Element are types
class Promise<Value>: Future<Value> {}               // Value (param) plain; Future, Value (super) types
func value<T>(at keyPath: KeyPath<Element, T>) -> T? // T (param) plain; KeyPath, Element, T (uses) types
```

Types in `where`-clauses and associated-type constraints are highlighted:
`extension Hello where Foo == String, Bar: Numeric` → `Hello, Foo, String, Bar, Numeric` are types.
Dotted type names are each highlighted: `Swift.Error` → both parts are types.

### Function calls (`.call`)

- An identifier **immediately followed by `(`** is a call: `add(1, 2)`, `handler(nil)`,
  `_myFunction()`. Leading-underscore names starting with a lowercase letter are calls.
- **Trailing-closure calls:** an identifier followed by a `{` (optionally after `()`) is a call:
  `call { … }`, `call() { … }`, `call {}`. This applies even when the method name is itself a
  keyword accessed as a member: `publisher.catch { … }` → `catch` is a call. It does **not** apply
  in control-flow positions — a `{` following `if`, `for`, `switch`, `&&`, or `||` on the same line
  is not a call.
- **Initializers are never regular calls.** `init` always stays a **keyword**: `String()` →
  `String` is a type, `()` plain; `String.init()` → `String` type, `init` keyword; `.init()` →
  `init` keyword; `Task.init {}` → `init` keyword.
- **Enum cases with associated values** in a call-like position are treated as calls:
  `call(.error(error))` → `error` is a call (whereas a bare `.aCase` is *dot-access*, below). In a
  `switch` `case` pattern, an associated-value case is **not** a call (`case .one(let a)` →
  `one` is dot-access).
- A call is not highlighted when the identifier is a non-`call`-eligible keyword, or when a
  preceding keyword forbids it: the *only* keywords that allow a following call are `return`,
  `try`, `throw`, `if`, `in`, and `await` — **every other preceding keyword forbids it**.
- `String.self` → `self` is a keyword, `String` a type; `Array<String>.call()` → `call` is a call.
- The `XCTAssert…` family are calls: `XCTAssertThrowsError(try function())` → the assert name and
  `function` are calls, `try` a keyword.

### Numbers (`.number`)

Integer, floating-point (a `.` between two numeric tokens), and underscore-grouped literals
(`1_000_000`) are numbers. A token is **not** a number if the previous token ends with `$` (closure
index shorthand like `$0`).

### Strings (`.string`)

- **Single-line** `"…"`, including escaped quotes (`"Hello \" World"`). A string passed to a call
  keeps the call classification: `call("Hello, world!")`.
- **Multi-line** `"""…"""`.
- **Raw** strings `#"…"#` and `#"""…"""#`.
- **Interpolation.** Inside a normal string, `\(…)` is an interpolation: the delimiters and the
  expression inside are **not** part of the string — the expression is highlighted as ordinary code
  and the surrounding quotes/segments stay strings. This holds for custom labels (`\(label: a, b)`),
  closure shorthand (`\($0)`), bracketed contexts (`"[\(text)]"`), and nested strings
  (`"\(name ?? "name")"` → the inner `"name"` is a string). In a **raw** string, only `\#(…)` is a
  real interpolation; a plain `\(…)` inside a raw string is literal text (part of the string).

Worked example:

```
highlight("Hello \(variable) world \(call())")
// <span class="string">"Hello</span> \(variable) <span class="string">world</span> \(<span class="call">call</span>())<span class="string">"</span>
```

### Comments (`.comment`)

- `//` and `///` begin a single-line comment: the marker and the rest of the line are one comment
  run (`// Hey I'm a comment!`). This holds even with no whitespace before the marker
  (`String?//One`) or when the comment abuts punctuation (`,//TODO:`).
- `/* … */` and `/** … */` are multi-line comments spanning from the opening to the closing marker,
  inclusive, across newlines.
- Comments are isolated from the surrounding classification — a comment touching a generic list,
  initializer, protocol name, or optional/array type only colors the comment characters
  (`Box/*Start*/<Content>/*End*/` → the two `/*…*/` are comments, the rest classified normally).

### Preprocessing (`.preprocessing`)

- The conditional-compilation directives `#if`, `#endif`, `#elseif`, `#else`, **and everything else
  on the same line as one of them**, are preprocessing: `#if os(iOS)` → both `#if` and `os(iOS)`
  are preprocessing.
- The `#warning` and `#error` directive tokens are preprocessing; their parenthesized arguments are
  classified normally (`#warning("Hey!")` → `#warning` preprocessing, `"Hey!"` a string).
- Note that `#selector`, `#available`, `#file`, `#line`, and `#function` are **keywords**, not
  preprocessing.

### Properties (`.property`)

- A member accessed through `.` / `?.` (etc.) is a property: `object.property`,
  `object?.property`, `call().property`, `Enum.allCases`, `LoadingState<Output>.idle`. A member
  immediately followed by `(` is a **call**, not a property.
- **Key paths:** the component after `\.` (or `(\.`) is a property: `\.property`,
  `user.bind(\.name, to: \.text)` → `name`, `text` are properties.
- **Projected property-wrapper values:** a `$`-prefixed identifier whose second character is a
  letter is a property: `$value`, `self.$value`, `call(&$value)`.
- **Exception — `import` statements.** Members are **not** highlighted inside an `import`
  statement; the dotted module path stays plain text. `import UIKit` → only `import` is a keyword;
  `import os.log` → `import` is a keyword and `os.log` is entirely plain (neither `os` nor `log` is a
  property or dot-access). (This applies to both the property and dot-access rules: when the first
  token on the line is `import`, later `.`-separated components are not highlighted.)

### Dot access (`.dotAccess`)

A leading-dot symbol that is not otherwise a property is dot-access — typically an enum case
referenced by shorthand: `.aCase`, `call(.aCase)`, `dictionary[.key]`, and `switch` `case .one`.
`self` and `init` reached this way are not dot-access (`.init()` → `init` keyword).

## Reference behavior

The exact expected output for any input is whatever the described rules produce; when a rule is
ambiguous, the worked examples are authoritative. Aim to reproduce the classification and HTML
rendering exactly, including whitespace preservation, same-type span merging, and HTML escaping.
