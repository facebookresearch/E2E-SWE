# Expression — a runtime expression engine for Swift

Build a small, dependency‑free Swift library that parses and evaluates mathematical
(and, optionally, arbitrarily‑typed) expressions **at runtime** from a string such as
`"5 + 6"` or `"foo ? bar : baz"`. It is conceptually similar to Foundation's
`NSExpression`, but with first‑class support for custom operators/functions, a
Swift‑friendly API, an optimizer, and detailed error reporting.

The library has two layers:

1. **`Expression`** — evaluates an expression to a `Double`. This is the core engine
   (tokenizer, parser, optimizer, evaluator, standard math/boolean library).
2. **`AnyExpression`** — built on top of `Expression`, evaluates to arbitrary Swift
   values (`Double`, `String`, `Bool`, `Array`, `Dictionary`, `Range`, `Optional`, …).

Everything below is the public contract your implementation must satisfy. *How* you
implement the tokenizer, parser and optimizer is up to you.

---

## Packaging & build requirements

* Ship a **Swift Package Manager** package whose library code is a single module named
  **`Expression`**, importable with `import Expression`. Put all library sources under
  `Sources/` (a single module/target). Everything the contract describes below must be
  declared `public`.
* No third‑party dependencies. Foundation is allowed.
* Both the `Expression` and `AnyExpression` types live in the `Expression` module.
* The package must build offline with `swift build`.

The grading harness compiles your `Sources` into a module named `Expression` and runs a
hidden XCTest suite that does `import Expression` and exercises only the public API
described here.

---

# Part 1 — `Expression`

```swift
public final class Expression: CustomStringConvertible {
    public typealias SymbolEvaluator = (_ args: [Double]) throws -> Double
    public var description: String { get }   // normalized form (see “Description”)
    public var symbols: Set<Symbol> { get }  // symbols still referenced after optimization
    public func evaluate() throws -> Double
}
```

## Symbols

```swift
public enum Symbol: Hashable, CustomStringConvertible {
    case variable(String)              // a named constant/variable identifier
    case infix(String)                 // binary operator: a OP b
    case prefix(String)                // prefix operator: OP a
    case postfix(String)               // postfix operator: a OP
    case function(String, arity: Arity)// name(args…)
    case array(String)                 // name[index]

    public var name: String { get }    // the underlying string for any case
    public var description: String { get }
}
```

`Symbol.description` is used inside error messages and must be exactly:

| case | `description` |
|---|---|
| `.variable("foo")`  | `variable foo` |
| `.infix("+")`       | `infix operator +` |
| `.prefix("-")`      | `prefix operator -` |
| `.postfix("%")`     | `postfix operator %` |
| `.function("foo", …)` | `function foo()` |
| `.array("foo")`     | `array foo[]` |
| `.infix("?:")`      | `ternary operator ?:` |
| `.infix("[]")`      | `subscript operator []` |
| `.infix("()")`      | `function call operator ()` |

(The name shown is the *escaped* identifier — for ordinary identifiers/operators this is
just the name itself; quoted identifiers keep their surrounding quotes.)

### Arity

```swift
public enum Arity: ExpressibleByIntegerLiteral, Hashable, CustomStringConvertible {
    case exactly(Int)
    case atLeast(Int)
    public static let any = Arity.atLeast(0)
    // integer literals create `.exactly`, e.g. `.function("f", arity: 2)`
}
```

`Arity.description`: `.exactly(n)` → `"n argument"` (n == 1) or `"n arguments"`;
`.atLeast(n)` → `"at least n argument(s)"` (same singular/plural rule).

**Arity equality is asymmetric/containment‑like:** an `.atLeast(min)` is considered equal
to an `.exactly(v)` when `v >= min` (and vice‑versa). Two `.exactly` (or two `.atLeast`)
are equal iff their integers match. This is what lets a call `f(x)` match a variadic
symbol `.function("f", arity: .atLeast(1))` stored in a dictionary, and it must hold for
`Symbol`/`Error` equality too. (All `Arity` values hash equal, so equality alone
distinguishes them.)

### Options

