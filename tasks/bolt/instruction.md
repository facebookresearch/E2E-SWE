# Bolt

Build **Bolt**, a lightweight, statically typed scripting language written in
C99 that is designed to be embedded in host applications. A bolt program is
compiled to bytecode and executed on a small register-based virtual machine
with a mark-and-sweep garbage collector. Values are 64-bit NaN-boxed so that
numbers, booleans, `null`, and boxed object pointers share one uniform
`bt_Value` representation.

The host application creates a `bt_Context`, opens the standard-library
modules on it, and then either:

  * runs bolt source text (`bt_run` / `bt_compile_module`), or
  * registers native C functions inside a bolt module that bolt code can then
    `import` and invoke, or
  * looks up an exported bolt function and invokes it from C with typed
    arguments.

Both directions of the C ↔ bolt boundary are supported without any glue-code
generator: the type of every function (native or bolt-defined) is encoded in
the `bt_Type` you register alongside it, and bolt's parser type-checks every
call against those signatures.

Here is a small program showing bolt's core idioms end-to-end:

```bolt
import print, error, Error, to_string from core

type Priority = enum { Low, Medium, High }

let const priority_name: { ..Priority: string } = {
    Priority.Low: "low", Priority.Medium: "medium", Priority.High: "high"
}

type Task = {
    title: string,
    priority: Priority,
    hours: number
}

fn Task.new(title: string, priority: Priority, hours: number): Task | Error {
    if hours <= 0 { return error("hours must be positive") }
    return Task => { title: title, priority: priority, hours: hours }
}

fn Task.@format(this) {
    return "[" + priority_name[this.priority]! + "] " + this.title +
           " (" + to_string(this.hours) + "h)"
}

fn Task.escalate(this): Task {
    let const p = if this.priority == Priority.Low then Priority.Medium else Priority.High
    return Task => { title: this.title, priority: p, hours: this.hours }
}

let const raw = [
    Task.new("write spec",  Priority.High,   4),
    Task.new("code review", Priority.Medium, 2),
    Task.new("fix flake",   Priority.Low,    1),
    Task.new("skip me",     Priority.Low,   -1)
]

let const tasks: [Task] = raw
    .filter(fn(r: Task | Error) { return r is Task })
    .map(fn(r: Task | Error) { return r as Task! })

let const urgent = tasks.filter(fn(t: Task) { return t.priority == Priority.High })

let hours_total = 0
for t in tasks.each() { hours_total += t.hours }

for t in tasks.each() { print(t) }
print("urgent count: " + to_string(urgent.length()))
print("total hours: " + to_string(hours_total))

match let bumped = Task.new("re-plan", Priority.Low, 0) {
    is Error { print("skip: " + bumped.what) }
    is Task  { print("added: " + to_string(bumped.escalate())) }
}
```

## 1. Dependencies and build contract

* A C99 compiler (`gcc` on Linux). No C++ required.
* Standard C library plus `libm` (Bolt uses `math.h` for numeric intrinsics).
* No external third-party libraries are needed at runtime — the regex module
  ships a vendored `picomatch` engine inside the bolt source tree.
* CMake ≥ 3.16 is available if your build uses it. Any build system is
  acceptable as long as the install contract below holds.

### 1.1 Install contract

After `./setup.sh` completes, a freshly written C driver must build and run
with the following command, from any working directory:

```
gcc -std=c99 driver.c -lbolt -lm -o driver
./driver
```

For that command to work, `setup.sh` must place:

  * The compiled static library at `/usr/local/lib/libbolt.a` (so `-lbolt`
    resolves without a `-L` flag), and then run `ldconfig`.
  * All public headers under `/usr/local/include/` in the same tree layout
    they occupy in the source repository.    
  * A C driver reaches every public API by `#include "bolt.h"` (which
    transitively pulls in `bt_context.h`, `bt_object.h`, `bt_value.h`, and
    the buffer / opcode / tokenizer headers) plus, optionally,
    `#include "bt_embedding.h"` for the native-function helpers and
    `#include "boltstd/boltstd.h"` for the standard-library opener.

`setup.sh` runs offline (`PIP_NO_INDEX=1`; no network); `apt-get install` and
`pip install` inside it will fail. A CLI shell does not need
to be installed.

## 2. C embedding API

All public entry points are prefixed `bt_`, use `lower_snake_case` for
functions and `PascalCase` for types, and take the owning `bt_Context*` as
the first argument whenever they may allocate. Callers must include one or
more of `"bolt.h"`, `"bt_embedding.h"`, and `"boltstd/boltstd.h"`.

