# Participle --- Parser Construction Library for Go

Build `participle`, a Go library that constructs recursive-descent parsers from annotated Go struct types. Instead of writing BNF rules in a separate file, users annotate struct fields with grammar expressions via struct tags. The library uses reflection to build and run a parser at runtime. It also includes a tokenizer framework (`lexer` sub-package) supporting simple regex-based lexers, stateful lexers with push/pop state transitions, and a default lexer based on Go's `text/scanner`.

## Dependencies

- None. Pure Go standard library only (no external modules).

## Build Environment

- Go 1.22 toolchain, fully offline (no module downloads)
- Module path: `github.com/alecthomas/participle/v2`
- The `lexer` sub-package lives at `github.com/alecthomas/participle/v2/lexer`

Your `setup.sh` must build the project offline. Example:

```bash
#!/bin/bash
export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOCACHE="${GOCACHE:-/tmp/gocache}"
go build ./... || return 1
```

The `go.mod` must declare module `github.com/alecthomas/participle/v2` with `go 1.22`.

## Package Structure

```
/app/
  go.mod
  setup.sh
  *.go                  # package participle (root)
  lexer/
    *.go                # package lexer
```

The root package is `participle`. The sub-package is `lexer`. Tests import the root package as an external test package (`participle_test`).

## API Reference

### 1. Lexer Sub-Package (`participle/lexer`)

#### Core Types

| Type | Definition |
|------|-----------|
| `TokenType` | `int` (alias). Negative integers. |
| `EOF` | `TokenType = -(iota + 1)` --- the end-of-file sentinel token type. |
| `Token` | `struct { Type TokenType; Value string; Pos Position }` |
| `Position` | `struct { Filename string; Offset int; Line int; Column int }` |

`Token.String()` returns a human-readable representation. `Token.GoString()` returns a Go-syntax representation. `Token.EOF()` returns true when `Type == EOF`.

`Position.String()` returns `"line:col:"` when `Filename` is empty, or `"filename:line:col:"` when set.

`Position.Advance(span string)` mutates the position by advancing through the characters in `span`, incrementing `Line` on `\n` and resetting `Column`, otherwise incrementing `Column` and `Offset`.

`Position.Add(pos Position) Position` returns a new Position with fields summed.

#### Interfaces

```go
type Definition interface {
    Symbols() map[string]TokenType
    Lex(filename string, r io.Reader) (Lexer, error)
}

type StringDefinition interface {
    Definition
    LexString(filename, input string) (Lexer, error)
}

type BytesDefinition interface {
    Definition
    LexBytes(filename string, input []byte) (Lexer, error)
}

type Lexer interface {
    Next() (Token, error)
}
```

`Definition` maps symbol names to their `TokenType` values via `Symbols()` and creates a `Lexer` from an `io.Reader`. `StringDefinition` and `BytesDefinition` are optional fast-path interfaces.

#### Default Lexer

When no custom lexer is specified, the parser uses a default lexer based on Go's `text/scanner` package. It produces these token types:

- `Ident` --- identifiers
- `Int` --- integer literals
- `Float` --- floating-point literals
- `String` --- double-quoted string literals
- `Char` --- single-quoted character literals
- `Comment` --- comments
- Single-character punctuation tokens named by their rune (e.g., `+`, `-`, `(`, `)`, etc.)

#### Simple Lexer

For grammars that need custom tokenization via regular expressions:

```go
type SimpleRule struct {
    Name    string
    Pattern string
}

func NewSimple(rules []SimpleRule) (*StatefulDefinition, error)
func MustSimple(rules []SimpleRule) *StatefulDefinition
```

Rules are tried in order. Each `Pattern` is a Go regexp. The first matching pattern wins for each token. Since `NewSimple` returns a `*StatefulDefinition`, all stateful-lexer conventions apply to simple lexers too --- in particular, rules whose names start with a lowercase letter are automatically elided from the token stream.

#### Stateful Lexer

For grammars that need context-dependent tokenization with state transitions:

```go
type Rule struct {
    Name    string
    Pattern string
    Action  Action
}

type Rules = map[string][]Rule

func New(rules Rules) (*StatefulDefinition, error)
func MustStateful(rules Rules) *StatefulDefinition
```

Lexing starts in the `"Root"` state. Rules within each state are tried in order.