```swift
public struct Options: OptionSet {
    public init(rawValue: Int)
    public static let noOptimize: Options    // disable the optimizer
    public static let boolSymbols: Options   // enable the standard boolean library
    public static let pureSymbols: Options    // treat user `symbols` as pure (inlinable)
}
```

### Errors

```swift
public enum Error: Swift.Error, CustomStringConvertible, Equatable {
    case message(String)              // application-specific / formatted message
    case unexpectedToken(String)
    case missingDelimiter(String)
    case undefinedSymbol(Symbol)
    case arityMismatch(Symbol)
    case arrayBounds(Symbol, Double)
    public static let emptyExpression = Error.unexpectedToken("")
}
```

`Error.description` must be exactly:

| case | `description` |
|---|---|
| `.message(m)` | `m` |
| `.emptyExpression` | `Empty expression` |
| `.unexpectedToken(s)` | `` Unexpected token `s` `` |
| `.missingDelimiter(s)` | `` Missing `s` `` |
| `.undefinedSymbol(sym)` | `Undefined <sym.description>` |
| `.arityMismatch(sym)` | `<Sym.description, first letter capitalized> expects <arity>` |
| `.arrayBounds(sym, i)` | `Index <i> out of bounds for <sym.description>` |

For `.arityMismatch`, the arity shown is the symbol's *expected* arity: a function's own
arity; `1` for `.array`/`.postfix`/`.prefix`/`.infix("[]")`; `2` for other `.infix`;
`3` for `.infix("?:")`; `at least 1` for `.infix("()")`; `0` for `.variable`. Numbers in
messages render as integers when integral (e.g. `3`, not `3.0`). Example:
`Error.arityMismatch(.function("foo", arity: 1)).description == "Function foo() expects 1 argument"`.

## Construction

```swift
// Primary
public convenience init(_ expression: String,
                        options: Options = [],
                        constants: [String: Double] = [:],
                        arrays: [String: [Double]] = [:],
                        symbols: [Symbol: SymbolEvaluator] = [:])

// From a pre-parsed expression (same defaults)
public convenience init(_ expression: ParsedExpression,
                        options: Options = [],
                        constants: [String: Double] = [:],
                        arrays: [String: [Double]] = [:],
                        symbols: [Symbol: SymbolEvaluator] = [:])

// Advanced: dynamic symbol resolution.
public init(_ expression: ParsedExpression,
            impureSymbols: (Symbol) -> SymbolEvaluator?,
            pureSymbols: (Symbol) -> SymbolEvaluator? = { _ in nil })

public convenience init(_ expression: ParsedExpression,
                        pureSymbols: (Symbol) -> SymbolEvaluator?)
```

Resolution order for a symbol during evaluation: a matching entry in `symbols`
(or returned by the `impureSymbols`/`pureSymbols` closures) wins; otherwise the standard
math library; otherwise, if `.boolSymbols` is set, the standard boolean library;
otherwise an error is produced. In the advanced initializer, returning `nil` from both
closures falls back to the standard libraries; to *disable* the standard libraries, return
a throwing evaluator instead of `nil`.

**Default `options` is `[]`** — i.e. the optimizer is ON and boolean symbols are OFF
unless you pass `.boolSymbols`.

## Parsing & caching

```swift
public static func parse(_ expression: String, usingCache: Bool = true) -> ParsedExpression

public struct ParsedExpression {}   // opaque; returned by `parse`, accepted by the initializers
```

Parsed expressions are cached by source string by default (`usingCache: false` opts out).
Parse errors are *deferred*: parsing never throws — a malformed expression surfaces its error
from `evaluate()`.

## Tokenizer rules

* **Numbers**: decimal integers and floats, a leading decimal point (`.5`), scientific
  notation (`1.5e2`, `2E-3`), and hexadecimal (`0xFF`). A malformed numeric prefix such as
  `0x` or `1e` is a parse error.
