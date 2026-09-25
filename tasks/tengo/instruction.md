# tengo — a small embeddable scripting language, in Go

Build `tengo`, a command-line interpreter for a small dynamically-typed scripting language,
implemented in Go. It reads a script file, compiles and executes it, and the script produces output
by calling functions from the built-in `fmt` module. Execution is deterministic: the same script
always produces the same output.

You only need to implement the surface described in this document. Where a behavior matches Go's
own semantics (arithmetic, `fmt` formatting verbs, regular expressions), implement those standard
semantics exactly.

## Environment, dependencies, and build

- The implementation must be in **Go** using **only the standard library** — no third-party modules.
  The grading environment is **offline** (no network), so nothing can be downloaded.
- Provide a `go.mod`. The build must succeed offline with `go build` (the module cache is empty;
  there is nothing to fetch because you use only the standard library).
- Provide a `setup.sh` in the working directory that builds the program to the path **`/app/tengo`**:

  ```sh
  go build -o /app/tengo .
  ```

  The grader runs `setup.sh` then invokes `/app/tengo`. Organize your Go source however you like;
  only the CLI behavior is graded.

## Command-line interface

```
tengo <script-file>
```

- The program is given the path to a script file as its argument, compiles it, and runs it.
- Anything the script prints (via the `fmt` module) goes to **standard output**.
- On success the exit status is **0**.
- If the script has a **compile-time error** (syntax/parse error, or a use of an unsupported
  construct such as tuple assignment) or a **runtime error**, the program writes **nothing to
  standard output**, writes a diagnostic to **standard error**, and exits with a **nonzero** status.
  You do not need to match the exact wording of diagnostics — only empty stdout, a non-empty stderr
  message, and the nonzero exit status are graded.
- Module imports of the form `import("./name")` are resolved relative to the **current working
  directory** (see *Modules*).

## Values and types

Every value has one of these types; `type_name(v)` returns the type's name as a string:

| type | name | notes |
| --- | --- | --- |
| int | `"int"` | signed 64-bit integer |
| float | `"float"` | 64-bit IEEE-754 float |
| bool | `"bool"` | `true` / `false` |
| char | `"char"` | a Unicode code point (like a Go `rune`) |
| string | `"string"` | immutable UTF-8 text |
| bytes | `"bytes"` | a mutable byte sequence |
| array | `"array"` | ordered, mutable, mixed-type list |
| map | `"map"` | string-keyed, mutable |
| immutable-array / immutable-map | `"immutable-array"` / `"immutable-map"` | see *Immutability* |
| undefined | `"undefined"` | absence of a value |
| error | `"error"` | see *Errors* |
| function | `"function"` | a callable value |

### Literals

`123` (int), `3.14` / `1e10` (float), `true`/`false` (bool), `"text"` and `` `raw` `` (string),
`'A'` (char), `[1, 2, 3]` (array), `{a: 1, b: 2}` (map), `undefined`, and `func(args) { ... }`
(function). Map keys in a literal are bare identifiers or string literals; the value type is any.

## Variables and scope

- `:=` **defines** a new variable in the current scope; `=` **reassigns** an existing variable.
- A variable may be reassigned a value of a different type.
- **Compound assignment**: `x op= y` updates a variable in place and is equivalent to `x = x op y`,
  for the operators `+= -= *= /= %= &= |= ^= &^= <<= >>=` (so `s += i` means `s = s + i`).
- **Increment / decrement**: the statements `x++` and `x--` add or subtract one (`x = x + 1` /
  `x = x - 1`). Like compound assignment these are statements, not expressions; the post clause of a
  C-style `for` loop is typically `i++`.
- Scopes are lexical: a `:=` inside a function body defines a local that **shadows** an outer
  variable of the same name; assignments with `=` reach the nearest enclosing definition.
- **Tuple / multiple assignment is not supported.** `a, b = b, a` is a compile error.

## Operators

### Arithmetic
- `+ - * / %` on ints; `+ - * /` on floats.
- **Integer division and `%` truncate toward zero** (`5/2 == 2`, `-7/2 == -3`, `7/-2 == -3`).
- If either operand is a float, the other is promoted and the result is a **float**
  (`1 + 2.0 == 3.0`, `5 / 2.0 == 2.5`).
- `+` also **concatenates** strings (`"foo" + "bar"`) and **arrays** (`[1,2] + [3,4]`).
- char ± int yields a char shifted by that many code points.

### Bitwise (ints): `&` `|` `^` `&^` (AND-NOT) `<<` `>>`.

### Unary: `-x`, `+x`, `^x` (bitwise complement), `!x` (logical NOT).

### Comparison: `== != < <= > >=`. Ordering works on ints, floats, chars, and **strings**
(lexicographic by code point).

### Logical: `&&` and `||` with **short-circuit** evaluation — the right operand is not evaluated
when the left already determines the result. They return a bool for bool operands.

### Ternary: `cond ? a : b` evaluates `a` if `cond` is truthy, else `b`. It is right-associative, so
`a ? b : c ? d : e` parses as `a ? b : (c ? d : e)` (a multi-way selection).

