# Parsing — a parser-combinator library with invertible printing

Implement a Swift library, in a module named **`Parsing`**, for turning unstructured input into
structured data by *composing small parsers into larger ones*, with the distinguishing feature that
every parser can also be run **in reverse as a printer** (turning structured data back into the
original unstructured form).

The whole public surface is exposed by `import Parsing`. Organize the source however you like under
`Sources/Parsing/`; only the public API and its observable behavior matter.

## Environment

- Swift 6 toolchain, built in the Swift 5 language mode.
- **No external dependencies.** Only the Swift standard library and `Foundation` (used by
  `CharacterSet`, etc.) are available. Do not depend on any package.

## Core concepts

### The `Parser` protocol

A parser incrementally consumes from the front of a mutable input and produces an output:

```swift
public protocol Parser<Input, Output> {
  associatedtype Input
  associatedtype Output
  func parse(_ input: inout Input) throws -> Output
}
```

- A parser mutates `input` in place, removing the portion it consumed and leaving the remainder.
- **A failure does not rewind the input.** Whatever a parser accepted before it throws stays
  consumed — including when the rejection comes from validating what it just read (e.g. an
  accumulated number that turns out not to fit the target type). Restoring the input on failure is
  opt-in, via `Backtracking` or a combinator documented to backtrack.
- A conforming type may instead implement a computed `body` built with the `@ParserBuilder` result
  builder (below) and inherit a default `parse(_:)` that delegates to the body. Support both styles:
  a type with a `body` that is itself a parser over the same `Input`/`Output` need not implement
  `parse` directly.

Provide these ergonomic, non-mutating entry points on every parser:

- `parse(_ input: Input) throws -> Output` — parse a value without threading an `inout` variable.
- `parse<C: Collection>(_ input: C) throws -> Output where Input == C.SubSequence` — parse a whole
  collection. **This form requires the entire input to be consumed**: it behaves as if an `End`
  parser (below) were appended, so leftover input is an error.
- `parse<S: StringProtocol>(_ input: S) throws -> Output where Input == S.SubSequence.UTF8View` —
  the same, entering through the string's UTF-8 view.

The `inout` `parse(&input)` form does **not** require full consumption — it leaves whatever it did
not consume in `input`.

### The `ParserPrinter` protocol

A parser-printer additionally runs in reverse, printing an output back into input. Because printing
is the inverse of parsing, it builds the input up **in reverse** (prepending to the front):

```swift
public protocol ParserPrinter<Input, Output>: Parser {
  func print(_ output: Output, into input: inout Input) throws
}
```

Provide these conveniences:

- `print(_ output: Output) throws -> Input` when `Input` is empty-initializable (start from an
  empty input and return the printed result).
- `print(into input: inout Input)` and `print() -> Input` when `Output == Void`.

Most built-ins below are parser-printers; a few operations (`map` with a plain closure, `flatMap`,
`compactMap`) are parse-only and lose printability.

## The builder DSL

### `Parse` and `@ParserBuilder`

`Parse` is the entry point into `@ParserBuilder` syntax, where you list parsers to run one after
another:

```swift
let point = Parse(input: Substring.self) {
  "("
  Int.parser()
  ","
  Int.parser()
  ")"
}
try point.parse("(2,-4)")  // (2, -4)
```

`@ParserBuilder` rules (these are the heart of the DSL — implement them precisely):

- **Void outputs are dropped.** A parser whose `Output` is `Void` (e.g. a string literal, `Skip`)
  contributes nothing to the result. Running several parsers where only one produces a non-void
  output yields just that output (not a tuple).
- **Non-void outputs accumulate into a flat tuple, in order.** Two non-void parsers yield a
  2-tuple, three yield a 3-tuple, and so on. Accumulation **flattens**: after building up an
  `(A, B)` tuple, appending a parser with output `C` yields a flat `(A, B, C)`, never `((A, B), C)`.
  Support long tuples (at least 12 elements).
- **`if` without `else`**: a void body becomes an optionally-run void parser (still contributes
  nothing); a non-void body of output `T` makes the result optional `T?` (nil when the branch is
  skipped).
- **`if`/`else`**: produces a parser that runs one branch or the other (both branches must share
  `Input` and `Output`).
- **`Substring` ↔ UTF-8 bridging.** Inside a builder whose `Input` is `Substring`, a parser written
  against `Substring.UTF8View` (such as `Int.parser()`, `Bool.parser()`, `Digits`) is
  automatically adapted to run on the `Substring` by converting to/from its UTF-8 view. This is why
  UTF-8–oriented number parsers can be dropped straight into a `Substring` builder.

`Parse` also has forms that bake a transform into the builder:

- `Parse(input:_ transform:with:)` — apply a closure to the accumulated tuple, e.g.
  `Parse(input: Substring.self, User.init(id:name:isAdmin:)) { … }`. (Parse-only.)
- `Parse(input:_ conversion:with:)` — apply a `Conversion` (below) to the tuple; this **preserves
  printability**.

### `ParsePrint`

`ParsePrint` is like `Parse` but requires everything in the builder to be a parser-printer, so the
result is guaranteed invertible (and misuse of a non-printable operator is a compile error). It has
the same builder and `.init(_ conversion:with:)` forms:

```swift
let welcoming = ParsePrint {
  "Hello "
  Int.parser()
  "!"
}
try welcoming.parse("Hello 42!")  // 42
try welcoming.print(1729)         // "Hello 1729!"
```

### `OneOf` and `@OneOfBuilder`

`OneOf` runs a list of alternative parsers (all with the same `Input`/`Output`) and returns the
first success, backtracking the input before trying each:

```swift
let currency = OneOf {
  "€".map { Currency.eur }
  "£".map { Currency.gbp }
  "$".map { Currency.usd }
}
```

- List alternatives **most specific first**: when two alternatives can both match a prefix, the one
  that matches fewer inputs must come first.
- Support a `for … in` loop inside the builder to add a homogeneous list of alternatives.
- If every alternative fails, the failure combines all of them (see the error-format section).
- `OneOf` backtracks before each alternative but does not undo the last (successful-prefix) parser;
  full backtracking is available via `Backtracking`.

## Built-in parsers and parser-printers

### Numbers and booleans (over UTF-8 code units)

These are exposed as static factories on the standard-library types and operate on any collection
of UTF-8 code units (they print only when the input is a prependable collection):

- `Int.parser(of:radix:)` (and the same on every `FixedWidthInteger`, e.g. `UInt8`): parses an
  optional leading `+`/`-` sign (for signed types) then digits in the given `radix` (default `10`,
  which must be in `2...36`). Overflowing the type is a failure (see error format). Prints the
  decimal (or radix) text.
- `Double.parser(of:)` (the same factory exists on every `BinaryFloatingPoint &
  LosslessStringConvertible` type): parses decimal numbers, an optional fraction (including a
  leading `.`), scientific exponents
  (`e`/`E` with optional sign), hexadecimal floats (`0x…`, `0x…p…`), and case-insensitive
  `inf`/`infinity`/`nan` (with optional sign). A trailing `e`/`E` with no exponent digits is not
  consumed. Underflowing exponents yield `0`/`-0`; overflowing yield `±infinity`.
- `Bool.parser(of:)`: matches the literal text `true` or `false`; prints it back.

### `Digits`

`Digits` parses a run of ASCII digits into an `Int` (no sign):

- `Digits()` parses one or more digits; `Digits(n)` parses exactly `n` digits; `Digits(n...)` parses
  at least `n`. Failures read `expected <n> digits` / `expected at least <n> digits`.
- As a printer it **zero-pads to the minimum width** (`Digits(2).print(1)` → `"01"`,
  `Digits().print(0)` → `"0"`) and fails to print a value needing more digits than the maximum
  allows (e.g. printing `255` with `Digits(2)`).

### Substring/collection parsers

Generic over `Input: Collection` (printers require a prependable collection):

- `Prefix`: consumes a run of elements.
  - `Prefix(n)` — exactly `n` elements (fails `expected <k> more elements` if fewer remain).
  - `Prefix(while:)` — greedily while a predicate holds (minimum 0, never fails on count).
  - `Prefix(n, while:)` — exactly `n` leading elements, each satisfying the predicate (e.g.
    `Prefix(2) { $0 == "A" }`); fails (like the count minimums) when fewer than `n` satisfying
    elements are available.
  - `Prefix(n...)`, `Prefix(...n)`, `Prefix(n..., while:)`, `Prefix(...n, while:)` — bounded by a
    count range, optionally also limited by a predicate. A range minimum that can't be met fails
    `expected <k> more elements satisfying predicate`.
- `PrefixUpTo(match)` — consumes everything up to (but not including) the first occurrence of a
  given sub-sequence; fails `expected prefix up to <value>` if the match never occurs.
- `PrefixThrough(match)` — consumes everything up to and including the first occurrence.
- `Rest()` — consumes all remaining input; fails on empty input with `expected a non-empty input`.
- `End()` — succeeds only when the input is empty; otherwise fails `expected end of input`.
- `StartsWith(prefix)` — matches (and consumes) a fixed prefix; output is `Void`. The prefix may be
  any collection whose `Element` matches the input's; it need not be the input's own type.
