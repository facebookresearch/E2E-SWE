# Feral — reference interpreter for a minimalist dynamic language

Feral is a small, dynamically typed, imperative, interpreted programming language. The toolchain is written in C++20. It is a full compiler stack: a lexer, an AST parser, AST passes (simplification + bytecode codegen), and a stack-based bytecode virtual machine. The `feral` executable takes a `.fer` source file, compiles it, and runs it end-to-end.

Feral's design goal is minimalism: the language syntax has no built-in module system, no built-in struct syntax, and no built-in exception syntax. Instead, imports, structs, and error propagation are exposed as ordinary library functions (`import`, `struct`, `raise`) that operate on ordinary first-class values. This makes almost everything in Feral a variable that can be passed, stored, and returned.

---

## 1. Deliverables — the runtime contract

Your build must produce, at the following exact filesystem locations:

| Path | What it is |
|---|---|
| `/usr/local/bin/feral` | The interpreter executable. Given a `.fer` path, it lexes, parses, and runs the script. |
| `/usr/local/lib/libferal.so` | The main C++ library containing the lexer / parser / VM. Loaded at process start via the executable's rpath or the linker default search path. |
| `/usr/local/lib/feral/prelude/prelude.fer` | The Feral prelude script (see §5). Loaded automatically as the first module of every VM. |
| `/usr/local/lib/feral/prelude/libferalPrelude.so` | The prelude's C++ companion (see §5). Loaded from `prelude.fer` via `loadlib('prelude/Prelude')`. |
| `/usr/local/lib/feral/std/io.fer` | The `std/io` module (see §6.1). |
| `/usr/local/lib/feral/std/libferalIO.so` | The `std/io` C++ companion. |
| `/usr/local/lib/feral/std/assert.fer` | The `std/assert` module (see §6.2). Pure Feral, no C++ companion. |

The executable resolves the standard-library root as follows: at start-up it reads its own path via `readlink /proc/self/exe`, takes the grandparent directory as `installPath`, and joins `lib/feral` onto it to produce `libPath` (the directory searched by `import(...)` and `loadlib(...)`). So placing the binary at `/usr/local/bin/feral` gives `libPath = /usr/local/lib/feral` automatically. The environment variable `FERAL_PATHS` (semicolon-separated) may prepend additional directories to the module search path.

Invoked with `feral /path/to/script.fer`, the interpreter compiles and runs the script and exits with status `0` on success. Any uncaught error (a `raise` that reaches the top of the call stack, a syntax error, a type error) terminates the program with a non-zero exit code and prints a diagnostic to stderr. There is no interactive REPL in this scope.

---

## 2. Lexical grammar

Whitespace (space, tab, newline, `\r`) is not significant except as a token separator. Two comment forms exist:

- `# ... newline` — line comment, terminates at end of line.
- `/* ... */` — block comment, **nestable**: `/* outer /* inner */ still outer */` is a single comment token.

### Identifiers, keywords, atoms

Identifiers match `[A-Za-z_][A-Za-z0-9_]*`. The reserved keywords are:

    let  fn  if  elif  else  for  in  while  return  yield
    await  wait  continue  break  void  true  false  nil
    or  defer  inline

An **atom** is a dot-prefixed identifier written as `.name`. The `.` is stripped at lex time and the token becomes a string literal whose value is `name`. The lexer only recognises a leading `.` as starting an atom when the preceding character is not a letter, digit, `_`, `)`, `]`, `'`, `"`, or backtick (so `foo.bar` remains member access rather than "identifier `foo` followed by atom `.bar`"). Two compile-time-substituted identifiers are also recognised: `__SRC_PATH__` (absolute path of the current source file, as a string) and `__SRC_DIR__` (its parent directory).

### Literals

- **Integer** — three bases:
  - decimal: `123` (leading `0` is only allowed for a single-digit `0`)
  - hexadecimal: `0xFF`, `0Xff`
  - octal: `0777` (leading `0` followed by octal digits) — traditional C style; there is no `0o`/`0O` prefix, and there are no binary (`0b`) literals.