**Actions:**
- `Push(state string) Action` --- push current state onto the stack, switch to the named state.
- `Pop() Action` --- pop the state stack, return to the previous state.

**Special rules:**
- `Include(state string) Rule` --- inline all rules from the named state at this position (not a real rule, just an expansion directive).
- `Return() Rule` --- return to the parent state (pop the state stack) without consuming any input. Place it as the last rule in a sub-state; when no other rule in the state matches, `Return()` fires and the lexer resumes in the parent state.

**Auto-elision:** Rules whose names start with a lowercase letter are automatically elided from the token stream (convenient for whitespace, comments, etc.).

**Backreferences:** `\N` in a pattern (where N is a digit) matches capture group N from the rule that triggered the `Push` into the current state.

#### StatefulDefinition

`StatefulDefinition` implements `Definition`, `StringDefinition`, and `BytesDefinition`.

#### Utility Functions

```go
func Must(def Definition, err error) Definition
func ConsumeAll(lexer Lexer) ([]Token, error)
func SymbolsByRune(def Definition) map[TokenType]string
func MakeSymbolTable(def Definition, types ...string) (map[TokenType]bool, error)
func EOFToken(pos Position) Token
```

- `Must` panics on non-nil error, otherwise returns the definition.
- `ConsumeAll` reads all tokens from a lexer until EOF.
- `SymbolsByRune` returns a reverse map from `TokenType` to symbol name.
- `MakeSymbolTable` returns a set of `TokenType` values for the given type names; errors if a name is not in the definition's symbol table.

#### PeekingLexer

`PeekingLexer` wraps a `Lexer` with peek/cursor semantics. It is used by `Parseable` implementations and internally by the parser.

```go
func Upgrade(lexer Lexer, elide ...TokenType) (*PeekingLexer, error)
```

Key methods:
- `Peek() Token` --- look at the next token without consuming.
- `Next() Token` --- consume and return the next token.
- `RawPeek() Token` --- peek including elided tokens.
- `RawCursor() int` --- current raw cursor position.
- `Length() int` --- total number of raw tokens.
- `Range(start, end int) []Token` --- slice of raw tokens by index.
- `Cursor() int` --- current cursor position.

### 2. Root Package (`participle`)

#### Parser Construction

```go
func Build[G any](options ...Option) (*Parser[G], error)
func MustBuild[G any](options ...Option) *Parser[G]
```

`Build` inspects the struct type `G` using reflection, parses the grammar from its struct tags, and compiles a recursive-descent parser. `MustBuild` panics on error.

#### Parser Methods

```go
func (p *Parser[G]) Parse(filename string, r io.Reader, options ...ParseOption) (*G, error)
func (p *Parser[G]) ParseString(filename, s string, options ...ParseOption) (*G, error)
func (p *Parser[G]) ParseBytes(filename string, b []byte, options ...ParseOption) (*G, error)
func (p *Parser[G]) ParseFromLexer(lex *lexer.PeekingLexer, options ...ParseOption) (*G, error)
func (p *Parser[G]) String() string
func (p *Parser[G]) Lexer() lexer.Definition
func (p *Parser[G]) Lex(filename string, r io.Reader) ([]lexer.Token, error)
```

- `Parse`, `ParseString`, `ParseBytes` --- parse input into a `*G`. Return error on parse failure.
- `ParseFromLexer` --- parse from a pre-built `PeekingLexer`.
- `String()` --- return an EBNF-like representation of the compiled grammar.
- `Lexer()` --- return the parser's lexer definition.
- `Lex()` --- tokenize input using the parser's lexer, with all configured token transformations (`Upper`, `Map`, `Unquote`) applied to token values.

#### Struct Tag Grammar Syntax

The grammar is specified via struct field tags. The tag value is either the entire struct tag content (`` `@Ident` ``) or a named `parser` tag (`` `parser:"@Ident" json:"name"` ``).

**Expressions:**

| Syntax | Meaning |
|--------|---------|
| `@<expr>` | Capture: evaluate `<expr>` and assign result to this field |
| `@@` | Recursive capture: parse into this field's own struct type |
| `<Identifier>` | Match a token whose type name is `Identifier` |
| `"literal"` | Match a token whose value is `literal` (double-quoted) |
| `'literal'` | Match a token whose value is `literal` (single-quoted) |
| `"literal":Identifier` | Match a token with value `literal` AND type `Identifier` |
| `( ... )` | Grouping |
| `expr1 \| expr2` | Alternation: try `expr1` first, backtrack and try `expr2` on failure |
| `~expr` | Negation: succeed only if `expr` does NOT match at the current position, then consume and return one token. If `expr` does match, the negation fails. |
| `(?= ...)` | Positive lookahead: assert `...` matches without consuming tokens |
| `(?! ...)` | Negative lookahead: assert `...` does NOT match, without consuming tokens |