* **Identifiers**: begin with a letter, `_`, `$`, `@`, or `#`, followed by letters, digits,
  or the same starter set; unicode letters are allowed. Identifiers may contain `.` as an
  internal separator (`foo.bar` is one identifier) and may *end* with a single `'`. Quoted
  identifiers delimited by `'`, `"`, or `` ` `` may contain any character (escapes with `\`
  are decoded, but the surrounding quotes are retained in the name).
* **Operators**: one or more operator characters. `,` is an operator but cannot combine
  with other characters. Brackets `()[]{}` are reserved. Whether an operator binds as
  prefix/infix/postfix is disambiguated by the surrounding whitespace (Swift‑style):
  `a - b` is infix, `a -b`/`-a` is prefix, `a- ` is postfix, etc. This whitespace pattern
  only gives a *tentative* fixity; the parser reconciles by position, so an operator that
  ends up **between two operands always binds as infix** regardless of asymmetric spacing
  (e.g. `6 * 2 +1` parses like `6 * 2 + 1`). A prefix or postfix reading is kept
  only where an infix one is impossible — a leading or operator‑following position for prefix
  (`-a`, `a * -b`), an operand with no following operand for postfix (`a- `). Any identifier
  may also be used as an infix or postfix operator (e.g. `true or false`, `5 ms`).

## Operator precedence

Operators bind according to the table below (each row is one precedence level; **lower
rows bind tighter**). Within a level, evaluation is left‑associative unless the row is
marked right‑associative.

| Level (loosest → tightest) | Operators | Assoc. |
|---|---|---|
| comma | `,` | left |
| assignment | `=` `*=` `/=` `%=` `+=` `-=` `<<=` `>>=` `&=` `^=` `\|=` `:=` | right |
| ternary | `?` `:` | left |
| or | `\|\|` `or` | left |
| and | `&&` `and` | left |
| comparison | `<` `<=` `>=` `>` `==` `!=` `<>` `===` `!==` `lt` `le` `lte` `gt` `ge` `gte` `eq` `ne` | **right** |
| null‑coalescing | `??` `?:` | left |
| casting | `is` `as` `isa` | left |
| range | `..` `...` `..<` | left |
| additive (default) | `+` `-` `\|` | left |
| multiplicative | `*` `/` `%` `&` | left |
| exponent | `^` | left |
| bitshift | `<<` `>>` `>>>` | left |
| subscript | `[]` | left |

Any operator **not** in the table (including all user‑defined operators) takes the
**additive** precedence/associativity. Prefix operators bind tighter than postfix, which
bind tighter than any infix operator. The ternary `a ? b : c` is parsed as a single infix
operator `?:` taking three arguments.

## `description` (normalized form)

`description` renders the parsed (and optimized) expression canonically:

* infix operators are surrounded by single spaces (`a+b` → `a + b`); `,` renders as `, `;
* prefix/postfix operators attach to their operand with no space (`-foo`, `foo%`);
* parentheses are inserted **only** where required to preserve the parse, and redundant
  parentheses are dropped (`(a+b)+c` → `a + b + c`, but `(a+b)*c` → `(a + b) * c`);
* nesting that needs grouping is parenthesized (`- -foo` → `-(-foo)`, `foo% !` → `(foo%)!`);
* a folded constant renders as its numeric value (integral → no decimal):
  `32 + 200014` → `200046`, `2.4 + 7.65` → `10.05`.

## `symbols`

`symbols` returns the set of symbols still referenced **after optimization**. A fully
constant‑folded expression has an empty set. Example:
`Expression("mod(foo, bar)", symbols: [.variable("foo"): …, .variable("bar"): …]).symbols`
equals `[.function("mod", arity: 2), .variable("foo"), .variable("bar")]`.

## Optimizer

With the optimizer on (the default):

* `constants` and `arrays` values are **always** inlined to their literal value.
* A standard‑library (or user) **pure** function/operator whose arguments are all constant
  is folded to its result. Standard math and boolean symbols are pure.
* **Variables and array symbols** supplied via `symbols` are **never** inlined (they may
  change between evaluations).
* User entries in `symbols` are treated as *potentially impure* and are **not** folded
  unless you pass `.pureSymbols` (then non‑variable/array user symbols may be folded).
* Overriding a standard symbol via `symbols` makes it user‑supplied — it is no longer
  folded unless `.pureSymbols` is set.
* `.noOptimize` disables all of the above; `symbols`/`description` then reflect the raw
  parse (`Expression("3 * 5", options: .noOptimize).description == "3 * 5"`).

## Standard math library (always available)

* constant: `pi`
* infix: `+` `-` `*` `/` `%` (`%` and `mod` use floating‑point remainder, `fmod`)
* prefix: `-`
* unary functions: `sqrt ceil floor round cos acos sin asin tan atan abs log`
* binary functions: `pow(x,y) atan2(x,y) mod(x,y)`
* variadic functions: `max(x,y,…) min(x,y,…)` (each `arity: .atLeast(2)`)

`/` by zero yields `Double.infinity` (IEEE semantics). Note `^` appears in the precedence
table but has **no** default implementation — using it without supplying an `.infix("^")`
symbol is an undefined‑symbol error.

Functions may be **overloaded by arity** (e.g. supply `.function("pow", arity: 1)` and the
built‑in `pow/2` still works). Calling a known function name with an unsupported argument
count raises `.arityMismatch` with the *expected* arity.

## Standard boolean library (only with `.boolSymbols`)

Follows the C convention (`0` is false, any non‑zero is true); comparisons/logic return
`1`/`0`. There is **no** short‑circuiting.

* constants: `true` (1), `false` (0)
* infix: `==` `!=` `>` `>=` `<` `<=` `&&` `||`
* prefix: `!`
* ternary `?:`: three‑argument form `a ? b : c` returns `b` if `a != 0` else `c`; a
  two‑argument form `a ?: b` returns `a` if `a != 0` else `b`.

## Validation helpers

```swift
public static func isValidIdentifier(_ string: String) -> Bool
public static func isValidOperator(_ string: String) -> Bool
```

`isValidIdentifier` is true for a string that is exactly one identifier token (e.g. `foo`,
`foo.bar`, `foo'`, unicode, quoted forms) and false otherwise (e.g. `"foo bar"`, an empty
string, a bare operator). `isValidOperator` is true for a string that is exactly one
operator token, including `,` and `:` — and false for `(`, `[`, an identifier, or an empty
string.

