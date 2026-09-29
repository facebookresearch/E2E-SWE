# Build `jp`: a JMESPath JSON query command-line tool

Implement a command-line program named **`jp`** that evaluates a [JMESPath](https://jmespath.org)
expression against a JSON document and prints the resulting JSON. JMESPath is a query language for
JSON (the same language used by the AWS CLI's `--query`): an expression navigates, filters, projects,
and transforms a JSON input into a JSON output.

## Language and build

- Write the program in **Go, using only the Go standard library**. Do not add any third-party module
  dependencies (no `require` entries beyond the standard library). `encoding/json` is available and
  is the expected way to parse and emit JSON.
- Provide an executable shell script **`/app/setup.sh`** that builds your program to the path
  **`/app/jp`**. For example, if your `package main` is at the module root, `setup.sh` contains:
  `go build -o /app/jp .`
- The build runs **offline** (`GOPROXY=off`), so everything must compile from the standard library
  with no network access.

## Command-line interface

```
jp [options] <expression>
```

- The single positional argument is the JMESPath **expression**.
- By default the JSON **input** is read from **stdin**. Options may appear before or after the
  expression.

Options:

- `-c`, `--compact` — emit compact JSON (no insignificant whitespace) instead of the default
  pretty-printed form.
- `-u`, `--unquoted` — if the final result is a JSON **string**, print it without the surrounding
  double quotes. For any non-string result this option has no effect (normal JSON is printed).
- `-f`, `--filename <path>` — read the input JSON from the given file instead of stdin.

### Output format

- The result is serialized as JSON followed by a single trailing newline (`\n`).
- **Default (pretty):** indent nested structures by **two spaces** per level, matching Go's
  `encoding/json` `MarshalIndent(v, "", "  ")`. For example, the result `[1,2]` prints as:

  ```
  [
    1,
    2
  ]
  ```

- **Compact (`-c`):** a single line with no extra whitespace, e.g. `[1,2]`.
- **Object keys are emitted in sorted (lexicographic) order** in both modes — e.g. the object
  `{"b":1,"a":2}` prints compactly as `{"a":2,"b":1}`. (This is the standard `encoding/json` object
  ordering.)
- Numbers print in canonical JSON form: an integral value has no decimal point (`6`, `3`), a
  fractional value keeps its fraction (`1.5`, `3.5`).
- A JSON `null` result prints as `null`.

### Exit status and errors

- On success, exit **0**.
- A valid expression that simply matches nothing (e.g. selecting a field that does not exist)
  is **not** an error: the result is JSON `null` and the exit code is `0`.
- On any error, exit with a **non-zero** status and write a diagnostic message to **stderr**. Errors
  include: a syntactically invalid expression, a reference to an unknown function, a function called
  with the wrong number of arguments or an argument of the wrong type, JSON input that fails to
  parse, and invoking the tool with no expression argument. The exact wording of diagnostics is not
  constrained.

## JMESPath semantics to implement

Implement standard JMESPath evaluation. The behaviors below are all exercised and must match exactly.

### Identifiers and sub-expressions

- A bare identifier selects a field of the current object: `a`. Chaining with `.` walks deeper:
  `a.b.c`.
- An identifier containing characters outside `[A-Za-z0-9_]` (spaces, dots, non-ASCII, etc.) must be
  written as a **double-quoted** identifier, parsed as a JSON string: `"foo bar"`, `a."b.c"`,
  `"café"`.
- Selecting a field that is absent, or indexing/sub-expression on `null`, yields `null`.

### Index and slice expressions

- `a[N]` indexes into an array. Negative indices count from the end (`a[-1]` is the last element).
  An out-of-range index yields `null`.
- Slices use `[start:stop:step]`, following Python-like semantics: any of the three may be omitted
  (`[:2]`, `[2:]`, `[::2]`), `step` may be negative to reverse with explicit bounds (`[4:1:-1]`,
  `[::-2]`), negative bounds count from the end (`[-2:]`), and out-of-range bounds are clamped
  (`[1:10]` on a 3-element array yields elements 1..2). Slicing is defined for arrays only; slicing
  any non-array yields `null`.

### Wildcards, projections, and flatten

- `a[*]` is a **list projection**: the expression to its right is applied to every element and the
  results are collected into a new array. Elements for which the right-hand expression yields `null`
  are **dropped** from the result. Example: `a[*].b`. A list wildcard applied to a value that is
  **not an array** yields `null`.
- `*` is an **object projection**: it projects the right-hand expression over the *values* of an
  object. Examples: `*.b`, `*`. The **order** of the projected values is unspecified (just as for
  `keys`/`values`).
- A **filter** `[?...]` (see below) also starts a projection: the sub-expressions after it are
  applied to each surviving element. Example: `a[?x].y.z`.
- `[]` is the **flatten** operator: it merges one level of nested arrays into a single array and
  starts a projection over the merged elements. Example: `a[].b`. Flatten composes both inside a
  projection (`a[*].b[].c`) and when chained (`a[].b[].c`).
- A projection **continues** through following sub-expressions, index expressions, slices,
  wildcards, filters, and multiselect expressions — each is applied element-wise, and any
  element for which the continuation yields `null` is dropped. In particular indexing applies
  *within* a running projection: `a[*].b[0]` indexes into each projected `b` (and drops an element
  whose `b` is empty). A projection nested inside a projection **nests** rather than flattens:
  `a[*].b[*]` returns an array of arrays, and `a[*].[b,c]` / `a[*].b[0:2]` likewise produce one
  array per element. A bare `[*]` or `[]` at the start of an expression projects over / flattens the
  top-level input array (`[]` on `[[1,2],[3,[4]]]` yields `[1,2,3,[4]]`; chaining `[][]` flattens a
  second level).
- A **pipe** `|` **stops** the current projection and feeds the whole collected result to the
  right-hand expression as a single value. Contrast `a[*].b[0]` (index each element) with
  `a[*].b | [0]` (index the assembled array).

### Filter expressions

- `a[?<comparison>]` keeps the elements of array `a` for which the comparison is truthy.
- Comparators: `==`, `!=`, `<`, `<=`, `>`, `>=`.
  - `==` / `!=` compare any two values by deep equality and are **type-sensitive**: the number `2`
    and the string `"2"` are not equal.
  - The ordering comparators `<`, `<=`, `>`, `>=` are defined **only for two numbers**. If either
    operand is not a number the comparison yields no match (the element is filtered out), e.g.
    `a[?b<'m']` matches nothing when `b` is a string.
- Boolean operators: `&&` (and), `||` (or), and unary `!` (not). `&&` binds tighter than `||`.
  `||` and `&&` return one of their **operands** (not a coerced boolean): `x || y` is `x` if `x` is
  truthy else `y`; `x && y` is `x` if `x` is falsy else `y`. Parentheses group sub-expressions.
- **Truthiness:** `null`, `false`, an empty string, an empty array, and an empty object are falsy;
  everything else is truthy — in particular the number `0` and non-empty containers are truthy.
  `a[?b]` keeps elements whose `b` is truthy.
- A filter comparison may call functions (`a[?contains(tags, 'x')]`) and may compare against literals
  including the JSON `null` literal (`a[?b == \`null\`]`).

### Multiselect

- **Multiselect list** `[expr1, expr2, ...]` evaluates each expression against the current node and
  returns an array of the results: `[a, b]`.
- **Multiselect hash** `{key1: expr1, key2: expr2, ...}` returns a new object mapping each key to its
  evaluated expression: `{x: a, y: b}`. A multiselect hash may be applied within a projection
  (`people[*].{f: first, l: last}`).

### Or / and / not / grouping

- `x || y` returns `x` if it is truthy, otherwise `y`.
- `x && y` returns `x` if it is falsy, otherwise `y`.
- `!x` returns the boolean negation of the truthiness of `x`.
- Parentheses control precedence: `(a || b).c`.

### Literals and the current node

- **JSON literals** are written in backticks and **must contain valid JSON**: `` `[1, 2]` ``,
  `` `true` ``, `` `null` ``, `` `3.0` ``, and JSON strings as `` `"foo"` ``. A backtick literal
  whose contents are not valid JSON (for example a bare word `` `foo` ``) is an **error** — bare
  words are not implicitly quoted.
- **Raw string literals** are written in single quotes and are taken verbatim as strings: `'foo'`,
  `'a, b'`. Use these (or a quoted JSON string literal) for string operands, e.g.
  `starts_with(s, 'foo')`.
- `@` refers to the **current node** (the whole input at the top level).

### Built-in functions

These functions are called from within the JMESPath expression passed to the CLI (for example
`jp 'sort_by(a, &age)'` or `jp 'length(@)'`), so they are part of the tool's observable behavior.
Implement them with standard JMESPath semantics:

- `length(subject)` — number of elements in an array or object, or Unicode characters in a string.
- `starts_with(subject, prefix)` / `ends_with(subject, suffix)` — boolean string tests.
- `contains(subject, search)` — for an array, whether `search` is an element; for a string, whether
  `search` is a substring. Returns a boolean.
- `join(glue, string_array)` — join an array of strings with the `glue` string.
- `reverse(subject)` — reverse an array or a string.
- `to_string(arg)` — the JSON string form of `arg` (a string argument is returned unchanged).
- `to_number(arg)` — parse a numeric string to a number; returns `null` if it is not a valid number.
- `abs`, `ceil`, `floor` — numeric functions on a single number. `ceil`/`floor` return integral
  values.
- `avg(number_array)` — arithmetic mean (a number). `sum(number_array)` — sum (0 for an empty array).
- `max(array)` / `min(array)` — the maximum / minimum of an array of **numbers or strings** (strings
  compared lexicographically).
- `sort(array)` — a new array sorted ascending (numbers numerically, strings lexicographically).
- `sort_by(array, &expr)` — sort the array by the value that `&expr` produces for each element. The
  sort is **stable**: elements whose keys compare equal keep their original relative order.
- `max_by(array, &expr)` / `min_by(array, &expr)` — the element whose `&expr` value is greatest /
  least.
- `map(&expr, array)` — apply the expression `&expr` to each element, returning an array of results.
  Unlike a projection, `map` **keeps** every result, so an element whose `&expr` is `null` yields a
  `null` entry (the output length always equals the input length).
- `type(arg)` — the JMESPath type name of `arg`, one of `"string"`, `"number"`, `"boolean"`,
  `"array"`, `"object"`, `"null"`.
- `keys(obj)` / `values(obj)` — arrays of the object's keys / values. **The order of the returned
  array is unspecified.**
- `merge(obj1, obj2, ...)` — a single object combining all arguments; keys from later arguments
  override earlier ones.
- `not_null(arg1, arg2, ...)` — the first argument that is not `null`.
- `to_array(arg)` — `arg` unchanged if it is already an array, otherwise a single-element array
  containing `arg`.

An `&expr` argument (used by `sort_by`, `max_by`, `min_by`, `map`) is an **expression reference**:
the expression is evaluated against each element rather than immediately.