### 2.1 Context lifecycle

```c
typedef struct bt_Context bt_Context;

typedef struct bt_Handlers {
    void*  (*alloc)  (size_t size);
    void   (*free)   (void* ptr);
    void*  (*realloc)(void* ptr, size_t size);
    void   (*on_error)(bt_ErrorType type, const char* module,
                       const char* message, uint16_t line, uint16_t col);
    void   (*write)   (bt_Context* ctx, const char* msg);
    char*  (*read_file) (bt_Context* ctx, const char* path, void** out_handle);
    void   (*close_file)(bt_Context* ctx, const char* path, void*  in_handle);
    void   (*free_source)(bt_Context* ctx, char* source);
} bt_Handlers;

typedef enum { BT_ERROR_PARSE, BT_ERROR_COMPILE, BT_ERROR_RUNTIME } bt_ErrorType;

bt_Handlers bt_default_handlers(void);
void        bt_open (bt_Context** context, bt_Handlers* handlers);
void        bt_close(bt_Context* context);
```

`bt_default_handlers()` returns a struct populated with sensible libc defaults
(`malloc`/`realloc`/`free`, `fopen`/`fclose`, a `write` callback that calls
`printf("%s", msg)` on stdout, and an `on_error` callback that prints a
labelled error line for parse, compile, and runtime errors). Copy the return
value, mutate any field you want to override, and pass a pointer to `bt_open`.

`bt_open` allocates a fresh context using `handlers->alloc`, initialises the
GC and interned string table, registers the fundamental types (`number`,
`bool`, `string`, `null`, `any`, `Type`, `array`, `table`, `module`), and
sets sensible defaults for the compiler and the module search path.
`bt_close` runs a full GC sweep, frees the context and every object it
owns, then frees the module-path chain.

### 2.2 Running bolt source

```c
bt_bool    bt_run           (bt_Context* context, const char* source);
bt_Module* bt_compile_module(bt_Context* context, const char* source,
                             const char* module_name);
```

`bt_run` compiles `source` as an anonymous module, executes it on a
temporary thread, and returns `BT_TRUE` on success or `BT_FALSE` if a parse,
compile, or runtime error occurred (the error is reported through
`handlers->on_error`).

`bt_compile_module` produces a `bt_Module*` without running it. The returned
module can subsequently be executed with `bt_execute` (see §2.3) to populate
its `export` bindings, then queried for individual exports with
`bt_module_get_export`.

### 2.3 Threads and function invocation

```c
typedef struct bt_Thread   bt_Thread;
typedef union  bt_Callable bt_Callable;   /* modules, fns, closures, native fns */

bt_Thread* bt_make_thread   (bt_Context* context);
void       bt_destroy_thread(bt_Context* context, bt_Thread* thread);

bt_bool bt_execute          (bt_Context* context, bt_Callable* callable);
bt_bool bt_execute_on_thread(bt_Context* context, bt_Thread* thread,
                             bt_Callable* callable);
bt_bool bt_execute_with_args(bt_Context* context, bt_Thread* thread,
                             bt_Callable* callable,
                             bt_Value* args, uint8_t argc);
```

`bt_execute` allocates a temporary thread, invokes the callable on it, then
destroys the thread. Use it for one-shot calls such as running a compiled
module's body. `bt_execute_on_thread` runs on a caller-supplied thread
(which can be reused across many calls to amortise thread setup).
`bt_execute_with_args` additionally pushes `argc` positional arguments
before invoking.

All three return `BT_TRUE` iff the callable ran to completion without a
runtime error. On error, `handlers->on_error` receives a `BT_ERROR_RUNTIME`
message and the thread is left safe to destroy.

A `bt_Module*` is a valid `bt_Callable*` (invoking it runs the module body).
A pointer obtained from `BT_AS_OBJECT(exported_value)` for an exported bolt
function is also a valid `bt_Callable*`.

### 2.4 Modules and exports

```c
typedef struct bt_Module bt_Module;

bt_Module* bt_make_module      (bt_Context* context);
void       bt_register_module  (bt_Context* context, bt_Value name, bt_Module* module);

void       bt_module_export_native(bt_Context* context, bt_Module* module,
                                   const char* name, bt_NativeProc proc,
                                   bt_Type* return_type,
                                   bt_Type** arg_types, uint8_t arg_count);

bt_Value   bt_module_get_export(bt_Module* module, bt_Value key);
```