---

# Part 2 — `AnyExpression`

```swift
public struct AnyExpression: CustomStringConvertible {
    public typealias SymbolEvaluator = (_ args: [Any]) throws -> Any
    public typealias Symbol = Expression.Symbol
    public typealias Error  = Expression.Error
    public typealias Options = Expression.Options

    public init(_ expression: String,
                options: Options = .boolSymbols,
                constants: [String: Any] = [:],
                symbols: [Symbol: SymbolEvaluator] = [:])

    public init(_ expression: ParsedExpression,
                options: Options = [],
                constants: [String: Any] = [:],
                symbols: [Symbol: SymbolEvaluator] = [:])

    public init(_ expression: ParsedExpression,
                impureSymbols: (Symbol) -> SymbolEvaluator?,
                pureSymbols: (Symbol) -> SymbolEvaluator? = { _ in nil })
    public init(_ expression: ParsedExpression, pureSymbols: (Symbol) -> SymbolEvaluator?)

    public func evaluate<T>() throws -> T
    public var symbols: Set<Symbol> { get }
    public var description: String { get }
}
```

`AnyExpression` reuses the same parser, precedence and symbol model as `Expression`. It
differs as follows:

* symbol evaluators take and return `Any`;
* the **boolean library is enabled by default** (note the `options` default above);
* there is no separate `arrays:` argument — pass arrays/dictionaries through `constants`;
* `constants` may hold any Swift value, including arrays, slices, dictionaries, ranges,
  string indices, `Optional`, `NSNull`, and even `SymbolEvaluator` closures.

## Result typing — `evaluate<T>()`

`evaluate()` returns the requested type, applying lenient conversions:

* `T` → `Optional<T>`
* numeric → numeric (e.g. `Double` result requested `as Int` truncates; `Int8`, `CGFloat`,
  etc. all work) — `AnyExpression("57.5").evaluate() as Int == 57`, `as Double == 57.5`;
* `Bool` → numeric and numeric → `Bool` (`0` is false, non‑zero true) —
  `AnyExpression("5 > 4").evaluate() as Double == 1.0`, `AnyExpression("0.6").evaluate() as Bool == true`;
* `Array<numeric>` → `Array<numeric>`;
* any value → `String` (its stringified form).

