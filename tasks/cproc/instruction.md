# cproc

Build **cproc**, a small C11 compiler written in standard C99 that emits
[QBE](https://c9x.me/compile/) textual intermediate language (IL) and drives
the whole compile pipeline end-to-end.

The compiler is composed of two binaries that cooperate:

* `cproc-qbe` — the compiler frontend: reads one preprocessed translation
  unit (named as a file argument or read from standard input), parses C,
  type-checks, and emits QBE IL on stdout. Pure C99, no external
  dependencies beyond libc.
* `cproc` — a driver that, for each `.c` input, invokes the following tools
  in order: an external preprocessor (`cpp`), the frontend (`cproc-qbe`),
  the QBE code generator (`qbe`), an assembler (`as`), and — if linking is
  requested — a linker (`ld`). The exact plumbing between stages (pipes,
  temporary files) is an internal implementation detail.

External tools invoked by the driver (`cpp`, `qbe`, `as`, `ld`) are all
pre-installed at `/usr/local/bin/` and available at runtime; you do not need
to install them. Because the build runs offline, the linked QBE IL reference is
unavailable during implementation — the accepted IL syntax can instead be
explored locally with the pre-installed `/usr/local/bin/qbe`. The compiler is
judged by the observable runtime behavior (exit status and stdout) of the
executables it produces, not by the textual form of the emitted IL.

The two-binary QBE pipeline is a requirement, not a suggestion: `cproc-qbe`
must itself parse and type-check its C input and emit QBE IL, and `cproc`
must feed that IL through `qbe` to obtain assembly. Delegating the
translation of user programs to another C compiler present in the image
(`gcc`, `cc`, `clang`, ...) is not a conforming implementation; those
compilers may only be used to build your own sources during `setup.sh`.
Only the textual form of the IL you emit is unconstrained.

## Build contract

After `./setup.sh` completes, the following must work for any C11 program
`hello.c` in the subset described below, from any working directory:

```
cproc hello.c -o hello
./hello
```

For that command to work, `setup.sh` must place:

* `/usr/local/bin/cproc` — the driver.
* `/usr/local/bin/cproc-qbe` — the frontend the driver invokes at the
  code-generation stage.

`setup.sh` runs offline (`PIP_NO_INDEX=1`; no network). `apt-get install`,
`pip install`, and `git clone` inside it will fail.

## Supported C subset

Target the following subset of C11 for the `x86_64-linux-gnu` host (LP64
data model). Every listed feature should compile and behave per the C
standard except where narrower guarantees are noted below.

### Types and declarations

* Integer types: `_Bool`, `char`, `signed char`, `unsigned char`, `short`,
  `unsigned short`, `int`, `unsigned int`, `long`, `unsigned long`,
  `long long`, `unsigned long long`. Type sizes on the target: `char==1`,
  `short==2`, `int==4`, `long==8`, `long long==8`, `void*==8`. Standard
  integer promotion and usual-arithmetic conversions apply.
* Floating-point types: `float` (IEEE-754 single-precision) and `double`
  (IEEE-754 double-precision).
* Enumeration types (`enum tag { A, B = 5, C }`). Enumerators without an
  explicit value continue sequentially from the previous one (`C == 6`
  above). An `enum` type has the same size and alignment as `int`, and
  enum values are usable wherever an `int` is expected (arithmetic,
  `switch` labels, function arguments).
* Pointer types, including pointer arithmetic, pointer-to-pointer,
  function pointers, and array-to-pointer decay. Pointer difference has
  type `ptrdiff_t` (defined in `<stddef.h>`).
* Array types (fixed-size); multi-dimensional arrays; string literals as
  `char[]` initializers.
* Struct and union types.
  - **Layout**: aggregate layout follows the platform ABI for the
    `x86_64-linux-gnu` target. Member offsets are observable with
    `offsetof` (from `<stddef.h>`).
  - **Bit-fields** on signed and unsigned integer types. A signed
    bit-field sign-extends on load; an unsigned bit-field zero-extends.
    Adjacent bit-fields inside a storage unit are stored independently.
  - **Unions** share storage across their members: writing one member
    and reading another exposes the underlying byte representation.
    On x86_64 (little-endian), after
    `union U { unsigned int i; unsigned char b[4]; } u; u.i = 0x11223344;`
    the bytes read as `b[0]==0x44`, `b[1]==0x33`, `b[2]==0x22`,
    `b[3]==0x11`.
  - **Designated initializers** `{ .field = value }` for structs and
    `{ [index] = value, ... }` for arrays. Members / elements not
    mentioned are zero-initialized.
  - **Compound literals** `(T){ ... }` construct an anonymous struct or
    array value usable directly in an expression (for example, as a
    function-call argument).
* `typedef` — creates a type alias usable everywhere the underlying type
  would work, including struct types (`typedef struct { int x; } Point;`)
  and function-pointer types with parenthesised parameter lists
  (`typedef int (*BinOp)(int, int);`).

Type qualifiers: `const`.

Storage-class specifiers: `static`, `extern`, `auto`.

Alignment: `_Alignof(int) == 4`, `_Alignof(double) == 8`.

### Expressions and operators

* Arithmetic: `+ - * / %` (integer and floating); unary `+ - ~ !`; pre/post
  increment/decrement. Signed integer division truncates toward zero and
  `(a/b)*b + a%b == a` for all integer operands — so `(-7)/2 == -3`,
  `(-7)%2 == -1`, `(7)%(-2) == 1`. Unsigned overflow wraps modulo `2^N`.
* Bitwise: `& | ^ << >>`. Signed right-shift on the target is arithmetic
  (sign-preserving): `(int)(-8) >> 1 == -4`.
* Logical: `&& || !`.
* Relational and equality: `< <= > >= == !=`.
* Assignment: `=` and all compound forms (`+=`, `-=`, `*=`, `/=`, `%=`,
  `&=`, `|=`, `^=`, `<<=`, `>>=`). A compound assignment evaluates its
  left operand only once, even when that operand has side effects: after
  `int arr[3] = {10, 20, 30}; int i = 1; arr[i++] += 5;` the array is
  `{10, 25, 30}` and `i == 2`.
* Address-of / dereference: `&`, `*`.
* Member access: `.` and `->`.
* Subscript: `a[i]`.
* Function call.
* Cast: `(T)expr`.
* Ternary: `cond ? a : b`.
* Comma: `a, b`.
* `sizeof`, `_Alignof`.

### Statements and control flow

* Expression statement, block (`{ ... }`), null statement.
* `if` / `else`.
* `while`, `do`-`while`, `for` (including omitted / empty clauses).
* `switch` / `case` / `default` on integer expressions, with C's
  fallthrough semantics (a missing `break` falls into the next case).
* `break`, `continue`, `goto <label>` (forward and backward), `return`.
* **Block scope**: a variable declared inside a block shadows any outer
  declaration of the same name for the extent of that block; the outer
  binding is restored on block exit. The induction variable of a
  `for (int i = ...; ...; ...)` is block-scoped to the loop.

### Functions

* Function definition and declaration; prototypes; forward declaration.
* Direct recursion and **mutual recursion** between functions that
  forward-declare each other (`static int is_odd(int); static int
  is_even(int n) { ... is_odd(n-1) ... }`).
* Variadic functions via `<stdarg.h>` (`va_list`, `va_start`, `va_arg`,
  `va_end`) for `int`, pointer, and `double` arguments.
* `void` return type; multiple `return` statements per function are
  permitted; `return` without an expression is allowed in a `void`
  function.
* **`static` local variables** persist across successive calls to the
  same function and are initialised only once (on first entry). A
  function `int counter(void) { static int n = 0; return ++n; }`
  returns `1, 2, 3, ...` on successive calls.

### Preprocessor

The driver invokes an external `cpp` (installed at `/usr/local/bin/cpp`)
for the preprocess stage. cproc itself does not need a preprocessor
implementation — its job is to invoke `cpp` with the correct flags and
forward the preprocessor output to the frontend. The following features
must work end-to-end:

* `#include` for system (`<...>`) and local (`"..."`) headers.
* `#define` for both object-like (`#define NAME value`) and function-like
  (`#define NAME(args) body`) macros.
* Conditional compilation: `#if`, `#ifdef`, `#ifndef`, `#else`, `#elif`,
  `#endif`.
* The `#` stringification operator (`#x` → string literal of `x`).
* The `##` token-pasting operator (`a ## b` → concatenated identifier).
* Predefined macros `__LINE__` (the current source line number as an
  integer) and `__FILE__` (the current source file name as a string
  literal).

### Standard library headers

Programs may `#include` any header from the system libc at
`/usr/include/`. Headers exercised end-to-end include:

* `<stdio.h>` — `printf`, `sprintf`, `sscanf`, `puts`.
* `<stdlib.h>` — `malloc`, `free`, `NULL`.
* `<string.h>` — `strlen`, `strcmp`, `strncmp`, `strcpy`, `strchr`,
  `memcpy`.
* `<stdarg.h>` — `va_list`, `va_start`, `va_arg`, `va_end`.
* `<stddef.h>` — `ptrdiff_t`, `size_t`, `NULL`.
* `<stdint.h>` — `int64_t` and other exact-width integer typedefs.
* `<stdbool.h>` — `bool`, `true`, `false`.
* `<assert.h>` — `assert`.
* `<limits.h>` — `INT_MAX`, `LONG_MAX`, etc.
* `<math.h>` — `sqrt`, `sin`, `cos`, `pow`, `fabs`. **Programs that call
  these must be linked against libm — see the `-l` CLI flag below.**
* `<inttypes.h>` — `PRId64`, `SCNd64`, etc.: `printf` / `scanf`
  format-specifier macros for the exact-width integer types.

**Format specifiers** the driver-produced binaries must handle correctly
via `printf` / `sprintf` / `sscanf` include at least: `%d`, `%u`, `%x`,
`%s`, `%f`, `%.Nf`, `%0Nd`, `%ld`, `%lld`, and the `PRId64` / `SCNd64`
macros from `<inttypes.h>`.

## Command-line interface

`cproc` supports the following invocation shapes:

```
cproc [-c] [-D name[=value]] [-I dir] [-l lib] [-o output] input.c...
cproc [-o output] input.o...
```

* Default (no `-c`) runs the full pipeline and links to an executable.
  Multiple `.c` and `.o` inputs may be mixed on one command line; they
  are all linked together.
* `-o <file>` writes the final output to `<file>`. Default output name
  when linking is `a.out`.
* `-c` — compile and assemble a single `.c` input to a relocatable ELF
  object (`.o`) file and stop before the link stage. `cproc` can
  subsequently be invoked with one or more `.o` inputs to link them
  into an executable, resolving cross-translation-unit symbol references.
* `-D name[=value]` — pass to the preprocessor as a macro definition
  (visible to `#ifdef` and to plain macro expansion during compilation).
* `-I dir` — pass to the preprocessor as an additional include search
  directory. `#include "name.h"` will then find `dir/name.h`.
* `-l lib` — pass to the linker as `-l lib`. In particular, programs
  that use `<math.h>` must be compiled as
  `cproc source.c -lm -o out`, because the driver's default link command
  links against `libc` but not `libm`.

Additional flags may be recognised but are not required by the specification.