- **Float** — `digit+ '.' digit+` (both integer and fractional parts required; no scientific notation).
- **String** — three interchangeable quoting styles: `'...'`, `"..."`, and `` `...` ``. Backslash escapes (`\n \t \r \\ \' \" \``) are recognised in all three. A single leading newline and a single trailing newline inside the quotes are stripped (so a heredoc-like block quote works cleanly).
- **Prefixed literal** — an identifier written immediately adjacent (no whitespace) to a **string** literal desugars to a function call: `ref"x"` → `ref("x")`, `bin"1011"` → `bin("1011")`. This form works only with string literals; integer and float literals do not accept adjacent-identifier prefixes/suffixes.

---

## 3. Program structure and statements

A source file is a bare sequence of statements — there is no enclosing `main` function.

    program = { statement } ;

Statements come in three flavours by punctuation:

1. **Semicolon-terminated:** `let` bindings, `return`, `defer`, `continue`, `break`, and bare expressions must end with `;`.
2. **Block-tail:** `if`/`elif`/`else`, C-style `for`, `for x in ...`, `while`, and standalone `{ ... }` blocks have no trailing `;`.
3. **Braced blocks:** `{ ... }` introduces a nested lexical scope.

### Variable declarations

    let x = 1;
    let a = 1, b = 2, c = 3;              # comma-separated bindings
    let m in someType = 5;                # optional type-annotation expression
    let 'operator+' in IntTy = fn(...) {} # string-literal binding name (see §5)
    let .name = ...;                      # atom binding name (see §5)

A `let` binding accepts either an identifier, a string literal, or an atom as the name. String-literal and atom names are used to attach members (typically operators or methods) to a type — see the `in <Type>` form in §5.

### `if` / `elif` / `else`

    if cond1 { ... }
    elif cond2 { ... }
    elif cond3 { ... }
    else { ... }

Zero or more `elif`s, at most one `else`. Prefixing with `inline if` suppresses the block's scope-push, causing declarations inside it to leak into the enclosing scope (a compile-time conditional-inclusion pattern).

### Loops

    # C-style — every clause optional; `for ;; { ... }` is valid infinite loop.
    for let i = 0; i < n; ++i { ... }

    # For-in — desugars to a C-style loop over an iterator returned by `.each()`
    # (or any object supporting `.next()` returning `nil` at exhaustion).
    for item in someVec.each() { ... }

    while cond { ... }

`continue` skips to the next iteration; `break` exits the loop.

### `defer`

`defer expr;` schedules `expr` to run when the enclosing function returns. Multiple `defer` statements fire in reverse order of scheduling (LIFO).

### `return` / `yield` / `await` / `wait`

`return [expr];` exits the enclosing function. `yield`, `await`, and `wait` are expression-level constructs used with async/coroutine calls; a coroutine is any function invoked via the built-in `async(...)` (see the prelude reference for details — the details of coroutine execution are not exercised in this scope).

---

## 4. Expressions

Precedence table (lowest to highest — level 1 is innermost / most binding):

| Lvl | Operators | Assoc | Notes |
|---|---|---|---|
| 18 | `,` | left | Comma expression. |
| 17 | `=` | right | Assignment. |
| 15 | `? :` | none | Ternary. Both branches parse at level 16. |
| 16 | `+=` `-=` `*=` `/=` `%=` `<<=` `>>=` `&=` `\|=` `~=` `^=`, `or`-block | left | Compound assign + error handler tail (see below). |
| 14 | `??` | left | Nil-coalesce: `a ?? b` returns `a` when non-`nil`, else `b`. |
| 13 | `\|\|` | left | Logical OR (short-circuits). |
| 12 | `&&` | left | Logical AND (short-circuits). |
| 11 | `\|`  | left | Bitwise OR. |
| 10 | `^` | left | Bitwise XOR. |
| 9 | `&` | left | Bitwise AND. |
| 8 | `==` `!=` | left | Equality. |
| 7 | `<` `<=` `>` `>=` | left | Relational. |
| 6 | `<<` `>>` | left | Bit shift. |
| 5 | `+` `-` | left | Additive. |
| 4 | `*` `/` `%` `**` `//` | left | Multiplicative. `**` = exponent, `//` = integer square-root. |
| 3 | prefix `++` `--` `+` `-` `*` `&` `!` `~` | right | Zero or more; innermost first. `-` folded into literal at parse time. |
| 2 | postfix `++` `--` `...` | — | At most one. `...` is variadic-unpack in call args. |
| 1 | `()` `[]` `.` `->` | left | Primary + suffix chain. `->` is an alias for `.` (identical DOT expression). |