Numeric precision is preserved end‑to‑end: large integer constants such as `UInt64.max`
survive a pass‑through expression (`AnyExpression("true ? a : b", constants: ["a": UInt64.max, …]).evaluate() == UInt64.max`).
Requesting an incompatible type (e.g. a `String` result `as Bool`) throws.

## Literals & values

* **Strings**: single‑ or double‑quoted literals (`'foo'`, `"foo"`).
* **`+` is overloaded**: numeric addition for numbers, **concatenation** for strings, and
  **array concatenation** for arrays. When either side of `+` is a string, the other side
  is stringified and the two are concatenated: `"5 + 'foo'"` → `"5foo"`, `"'foo' + 5"` →
  `"foo5"`, `"'foo' + 5.1"` → `"foo5.1"`, `"'foo' + true"` → `"footrue"`,
  `"'foo' + 'bar'"` → `"foobar"`. Stringification renders integral numbers without a
  trailing `.0`.
* **Array literals**: `[1, 2, 3]`, `['a', 'b', 'c']`, mixed/sub‑expressions allowed.
  Indexing: `[1,2,3][1] == 2`. Concatenation: `[1,2] + [3,4] == [1,2,3,4]`.
* **Subscripting** with `[]` works on arrays, array slices, strings, and dictionaries.
  Array/string indices are integer; dictionary keys may be any `Hashable` (with numeric key
  coercion, so an `Int` key matches a `Double` index and vice‑versa). Out‑of‑range array
  access throws `.arrayBounds`.
* **Ranges**: `1 ... 3` and `1 ..< 3` produce `ClosedRange`/`Range`; partial ranges
  (`...n`, `..<n`, `n...`) are supported; ranges over `Int` or `String.Index` can slice
  arrays and strings.
* **Optionals / null**: `nil` is a literal; `??` is null‑coalescing (`a ?? b` yields `b`
  when `a` is nil, else `a`); `NSNull` and (implicitly‑unwrapped / doubly‑) optionals are
  treated as `nil`; `x == nil` works. Reaching a `nil` where a concrete value is required
  (e.g. `nil + 'bar'`) throws.

## Comparisons

`==`/`!=` work for any `Hashable` values, including `String`, arrays and dictionaries
(`["hello","world"] == ["hello","world"]` is true). `NaN == NaN` is false and
`NaN != NaN` is true. Boolean operators (`&&`, `||`, `!`) return `Bool`.

## Anonymous functions

A value that is an `Expression.SymbolEvaluator` or `AnyExpression.SymbolEvaluator` may be
**called** by applying the function‑call operator `()` to it — the first operand is the
callee and the rest are the arguments. This makes higher‑order use possible:

```swift
let add: Expression.SymbolEvaluator = { $0[0] + $0[1] }
let e = AnyExpression("foo()(1, 2)", options: .pureSymbols,
                      symbols: [.function("foo", arity: 0): { _ in add }])
try e.evaluate() == 3
```

## Errors

`AnyExpression` reuses `Expression.Error`. Undefined symbols, arity mismatches, and array
out‑of‑bounds use the same cases as `Expression`. Type errors (subscripting a non‑array,
comparing non‑Hashables, mismatched range endpoints, a `nil` used as a value, an
incompatible result type, etc.) are reported by **throwing** an error from `evaluate()`.

---

## Quick examples

```swift
import Expression

try Expression("5 + 6").evaluate()                       // 11
try Expression("2 + 3 * 4").evaluate()                   // 14
try Expression("foo + bar", constants: ["foo": 4, "bar": 5]).evaluate()   // 9
try Expression("baz(5)", symbols: [.function("baz", arity: 1): { $0[0] + 1 }]).evaluate() // 6
try Expression("5 > 3 ? 10 : 20", options: .boolSymbols).evaluate()       // 10
Expression("(a + b) * c").description                    // "(a + b) * c"

try AnyExpression("'hello' + ' world'").evaluate() as String   // "hello world"
try AnyExpression("['a','b','c'][1]").evaluate() as String     // "b"
try AnyExpression("foo ?? 'bar'", constants: ["foo": nil as Any]).evaluate() as String  // "bar"
```