`bt_make_module` creates an empty module. `bt_register_module` registers it
under a string name so bolt code can `import <name>`.
`bt_module_export_native` binds a C function under a name inside a module,
carrying the full signature (`return_type` may be `NULL` for a fn that
returns nothing; `arg_types` may be `NULL` when `arg_count == 0`).
`bt_module_get_export` looks up an export by name and returns its
`bt_Value` (or `BT_VALUE_NULL` if absent).

The standard library is opened with:

```c
void boltstd_open_all(bt_Context* context);
```

which registers every module described in §3 on `context`.

### 2.5 The native-function protocol

A native function bound with `bt_module_export_native` must have the
signature:

```c
typedef void (*bt_NativeProc)(bt_Context* ctx, bt_Thread* thread);
```

Inside the body the helpers from `"bt_embedding.h"` retrieve arguments and
publish the return value:

```c
uint8_t  bt_argc(bt_Thread* thread);
bt_Value bt_arg (bt_Thread* thread, uint8_t idx);
void     bt_return(bt_Thread* thread, bt_Value value);
```

`bt_argc` returns the number of arguments passed to this invocation
(including variadic overflow). `bt_arg(thread, i)` returns the i-th
argument; the value is guaranteed to match the type declared for that slot
at registration time. `bt_return` writes the function's return value into
the thread's return slot; it does not stop execution, so call it exactly
once and then return from the C function normally.

### 2.6 Boxed values

The `bt_Value` type is a 64-bit NaN-boxed union. Callers construct and
consume values through helpers rather than reading the bits directly.

```c
typedef uint64_t bt_Value;

/* Constructors. */
bt_Value bt_make_number(double v);
bt_Value bt_make_bool  (bt_bool cond);
bt_Value bt_make_null  (void);
bt_Value bt_value      (bt_Object* obj);     /* box a bt_Object pointer */
#define  BT_VALUE_NULL              /* the boxed null value */
#define  BT_VALUE_CSTRING(ctx, str) /* box an interned C string as bt_Value */

/* Predicates. */
bt_bool bt_is_number(bt_Value v);
bt_bool bt_is_bool  (bt_Value v);
bt_bool bt_is_null  (bt_Value v);
bt_bool bt_is_object(bt_Value v);

/* Accessors — the caller is responsible for checking the type first. */
double     bt_get_number(bt_Value v);
bt_bool    bt_get_bool  (bt_Value v);
bt_Object* bt_object    (bt_Value v);
#define    BT_AS_OBJECT(v)   /* unbox to bt_Object*; UB if not an object */
```

### 2.7 Types registered with signatures

Every bound function needs a `bt_Type*` for each argument and (optionally)
the return type. The following primitive-type accessors return the singleton
`bt_Type*` registered on `context`:

```c
bt_Type* bt_type_number(bt_Context* context);
bt_Type* bt_type_bool  (bt_Context* context);
bt_Type* bt_type_string(bt_Context* context);
bt_Type* bt_type_any   (bt_Context* context);
bt_Type* bt_type_null  (bt_Context* context);
```

Pass an array of `bt_Type*` and its length as the `arg_types` / `arg_count`
arguments of `bt_module_export_native`.

### 2.8 Minimal embedding example

The following C driver opens a bolt context, exposes a native `add(a, b)`
function under a module named `demo`, and then runs bolt source that imports
and calls it. It is illustrative of the shape a real host application takes;
it is not a required file.

```c
#include <stdio.h>
#include "bolt.h"
#include "boltstd/boltstd.h"
#include "bt_embedding.h"

static void native_add(bt_Context* ctx, bt_Thread* thr) {
    double a = bt_get_number(bt_arg(thr, 0));
    double b = bt_get_number(bt_arg(thr, 1));
    bt_return(thr, bt_make_number(a + b));
}

int main(void) {
    bt_Context* ctx = NULL;
    bt_Handlers h   = bt_default_handlers();
    bt_open(&ctx, &h);
    boltstd_open_all(ctx);

    bt_Module* mod = bt_make_module(ctx);
    bt_Type*   num = bt_type_number(ctx);
    bt_Type*   args[] = { num, num };
    bt_module_export_native(ctx, mod, "add", native_add, num, args, 2);
    bt_register_module(ctx, BT_VALUE_CSTRING(ctx, "demo"), mod);

    bt_bool ok = bt_run(ctx,
        "import print from core\n"
        "import add   from demo\n"
        "print(add(3, 4))\n");

    bt_close(ctx);
    return ok ? 0 : 1;
}
```

### 2.9 Invoking a bolt-exported function from C

To call a bolt-defined function from C: compile the module, run its body so
its `export` bindings are populated, then look up the export and invoke it
via `bt_execute_with_args`.