### `or`-blocks (error handling)

At expression level 16, an expression may be followed by `or [ident] { block }`:

    let x = tryStuff() or e {
        io.println('failed: ', e.str());
        return -1;
    };

The block is wrapped in an anonymous function that receives two arguments: `self` (the calling object) and the named identifier bound to the error value. If no identifier is provided, `_` is used. If the preceding expression raises, the block runs (and its return value becomes the value of the overall `or` expression); otherwise the block is skipped.

### `??` (nil-coalesce), unary and postfix

- `a ?? b` evaluates to `a` when `a` is not `nil`, else `b`. `b` is only evaluated if needed.
- Prefix `!x` is logical NOT; `~x` is bitwise NOT.
- Postfix `x...` inside a call argument list unpacks the iterable `x` into positional arguments.

### Primary expressions and suffixes

A primary is one of: an identifier, a string / int / float / atom literal, `void`, `true`, `false`, `nil`, a parenthesised expression, a function literal (`fn (params) { body }`), an `await`/`wait` expression, or a `yield` expression.

A suffix chain follows the primary and applies left-to-right:

- `[expr]` — subscript.
- `(arg, arg, ...)` — function call. A call argument may be positional (`expr17`) or named (`ident = expr17` / `'string' = expr17` / `.atom = expr17`). Bare identifiers on the LHS of `=` in a call are coerced to string tokens.
- `.name` or `->name` — member access. Both operators produce the identical DOT expression.

Example: `foo.bar[0]().baz->quux(1, key = 2)` is a valid chain.

---

## 5. Functions and structs (library, not syntax)

Functions and structs are ordinary values produced by expressions.

### Function literals

    let helloFn = fn(name, greeting = 'Hello', .kw) {
        let punct = kw['punctuation'] ?? '.';
        return greeting + ', ' + name + punct;
    };
    helloFn('world');                              # positional         -> "Hello, world."
    helloFn('you', punctuation = '!');             # named args -> `.kw` bundle -> "Hello, you!"

Parameter forms:

- `IDENTIFIER` — regular parameter.
- `IDENTIFIER = expr` — regular parameter with default.
- `IDENTIFIER '...'` — variadic parameter (collects remaining positional args into a vector). At most one, must be last.
- `STR_LITERAL` or `ATOM` — keyword-args bundle: collects **all** named-argument-form call sites into a map keyed by their names. At most one. **Named call-site args always land in this bundle even if a regular parameter shares their name** — they never bind to a same-named regular parameter; use the bundle to read them out.

The parser silently inserts `self` as the first parameter of every function; users do not write it explicitly. Inside a member-function call `obj.fn(args)`, `self` is bound to `obj`.

### Structs (built-in `struct(...)`)

`struct(field = default, ...)` is a global function (from the prelude) that returns a struct **type**. Calling the type value constructs an **instance**:

    let Point = struct(x = 0, y = 0, tag = 'origin');
    let a = Point();                # a.x==0, a.y==0, a.tag=='origin'
    let b = Point(3, 4);            # positional x, y
    let c = Point(tag = 'here');    # named-arg override

Fields are read and written with `.` syntax: `a.x = 5;`, `a.y`. Struct types are first-class values, so they can be passed, stored, and returned.

### Associated functions

Attach a member function to a struct type (or to any type) with the `in` binding form:

    let increment in Point = fn(delta = 1) {
        self.x += delta;
        return self.x;
    };
    let p = Point(10);
    p.increment(5);                 # `self` is bound to `p`; returns 15

The name in `let name in Ty = ...` may be a string literal or atom, which is used to attach special names (e.g., `let '+' in Point = fn(other) { ... }` to overload `+` on `Point`).

### Enum (library function)

`enum(...)` is also a global function (from the prelude). It returns a struct-like value whose fields are the identifiers passed in, each bound to a sequential integer starting at 0:

    let Color = enum(.red, .green, .blue);
    # Color.red == 0, Color.green == 1, Color.blue == 2

