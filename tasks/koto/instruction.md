# Koto-Mini — Embed a Tiny Dynamic Language in Rust

Your job is to build a miniature scripting language from scratch, packaged as a Rust crate named `koto`. The crate will let a host program compile a short script and get back a dynamic value. You own the internals — how you parse or evaluate is up to you.

## Packaging

- Crate name `koto`, Rust edition `2024`, toolchain `>= 1.85`.
- The build environment is fully offline with **no third-party crates** — use only the Rust standard library.
- Source files are UTF-8 text.
- Provide a module `koto::prelude` so that `use koto::prelude::*;` brings all public items into scope for callers.

## Interpreter API

From the prelude, users should get:

- **`KValue`** — the single dynamic value that can hold an int, float, bool, null, string, list, tuple, map, or function. It must be fully owned and not borrow from the interpreter — since `compile_and_run` returns a `KValue` that you keep in a local variable and later move into `value_to_string` (both take `&mut self`), `KValue` cannot carry a lifetime tied to `Koto`.
- **`Koto`** — the interpreter instance:
  - `Koto::default()` (or `Koto::new()`) creates a fresh one.
  - `compile_and_run(&mut self, script)` executes a script. `script` can be a `&str` — accept it via `Into<CompileArgs>` and also expose `CompileArgs` with `CompileArgs::new(&str)` so both forms work. On success return `Ok(KValue)` with the value of the last expression in the script. On **any** compile-time or runtime problem, return `Err(_)` — never panic or abort.
  - `value_to_string(&mut self, value: KValue)` takes ownership of a value and returns `Result<String, E>` with its display form. This must respect custom `@display` logic (see below).
- An error type `E` that implements `Display`. The exact wording isn't checked; only `Ok` vs `Err` matters.

## The language — what a script can say

**Values and literals:**
- `null`, booleans `true` / `false`, integers (`42`, `0x2a`, `0o52`, `0b1010` are all decimal/hex/octal/binary), floats, and single-quoted strings like `'hi'`.
- Collections: lists `[1, 2, 3]`, tuples `(1, 2)`, maps inline `{x: 1, y: 2}` and also in an indented block form where each `key: value` lives on its own indented line.

**Operators:** `+ - * / % ^` and comparisons `== != < <= > >=`, plus logical `and` / `or` / `not`. Division `/` is *true* division and always produces a float — the result is never an integer, even when the operands divide exactly. `^` is exponentiation, so `2 ^ 3` is `8`.

**Truthiness — koto has its own rule:** only `false` and `null` are false. Everything else counts as true, including `0`, `""`, `[]`, `{}`.

**Bindings and mutation:** `name = expr` creates or rebinds. You can also assign into a slot: `list[i] = v`, `map.key = v`, `map.key += v`, etc. Compound forms `+= -= *= /= %=` work on variables, fields, and indexed slots.

**Conditionals:** `if cond then a else b` works as an expression, and there is also an indented block form.

**Functions:** closures look like `|x, y| x + y` or `|| 42` when they take nothing. You can call them with or without parentheses — `f 2` means the same as `f(2)`, including inside arguments like `koto.type (foo 0)`. Without parentheses the call takes the entire following expression as its single argument, so `f a + b` is interpreted as `f(a + b)`.

**Capture is by copy — this is critical for correctness:** when a closure is made, it snapshots the current values of free variables. If you later rebind the outer name, the closure still sees the old snapshot. If the closure mutates a captured primitive (number, bool, string), that mutation is thrown away after the call — each invocation starts from the captured snapshot again. To share mutable state between calls, capture a container — a list or a map — and mutate *through* it; because the container itself is shared, the mutation is visible. A free name that has no value at all when the closure is made has nothing to snapshot: it is looked up in the script's top-level scope when the function runs, so a function body may use a top-level name that is bound only later.

**Indexing, field access, and slicing:** `x[i]` gets an element, `x[i] = v` sets it. Maps also allow `m.key` / `m.key = v` dot access for normal keys (and for mutation like `m.x += 1`). `x[a..b]` takes a slice where `b` is exclusive. For a **list**, slicing builds a brand-new list with copied-out elements. For a **string**, slicing returns the substring.

**String interpolation:** inside a single-quoted string you can write `'{expr}'` and the expression inside the braces is evaluated and spliced into the string.

**Indentation:** block forms for maps, function bodies, and `if` branches are indentation-sensitive — dedent closes the block. A function whose body is an indented block runs its lines top to bottom and the value of the last expression is its return; if that block is a list of `key: value` lines it builds a map (used for objects with `@` entries).

## How collections behave — shared vs copied

- **Lists and maps are references.** `b = a` doesn't duplicate data; both names point at the same list/map. Mutating through one name is visible through the other.
- **List slices are the exception** — they copy, so mutating the slice does not affect the original.
- **Tuples are immutable** containers, but they may hold a reference to a mutable list inside. If you mutate that inner list, the change is still observable via the tuple.

## Objects via `@` meta entries

A map can carry special entries whose keys start with `@`. These let a map act like an object:

- `@+`, `@-`, `@*` overload `+`, `-`, `*`. `@==` and `@<` overload equality and less-than.
- **Derived comparisons:** if a map only defines `@<` and `@==`, you must automatically derive `>`, `>=`, `<=`, `!=` from them. The user should not have to write all four.
- **`@+=` is separate:** it is *not* derived from `@+`. If you want `obj += x` to work you must define `@+=` explicitly. Its convention is to mutate `self` and return `self`.
- `@index` makes `obj[i]` work, `@size` is consulted by the `size` builtin, `@call` makes the map itself callable as `obj(...)`, `@type` returns the string that `koto.type(obj)` sees, and `@display` controls how the object turns into text for `value_to_string` and for interpolation. A `@` entry can be a plain stored value or a function — both are valid, e.g. `@type: "Foo"` as a string versus `@display: || ...` as a function — field access and calls handle them consistently.
- **Named metas:** `@meta foo: 1` creates a field `obj.foo` alongside normal keys — you can read `m.x` and `m.foo` the same way, and mix them in the same map.
- Inside any meta function, `self` refers to the owning map, so `@display: || 'hi {self.data}'` can see its own fields.

## How values render to text

Rendering is a fixed contract — string comparison is exact:

- A **bare string** at the top level renders as its raw contents, no quotes.
- **Inside a list or tuple**, a string renders *with* single quotes. Two strings in a tuple look like `('H', 'e')`.
- **Tuples** look like `(a, b, c)` — parentheses, comma+space between elements.
- **Lists** look like `[a, b, c]` — square brackets, comma+space between elements — following the same in-container string-quoting rule as tuples.
- Integers render as plain numerals; a float always renders with a decimal point and its shortest round-tripping digits — never zero-padded — so a whole-valued float ends in `.0`. Booleans render as lowercase `true` / `false`, and `null` renders as `null`.
- If a value carries `@display`, that function decides the text.

## Tiny standard library

- `koto.type(v)` → string name of the type, honoring `@type`.
- `size v` — prefix form — length of a string/list/tuple/map, honoring `@size`.

## What counts as failure

- A script with invalid syntax, or any runtime problem (wrong type for an operator, missing field, calling something that isn't callable, out-of-range index, etc.), must cause `compile_and_run` to return `Err`. It must never panic, unwind, or kill the process.
- The last expression in a script determines the returned `KValue`. Empty or non-expression scripts follow the same error rule if they can't produce a value.

Build only what is described above — no extra syntax is required. Keep the implementation to what a short script can observe from the outside, and leave the internal design to you.