```c
bt_Module* mod = bt_compile_module(ctx,
    "export fn multiply(a: number, b: number): number { return a * b }",
    "arith");
bt_execute(ctx, (bt_Callable*)mod);                              /* run module body */

bt_Value    fn  = bt_module_get_export(mod, BT_VALUE_CSTRING(ctx, "multiply"));
bt_Thread*  thr = bt_make_thread(ctx);
bt_Value    args[] = { bt_make_number(6), bt_make_number(7) };
bt_execute_with_args(ctx, thr, (bt_Callable*)BT_AS_OBJECT(fn), args, 2);
bt_destroy_thread(ctx, thr);
```

The same `bt_Thread*` may be reused across multiple invocations.

### 2.10 Overriding the write handler

`handlers->write(ctx, msg)` receives every substring emitted by `core.print`
/ `core.write` inside a bolt program — including the trailing `"\n"` that
`print` appends after its arguments. Replacing the default with a custom
callback is the supported way to redirect bolt output (to a buffer, a log
sink, a UI widget, etc.):

```c
static char capture[4096]; static int len = 0;
static void my_write(bt_Context* ctx, const char* msg) {
    int n = (int)strlen(msg);
    if (len + n < (int)sizeof(capture)) { memcpy(capture + len, msg, n); len += n; }
}

bt_Handlers h = bt_default_handlers();
h.write = my_write;
bt_open(&ctx, &h);
```

## 3. Standard library

Every stdlib function listed here is exposed on its module (`arrays.push(a, v)`),
and — where marked with **[proto]** — also as a prototype method on the
corresponding built-in type (`a.push(v)`). Both forms are equivalent.

### 3.1 `core`

```ts
type Error = unsealed {
    what: string
}

// Iterate all arguments, `to_string` each, join with a single space, and
// then emit the joined text through the context's write handler. `print`
// additionally appends a trailing "\n".
core.print(args: ..any)
core.write(args: ..any)

// Convert any bolt value to its string representation. Numbers with an
// integer value format as `%lld` (e.g. `"5"`); non-integer numbers format
// as `%.9f` (e.g. `"0.500000000"`); `true` / `false` / `null` render as
// those literal words. Table values with an `@format` metamethod format
// through it; a `Type` value renders as its type name (so
// `to_string(type(number))` is `"number"`, and each entry returned by
// `meta.get_union_entry` prints as its name); other objects render as
// `<0x…: kind>`.
core.to_string(x: any): string

// Construct an `Error` value with the given message. Used by fallible
// functions that return `T | Error`.
core.error(what: string): Error

// Run `f` on a fresh thread and return either its returned value or an
// `Error` describing a runtime error raised while it was running. Any
// runtime error inside `f` (including one raised by `core.throw`) is
// caught; the `Error`'s `what` is the runtime-error message.
core.protect(f: fn(..T): R, args?: ..T): R | Error

// If `r` is an `Error`, raise a runtime error whose message is
// (optionally) `reason + ": " + r.what` and whose exact wording is
// otherwise unspecified. Otherwise return `r` narrowed to the non-Error
// variant of the union.
core.assert(r: T | Error, reason?: string): T
```

### 3.2 `arrays`

Every function is a freestanding module member AND a prototype method on the
`array` type. Arrays are typed containers (`[T]`); indexing outside bounds
raises a runtime error.

```ts
arrays.length(a: [T]): number                                 // [proto] a.length()
arrays.push  (a: [T], item: T)                                // [proto] a.push(item)
arrays.pop   (a: [T]): T?                                     // [proto] a.pop()
arrays.each  (a: [T]): fn: T?                                 // [proto] a.each()
arrays.map   (a: [T], f: fn(T): R): [R]                       // [proto] a.map(f)
arrays.filter(a: [T], f: fn(T): bool): [T]                    // [proto] a.filter(f)
arrays.slice (a: [T], start: number, length: number): [T]     // [proto] a.slice(s, l)

// In-place; returns the same array (allowing chaining).
arrays.reverse(a: [T]): [T]                                   // [proto] a.reverse()

// In-place quicksort. The single-argument form is a fast path for
// [number] that requires no comparator; the two-argument form applies
// `less(x, y) -> bool` and works for any element type.
arrays.sort(a: [number]): [number]                            // [proto] a.sort()
arrays.sort(a: [T], less: fn(T, T): bool): [T]                // [proto] a.sort(less)

// Extend `dst` in place by appending every element of every source array,
// left to right.
arrays.concatenate(dst: [T], src: ..[T])                      // [proto] dst.concatenate(...)
```