- **String literals are parsers.** A `String` (and `String.UTF8View`, `String.UnicodeScalarView`)
  used directly in a builder is a `Void`-output parser matching that exact text; failure reads
  `expected "<literal>"`.
- `Whitespace(_:)` — consumes Unicode whitespace. A `Configuration` selects `.all` (default),
  `.horizontal` (spaces/tabs, stops at line breaks), or `.vertical` (line breaks). It never fails
  by default (minimum 0).
- `CharacterSet` (Foundation) is a parser over `Substring`: it consumes the leading run of members
  (`CharacterSet.alphanumerics`, `CharacterSet(charactersIn:)`, etc.) and never fails (may return
  an empty match).

### Input abstraction

Parsers are generic over the input type: the same parser can run on a `Substring`, its `.utf8`
view, or its `.unicodeScalars` view. `From` enters a different input domain for a sub-parser:

```swift
let p = Parse(input: Substring.UTF8View.self) {
  "caf".utf8
  From(.substring) { "é" }   // parse this fragment in the grapheme-aware Substring domain
}
```

`From(conversion) { … }` applies a `Conversion` to move into `conversion`'s output input-type, runs
the sub-parser there, and converts back. Use `.substring` and `.utf8` conversions for
UTF-8↔Substring bridging (grapheme normalization means `"é"` matches both the precomposed and
decomposed encodings when parsed in the Substring domain).

## Operators and combinators

Methods available on parsers (and, where noted, parser-printers):

- `map` — transform output. With a plain closure it is **parse-only**; with a `Conversion` it is
  **printable**; a `Void`→value closure form prints when the output is `Equatable`.
- `compactMap` — transform, treating `nil` as a parse failure. Parse-only.
- `filter` — succeed only when a predicate holds. Printable.
- `flatMap` — choose a follow-on parser from the previous output (used with `Always`/`Fail` and
  `if`/`else` for validated parses). Parse-only.
- `Many` — run an element parser repeatedly, accumulating results:
  - `Many { element } separator: { … } terminator: { … }` (separator and terminator optional).
    The terminator, when present, must match after the last element (proves full consumption).
  - Bounds: `Many(n...)` (at least n), `Many(...n)` (at most n), etc. Falling below the minimum
    fails `expected <k> more value(s) of "<T>"`; a maximum stops early.
  - `Many(into: initial, updateAccumulatingResult)` reduces into an arbitrary accumulator instead
    of an array.
  - Detects a non-consuming element parser as an **infinite loop** and fails (summary
    `infinite loop`, label `expected input to be consumed`).
  - As a printer it decumulates the collection in reverse, re-emitting separators, and enforces the
    same bounds (see printing errors).
- `Optionally { … }` — run a parser, backtracking and returning `nil` on failure; prints the
  wrapped value, or nothing for `nil`.
- `Skip { … }` — run a parser and discard its output (result `Void`); prints the parser.
- `Peek { … }` — run a parser to assert it *would* succeed, without consuming input (result `Void`).
- `Not { … }` — succeed (consuming nothing) only if the inner parser fails; otherwise fail
  `expected not to be processed`.
- `Backtracking { … }` — restore the input to where it started if the inner parser fails.
- `pipe { downstream }` — feed this parser's output as the input to a downstream parser (e.g.
  `Prefix(4).pipe { Bool.parser() }`). The downstream sub-input must be fully consumed, else fail
  `expected end of pipe`.
- `replaceError(with:)` — turn a failure into a given default value; the resulting parse cannot
  throw.
- `Always(value)` — always succeed with a value, consuming nothing. `Fail(throwing: error)` —
  always fail with the given error. Both are parser-printers.

## Conversions

`Conversion` is a reversible transform used by `map`, `From`, and the `Parse`/`ParsePrint`
conversion inits:

```swift
public protocol Conversion<Input, Output> {
  func apply(_ input: Input) throws -> Output    // parse direction
  func unapply(_ output: Output) throws -> Input // print direction
}
```

Provide these built-in conversions (as static members usable as `.name`):

- `.memberwise(Type.init)` — convert between a tuple and a struct built from a memberwise
  initializer, in both directions. This is how a `ParsePrint` produces and prints a struct:
  `ParsePrint(.memberwise(User.init(id:name:isAdmin:))) { … }`.
- `.string` — `Substring` ↔ `String` (and UTF-8-bytes ↔ `String`).
- `.substring` — UTF-8 view / unicode-scalar view ↔ `Substring`.
- `.utf8` — `Substring` ↔ its UTF-8 view.

## Enum parsers

Any enum that is `CaseIterable & RawRepresentable` (with a `String` or integer raw value) gets a
`.parser(of:)` that parses one case by matching its raw value:

```swift
enum Person: String, CaseIterable { case blob = "Blob"; case blobJr = "Blob Jr" }
Person.parser()  // parses "Blob" or "Blob Jr"
```

Cases are attempted **longest raw value first**, so `"Blob Jr"` is matched before the shorter prefix
`"Blob"`, and `-42` before `-4`. If no case matches, the failure combines all attempts.

## Error messages (the diagnostic format)

A failed parse throws an error whose textual description is a compiler-style diagnostic. Matching
this format exactly is part of the task. The single-failure shape is:

```
error: <summary>
<gutter>--> input:<line>:<column>
<line-number> | <source line>
<gutter> | <spaces>^^^ <label>
```

Rules:

- Positions are **1-based**. In the single-column form `<column>` is the column of the first
  unconsumed element; in the range form below, `C1` is the first column of the underlined span.
- `<gutter>` is spaces as wide as `<line-number>`; the `-->` line and the caret line are indented by
  it, and the separator is ` | `.
- `<summary>` is `unexpected input` for an expectation failure, or the failing error's own message
  otherwise (e.g. a thrown error's description, `infinite loop`, or
  `round-trip expectation failed`). A custom `Error` that is a `LocalizedError` renders via its
  `errorDescription`.
- `<label>` is the specific expectation, e.g. `expected integer`, `expected double`,
  `expected "true" or "false"`, `expected end of input`, `expected "<literal>"`,
  `expected <k> more elements`, `expected <k> more value(s) of "<T>"`,
  `expected not to be processed`, `expected end of pipe`, `expected prefix up to "<x>"`. A caret
  with no label omits the trailing text.
- The caret run is `^` repeated to cover the failing span (at least one), positioned under the
  failing column.
- When the failure spans a **range** on one line, the location becomes `input:L:C1-C2` (through
  column) and the carets cover the span; across lines it becomes `input:L1:C1-L2:C2`.
- The shown source line is **windowed** to the failure: at most 20 columns of context precede the
  caret, and the line is truncated to fit (~75 columns), with a leading and/or trailing `…` when
  truncated. **Trailing whitespace** on the shown line is rendered as `␣`.

Worked examples:

```
error: unexpected input
 --> input:1:5
1 | (42,blob)
  |     ^ expected integer
```

```
error: unexpected input
 --> input:1:4
1 | 123␣␣␣
  |    ^ expected end of input
```

```
error: failed to process "UInt8"
 --> input:1:1-4
1 | 1234 Hello
  | ^^^^ overflowed 255
```

When several alternatives fail:

- Failures at the **same position** are grouped under one source line, one caret line per
  expectation, with **no** banner:

  ```
  error: unexpected input
   --> input:1:1
  1 | London, Hello!
    | ^ expected "New York"
    | ^ expected "Berlin"
  ```

- Failures at **different positions** are each rendered as their own block (separated by a blank
  line), ordered **furthest-progress first**, under a banner:

  ```
  error: multiple failures occurred

  error: unexpected input
   --> input:1:4
  1 | Berkeley, Hello!
    |    ^ expected "lin"

  error: unexpected input
   --> input:1:1
  1 | Berkeley, Hello!
    | ^ expected "New "
  ```

- Multi-digit line numbers keep the gutter aligned:

  ```
  error: unexpected input
     --> input:100:6
  100 | Hello
      |      ^ expected 1 more value of "()"
  ```

## Printing round-trip errors

Printers validate that the value they are given could actually have been parsed. When it could not,
they fail with a `round-trip expectation failed` summary and an explanatory body. Match these
messages for the following cases:

- A `Many` printer given fewer values than its minimum:

  ```
  error: round-trip expectation failed

  A "Many" parser that requires at least 6 values of Int was given only 5 values to print.
  ```

- A `Digits` printer given a value with more digits than its maximum:

  ```
  error: round-trip expectation failed

  A "Digits" parser configured to parse at most 2 digits tried to print 255 (3 digits).
  ```

- An `End` printer asked to print when input remains:

  ```
  error: round-trip expectation failed

  An "End" parser-printer expected no more input, but more was printed.

  "Hello, world!"

  During a round-trip, the "End" parser-printer would have failed to parse at this remaining input.
  ```

- A `Rest` printer asked to print an empty value:

  ```
  error: round-trip expectation failed

  A "Rest" parser-printer attempted to print an empty Substring.

  During a round-trip, the "Rest" parser-printer would have failed to parse an empty input.
  ```

`Optionally`, `Skip`, `Backtracking`, `Peek`, `Not`, `PrefixUpTo`, and `PrefixThrough` are all
invertible and must round-trip cleanly when used within a printer that supplies the surrounding
context they expect (e.g. `PrefixUpTo` requires the delimiter it stops before to be printed after
it).