---

## 6. Standard library subset (in scope)

The only two standard modules in scope are `std/io` and `std/assert`. Both are loaded via the built-in `import(name)` function, which searches `libPath` and any `FERAL_PATHS` entries for a matching `.fer` file.

### 6.1 `std/io`

Loading `std/io` brings the following names into the module's local namespace. These are exposed by the C++ companion via `loadlib('std/IO')`; the `io.fer` script is what triggers that load.

| Name | Signature | Behaviour |
|---|---|---|
| `print` | `fn(args...) -> Int` | Writes each of `args` to stdout in order, calling `.str()` on each. Returns the number of bytes written. No trailing newline. |
| `println` | `fn(args...) -> Int` | Same as `print`, then writes a single `\n`. With zero args, just writes `\n`. Returns the total bytes written (including the newline). |
| `eprint` | `fn(args...) -> Int` | Same as `print` but writes to stderr. |
| `eprintln` | `fn(args...) -> Int` | Same as `println` but writes to stderr. |
| `fprint` | `fn(file, args...) -> Int` | Writes to the given `File` handle. |
| `fprintln` | `fn(file, args...) -> Int` | `fprint` with a trailing newline. |
| `scanNative` | `fn() -> Str` | Reads a single line from stdin (strips trailing `\r` and `\n`). |
| `scanEOF` | `fn() -> Str` | Reads all of stdin until EOF (strips a single trailing `\r`/`\n`). |
| `fflush` | `fn(file) -> Nil` | Flushes the given `File` handle. |
| `readChar` | `fn(file_descriptor:Int) -> Str` | Reads one byte from the given fd. Raises on read failure. |
| `stdin`, `stdout`, `stderr` | `File` | The three standard streams as `File` values. |

Example:

    let io = import('std/io');
    io.println('hello ', 'world');    # writes "hello world\n"
    io.print('no-newline');

### 6.2 `std/assert`