`arrays.each(a)` returns a closure iterator: each call yields the next
element and returns `null` after the last one, making it usable as the
right-hand side of `for x in a.each() { ... }`.

### 3.3 `tables`

```ts
type Pair<K, V> = { key: K, value: V }

// Iterator over the (key, value) pairs of a table, yielding `null` after
// the last one. Suitable as the right-hand side of
// `for pair in tables.pairs(t) { … }`.
tables.pairs(t: table): fn: tables.Pair?
tables.length(t: table): number
```

### 3.4 `strings`

Every function is also a prototype method on the `string` type.

```ts
strings.length(s: string): number                             // [proto] s.length()

// Copy the substring `[start, start+length)` of `s`.
strings.substring(s: string, start: number, length: number): string    // [proto]

// Return the byte offset of the first occurrence of `needle` in `haystack`,
// or `-1` if absent.
strings.find(haystack: string, needle: string): number        // [proto]

// Return a new string with every occurrence of `from` in `s` replaced by
// `to` (non-overlapping, left-to-right).
strings.replace(s: string, from: string, to: string): string  // [proto]

// Return `true` iff `haystack` begins with `needle` (comparing bytes).
strings.starts_with(haystack: string, needle: string): bool   // [proto]

// Return a byte-reversed copy of `s`.
strings.reverse(s: string): string                            // [proto]

// printf-style formatter. Supported specifiers:
//   %d, %i  — argument formatted as a signed decimal integer.
//   %f      — argument formatted with default decimal notation.
//   %s, %v  — argument formatted via `core.to_string`.
//   %%      — a literal `%`.
// Extra arguments beyond the placeholders are ignored; missing arguments
// render as `<invalid>`.
strings.format(template: string, args: ..any): string         // [proto]
```

### 3.5 `math`

```ts
math.pi:       number         math.tau:      number         math.e:        number
math.epsilon:  number         math.infinity: number         math.nan:      number
math.huge:     number

math.sqrt (n: number): number
math.pow  (a: number, b: number): number
math.abs  (n: number): number
math.floor(n: number): number
math.ceil (n: number): number
math.mod  (a: number, b: number): number

math.min(n: number, rest: ..number): number
math.max(n: number, rest: ..number): number
```

### 3.6 `meta`

```ts
type meta.Annotation = { name: string, args: [any] }

// Run one GC cycle; return the number of objects collected.
meta.gc(): number

// Return the number of variants in a union `Type`.
meta.get_union_size(t: Type): number

// Return the n-th variant type of a union (0-based, in declaration order).
meta.get_union_entry(t: Type, n: number): Type

// Return every annotation attached to `t` in source order. `t` may be a
// Type value, a function or closure value, or any object that carries
// annotations. Returns an empty array on values without annotations.
meta.annotations(t: any): [meta.Annotation]

// Return the annotations attached to `field` inside the tableshape `t`.
// `field` is typically a string key. Returns an empty array on fields
// without annotations, or on values of `t` that are not tableshapes.
meta.field_annotations(t: Type, field: any): [meta.Annotation]
```

### 3.7 `regex`

```ts
type Regex = <opaque userdata>

// Compile a pattern into a `Regex` object, or return an `Error` if the
// pattern is invalid.
regex.compile(pattern: string): Regex | Error

// Return the number of capture groups in `r`, INCLUDING the group-zero
// full-match capture (so a pattern with two parenthesised captures
// reports `3`).
regex.groups(r: Regex): number                                // [proto] r.groups()

// Match `r` against `s`. On a match, return an array of `groups(r)`
// strings: index 0 is the full match, indices 1.. are the parenthesised
// captures in source order. On no match, return `null`.
regex.eval(r: Regex, s: string): [string]?                    // [proto] r.eval(s)
```

### 3.8 `io`

The `io` module wraps the C standard-library file API. `File` is an opaque
userdata handle; all functions may fail and return an `Error`, which is
typically unwrapped with `core.assert(io.open(path, mode), "…")`.

```ts
type File = <opaque userdata>

// `mode` follows fopen(3): "r", "w", "rb", "wb", etc.
io.open(path: string, mode: string): File | Error

// Read up to `length` bytes starting from the file's current position.
io.read(f: File, length: number): string | Error

// Write `content` at the current position.
io.write(f: File, content: string): Error?

// Return the total size of the file in bytes.
io.get_size(f: File): number | Error

// Close a file handle. Returns an `Error` if already closed.
io.close(f: File): Error?
```

## 4. Bolt language

