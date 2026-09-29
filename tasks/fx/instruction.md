# fx

Build **fx**, a toolkit for working with **spreadsheet (Excel-style) formulas**: a tokenizer, a
parser that produces an AST, a formula/token stringifier, parsers and stringifiers for A1, R1C1, and
structured (table) references, and utilities for column-letter conversion, range normalization, and
translating references between A1 and R1C1 notation. Implement the semantics described below; you
have no network access.

## Runtime & packaging

- Node 20. **No runtime dependencies** and no build/transpile step are required. No network access.
- Deliverables under `/app`:
  1. A CommonJS module at **`/app/fx.js`** whose export **is the fx API object** — i.e.
     `const fx = require("/app/fx.js")` must work and expose all the named exports below (e.g.
     `fx.tokenize`, `fx.parse`, …). You may split your implementation across files under `/app` and
     `require` them from `/app/fx.js`.
  2. A **`/app/setup.sh`** that is **run via `bash ./setup.sh`** (offline) before the tests run.
     This module has no build step, so it can be a no-op (`:`).

Results are compared by their **JSON-normalized structure** (the observable shape), so you may
represent tokens / AST nodes / reference objects with any internal object type.

## `tokenize(formula: string, options?): Token[]`

Split a formula string into an array of tokens. A **Token** is `{ type: string, value: string }`
where `value` is the exact source substring. Two conditional extra fields:

- with `options.withLocation === true`, each token also has `loc: [start, end]` (0-based; `end` is
  the index of the first character **after** the token).
- an **unterminated** string token also has `unterminated: true`.

**Token `type` values** (accessible as named constants on `tokenTypes`, e.g.
`tokenTypes.REF_RANGE === "range"`):

| type string | `tokenTypes` key | produced for |
|---|---|---|
| `"fx_prefix"` | `FX_PREFIX` | a leading `=` |
| `"operator"` | `OPERATOR` | `+ - * / ^ & = < > <= >= <> : , % # @ ( ) { } ; !` |
| `"number"` | `NUMBER` | a numeric literal |
| `"string"` | `STRING` | a `"…"` string |
| `"bool"` | `BOOLEAN` | `TRUE` / `FALSE` |
| `"error"` | `ERROR` | an error literal (`#REF!`, `#VALUE!`, …) |
| `"func"` | `FUNCTION` | a name immediately followed by `(` |
| `"range"` | `REF_RANGE` | an A1 (or R1C1, with `r1c1:true`) cell/range |
| `"range_named"` | `REF_NAMED` | a defined name (identifier that is not a function call) |
| `"structured"` | `REF_STRUCT` | a structured/table reference |
| `"context"` | `CONTEXT` | an unquoted sheet/workbook prefix |
| `"whitespace"` | `WHITESPACE` | a run of spaces |

**Options** (defaults in parentheses):

- `withLocation` (`false`) — attach `loc` arrays (above).
- `mergeRefs` (`true`) — merge a `context` + `!` + `range` (+ `:` + `range`) run into a single
  `range` token whose `value` is the whole reference (e.g. `Sheet1!A1:B2`). With `mergeRefs:false`
  those parts stay as separate `context`/`operator`/`range` tokens.
- `negativeNumbers` (`true`) — fold a unary minus into the following number so `=-1` yields a single
  `{type:"number", value:"-1"}`. A minus that is **binary** (between two values, e.g. `=1-1`) stays a
  separate `operator` token.
- `r1c1` (`false`) — read ranges in R1C1 notation (so `R[-1]C` is one `range` token).

## `parse(tokens: Token[], options?): Node`

Parse a **token array** (call `tokenize` first) into an AST node; throws on invalid syntax. Leading
whitespace and the `fx_prefix` token are ignored. **Node** types (string in `type`; the same strings
are exposed on `nodeTypes`, e.g. `nodeTypes.CALL === "CallExpression"`), each optionally serialized
with a `loc` when tokens carried locations:

- **`Literal`** — `{ type:"Literal", value, raw }`. `raw` is the source text; `value` is coerced: a
  number → its `Number`, `TRUE`/`FALSE` → boolean, a string → the unquoted text with `""` → `"`.
- **`ErrorLiteral`** — `{ type:"ErrorLiteral", value, raw }` (an error literal such as `#REF!`).
- **`ReferenceIdentifier`** — `{ type:"ReferenceIdentifier", value, kind }` where `kind` is
  `"range"` (a cell/range), `"beam"` (whole row/column like `A:B`), `"name"` (a defined name), or
  `"table"` (a structured reference).
