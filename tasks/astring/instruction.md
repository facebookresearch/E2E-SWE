# astring

Build **astring**, a fast JavaScript code generator: it takes an **ESTree** Abstract Syntax Tree and
renders it back to formatted JavaScript source. This is the reverse of a parser.

## Build / environment

- Language: **JavaScript** for **Node.js 20** (CommonJS). The environment is **offline** — do not
  fetch anything and do not use any third-party package (the standard library is enough).
- Expose the generator at **`/app/astring.js`** via `require("/app/astring.js")`, exporting a function
  **`generate`** (see API).
- Provide an executable **`/app/setup.sh`** (may be a no-op `:`); it is run by the harness via
  `bash ./setup.sh` to build/install the project offline.

## API

- `generate(node): string` — render the ESTree `node` (typically a `Program`) to a
  JavaScript source string and return it. The graded behavior takes no options: indentation is
  fixed at two spaces and the line terminator at `\n`.

### Input AST shape
Inputs are plain ESTree objects (as produced by a standard parser) with two normalizations: positional
fields (`start`, `end`) are removed, and **`Literal` nodes carry no `raw`** — so a literal must be
rendered from its `value` (and, where present, from `regex` / `bigint`). Node `type` values follow
ESTree (e.g. `Program`, `ExpressionStatement`, `BinaryExpression`, `ArrowFunctionExpression`,
`ClassDeclaration`, `ObjectExpression`, `Property`, `MemberExpression`, `TemplateLiteral`, …).

## Output format (match exactly)

### Whitespace & structure
- Indentation is **two spaces** per nesting level. Line terminator is `\n`. The output ends with a
  trailing newline.
- A `Program` renders each top-level statement on its own line.
- A block (`BlockStatement`, class/function body) opens with `{` on the current line, renders each
  child on its own indented line, and closes with `}` on its own line. An empty block is `{}`.
- Statements that need a terminator end with `;` (expression, `return`, `throw`, variable
  declarations, `break`/`continue`, `import`/`export`, etc.). An `EmptyStatement` renders as `;`.
- Binary/logical operators, assignments, and `key: value` in objects are surrounded by single spaces
  (`a + b`, `a ||= b`, `{ a: 1 }`). `?`/`:` in a conditional are space-padded (`a ? b : c`).
- The multi-line object/block rules above are authoritative: a **non-empty** `ObjectExpression` or
  block always renders each property/statement on its own indented line. Some inline examples further
  down compress an object or block body onto one line for readability (e.g. `({ a: 1 })`,
  `(async () => { return a; })`); the real output is the multi-line form (`({\n  a: 1\n})`). Only an
  empty block/body stays on one line as `{}`.

### Statements (control flow)
Control-flow statements render with the keyword, a parenthesized head where applicable, and a single
space before the (usually block) body:
- `if (test) <body>` with an optional `else <body>`. A following `else`/`else if` sits on the same
  line as the preceding block's closing brace: `} else {`, `} else if (test) {`.
- `while (test) <body>`; `do <body> while (test);` — the `while` clause follows the body's closing
  brace on the same line and the statement ends with `;`.
- A C-style `for (init; test; update) <body>`: the three header clauses are separated by `; `
  (semicolon + space) and any may be omitted.
- `for (left in right) <body>` and `for (left of right) <body>` (prefix `for await` for an async
  `for await...of`); `left` may be a variable declaration or a binding pattern.
- `switch (disc) { … }` renders each `case <test>:` / `default:` label at one indent level and the
  statements of its consequent at two indent levels.
- `try <block>` with an optional `catch (param) <body>` (bare `catch <body>` when there is no
  binding) and an optional `finally <body>`; each `catch`/`finally` keyword follows the previous
  block's closing brace on the same line.
- `throw expr;`; `break;` / `break label;`; `continue;` / `continue label;`; a labeled statement is
  `label: <stmt>`.

### Parenthesization (precedence)
Emit parentheses around a sub-expression **only when required** to preserve the tree's meaning under
JavaScript operator precedence and associativity — the output must re-parse to the same tree, so wrap
wherever the ECMAScript grammar would otherwise reject the bare combination:
- A child of lower precedence than its parent operator is wrapped (`(a + b) * c`), while a
  higher-or-equal child on the naturally-associative side is not (`a + b * c`, `a - b - c`).