Bolt is statically typed with rich local type inference. Types are inferred
whenever possible (from initialisers, from `return` sites, from `is`
narrowings); explicit annotations pin a value's type when inference is
ambiguous or when documenting intent.

### 4.1 Fundamental types

| Bolt type | What it holds                                                    |
|-----------|------------------------------------------------------------------|
| `number`  | IEEE-754 double-precision floating point.                        |
| `bool`    | `true` or `false`.                                               |
| `string`  | Immutable UTF-8 byte sequence.                                   |
| `null`    | The single value `null`.                                         |
| `any`     | Union of all types; must be narrowed before being operated on.   |
| `Type`    | A first-class type value produced by `type(...)` / `typeof(...)`.|

Bolt has **no truthiness**: every conditional expression must have static
type `bool`. `0`, `""`, and empty arrays are all valid `bool`-typed uses of
comparison, not truthy proxies.

### 4.2 Literals, arrays, and tables

```
let a = 0             // number
let b = 0.5           // number
let s = "hello"       // string
let n = null          // null
let t = true          // bool

let arr    = [1, 2, 3]                // typed as [number]
let mixed  = [1, true, "x"]           // typed as [number | bool | string]
let typed  = [1, 2, 3 : number]       // explicit element type
let widen  = [1, 2 : any]             // widen the element type to any

let point  = { x: 10, y: 20 }         // sealed table: only `x` and `y` may be
                                      // read or written on this value.
let bag    = unsealed { x: 10 }       // unsealed table: `bag.y = 5` is legal;
                                      // reading an undefined key yields `any`
                                      // (which is `null` when the key is absent).
```

Bracket access works uniformly: `arr[1]`, `point["x"]`, `bag[key]`. For
string-typed keys, `.name` is shorthand for `["name"]`.

### 4.3 Bindings

```
let x = 10           // mutable binding, inferred type
let const c = 20     // immutable binding; also disallows interior mutation
let const y: number  // typed with default value (0 for number, "" for
                     // string, false for bool, null for any, an empty
                     // instance for a tableshape whose members can default,
                     // etc.)
```

`const` prohibits both reassignment and interior mutation, so
`let const t = { x: 1 }; t.x = 2` is a compile-time error.

### 4.4 Operators

```
+ - * /              arithmetic on `number`
-x                   negation
+                    string concatenation (when both sides are `string`)
== !=                equality (structural for primitives; identity for
                     arrays and tables unless overridden by `@eq` / `@neq`)
< <= > >=            numeric ordering (or via `@lt` / `@lte`)
and or not           bool logic (no truthiness coercion)
[ ]                  index a table or array
.                    field access on a table
```

Null-related operators:

```
x?      postfix test — evaluates to `true` iff `x` is not `null`; inside an
        `if x? { … }`, `x` is narrowed to a non-null type in the body.
x!      postfix unwrap — evaluates to `x` narrowed to a non-null type; raises
        a runtime error if `x` is `null`.
a ?? b  null-coalescing — evaluates to `a` if it is non-null, else `b`. The
        expression's type is the union of the operand types minus `null`.
t?.k    null-safe indexing — walks through `null` intermediates, yielding
        `null` if any step is `null`.
```

Type operators:

```
x is T   evaluates to `bool`; also narrows `x` to `T` within the block of an
         enclosing `if` / `match` branch where it is the sole condition.
x as T   attempts a value-level cast; result type is `T?` (yields `null`
         on failure). `x as T!` combines the cast with `!` to unwrap.

type(T)      returns a `Type` value representing the type expression T.
typeof(expr) returns a `Type` value for the static type of `expr`
             (the expression is not evaluated).
```

### 4.5 Control flow

**If / else / if let.** `if` and `else if` chains may be either block-bodied
(`if x { … } else { … }`) or single-expression bodied (`if x then … else …`).

```
if x > 0 { … }
else if x == 0 { … }
else { … }

if x > 0 then print(x)      // single-expression form
else print(-x)

if let y = maybe() { … }    // `maybe` returns T?; the branch runs only when
                            // the value is non-null and binds it as `y`.
```

**Match.** Statement-form match uses block bodies for each arm; an `else`
arm is optional. When the arm condition is `is Type`, the matched binding
is narrowed to `Type` inside that arm's body.

```
match value {
    is number { … }
    is bool   { … }
    is string { … }
    else      { … }
}

// `match let` binds the matched expression to a fresh name.
match let r = safe_divide(a, b) {
    is Error  { print("failed: " + r.what) }
    is number { print("got: " + to_string(r)) }
}
```

Match arms may also match:

```
match n {
    < 0        { … }        // operator-prefix arm
    0          { … }        // literal arm
    1, 2, 3    { … }        // multiple literals share one body
    > 100      { … }
    else       { … }
}
```

**Match as an expression.** When used as an expression, arms use the
`then <expr>` form separated by commas or newlines, and every arm must produce a value:

```
let name = match n {
    1, 2, 3 then "small",
    > 100   then "huge",
    else "mid"
}
```

The value of a match-expression is the value of the taken arm; the result
type is the narrowest union of every arm's expression type.

**For.** Four flavours of loop are spelt with the `for` keyword. In every
case, `{ body }` can be replaced with `do <single-expression>`.

```
for i in 10 { … }                 // numeric: i takes 0, 1, …, 9
for i in 5 to 10 { … }             // numeric: i takes 5, 6, …, 9
for i in 0 to 10 by 2 { … }        // numeric with step
for cond { … }                     // while-style: repeat while `cond`
for { … }                          // infinite loop
for x in a.each() { … }            // iterator: run until iterator yields null
```

Adding `const` to the iterator binding makes the element immutable:
`for const x in a.each() { … }`.

**For-expression.** A `for` used as an expression collects each iteration's
value into an array:

```
let squares: [number] = for i in 5 do i * i    // [0, 1, 4, 9, 16]
```

`break` exits the enclosing loop; `continue` starts the next iteration.

### 4.6 Functions

```
fn add(a: number, b: number): number { return a + b }

fn add_default(a: number, b: number) { return a + b }  // return type inferred

fn log(x: number): ! { print(x) }                       // ! = returns nothing

let const inc = fn(a: number) { return a + 1 }          // anonymous fn value
```

A zero-argument function may omit the parameter list entirely:
`fn make_counter { … }` is equivalent to `fn make_counter() { … }`, and an
anonymous `fn { … }` is equivalent to `fn() { … }`.

Statement-form `fn` desugars to `let const <name> = fn(…): … { … }`;
recursion is supported only for statement-form functions with a fully
declared return type (so `fn fib(n: number): number { … }` can call itself,
but a `let const fib = fn(n) { … }` cannot).

**Closures.** Anonymous functions capture their enclosing scope's bindings
by reference. Primitive types (number, bool, string, null) are captured by
value at closure-construction time; complex types (arrays, tables) are
captured by reference and therefore share state across every closure that
captured the same binding.

**Iterators.** Any function of shape `fn: T?` is a valid iterator: calling
it repeatedly must yield successive values and finally `null`. That's what
`arrays.each` and `tables.pairs` return, and it's what a user-defined
iterator needs to produce.

### 4.7 Prototypes and methods

A tableshape can carry methods on its prototype. Declaring `fn T.name(…)`
adds a method to `T`'s prototype; when the first parameter is itself of
type `T`, the method is dot-callable on a value of `T`:

```
type Vec2 = { x: number, y: number }

fn Vec2.new(x: number, y: number) {
    return Vec2 => { x: x, y: y }               // `=>` = typed table literal
}

fn Vec2.sum(this) {                              // `this` is sugar for a
    return this.x + this.y                       // parameter typed as `Vec2`
}

let v = Vec2.new(3, 7)
print(v.sum())                                   // dot-call: this = v
print(Vec2.sum(v))                               // explicit call: same result
```

The `T => { … }` "fat arrow" constructor produces a table typed as `T`
(rather than the anonymous shape of the literal), which attaches `T`'s
prototype methods.

### 4.8 Metamethods

Prototype methods whose names start with `@` override the built-in behaviour
of an operator when applied to a value of that type:

| Metamethod  | Overrides                                                   |
|-------------|-------------------------------------------------------------|
| `@add`      | `x + y`                                                     |
| `@sub`      | `x - y`                                                     |
| `@mul`      | `x * y`                                                     |
| `@div`      | `x / y`                                                     |
| `@lt`       | `x < y`  (also drives `x > y` by operand reorder)           |
| `@lte`      | `x <= y` (also drives `x >= y` by operand reorder)          |
| `@eq`       | `x == y`                                                    |
| `@neq`      | `x != y`                                                    |
| `@format`   | `core.to_string(x)` — invoked whenever `x` is stringified,  |
|             | including inside `core.print` / `core.write`.               |

```
fn Vec2.@add(this, other: Vec2) {
    return Vec2 => { x: this.x + other.x, y: this.y + other.y }
}
fn Vec2.@format(this) {
    return "V(" + to_string(this.x) + "," + to_string(this.y) + ")"
}
```

Compound assignments (`+=`, `-=`, `*=`, `/=`) use the corresponding
metamethod when either operand is a table with one defined.