### Truthiness
`false`, `0`, `0.0`, `""` (empty string), `[]` (empty array), `{}` (empty map), and `undefined`
are **falsy**; all other values are **truthy**.

### Precedence (high → low)
1. unary operators
2. `* / % << >> & &^`
3. `+ - | ^`
4. `== != < <= > >=`
5. `&&`
6. `||`
7. `? :` (ternary)

Parentheses override precedence.

## Strings, chars, and bytes

- Strings are **immutable**: index-assignment such as `s[0] = char(88)` is a runtime error.
- Indexing a string returns a **char** (the code point at that byte offset).
- Slicing `s[lo:hi]` returns the substring over the half-open range `[lo, hi)`. Either bound may be
  omitted: `s[:hi]` defaults `lo` to 0 and `s[lo:]` defaults `hi` to the length. The same omitted-
  bound rule applies to array and bytes slices.
- `bytes(s)` converts a string to a bytes value; indexing bytes yields the int byte value;
  `string(b)` converts back; `len(b)` is the byte count.

## Arrays

- Mutable and mixed-type. `a[i] = x` updates in place.
- Arrays are indexed by an **int**. An out-of-range int index **returns `undefined`** (it is not an
  error), but indexing an array with a **non-int key** (e.g. a string, `a["k"]`) is a runtime error.
- Slicing `a[lo:hi]` clamps `lo`/`hi` to the array's bounds (e.g. `[1,2,3,4,5][-1:10]` is the whole
  array).

## Maps

- Keys are strings. Read/write via selector `m.key` or indexer `m["key"]`.
- A **missing key returns `undefined`**. Selecting through a missing key chains safely:
  `m.x.y.z` is `undefined` rather than an error.
- Assigning to a new key (`m.k = v`) adds it to a mutable map.
- **Iteration order over map keys is unspecified.** Do not rely on any particular order.

## Undefined

`undefined` represents a missing value. A function with no explicit `return` yields `undefined`; an
out-of-range index or missing map key yields `undefined`; a failed conversion (below) yields
`undefined`.

## Functions

- Defined as expression values: `f := func(a, b) { return a + b }`. There are no Go-style top-level
  `func name(...)` declarations. Because functions are ordinary values, a function literal can be
  **called immediately** (`func(a){ return a*a }(7)`), stored in arrays/maps, and passed to or
  returned from other functions (higher-order functions).
- **Closures** capture variables from the enclosing scope **by reference**: a captured variable is
  shared, so mutations to it persist across separate calls of the closure (e.g. a counter).
- **Recursion** works (a function may call the variable it is bound to).
- **Variadic**: a trailing `...param` collects extra arguments into an array
  (`func(a, b, ...c)` called as `f(1,2,3,4)` binds `c == [3, 4]`; with no extras `c == []`).
- **Argument spread**: an array argument followed by `...` is expanded into positional parameters
  (`f([1,2,3]...)`).
- Calling with the wrong number of arguments is a runtime error.

## Control flow

- `if cond { ... } else if cond2 { ... } else { ... }`. An optional init statement may precede the
  condition: `if x := f(); x > 0 { ... }` (the variable is scoped to the `if`).
- `for init; cond; post { ... }`, `for cond { ... }`, and `for { ... }` (infinite).
- `for-in` iterates iterables:
  - array: `for v in arr` (value) or `for i, v in arr` (index, value),
  - string: `for i, c in s` yields byte index `i` and **char** `c`,
  - bytes: `for i, b in bs` yields index `i` and the **int** byte value `b`,
  - map: `for k, v in m` yields key and value.
- `break` exits the innermost loop; `continue` skips to its next iteration.
- The blank identifier `_` may be used to ignore a loop variable.

## Immutability

`immutable(x)` returns an immutable view of an array or map; index-assigning into it is a runtime
error. `is_immutable_array` / `is_immutable_map` recognize these. `copy` of an immutable value
returns a **mutable** independent copy.

## Errors

`error(x)` creates an error value wrapping `x`; `e.value` reads it back; `is_error(e)` is `true`.
Operations that fail at runtime (immutable assignment, wrong argument count, indexing an array,
string, or bytes with a non-int key, etc.) abort the program with a nonzero exit and a stderr
diagnostic.

## Built-in functions (always in scope, no import)

- `len(v)` — length of a string (bytes), array (elements), map (keys), or bytes.
- `append(arr, x...)` — return a new/extended array with the given elements appended; `arr2...`
  spreads an array argument's elements.
- `copy(v)` — a deep-independent, mutable copy.
- `delete(map, key)` — remove a key from a map (returns `undefined`).
- `splice(arr, start, deleteCount, items...)` — remove `deleteCount` elements at `start`, insert
  `items` there, mutate `arr` in place, and **return an array of the removed elements**.
- `range(start, stop)` / `range(start, stop, step)` — an int array over the half-open interval
  `[start, stop)` stepping by `step` (default 1).