Pure-Feral module. Each function raises (via the prelude's `raise`) if the assertion fails; otherwise returns `nil` (implicitly).

| Function | Signature | Raises when |
|---|---|---|
| `eq(lhs, rhs)` | `fn(lhs, rhs) -> Nil` | `lhs != rhs` |
| `ne(lhs, rhs)` | `fn(lhs, rhs) -> Nil` | `lhs == rhs` |
| `gt(lhs, rhs)` | `fn(lhs, rhs) -> Nil` | `lhs <= rhs` |
| `lt(lhs, rhs)` | `fn(lhs, rhs) -> Nil` | `lhs >= rhs` |
| `ge(lhs, rhs)` | `fn(lhs, rhs) -> Nil` | `lhs < rhs` |
| `le(lhs, rhs)` | `fn(lhs, rhs) -> Nil` | `lhs > rhs` |

The raised message for `eq` reads `assertion '<lhs>' == '<rhs>' failed`; the other five follow the same pattern with the corresponding operator. Assertions in this style are the idiomatic Feral way to write test scripts.

---

## 7. The prelude — global names and built-in type operators

The **prelude** is loaded automatically as the first module of every VM run, and its exports are attached as module-locals or promoted to globals (depending on how the prelude registers them). Everything below is available at the top of every user script without any explicit `import`.

The prelude has two parts:

- `lib/prelude/Prelude.cpp` compiles into `libferalPrelude.so`, which the prelude script loads with `loadlib('prelude/Prelude')`. It registers the built-in type functions and a small set of built-in globals.
- `lib/prelude/prelude.fer` is a Feral script that runs on VM start-up and defines convenience wrappers, sorting helpers, and Feral-level associated functions for the built-in types.

### 7.1 Global names

    ref(v)          # marks v to be stored by reference (avoids copy on next `let`)
    const(v)        # sets const-flag on v
    deconst(v)      # unsets const-flag on v
    raise(args...)  # concatenates args via .str(), then raises the result as an error
    enum(atoms...)  # creates an enum-struct with sequentially numbered fields
    struct(fields)  # creates a struct type from `name = default` bindings
    irange(a, b [, step])  # int-iterator over [a, b) with optional step
    import(name)    # loads and returns a module (searches libPath + FERAL_PATHS)
    loadlib(name)   # loads the C++ shared library `libferal<Basename>.so` from lib path
    feral           # bound to the prelude module itself (see §7.4)

### 7.2 Module-locals defined by the prelude

    exit(code = 0)                       # sets exit code and terminates the VM
    setMaxRecursion(n = DEFAULT_MAX_RECURSION)
    getMaxRecursion() -> Int
    addGlobalModulePaths(paths...) -> Int
    removeGlobalModulePaths(paths...) -> Int
    crash()                              # dereferences null; useful for debug backtraces
    getCurrModule() -> Module            # the current module value
    varExists(name, module = nil) -> Bool
    getOSName() -> Str                   # "linux" / "windows" / ...
    getOSDistro() -> Str
    closure(callable, args...) -> Closure
    async(callable, args...) -> Async
    evalCode(code:Str) -> Var            # eval a full source snippet
    evalExpr(expr:Str) -> Var            # eval a single expression
    vecNew(items...) -> Vec              # variadic vector constructor
    mapNew(k1, v1, k2, v2, ...) -> Map   # variadic map constructor: an EVEN number of positional
                                         # args interpreted as alternating key/value pairs, e.g.
                                         # mapNew('a', 1, 'b', 2) builds the Map {'a': 1, 'b': 2}
    bytebufferNew(size) -> Bytebuffer
    version, versionMajor, versionMinor, versionPatch    # build info
    buildDate, buildCompiler, buildType

### 7.3 Built-in types and their operators

Every Feral value has a type; the built-in types are:

`All` (root), `Nil`, `Bool`, `Int`, `Flt`, `Str`, `Vec`, `Map`, `Func`, `Closure`, `Async`, `Frame`, `Module`, `TypeID`, `Dll`, `StructDef`, `Struct`, `Failure`, `Path`, `File`, `Stack`, `Bytebuffer`, iterators (`IntIterator`, `VecIterator`, `MapIterator`, `FileIterator`).

Type methods are registered by the prelude via `vm.addTypeFn<T>(loc, "name", fn)`. The important ones for user code:

- **Universal (`VarAll`):** `==`, `!=`, `??`, `_type_()`, `_typeName_()`, `_isType_(t)`, `_hasAttr_(name)`, `_getAttr_(name)`, `_getAttrs_()`, `_setAttr_(name, value)`, `_copy_()`, `bool`, `str`. Per-type `str()` follows conventional forms — for example `Bool.str()` returns the lowercase strings `"true"` / `"false"`; `Int.str()` and `Flt.str()` return the canonical decimal representation with no leading `+` and no trailing zeros beyond precision.
- **Int:** all arithmetic (`+ - * / % ** << >>`), compound-assign forms of each, comparison, bitwise (`& | ^ ~`), pre/post inc/dec, unary minus, `sqrt`, `popcnt`. Integer iteration (`irange(a,b,step).next()` yields an int iterator).
- **Flt:** arithmetic, compound-assign, comparison, pre/post inc/dec, unary minus, `**`, `round`, `sqrt`.
- **Str:** `+`, `+=`, `*` (repeat), `*=`, `/` (split-first), relational comparison, `==`, `!=`, `at(i)`, `[i]`, `len`, `clear`, `empty`, `front`, `back`, `push`, `pop`, `isChAt`, `set`, `insert`, `erase`, `find(needle) -> Int` (byte offset of first occurrence, or `-1` if not present), `rfind`, `substrNative(begin, len)`, `trim`, `lower`, `upper`, `replace`, `splitNative(delim, maxCount)`, `startsWith(prefix) -> Bool`, `endsWith(suffix) -> Bool`, `fmt(open, close, callback)`, `byt` (byte value), and hex/UTF8 helpers.
- **Vec:** `len`, `capacity`, `isRef`, `empty`, `front`, `back`, `push`, `pop`, `clear`, `erase`, `insert`, `appendNative`, `swap`, `reverse`, `set`, `at`, `[i]`, `subNative`, `sliceNative`, `each()` (returns a `VecIterator` with `.next()`).
- **Map:** `len`, `isOrdered`, `isRef`, `empty`, `insert(key, value)` (adds a new entry OR overwrites the value at an existing key; returns `nil`), `erase(key)`, `clear`, `find(key) -> Bool` (`true` if the key is present, `false` otherwise), `at(key)`, `[key]` (subscript; returns the value at `key`, or `nil` if the key is not present), `each()` (returns a `MapIterator` with `.next()` yielding a 2-tuple).
- **Struct (definition and instances):** `structDefSetTypeName`, `structDefLen`, `structToStr`, `structLen`.
- **Path** (`Path` is a filesystem-path value; `.path()` on a string produces one): join `/`, `/=`, comparison, `clear`, `len`, `empty`, `isAbsolute`, `isRelative`, `hasRoot`, `hasFile`, `hasFileExt`, `root`, `rootName`, `rootDir`, `normal`, `absolute`, `relative`, `relativeTo`, `parent`, `file`, `fileName`, `fileExt`, `fmt(fmtStr)` (`$s $p $d $f $b $e` shorthands — feral bin, path, dir, filename-only, basename, extension). The leaf accessors `file()`, `fileName()` and `fileExt()` each return a new `Path`: `file()` → the leaf name *including* its extension; `fileName()` → the leaf name *without* the extension, i.e. the stem; `fileExt()` → the extension *including* the leading dot, and empty when there is no extension. The `/` join operator accepts a Str or Path on its right-hand side (`p / other`).
- **File:** `open`, `close`, `fd`, `lines`, `seek`, `len`, `eachLine` (iterator).

Type conversion functions (`bool`, `int`, `flt`, `str`, `path`) are attached per-type; e.g. `x.str()` returns the string representation.

Named-string binding lets user code overload these operators for their own struct types:

    let Point = struct(x = 0, y = 0);
    let '+' in Point = fn(other) {
        return Point(self.x + other.x, self.y + other.y);
    };
    let p = Point(1, 2) + Point(3, 4);   # p.x==4, p.y==6

### 7.4 The `feral` module

The prelude also binds itself to a global named `feral`, so its module-locals are reachable through it: `feral.getOSName()`, `feral.exit(0)`, `feral.version`, `feral.binaryPath`, `feral.libPath`, etc.

---

## 8. Error handling

An error is raised either by the `raise(args...)` global (see §7.1) or by the interpreter itself (e.g. a type mismatch in an operator, division by zero, invalid subscript). A raised error propagates up the call stack until either:

- it is caught by an `or` block at expression level 16 (see §4), which receives the raised value bound to the given identifier and whose return value replaces the original expression; or
- it reaches the top of the script's call stack, in which case the interpreter prints the raised message to stderr and exits with a non-zero status (pending `defer` statements are not run on the unwinding raise path — see §3).

Within an `or` block, `e.str()` returns the error's textual message.

---

## 9. End-to-end example

The following script exercises most of what is described above. Running `feral this-script.fer` writes `all-ok\n` to stdout and exits 0.

    let io = import('std/io');
    let assert = import('std/assert');

    # 1. arithmetic + precedence
    assert.eq(1 + 2 * 3, 7);
    assert.eq(2 ** 3 ** 2, 64);      # `**` is left-assoc at level 4: (2**3)**2

    # 2. control flow
    let sum = 0;
    for let i = 1; i <= 10; ++i { sum += i; }
    assert.eq(sum, 55);

    # 3. closures via partial application (feral.closure)
    # Inner functions do NOT lexically capture the enclosing function's locals;
    # the scope chain is (local -> module globals). Bind values into a callable
    # up front via feral.closure(callable, ...boundArgs).
    let add = fn(a, b) { return a + b; };
    let inc = feral.closure(add, 1);
    let dec = feral.closure(add, -1);
    assert.eq(inc(10), 11);
    assert.eq(dec(10), 9);

    # 4. struct + associated fn
    let Point = struct(x = 0, y = 0);
    let translate in Point = fn(dx, dy) {
        self.x += dx; self.y += dy; return self;
    };
    let p = Point(1, 2).translate(3, 4);
    assert.eq(p.x, 4);
    assert.eq(p.y, 6);

    # 5. defer + raise + or-block
    let value = fn() { defer io.print(''); raise('boom'); };
    let r = value() or e { assert.eq(e.str(), 'boom'); return 42; };
    assert.eq(r, 42);

    io.println('all-ok');