### 4.9 Extension

A tableshape can extend another with `Base + { <new-fields> }`. The
extension inherits every layout field and every prototype method of the
base; a method defined on the extension with the same name overrides the
base's. When a value of the extension type is passed where the base type is
expected, calls through the base still dispatch to the extension's
overridden methods.

```
type Base = { name: string }
fn Base.greet(this) { print("hello " + this.name) }
fn Base.shout(this) { print("HEY " + this.name) }

type Derived = Base + { height: number }
fn Derived.greet(this) {
    Base.greet(this)                             // explicit base-method call
    print("height is " + to_string(this.height))
}

let d = Derived => { name: "Bob", height: 180 }
d.greet()          // "hello Bob" then "height is 180"
d.shout()          // "HEY Bob" — inherited unchanged from Base
```

Only one base type may be extended at a time.

### 4.10 Enums

```
type Color = enum { Red, Green, Blue }      // sealed: only these three values
let c = Color.Green
let n = c as number!                        // 1  (enums are 0-based ints)
let c2 = 2 as Color!                        // Color.Blue
let bad = 10 as Color                       // null — 10 is out of range
```

Enum-to-number and number-to-enum are `as`-casts and produce `T?`; casting
an out-of-range integer yields `null`.

### 4.11 Modules

Each bolt source file is a module. Registering native modules from C uses
the API in §2.4; the same import syntax reaches both flavours.

```
import core                             // module namespace
import * from core                      // wildcard: all exports as locals
import print, to_string, error from core   // named list
import core as c                        // alias

export let magic = 42                   // exports a binding
export fn multiply(a: number, b: number): number { return a * b }
```

An `export`-annotated `fn` or `let` adds the name to the module's exports
table; the value is available to importers and to `bt_module_get_export`.

### 4.12 Errors

`core.Error` is the standard error tableshape (`{ what: string }`).
Functions that can fail conventionally return `T | Error`; the caller
inspects the union with `match let` (§4.5) and narrows to either arm. This
is a discriminated-union pattern, not exception-based:

```
fn safe_divide(a: number, b: number): number | Error {
    if b == 0 { return error("cannot divide by zero") }
    return a / b
}

match let r = safe_divide(10, 0) {
    is Error  { print("failed: " + r.what) }
    is number { print("got: " + to_string(r)) }
}
```

`core.protect(f, …)` promotes a runtime error raised inside `f` (e.g. by
`core.throw` or an out-of-bounds array access) into an `Error` value
returned from `protect`.

### 4.13 Annotations

An annotation is a compile-time metadata tag attached to a type, field, or
method declaration. Annotations do not affect runtime behavior on their
own; they are read back at runtime via the `meta` module for reflection,
code generation, and API tagging.

Three syntactic forms:

```
#name                    marker annotation, no arguments
#name(a, b, c)           annotation carrying a call-style value list
#[name1, name2, ...]     bracket form combining multiple annotations
```

Multiple annotations on the same declaration may be written as adjacent
`#…` tokens (`#a #b type T = { … }`), inside a bracket list
(`#[a, b]`), or mixed (`#a #[b, c]`). All three forms produce the same
annotation list on the declaration, in source order. Each entry of a
bracket list is itself an annotation written without its `#`, so an entry
may carry its own argument list: `#[a(1), b]` is equivalent to `#a(1) #b`.

Attachment sites:

* **Type declarations** — a leading annotation attaches to the type value:
  ```
  #deprecated
  type Session = { id: number }
  ```
  Works for every kind of type — tableshape, enum, array, union, alias,
  extension (`Base + { … }`), and dictionary (`{ ..K: V }`).
* **Field declarations** inside a tableshape — the annotation attaches to
  the field slot:
  ```
  type Endpoint = {
      #route("/users")
      path: string
  }
  ```
* **Method declarations** — a leading annotation on `fn T.name(…)`
  attaches to the function value:
  ```
  #handler
  fn Session.refresh(this) { … }
  ```

Annotation arguments must be **literal expressions** — numbers, strings,
booleans, `null`, or previously-declared type names. Passing a runtime
identifier as an annotation argument is a compile-time error.

Reflection: `meta.annotations(t)` (§3.6) returns every annotation attached
to a type / function / closure value as `[meta.Annotation]`;
`meta.field_annotations(t, "field")` returns the annotations attached to a
specific field of a tableshape. Both return a fresh array on each call,
with elements in source order. Each element is a
`{ name: string, args: [any] }` — argument values retain their literal
types (numbers stay numbers, strings stay strings, and so on).