- Conversions: `string(v)`, `int(v)`, `float(v)`, `bool(v)`, `char(v)`, `bytes(v)`.
  - `string(123) == "123"`, `string(3.5) == "3.5"`, `string(true) == "true"`.
  - `int("-999") == -999`, `float("3.14") == 3.14`, `float(-51) == -51.0`, `bool(1) == true`.
  - `char(65)` is `'A'`; `int('A') == 65`. (`char` of a string yields `undefined`.)
  - A conversion that **fails** returns `undefined`; an optional **second argument is a default**
    used on failure: `int("foo")` is `undefined`, `int("foo", 42) == 42`.
- Type predicates returning bool: `is_int`, `is_float`, `is_string`, `is_bool`, `is_char`,
  `is_bytes`, `is_array`, `is_immutable_array`, `is_map`, `is_immutable_map`, `is_error`,
  `is_undefined`, `is_function`, `is_callable`, `is_iterable`.
- `type_name(v)` — the type name string (see the table above).
- `format(fmtStr, args...)` — return a string formatted with Go-style verbs (like `sprintf`).

## Modules (`import` / `export`)

- `import("name")` loads a standard-library module (below) and returns it.
- `import("./file")` loads a script module from `./file.tengo` resolved **relative to the current
  working directory** (the `.tengo` extension is implicit). The module file runs top-to-bottom; an
  `export <value>` statement stops it and returns that value to the importer (like `return`).
  - A module may `export` any value — a function, a map, an int, etc.
  - Exported values are immutable. A module without `export` yields `undefined`.

## Standard-library modules

### `fmt`
- `print(args...)` — write each argument's string form to stdout **with no separator** between them.
- `println(args...)` — same as `print` but append a single trailing newline. (So `println(1,2,3)`
  prints `123\n`, **not** `1 2 3`.)
- `printf(fmtStr, args...)` — write using Go-style format verbs (`%d %v %s %q %f %05.2f`, …).
- `sprintf(fmtStr, args...)` — like `printf` but return the string instead of printing it.
- Under `%v`, a whole-valued float prints with no decimals (`3.0` → `3`); an array prints as
  `[1, 2, 3]` and a map as `{k: v, ...}`; `undefined` prints as `<undefined>`.
- **Value representation and string quoting.** Every value has a canonical string form (its
  "representation"), which is what `%v` and the rendering of composite values use:
  - a **string** is shown **quoted** (`"foo"`), a **char** is shown as its bare character (`A`),
    numbers/bools are shown bare;
  - inside an **array** or **map** rendered by `%v` (or nested inside another composite), each
    element/value uses this representation, so **string elements appear quoted** while char and
    number elements appear bare — e.g. `["a", "b"]`, `[1, "X", 3]`, `{k: "v"}`, but
    `[A, B]` for an array of chars.
  - By contrast, `print`/`println` and the `%s` verb emit a **string's raw contents** with no
    quotes (`println("foo")` prints `foo`). Only the value representation / `%v` quotes strings.

### `math`
Constants `pi`, `e`, …; functions including `abs`, `ceil`, `floor`, `trunc`, `sqrt`, `pow`, `mod`,
`log`, `log2`, `log10`, `exp`, the trig family, and `max(a, b)` / `min(a, b)` (**two arguments**).
`abs` of an int returns an int; the others operate on floats.

### `text`
String utilities including: `split(s, sep)`, `split_n(s, sep, n)`, `join(arr, sep)`,
`replace(s, old, new, n)` (n replacements; use `-1` for all), `repeat(s, n)`, `substr(s, lo, hi)`,
`to_upper`, `to_lower`, `title`, `trim_space`, `trim(s, cutset)` (strip leading/trailing runes that
are in `cutset`), `trim_prefix(s, p)` / `trim_suffix(s, p)`, `contains(s, sub)`, `index(s, sub)`,
`last_index(s, sub)`, `has_prefix(s, p)`, `has_suffix(s, p)`, `fields(s)` (split on runs of
whitespace), `count(s, sub)`, `pad_left(s, width, pad)` / `pad_right(...)`, `atoi(s)`, `itoa(n)`,
`parse_int(s, base, bitSize)`, and regular-expression helpers `re_match(pattern, s)` (bool) and
`re_replace(pattern, s, repl)` (replace all matches). Regexes use Go's `regexp` (RE2) syntax.

### `enum`
Collection helpers taking `(collection, fn)` where `fn` is `func(index, value)`:
- `map(arr, fn)` — array of results,
- `filter(arr, fn)` — elements where `fn` is truthy,
- `each(arr, fn)` — call `fn` for each element (returns `undefined`),
- `find(arr, fn)` — the **first value** for which `fn` is truthy, or `undefined` if none match,
- `all(arr, fn)` / `any(arr, fn)` — bools,
- `chunk(arr, size)` — split into sub-arrays of length `size` (last may be shorter).

### `json`
- `encode(v)` — JSON bytes for `v` (arrays preserve order; object key order is unspecified).
- `decode(s)` — parse JSON text/bytes into tengo values. JSON numbers without a fractional part
  decode to **int**, others to **float**. Decoded objects are maps accessed by key.

### `base64`
- `encode(bytes)` → standard base64 string; `decode(str)` → bytes.

### `hex`
- `encode(bytes)` → lowercase hexadecimal string; `decode(str)` → bytes.