- **`UnaryExpression`** — `{ type:"UnaryExpression", operator, arguments:[expr] }`. Prefix `-`/`+`
  and postfix `%` (and `#`, `@`) are unary; `operator` is the symbol.
- **`BinaryExpression`** — `{ type:"BinaryExpression", operator, arguments:[left, right] }`.
  Operators include `+ - * / ^ & = < > <= >= <>` and range `:`. **A run of whitespace between two
  references is Excel's intersection operator**, represented as a binary node with `operator` equal
  to a single space `" "`.
- **`CallExpression`** — `{ type:"CallExpression", callee:{type:"Identifier", name}, arguments:[…] }`.
  A **missing argument** (e.g. `SUM(1,,3)`) is a `null` entry in `arguments`.
- **`ArrayExpression`** — `{ type:"ArrayExpression", elements }` where `elements` is an array of
  **rows**, each row an array of element nodes (`;` separates rows, `,` separates columns).
- **`Identifier`** — `{ type:"Identifier", name }` (used for a call's callee and lambda params).
- **`LambdaExpression`** — `{ type:"LambdaExpression", params:Identifier[], body:Node|null }` (from
  `LAMBDA(param, …, body)`).
- **`LetExpression`** — `{ type:"LetExpression", declarations:LetDeclarator[], body:Node|null }` (from
  `LET(name1, value1, …, body)`); each declaration is
  `{ type:"LetDeclarator", id:Identifier, init:Node|null }`.

Binary operator precedence is standard: `^` (highest), then `*` `/`, then `+` `-`, then `&`, then the
comparisons (`= < > <= >= <>`).

## `stringifyTokens(tokens: Token[]): string`

Concatenate every token's `value` back into the original string.

## References

Column and row coordinates are **0-based** (`A1` → column 0, row 0; the last cell `XFD1048576` →
column 16383, row 1048575). `context` is an array of prefix parts (`[]` when none, `["Sheet1"]` for a
sheet, and a workbook-qualified prefix splits into parts, e.g. `[Book1]Sheet1!A1` →
`context: ["Book1", "Sheet1"]`). Quoted sheet names are unwrapped and `''` → `'`. A whole-row beam
(e.g. `1:1`) leaves the column bounds `null`, mirroring how a whole-column beam (`A:A`) leaves the row
bounds `null`.

### A1 — `parseA1Ref(ref: string): object | undefined` and `stringifyA1Ref(obj): string`

`parseA1Ref` returns, for a range, `{ context: string[], range: RangeA1 }`; for a defined name,
`{ context: string[], name: string }`; or `undefined` if invalid. **RangeA1**:

```
{ top, left, bottom, right,        // 0-based ints; null for an unbounded side (e.g. a whole column)
  $top, $left, $bottom, $right }   // booleans: true when that side is absolute ("$")
```

E.g. `parseA1Ref("Sheet1!A$1:$B2")` → `{ context:["Sheet1"], range:{ top:0,left:0,bottom:1,right:1,
$top:true,$left:false,$bottom:false,$right:true } }`; `parseA1Ref("A:A")` → a range with
`top:null, bottom:null, left:0, right:0`. `stringifyA1Ref` is the inverse (round-trips the object
back to the string). `parseA1Range(rangeString): RangeA1 | undefined` parses **just** the range
portion (no `context` envelope), returning the bare `RangeA1`.

### R1C1 — `parseR1C1Ref(ref: string): object | undefined` and `stringifyR1C1Ref(obj): string`

Same envelope (`{context, range}` or `{context, name}`). **RangeR1C1** uses row/col pairs:

```
{ r0, c0, r1, c1,          // ints; r/c = row/col, 0 = first corner, 1 = second corner
  $r0, $c0, $r1, $c1 }     // booleans: true = ABSOLUTE (RnCn), false = RELATIVE (R[n]C[n])
```

For an **absolute** part the input is 1-based and stored 0-based (`R1C1` → `r0:0,c0:0,$r0:true,
$c0:true`). For a **relative** part the stored value is the literal offset (`R[9]` → `9,$…:false`;
`C` / `R` → `0` relative). A single `R0`/`C0` is **not** a valid range and parses as a name.

### Structured (table) — `parseStructRef(ref): object | undefined` and `stringifyStructRef(obj, options?): string`

`parseStructRef` returns `{ context: string[], table: string, columns: string[], sections: string[] }`
(`table` is `""` when omitted). `sections` are normalized lowercase keywords drawn from `headers`,
`data`, `totals`, `all`, `this row` (the `@` shorthand → `this row`). `columns` are the literal
column names (one, or two for a `col:col` range); brace escapes (`'@` → `@`) are removed.

E.g. `parseStructRef("[[#Data],[my column]:otherColumn]")` → `{ context:[], table:"",
columns:["my column","otherColumn"], sections:["data"] }`; `parseStructRef("[#All]")` →
`sections:["all"]`.

`stringifyStructRef` is the inverse (it round-trips a parsed reference back to its string). On output
it re-Title-cases section keywords (`[#Data]`, `[#Headers]`, `[#This row]`) and **always wraps each
column specifier in `[...]`** — even a bare alphanumeric name, so a column `"amount"` serializes as
`[amount]` (note the parse-side example above accepts a *bare* `otherColumn`, but output is always
bracketed). Special characters inside a column name are re-escaped with a leading apostrophe (inverse
of the parse-time `'@` → `@` rule, e.g. `@` → `'@`). A lone `this row` section serializes to the `@`
shorthand — e.g.
`stringifyStructRef({ table:"Sales", columns:["amount"], sections:["this row"] })` → `Sales[@amount]` —
**unless** `options.thisRow === true`, in which case it is written `[#This row]`.

## Column conversion

- `toCol(index: number): string` — 0-based column index → letters. `toCol(0)==="A"`,
  `toCol(26)==="AA"`, `toCol(16383)==="XFD"`.
- `fromCol(letters: string): number` — letters → 0-based index (case-insensitive). `fromCol("A")===0`,
  `fromCol("AA")===26`.

## Range utilities

- `addA1RangeBounds(range: RangeA1): RangeA1` — fill any missing side in place and return it: a
  `null`/absent `top→0`, `left→0`, `bottom→1048575`, `right→16383`, each with its `$…` flag `false`.
- `fixFormulaRanges(formula: string, options?): string` — return a normalized formula: reversed
  ranges are flipped to top-left order (`=B2:A1` → `=A1:B2`), lowercase cell refs are upper-cased
  (`=a1:b2` → `=A1:B2`), and a sheet prefix that would be ambiguous is single-quoted (a prefix that
  looks like a cell/column reference — e.g. `Sch1`, or a bare `C`/`R`/`RC` — so `=Sch1!B2` →
  `='Sch1'!B2`, `=C!B2` → `='C'!B2`). Structured references are also canonicalized — surrounding
  whitespace is removed and section keywords are re-cased (`=tbl[ [#data] , [col] ]` →
  `=tbl[[#Data],[col]]`).
- `mergeRefTokens(tokens: Token[]): Token[]` — the token-list form of `mergeRefs`: return a new list
  in which split `context`/`!`/`range` runs are merged into single `range` tokens.

## Translating A1 ↔ R1C1

- `translateFormulaToR1C1(formula: string, anchorCell: string): string` — rewrite A1 references as
  R1C1 relative to `anchorCell` (an A1 cell). Absolute A1 (`$A$1`) → absolute R1C1 (`R1C1`); relative
  A1 → offsets from the anchor (`=$A$1` @ `B2` → `=R1C1`; `=SUM(E10,$E$2,Sheet!$E$3)` @ `D10` →
  `=SUM(RC[1],R2C5,Sheet!R3C5)`).
- `translateFormulaToA1(formula: string, anchorCell: string, options?): string` — the inverse. By
  default references that fall outside the sheet **wrap** around the edges; with
  `options.wrapEdges === false` an out-of-bounds reference becomes `#REF!` (`=R[-1]C[-1]` @ `A1` →
  `=XFD1048576` by default, or `=#REF!` with `wrapEdges:false`).
- `translateTokensToR1C1(tokens, anchorCell): Token[]` and `translateTokensToA1(tokens, anchorCell,
  options?): Token[]` — the token-list forms of the two translations.

Translation applies to whole ranges as well as single cells (each corner is translated), e.g.
`translateFormulaToR1C1("=SUM(A1:B2)", "C3")` → `"=SUM(R[-2]C[-2]:R[-1]C[-1])"`.

## Type guards and constants

- Token guards (each takes a token, returns boolean by its `type`): `isRange`, `isFunction`,
  `isError`, `isWhitespace` (also `isLiteral`, `isOperator`, `isReference`, `isFxPrefix`).
- Node guards (each takes a node, returns boolean by its `type`): `isLiteralNode`, `isCallNode`,
  `isReferenceNode` (also `isBinaryNode`, `isUnaryNode`, `isArrayNode`, `isErrorNode`,
  `isIdentifierNode`, `isLambdaNode`, `isExpressionNode`).
- Constants: `MAX_COLS === 16383` (2^14−1), `MAX_ROWS === 1048575` (2^20−1). `tokenTypes` and
  `nodeTypes` are objects mapping the keys in the tables above to their string values.