- For a right-associative operator (`**`, assignment, conditional), the left operand is wrapped when it
  has equal precedence; for left-associative operators, the right operand is. `a ** b ** c` needs no
  parens; `a - (b - c)` does.
- A nullish-coalescing `??` cannot be combined with a logical `&&` or `||` as a bare operand —
  ECMAScript requires parentheses — so whichever operator is the child is wrapped, in either
  direction.
- `new` with a callee that is itself a call (or otherwise ambiguous) is wrapped: `new (a().b)()`.
- A `SequenceExpression` used as a call argument or other single-expression slot is wrapped: `f((a, b))`.
- When a prefix `+`/`-` unary operator is applied to an operand that itself begins with the same sign
  (another prefix `+`/`-` unary, or a `++`/`--` update with the matching sign), separate them with a
  **single space** — not parentheses — so the adjacent tokens do not merge into a different operator:
  `- -a`, `+ +a`, `- --a`, `+ ++a` (never `--a`/`++a`, and not `-(-a)`).
- An `ExpressionStatement` whose expression is a function, class, object-literal, **or
  arrow-function** expression is wrapped in parentheses — e.g. `(function () {})();`, `({ a: 1 });`,
  `(x => x ? a : b);`, `((a = 1) => a);`, `(() => ({ a: 1 }));`, `(async (a, b) => { return a; });`.
  This applies to the whole arrow-function family (async, default/rest params, concise or block body).

### Expressions
- `ArrowFunctionExpression`: a single non-rest, non-defaulted identifier parameter is rendered without
  parentheses (`x => …`); otherwise parameters are parenthesized. Prefix `async` when async. A concise
  body that is an `ObjectExpression` is wrapped: `() => ({ a: 1 })`.
- `ObjectExpression`: rendered multi-line when non-empty (one property per indented line); an empty
  object literal is `{}`. Properties: shorthand
  (`a`), `key: value`, computed keys `[expr]`, methods `m() {}`, accessors `get g() {}` / `set …`.
  A non-identifier / non-numeric key is a quoted string (`"x-y": 2`).
- Binding/destructuring patterns (`ObjectPattern`, `ArrayPattern`) render **single-line** — unlike an
  `ObjectExpression` they are never multi-line — with **no** spaces inside the braces/brackets and
  elements comma+space separated: `{a, b: c, ...r}`, `[a, b]`. A pattern uses shorthand (`a`) or
  `key: value` for a rename, and a `RestElement` renders as `...arg`.
- `MemberExpression`: `a.b` for identifier properties, `a[expr]` when computed, `?.` when optional.
  `CallExpression`/`NewExpression` use `(`arg, …`)`; `SpreadElement` is `...expr`.
- `ArrayExpression`: `[a, b]`; elided elements (holes) render as consecutive commas (`[1, , 3]`).
- `TemplateLiteral`: `` `text${expr}text` `` using each quasi's raw text and interleaving
  `${ … }` for expressions.
- `ClassDeclaration`/`ClassExpression`: `class Name extends Super { … }` with each member on its own
  line — methods, `get`/`set`, `static` members, class fields (`x = 1;`), and private names (`#p`).
- A generator renders its `*` attached to the keyword — `function* name(…)` and a generator method
  `*name() {}`; a delegating yield renders as `yield* expr` and a plain one as `yield expr`.
- `import`/`export`: named specifier lists render with **no** spaces inside the braces
  (`import {a as b} from "m";`, `export {b as y};`); a default plus named imports combine as
  `import def, {…} from "src";`. Aliasing renders as `imported as local` for imports and
  `local as exported` for exports, shown only when the two names differ. The module source is a
  double-quoted string, and `export default expr;` renders the expression after `export default`.

### Literals (rendered from `value`)
- String: a double-quoted string with standard escaping (as `JSON.stringify` of the string would
  produce). Number: the default JS string form of the numeric value (e.g. `1e+21`, `1e-7`, `255`,
  `1.5`). Boolean/null: `true` / `false` / `null`. `RegExpLiteral`: `/pattern/flags` from `node.regex`.
  `BigIntLiteral`: the digits from `node.bigint` followed by `n`.

## Scope
Cover the ES2022 node set exercised by the tests (expressions, statements, declarations, classes,
modules, template literals, optional chaining, logical assignment, `for await`, generators). Source-map
generation and comment attachment are out of scope.