**Repetition modifiers** (appear AFTER an expression):

| Modifier | Meaning |
|----------|---------|
| `*` | Zero or more |
| `+` | One or more |
| `?` | Zero or one |
| `!` | Require non-empty match |

`~` negates only the single term immediately following it, so a modifier written after a negation applies to the negation as a whole --- `~expr*` means zero or more repetitions of `~expr`, not a negation of `expr*`.

**Cross-field concatenation:** The grammar tags across all fields of a struct are concatenated in declaration order to form a single grammar expression. In the example below, `Expression`'s three fields combine into the expression `@@ ( @( "+" | "-" ) @@ )?`.

**Example grammar:**

```go
type Expression struct {
    Left  *Term     `@@`
    Op    string    `( @( "+" | "-" )`
    Right *Term     `  @@ )?`
}

type Term struct {
    Name   *string  `  @Ident`
    Number *float64 `| @Float`
}
```

#### Capture Semantics

When `@` captures a matched token's value into a struct field, the behavior depends on the field's type:

| Field Type | Capture Behavior |
|------------|-----------------|
| `string` | Assigned the token's text value. Multiple `@` captures on the same string field **concatenate**. When `@(group)` captures multiple tokens, their text values are concatenated into a single string. |
| `[]string` | Each capture appends to the slice. |
| `int`, `int8`, `int16`, `int32`, `int64` | Parsed via `strconv.ParseInt(value, 0, bitSize)`. The `0` base means `0x` hex, `0o` octal, `0b` binary prefixes are supported. |
| `[]int`, `[]int8`, etc. | Each capture is parsed as the element type and appended to the slice. |
| `uint`, `uint8`, `uint16`, `uint32`, `uint64` | Parsed via `strconv.ParseUint(value, 0, bitSize)`. |
| `float32`, `float64` | Parsed via `strconv.ParseFloat(value, bitSize)`. |
| `[]float32`, `[]float64` | Each capture is parsed as the element type and appended to the slice. |
| `bool` | Set to `true` when the expression matches. This is NOT parsing the literal strings "true"/"false" --- it acts as a flag indicating the branch was taken. |
| `*T` (pointer to struct) | A new `T` is allocated when the match succeeds. Remains `nil` when the optional expression does not match. |
| `[]*T` (slice of struct pointers) | Each successful match appends a new `*T`. |
| `lexer.Token` | Captures the raw `Token` value (type, value, position). |
| `[]lexer.Token` | Captures all matched tokens. |
| Types implementing `Capture` | Custom capture via the `Capture` interface. |
| Types implementing `encoding.TextUnmarshaler` | Captured via `UnmarshalText()`, called once per captured token. |

**Grouped capture concatenation applies to all scalar types, not just strings.** When `@(group)` captures multiple tokens into any scalar field (`int`, `float64`, etc.), the token text values are first concatenated into a single string, then the type-specific conversion (e.g., `strconv.ParseInt`) is applied to the concatenated result. For example, `@("-"? Int)` on an `int` field concatenates `"-"` and `"42"` into `"-42"` and then parses it as an integer.

#### Auto-Populated AST Fields

Certain field names have special meaning and are automatically populated without any grammar tag:

| Field | Type | Behavior |
|-------|------|----------|
| `Pos` | `lexer.Position` | Set to the position of the **first** token matched by this struct node. |
| `EndPos` | `lexer.Position` | Set to the position just **after** the last token matched by this struct node. |
| `Tokens` | `[]lexer.Token` | Populated with **all** tokens consumed by this node, including elided tokens (e.g., whitespace that was elided from the parser but is still available here). |

These fields must not have grammar tags --- they are filled in automatically.

#### Build Options

Options passed to `Build` or `MustBuild`:

| Option | Description |
|--------|-------------|
| `Lexer(def lexer.Definition)` | Use a custom lexer instead of the default `text/scanner`-based one. |
| `UseLookahead(n int)` | Set n-token lookahead for alternation (default 1). Negative values enable unbounded lookahead. |
| `Elide(types ...string)` | Remove the named token types from the parser's token stream. Elided tokens still appear in the `Tokens` auto-populated field. |
| `Map(mapper Mapper, symbols ...string)` | Transform tokens of the specified types before parsing. `Mapper` is `func(token lexer.Token) (lexer.Token, error)`. If no symbols are given, maps all tokens. |
| `Unquote(types ...string)` | Apply `strconv.Unquote` to token values. If no types specified, defaults to the `"String"` token type. |
| `Upper(types ...string)` | Uppercase token values of the specified types before matching. |
| `CaseInsensitive(tokens ...string)` | Match literals case-insensitively for the specified token types. |

#### Union Types

```go
func Union[T any](members ...T) Option
```

Register a union (sum) type. `T` must be an interface type. The `members` are concrete struct types (or pointers to structs) that implement `T`. When the parser encounters a field of type `T`, it tries each member in declaration order and uses the first one that matches.

The dynamic type stored in the union-typed field mirrors the kind of the matched member as it was registered: a member registered as a value struct (e.g. `unionAIdent{}`) is stored as a value (`unionAIdent`), while a member registered as a pointer (e.g. `&unionAIdent{}`) is stored as a pointer (`*unionAIdent`). A subsequent type assertion or type switch on the field therefore recovers the member with the same value/pointer kind it was registered with.

#### Parse Options

Options passed to `ParseString`, `Parse`, etc.:

| Option | Description |
|--------|-------------|
| `AllowTrailing(ok bool)` | If true, do not error when there are unconsumed tokens after parsing completes. |
| `Trace(w io.Writer)` | Write a trace of the parse process to `w`. |

#### Interfaces

```go
type Capture interface {
    Capture(values []string) error
}
```

Implement on a type to customize how captured token values are stored. The `values` slice contains all captured token strings.

```go
type Parseable interface {
    Parse(lex *lexer.PeekingLexer) error
}
```

Implement on a struct type to take full control of parsing for that node. The parser calls `Parse` instead of using struct tags. Return `NextMatch` to indicate no match (allowing the parser to try alternatives).

#### Error Types

```go
type Error interface {
    error
    Message() string
    Position() lexer.Position
}

type ParseError struct {
    Msg string
    Pos lexer.Position
}

type UnexpectedTokenError struct {
    Unexpected lexer.Token
    Expect     string
}
```

Both `ParseError` and `UnexpectedTokenError` implement the `Error` interface.

**Error helpers:**

```go
func Errorf(pos lexer.Position, format string, args ...any) Error
func Wrapf(pos lexer.Position, err error, format string, args ...any) Error
func FormatError(err Error) string
```

`FormatError` produces `"filename:line:col: message"` (omitting filename if empty).

#### Constants and Sentinels

```go
var NextMatch = errors.New("next match")  // returned by Parseable.Parse to signal no match
const MaxLookahead = 99999                // pseudo-infinite lookahead value
```

#### Sub-Parser Extraction

```go
func ParserForProduction[P, G any](parser *Parser[G]) (*Parser[P], error)
```

Extract a parser for a specific production (struct type `P`) from a compiled parser for `G`.

### 3. EBNF Output Format

`Parser.String()` returns an EBNF representation of the grammar. The format:

- Each struct type becomes a production on a single line: `ProductionName = expr .` (productions may be separated by blank lines).
- Production names are title-cased versions of the Go struct type names (e.g., `grammar` becomes `Grammar`, `inner` becomes `Inner`).
- Lexer token type names appear in angle brackets, fully lower-cased: `<ident>`, `<int>`, `<string>`.
- Literal matches appear as quoted strings: `"+"`, `"if"`.
- Alternation: `|`
- Modifiers: `*`, `+`, `?`, `!` (same as tag syntax)
- Negation: `~`
- Lookahead: `(?= ...)`, `(?! ...)`
- Grouping: `( ... )`

Union interface types also generate productions, named by title-casing the interface type name (e.g., `testUnionA` becomes `TestUnionA`). The body of a union production is the alternation of its registered member productions.

Within a production body, sequence terms are separated by single spaces and a repetition/optional modifier (`*`, `+`, `?`, `!`) is appended directly to its operand (e.g. `Atom*`).
