# lauf

Implement `lauf` — a stack-based bytecode interpreter with a C API and a
C++17 implementation. `lauf` is intended for embedding into other language
implementations that need to produce and execute bytecode quickly (for
example, a compile-time `constexpr` evaluator inside a C++ compiler, or the
runtime of a small DSL). The public API is entirely a C ABI; internals may
be C++17.

## Deliverable

Your repository must, after running your own `setup.sh`, provide:

- **Headers** installed under `/usr/local/include/lauf/`, so that C or C++
  client code can write
  ```c
  #include <lauf/asm/builder.h>
  #include <lauf/vm.h>
  ```
  with no `-I` flag.
- **Static libraries** installed under `/usr/local/lib/` with the
  `liblauf*.a` and (if your build depends on lexy — see below)
  `liblexy*.a` naming pattern. Any client program that links every static
  library matching `/usr/local/lib/liblauf*.a` plus
  `/usr/local/lib/liblexy*.a` (inside `-Wl,--start-group … -Wl,--end-group`
  along with `-lstdc++ -lm -lpthread`) must be able to resolve every symbol
  declared in the public headers.

## Toolchain and dependencies

- The build environment provides `clang` and `clang++`; your `setup.sh` must
  invoke one of these. `gcc` is not installed.
- The C++ implementation may use one external parser-combinator library:
  [`lexy`](https://lexy.foonathan.net). The pre-fetched
  lexy source is available at `/opt/lexy-src`.
- The image ships `clang`, `cmake`, `ninja-build`, and `make`. No network at
  build time. No pip index available at runtime.

## Configuration header — `lauf/config.h`

Provides:

- `typedef int64_t  lauf_sint;` and `typedef uint64_t lauf_uint;` — the
  integer types used throughout the bytecode.
- `LAUF_HEADER_START` / `LAUF_HEADER_END` macros expanding to
  `extern "C" {` / `}` when compiled as C++ and empty in C. Every public
  header wraps its declarations in these two macros.
- `LAUF_LIKELY(cond)`, `LAUF_UNLIKELY(cond)`, `LAUF_TAIL_CALL`,
  `LAUF_NOINLINE`, `LAUF_FORCE_INLINE`, `LAUF_UNREACHABLE` — these macros
  must be defined. They may resolve to compiler-specific hints (e.g. attribute
  builtins) or to no-op equivalents; the API's observable behavior does not
  depend on which.

## Runtime values — `lauf/runtime/value.h`

The type manipulated by the value stack is:

```c
typedef union lauf_runtime_value {
    lauf_uint                     as_uint;
    lauf_sint                     as_sint;
    void*                         as_native_ptr;
    lauf_runtime_address          as_address;
    lauf_runtime_function_address as_function_address;
} lauf_runtime_value;
```

`lauf_runtime_address` is a 64-bit packed struct with **exactly** the
following field order and widths (this layout is part of the ABI — a caller
that treats the union as `uint64_t` may modify individual fields
bit-arithmetically):

```c
typedef struct lauf_runtime_address {
    uint64_t allocation : 30;   /* first (lowest bits): AND-friendly */
    uint64_t generation : 2;    /* SHIFT + AND-friendly */
    uint64_t offset : 32;       /* SHIFT-friendly (last, highest bits) */
} lauf_runtime_address;

static const lauf_runtime_address lauf_runtime_address_null =
    {0x3FFFFFFF, 0x3, 0xFFFFFFFF};
```

`lauf_runtime_function_address` is:

```c
typedef struct lauf_runtime_function_address {
    uint16_t index;
    uint8_t  input_count;
    uint8_t  output_count;
} lauf_runtime_function_address;

static const lauf_runtime_function_address
    lauf_runtime_function_address_null = {0xFFFF, 0xFF, 0xFF};
```

The two `_null` constants are the sentinel "invalid" addresses returned by
runtime queries on failure.

## Module — `lauf/asm/module.h`

A module is a self-contained unit of assembled bytecode: function
definitions, function declarations (for extern calls to other modules), and
global memory. Only opaque handles are exposed; internals are implementation
defined.

```c
typedef struct lauf_asm_module     lauf_asm_module;
typedef struct lauf_asm_global     lauf_asm_global;
typedef struct lauf_asm_function   lauf_asm_function;
typedef struct lauf_asm_chunk      lauf_asm_chunk;
typedef union  lauf_asm_inst       lauf_asm_inst;

typedef struct lauf_asm_signature {
    uint8_t input_count;
    uint8_t output_count;
} lauf_asm_signature;
```

Module lifecycle:

```c
lauf_asm_module* lauf_asm_create_module(const char* name);
void             lauf_asm_destroy_module(lauf_asm_module* mod);
void             lauf_asm_set_module_debug_path(lauf_asm_module* mod, const char* path);
const char*      lauf_asm_module_name(const lauf_asm_module* mod);
const char*      lauf_asm_module_debug_path(const lauf_asm_module* mod);
```

`create_module` stores the name; `module_name` returns it. `set_module_debug_path`
records a path for diagnostics; `module_debug_path` returns it (NULL if never
set).

Globals:

```c
typedef enum lauf_asm_global_permissions {
    LAUF_ASM_GLOBAL_READ_ONLY,
    LAUF_ASM_GLOBAL_READ_WRITE,
} lauf_asm_global_permissions;

lauf_asm_global* lauf_asm_add_global(lauf_asm_module* mod, lauf_asm_global_permissions perms);
void             lauf_asm_define_data_global(lauf_asm_module* mod, lauf_asm_global* global,
                                             lauf_asm_layout layout, const void* data);
void             lauf_asm_set_global_debug_name(lauf_asm_module* mod, lauf_asm_global* global,
                                                const char* name);
bool             lauf_asm_global_has_definition(const lauf_asm_global* global);
lauf_asm_layout  lauf_asm_global_layout(const lauf_asm_global* global);
const char*      lauf_asm_global_debug_name(const lauf_asm_global* global);
```

`add_global` returns a fresh handle each time (never the same pointer as a
previous call on the same module). `has_definition` is false until
`define_data_global` is called and true after. `define_data_global` with
`data == NULL` zero-initializes the region. The permissions passed to
`add_global` are metadata for runtime access checks; `has_definition` is
unaffected by them.

Functions:

```c
lauf_asm_function* lauf_asm_add_function(lauf_asm_module* mod, const char* name,
                                         lauf_asm_signature sig);
void               lauf_asm_export_function(lauf_asm_function* fn);
const char*        lauf_asm_function_name(const lauf_asm_function* fn);
lauf_asm_signature lauf_asm_function_signature(const lauf_asm_function* fn);
bool               lauf_asm_function_has_definition(const lauf_asm_function* fn);

const lauf_asm_function* lauf_asm_find_function_by_name(const lauf_asm_module* mod,
                                                        const char*            name);
```

`add_function` returns a handle whose signature is queryable via
`function_signature`. `has_definition` is false until you build a body for
the function (see the Builder section below), then true. `find_function_by_name`
does a linear search over the module and returns NULL if the name is not
present.

Chunks:

```c
lauf_asm_chunk*    lauf_asm_create_chunk(lauf_asm_module* mod);
lauf_asm_signature lauf_asm_chunk_signature(const lauf_asm_chunk* chunk);
bool               lauf_asm_chunk_is_empty(const lauf_asm_chunk* chunk);
```

Chunks are like functions but reusable — they have no name and can be re-built
in-place. `create_chunk` returns a fresh chunk belonging to `mod`;
`chunk_is_empty` is true when no body has been built yet, false after any body
is built. `chunk_signature` returns the chunk's `lauf_asm_signature`
(input/output counts of the most recently built body).

## Type — `lauf/asm/type.h`

```c
typedef struct lauf_asm_layout {
    size_t size;
    size_t alignment;
} lauf_asm_layout;

lauf_asm_layout lauf_asm_array_layout(lauf_asm_layout element_layout, size_t element_count);
lauf_asm_layout lauf_asm_aggregate_layout(const lauf_asm_layout* member_layouts, size_t member_count);
```

`array_layout` returns the layout that would hold `count` elements of
`element_layout` (respecting alignment). `aggregate_layout` returns the
layout of a struct whose members are the given layouts in order. Both follow
the usual C struct and array layout rules.

```c
typedef bool lauf_runtime_builtin_impl(const lauf_asm_inst* ip,
                                       lauf_runtime_value* vstack_ptr,
                                       lauf_runtime_stack_frame* frame_ptr,
                                       lauf_runtime_process* process);

typedef struct lauf_asm_type {
    lauf_asm_layout             layout;
    size_t                      field_count;
    lauf_runtime_builtin_impl*  load_fn;
    lauf_runtime_builtin_impl*  store_fn;
    const char*                 name;
    const struct lauf_asm_type* next;   /* linked-list link for a library */
} lauf_asm_type;

extern const lauf_asm_type lauf_asm_type_value;
```

`lauf_asm_type_value` is the type that corresponds to a `lauf_runtime_value` —
size 8, alignment 8, one field. It is used by `load_field` / `store_field`
in bytecode to move whole values between memory and the value stack.

## Assembler builder — `lauf/asm/builder.h`

The builder produces the body of a function or chunk. It has an internal
"insertion point" (currently active block) and mutable state; each builder
belongs to exactly one thread.

Signature values `lauf_asm_signature` are stack effects: `input_count` values
are consumed from the top of the value stack, and `output_count` values are
produced. Signatures apply to functions, blocks, and instructions.

```c
typedef struct lauf_asm_build_options {
    void (*error_handler)(const char* fn_name, const char* context, const char* msg);
} lauf_asm_build_options;

extern const lauf_asm_build_options lauf_asm_default_build_options;

typedef struct lauf_asm_builder lauf_asm_builder;

lauf_asm_builder* lauf_asm_create_builder(lauf_asm_build_options options);
void              lauf_asm_destroy_builder(lauf_asm_builder* b);

void lauf_asm_build(lauf_asm_builder* b, lauf_asm_module* mod, lauf_asm_function* fn);
void lauf_asm_build_chunk(lauf_asm_builder* b, lauf_asm_module* mod, lauf_asm_chunk* chunk,
                          lauf_asm_signature sig);
bool lauf_asm_build_finish(lauf_asm_builder* b);
```

`build_finish` returns true iff the body is well-formed (all blocks reachable,
signatures balanced, terminators in place). On failure it either invokes
`error_handler` (if set) or attempts to repair the error. If it returns
true, the function's `has_definition` becomes true.

Blocks:

```c
typedef struct lauf_asm_block lauf_asm_block;

lauf_asm_block* lauf_asm_entry_block(lauf_asm_builder* b);
lauf_asm_block* lauf_asm_declare_block(lauf_asm_builder* b, size_t input_count);
void            lauf_asm_build_block(lauf_asm_builder* b, lauf_asm_block* block);
lauf_asm_function* lauf_asm_build_get_function(lauf_asm_builder* b);
size_t             lauf_asm_build_get_vstack_size(lauf_asm_builder* b);
```

A function's body always starts with the entry block, and control flow is
expressed by terminator instructions (`return`, `jump`, `branch`, `panic`).
`build_block` changes the insertion point to append to the given block.
Between two blocks the builder tracks the "vstack size" — a static
approximation of how many values are on the value stack at that program
point. Terminators must leave the value stack at a size compatible with the
successor block's `input_count`.

Instructions come in four broad groups.

### Global data + local variables

```c
lauf_asm_global* lauf_asm_build_data_literal(lauf_asm_builder* b, const unsigned char* ptr, size_t size);
lauf_asm_global* lauf_asm_build_string_literal(lauf_asm_builder* b, const char* str);

typedef struct lauf_asm_local lauf_asm_local;

lauf_asm_local* lauf_asm_build_local(lauf_asm_builder* b, lauf_asm_layout layout);
lauf_asm_layout lauf_asm_local_layout(lauf_asm_builder* b, lauf_asm_local* local);
```

`build_data_literal` searches the module's existing constant globals for one
that matches the given bytes; if found, returns the existing global,
otherwise adds a new one. `build_string_literal` is
`build_data_literal(b, str, strlen(str) + 1)` — two calls with the same
literal in the same builder session return the same global.

Locals live on the call frame and are freed on return.

### Block terminators

```c
void lauf_asm_inst_return(lauf_asm_builder* b);
void lauf_asm_inst_jump(lauf_asm_builder* b, const lauf_asm_block* dest);
const lauf_asm_block* lauf_asm_inst_branch(lauf_asm_builder* b,
                                           const lauf_asm_block* if_true,
                                           const lauf_asm_block* if_false);
void lauf_asm_inst_panic(lauf_asm_builder* b);
void lauf_asm_inst_panic_if(lauf_asm_builder* b);
```

`inst_branch` pops the top value (a uint condition). If the popped value is
statically known at build time, it returns the block that was statically
selected (so the other branch's code generation can be skipped);
otherwise NULL. `inst_panic` pops the top value as a message pointer and
invokes the panic handler. `inst_panic_if` is the conditional form: it consumes
a message pointer from the top of the stack and a `uint` condition immediately
below it (`cond msg => _`), invoking the panic handler only when the condition
is non-zero.

### Value-stack instructions

```c
void lauf_asm_inst_uint(lauf_asm_builder* b, lauf_uint value);   /* push uint */
void lauf_asm_inst_sint(lauf_asm_builder* b, lauf_sint value);   /* push sint */
void lauf_asm_inst_bytes(lauf_asm_builder* b, const void* ptr);  /* push raw bytes as uint */
void lauf_asm_inst_null(lauf_asm_builder* b);                    /* push null address */
void lauf_asm_inst_global_addr(lauf_asm_builder* b, const lauf_asm_global* global);
void lauf_asm_inst_local_addr(lauf_asm_builder* b, lauf_asm_local* local);
void lauf_asm_inst_function_addr(lauf_asm_builder* b, const lauf_asm_function* function);
void lauf_asm_inst_layout(lauf_asm_builder* b, lauf_asm_layout layout);

typedef enum lauf_asm_inst_condition_code {
    LAUF_ASM_INST_CC_EQ, LAUF_ASM_INST_CC_NE, LAUF_ASM_INST_CC_LT,
    LAUF_ASM_INST_CC_LE, LAUF_ASM_INST_CC_GT, LAUF_ASM_INST_CC_GE,
} lauf_asm_inst_condition_code;

void lauf_asm_inst_cc(lauf_asm_builder* b, lauf_asm_inst_condition_code cc);
```

`inst_cc` pops a three-way comparison result (sint −1 / 0 / +1) and pushes
1 if the comparison matches the given code, else 0. It is typically emitted
right after a comparison builtin like `$lauf.int.scmp`.

`inst_layout` pushes the given layout onto the value stack as two `uint`s in
the order alignment then size (`_ => alignment:uint size:uint`): the alignment
is pushed first (ending up below), and the size is pushed on top.

### Stack shuffling

```c
typedef struct lauf_asm_value { uint32_t _id; } lauf_asm_value;

lauf_asm_value lauf_asm_inst_value(lauf_asm_builder* b, uint16_t stack_index);
uint16_t       lauf_asm_inst_value_stack_index(lauf_asm_builder* b, lauf_asm_value value);
void           lauf_asm_inst_pop(lauf_asm_builder* b, uint16_t stack_index);
void           lauf_asm_inst_pick(lauf_asm_builder* b, uint16_t stack_index);
void           lauf_asm_inst_roll(lauf_asm_builder* b, uint16_t stack_index);
void           lauf_asm_inst_select(lauf_asm_builder* b, uint16_t count);
```

`pick(N)` duplicates the value at depth N (0 = top). `roll(N)` moves the
value at depth N to the top. `pop(N)` removes the value at depth N.
`select(count)` implements a stack multiplexer (top is the index, then
`count` candidates, produces the chosen candidate).

`lauf_asm_value` gives you a stable id for a stack slot that survives
subsequent stack manipulations. Get it with `inst_value` (records the id
for the value currently at `stack_index`); resolve it back with
`inst_value_stack_index` (returns the current index of the value; it must
still be on the stack).

### Function calls

```c
void lauf_asm_inst_call(lauf_asm_builder* b, const lauf_asm_function* callee);
void lauf_asm_inst_call_indirect(lauf_asm_builder* b, lauf_asm_signature sig);
void lauf_asm_inst_call_builtin(lauf_asm_builder* b, lauf_runtime_builtin callee);

lauf_asm_function* lauf_asm_inst_call_extern(lauf_asm_builder* b, const char* name,
                                             lauf_asm_signature sig);
```

`call` invokes the given function of the current module. `call_indirect`
takes a function pointer from the top of the value stack and calls it with
the given signature. `call_builtin` calls a builtin (see the Builtin
section). `call_extern` declares a function with the given name if it is
not declared yet, then emits a call to it (used to reference symbols that
will be linked in from another module).

### Fibers

```c
void lauf_asm_inst_fiber_resume(lauf_asm_builder* b, lauf_asm_signature sig);
void lauf_asm_inst_fiber_transfer(lauf_asm_builder* b, lauf_asm_signature sig);
void lauf_asm_inst_fiber_suspend(lauf_asm_builder* b, lauf_asm_signature sig);
```

Each consumes / produces values per the `lauf_asm_signature` argument, with
the same convention (top of the stack is the rightmost operand):

- `fiber_resume`: `handle:fiber in_0 … in_(N-1) => out_0 … out_(M-1)` — the
  target fiber handle sits at the bottom, *below* the `sig.input_count`
  argument values that are passed to the resumed fiber. It runs the fiber to
  its next suspension point (or completion) and pushes the `sig.output_count`
  results back.
- `fiber_transfer`: same operand layout as `fiber_resume`
  (`handle:fiber in_0 … in_(N-1) => …`, the handle below the inputs), but it
  does not save the caller's continuation on top of the target — see the
  runtime process API.
- `fiber_suspend`: `in_0 … in_(N-1) => out_0 … out_(M-1)` — suspends the
  current fiber and passes control (and the input values) back to its resumer.

### Memory access

```c
void lauf_asm_inst_array_element(lauf_asm_builder* b, lauf_asm_layout element_layout);
void lauf_asm_inst_aggregate_member(lauf_asm_builder* b, size_t member_index,
                                    const lauf_asm_layout* member_layouts, size_t member_count);
void lauf_asm_inst_load_field(lauf_asm_builder* b, lauf_asm_type type, size_t field_index);
void lauf_asm_inst_store_field(lauf_asm_builder* b, lauf_asm_type type, size_t field_index);
```

`load_field` and `store_field` invoke the `load_fn` / `store_fn` of the
given type at the given field index. For `lauf_asm_type_value` the value is
a whole `lauf_runtime_value`.

The four instructions have these value-stack effects (top of the stack is
the rightmost operand, matching `panic_if`'s `cond msg => _`):

- `array_element`: `ptr:address index:sint => elem_ptr:address` — the base
  pointer is below the index; the computed element address is pushed.
- `aggregate_member`: `ptr:address => member_ptr:address` — replaces the base
  pointer with the address of the selected member.
- `load_field`: `ptr:address => value` — pops the address and pushes the
  loaded value.
- `store_field`: `value ptr:address => _` — the target address is on top of
  the stack and the value to store is immediately below it; both are consumed
  and nothing is pushed.

## Program — `lauf/asm/program.h`

```c
typedef struct lauf_asm_program {
    const lauf_asm_module*   _mod;
    const lauf_asm_function* _entry;
    void*                    _extra_data;
} lauf_asm_program;

lauf_asm_program lauf_asm_create_program(const lauf_asm_module* mod,
                                         const lauf_asm_function* entry);
lauf_asm_program lauf_asm_create_program_from_chunk(const lauf_asm_module* mod,
                                                    const lauf_asm_chunk* chunk);

void lauf_asm_link_modules(lauf_asm_program* program, const lauf_asm_module* const* mods, size_t size);
void lauf_asm_link_module(lauf_asm_program* program, const lauf_asm_module* mod);
void lauf_asm_destroy_program(lauf_asm_program program);

typedef bool (*lauf_asm_native_function)(void* user_data, lauf_runtime_process* process,
                                         const lauf_runtime_value* input,
                                         lauf_runtime_value*       output);

void lauf_asm_define_native_global(lauf_asm_program* program, const lauf_asm_global* global,
                                   void* ptr, size_t size);
void lauf_asm_define_native_function(lauf_asm_program* program, const lauf_asm_function* fn,
                                     lauf_asm_native_function native_fn, void* user_data);

const lauf_asm_function* lauf_asm_program_entry_function(const lauf_asm_program* program);
```

A program bundles one or more modules and one entry function. The `_extra_data`
slot holds per-program native definitions and linked module list; you
control its lifetime. `link_module` resolves extern-function references by
name — if `program` has a `call_extern("f", …)`, and `mod` has a defined
function `"f"`, subsequent execution of the program calls the definition.

`define_native_global` overlays a program global with native (host) memory.
`define_native_function` overlays a program function with a C callback; the
callback receives arrays of input / output values in the same order as the
function's signature and returns `true` on success or `false` (via
`lauf_runtime_panic`) on failure.

## VM — `lauf/vm.h`

```c
typedef struct lauf_vm_panic_handler {
    void* user_data;
    void (*callback)(void* user_data, lauf_runtime_process* p, const char* msg);
} lauf_vm_panic_handler;

typedef struct lauf_vm_allocator {
    void* user_data;
    void* (*heap_alloc)(void* user_data, size_t size, size_t alignment);
    void  (*free_alloc)(void* user_data, void* ptr, size_t size);   /* size may be 0 */
} lauf_vm_allocator;

extern const lauf_vm_allocator lauf_vm_null_allocator;
extern const lauf_vm_allocator lauf_vm_malloc_allocator;

typedef struct lauf_vm_options {
    size_t initial_vstack_size_in_elements;
    size_t max_vstack_size_in_elements;
    size_t max_cstack_size_in_bytes;
    size_t initial_cstack_size_in_bytes;
    size_t step_limit;               /* 0 = unlimited */
    lauf_vm_panic_handler panic_handler;
    lauf_vm_allocator     allocator;
    void*                 user_data;
} lauf_vm_options;

extern const lauf_vm_options lauf_default_vm_options;

typedef struct lauf_vm lauf_vm;

lauf_vm* lauf_create_vm(lauf_vm_options options);
void     lauf_destroy_vm(lauf_vm* vm);

lauf_vm_panic_handler lauf_vm_set_panic_handler(lauf_vm* vm, lauf_vm_panic_handler h);
lauf_vm_allocator     lauf_vm_set_allocator(lauf_vm* vm, lauf_vm_allocator a);
lauf_vm_allocator     lauf_vm_get_allocator(lauf_vm* vm);
void*                 lauf_vm_set_user_data(lauf_vm* vm, void* user_data);
void*                 lauf_vm_get_user_data(lauf_vm* vm);

lauf_runtime_process* lauf_vm_start_process(lauf_vm* vm, const lauf_asm_program* program);

bool lauf_vm_execute(lauf_vm* vm, const lauf_asm_program* program,
                     const lauf_runtime_value* input, lauf_runtime_value* output);
bool lauf_vm_execute_oneshot(lauf_vm* vm, lauf_asm_program program,
                             const lauf_runtime_value* input, lauf_runtime_value* output);
```

`lauf_default_vm_options` provides sensible defaults (in particular a
`malloc`-based allocator and a no-op panic handler that just prints to
stderr). `vm_set_panic_handler` / `vm_set_allocator` swap in a new handler
and return the previous one.

`execute` runs the entry function to completion with the given input
values. `execute_oneshot` behaves as `execute` followed by
`asm_destroy_program`.

Input values are written from bottom to top: `input[0]` is the value at the
bottom of the entry function's stack, `input[N]` at the top. Outputs follow
the same convention.

If a panic occurs mid-execution, the handler is invoked and `execute*`
returns false. On false, `output` is not modified.

## Runtime process — `lauf/runtime/process.h`

```c
typedef struct lauf_runtime_process lauf_runtime_process;
typedef struct lauf_runtime_fiber   lauf_runtime_fiber;

typedef enum lauf_runtime_fiber_status {
    LAUF_RUNTIME_FIBER_READY,      /* 0 - created, not yet resumed */
    LAUF_RUNTIME_FIBER_RUNNING,    /* 1 */
    LAUF_RUNTIME_FIBER_SUSPENDED,  /* 2 */
    LAUF_RUNTIME_FIBER_DONE,       /* 3 */
} lauf_runtime_fiber_status;

lauf_vm*                 lauf_runtime_get_vm(lauf_runtime_process* process);
void*                    lauf_runtime_get_vm_user_data(lauf_runtime_process* process);
const lauf_asm_program*  lauf_runtime_get_program(lauf_runtime_process* process);

lauf_runtime_fiber*      lauf_runtime_get_current_fiber(lauf_runtime_process* process);
lauf_runtime_fiber*      lauf_runtime_iterate_fibers(lauf_runtime_process* process);
lauf_runtime_fiber*      lauf_runtime_iterate_fibers_next(lauf_runtime_fiber* iter);
bool                     lauf_runtime_is_single_fibered(lauf_runtime_process* process);

lauf_runtime_address       lauf_runtime_get_fiber_handle(const lauf_runtime_fiber* fiber);
lauf_runtime_fiber_status  lauf_runtime_get_fiber_status(const lauf_runtime_fiber* fiber);
lauf_runtime_fiber*        lauf_runtime_get_fiber_parent(lauf_runtime_process* process,
                                                         lauf_runtime_fiber* fiber);
const lauf_runtime_value*  lauf_runtime_get_vstack_ptr(lauf_runtime_process* process,
                                                       const lauf_runtime_fiber* fiber);
const lauf_runtime_value*  lauf_runtime_get_vstack_base(const lauf_runtime_fiber* fiber);

bool  lauf_runtime_call(lauf_runtime_process* process, const lauf_asm_function* fn,
                        const lauf_runtime_value* input, lauf_runtime_value* output);
lauf_runtime_fiber* lauf_runtime_create_fiber(lauf_runtime_process* process,
                                              const lauf_asm_function* fn);
bool  lauf_runtime_resume(lauf_runtime_process* process, lauf_runtime_fiber* fiber,
                          const lauf_runtime_value* input, size_t input_count,
                          lauf_runtime_value* output, size_t output_count);
bool  lauf_runtime_resume_until_completion(lauf_runtime_process* process,
                                           lauf_runtime_fiber* fiber,
                                           const lauf_runtime_value* input, size_t input_count,
                                           lauf_runtime_value* output, size_t output_count);
bool  lauf_runtime_destroy_fiber(lauf_runtime_process* process, lauf_runtime_fiber* fiber);
bool  lauf_runtime_panic(lauf_runtime_process* process, const char* msg);
void  lauf_runtime_destroy_process(lauf_runtime_process* process);

bool  lauf_runtime_set_step_limit(lauf_runtime_process* process, size_t new_limit);
bool  lauf_runtime_increment_step(lauf_runtime_process* process);
```

A process is created by `vm_start_process` and destroyed by
`runtime_destroy_process`. Every process has an initial "entry fiber" for
the program's entry function in the `READY` state. `resume(fiber, in, in_n,
out, out_n)` transitions the fiber to `RUNNING`; when the fiber suspends or
returns, the resumer sees the fiber back in `SUSPENDED` or `DONE`.
`resume_until_completion` keeps calling `resume` on whichever fiber is
current until the current fiber is done; the final current fiber is then
destroyed automatically.

`get_vstack_base` returns the base of the given fiber's value-stack storage
and `get_vstack_ptr` that fiber's current position within it; both are valid
non-null pointers for any live fiber, including one whose value stack
currently holds no values.

`panic` invokes the VM's panic handler and always returns `false` (a
convenience so a builtin can `return lauf_runtime_panic(p, msg);`).

`set_step_limit(new_limit)` sets the process's remaining step budget and
returns `true`; if the VM's configured `step_limit` ceiling is non-zero and
`new_limit` exceeds it, the budget is left unchanged and it returns `false` (a
ceiling of `0` — the "unlimited" default — accepts any limit). `increment_step`
consumes one step from the budget: while the remaining budget is `0`
(unlimited) it always returns `true`; otherwise it decrements the budget and
returns `false` on the increment that drives the budget to `0`, and `true`
before that — so with a budget of N the Nth `increment_step` call returns
`false`.

## Runtime memory — `lauf/runtime/memory.h`

```c
const void* lauf_runtime_get_const_ptr(lauf_runtime_process* p, lauf_runtime_address addr,
                                       lauf_asm_layout layout);
void*       lauf_runtime_get_mut_ptr(lauf_runtime_process* p, lauf_runtime_address addr,
                                     lauf_asm_layout layout);
const char* lauf_runtime_get_cstr(lauf_runtime_process* p, lauf_runtime_address addr);

bool  lauf_runtime_get_address(lauf_runtime_process* p, lauf_runtime_address* allocation,
                               const void* ptr);
lauf_runtime_address lauf_runtime_get_global_address(lauf_runtime_process* p,
                                                     const lauf_asm_global* global);
const lauf_asm_function* lauf_runtime_get_function_ptr_any(lauf_runtime_process* p,
                                                           lauf_runtime_function_address addr);
const lauf_asm_function* lauf_runtime_get_function_ptr(lauf_runtime_process* p,
                                                       lauf_runtime_function_address addr,
                                                       lauf_asm_signature signature);
lauf_runtime_fiber* lauf_runtime_get_fiber_ptr(lauf_runtime_process* p,
                                               lauf_runtime_address addr);
```

`get_const_ptr` returns a raw pointer if the allocation at `addr` is readable
for the given layout (i.e. exists, is not poisoned, and has at least
`layout.size` bytes at that offset with the required alignment); NULL
otherwise. `get_mut_ptr` is the same but additionally requires the allocation
to be writable (a `LAUF_RUNTIME_STATIC_ALLOCATION` created via
`add_static_const_allocation` fails the mut check — see below).
`get_cstr` returns a NUL-terminated C string starting at the address if
one is present; NULL otherwise.
`get_address` performs the inverse of `get_*_ptr` for a native pointer: given
an address in `*allocation` that already identifies the target allocation, it
computes the byte offset of `ptr` from that allocation's base, updates
`allocation->offset` to that offset, and returns `true`. It returns `false`
(leaving `*allocation` unchanged) if `ptr` does not fall within the
allocation's `[base, base + size)` range. Only the `offset` field is updated;
the allocation index and generation carried in `*allocation` are preserved.

`get_function_ptr_any` converts a function address back into the module
function it designates, returning NULL if the address is invalid (including the
`lauf_runtime_function_address_null` sentinel). `get_function_ptr` does the
same but additionally requires the address to carry the requested `signature`:
it returns NULL unless the address's `input_count` / `output_count` equal the
supplied `signature`, and otherwise resolves the same function
`get_function_ptr_any` would. A function address's `index` field identifies the
target function by its 0-based position among the functions added to the module
in insertion order — the first `add_function` is index 0, the next is 1, and so
on (the same order `find_function_by_name` scans) — so the null sentinel's
`index` (`0xFFFF`) matches no function. `get_fiber_ptr` correspondingly resolves
a fiber handle obtained from `get_fiber_handle` back to its fiber, returning
NULL for an invalid handle.

Allocations:

```c
typedef enum lauf_runtime_allocation_source {
    LAUF_RUNTIME_STATIC_ALLOCATION,
    LAUF_RUNTIME_LOCAL_ALLOCATION,
    LAUF_RUNTIME_HEAP_ALLOCATION,
} lauf_runtime_allocation_source;

typedef enum lauf_runtime_permission {
    LAUF_RUNTIME_PERM_NONE       = 0,
    LAUF_RUNTIME_PERM_READ       = 1 << 0,
    LAUF_RUNTIME_PERM_WRITE      = 1 << 1,
    LAUF_RUNTIME_PERM_READ_WRITE = LAUF_RUNTIME_PERM_READ | LAUF_RUNTIME_PERM_WRITE,
} lauf_runtime_permission;

typedef struct lauf_runtime_allocation {
    lauf_runtime_allocation_source source;
    lauf_runtime_permission        permission;
    void*                          ptr;
    size_t                         size;
} lauf_runtime_allocation;

bool                 lauf_runtime_get_allocation(lauf_runtime_process* p,
                                                 lauf_runtime_address addr,
                                                 lauf_runtime_allocation* result);
lauf_runtime_address lauf_runtime_add_static_const_allocation(lauf_runtime_process* p,
                                                              const void* ptr, size_t size);
lauf_runtime_address lauf_runtime_add_static_mut_allocation(lauf_runtime_process* p,
                                                            void* ptr, size_t size);
lauf_runtime_address lauf_runtime_add_heap_allocation(lauf_runtime_process* p,
                                                      void* ptr, size_t size);
bool                 lauf_runtime_leak_heap_allocation(lauf_runtime_process* p,
                                                       lauf_runtime_address addr);
size_t               lauf_runtime_gc(lauf_runtime_process* p);

bool lauf_runtime_poison_allocation(lauf_runtime_process* p, lauf_runtime_address addr);
bool lauf_runtime_unpoison_allocation(lauf_runtime_process* p, lauf_runtime_address addr);
bool lauf_runtime_split_allocation(lauf_runtime_process* p, lauf_runtime_address addr,
                                   lauf_runtime_address* addr1, lauf_runtime_address* addr2);
bool lauf_runtime_merge_allocation(lauf_runtime_process* p,
                                   lauf_runtime_address addr1, lauf_runtime_address addr2);
bool lauf_runtime_declare_reachable(lauf_runtime_process* p, lauf_runtime_address addr);
bool lauf_runtime_undeclare_reachable(lauf_runtime_process* p, lauf_runtime_address addr);
bool lauf_runtime_declare_weak(lauf_runtime_process* p, lauf_runtime_address addr);
bool lauf_runtime_undeclare_weak(lauf_runtime_process* p, lauf_runtime_address addr);
```

Semantic contract:

- `add_static_const_allocation` registers a read-only overlay on host memory.
  `get_mut_ptr` on such an allocation MUST return NULL.
- `add_static_mut_allocation` registers a read-write overlay.
- `add_heap_allocation` registers a heap allocation that participates in GC.
- The garbage collector is a conservative tracing GC: `gc()` sweeps all
  heap allocations that are unreachable and returns the number of bytes
  freed. `declare_reachable` / `declare_weak` let a user adjust reachability.
- `poison_allocation` marks the allocation as temporarily inaccessible;
  `get_*_ptr` on a poisoned allocation returns NULL until it is unpoisoned.
- `split_allocation` splits the allocation referenced by `addr` at the byte
  offset carried in `addr`, producing two independently-usable sub-allocations:
  `addr1` addresses the lower part (offsets `[0, split)`) and `addr2` the upper
  part (offsets `[split, size)`). Returns false if `addr` does not reference a
  usable allocation or its offset is out of range.
- `merge_allocation` reverses a split: given two adjacent sub-allocations with
  `addr1` immediately preceding `addr2` in memory, it recombines them into a
  single allocation addressable via `addr1` (which then spans the combined
  range). Returns false unless both addresses reference usable, previously-split,
  adjacent allocations.

## Reader / Writer — `lauf/reader.h`, `lauf/writer.h`

Readers are the input side of the text frontend; writers are the output side
of the dump backend. Both are opaque and destroyed via a matching destroy
call.

```c
typedef struct lauf_reader lauf_reader;

void         lauf_destroy_reader(lauf_reader* reader);
void         lauf_reader_set_path(lauf_reader* reader, const char* path);
lauf_reader* lauf_create_string_reader(const char* str, size_t size);
lauf_reader* lauf_create_cstring_reader(const char* str);
lauf_reader* lauf_create_file_reader(const char* path);  /* NULL on failure */
lauf_reader* lauf_create_stdin_reader(void);

typedef struct lauf_writer lauf_writer;

void         lauf_destroy_writer(lauf_writer* writer);
lauf_writer* lauf_create_string_writer(void);
const char*  lauf_writer_get_string(lauf_writer* string_writer);
lauf_writer* lauf_create_file_writer(const char* path);
lauf_writer* lauf_create_stdout_writer(void);
```

`create_file_reader` returns NULL if the file cannot be opened. The path
passed to `reader_set_path` must remain valid until the reader is destroyed.
`writer_get_string` returns a pointer to the accumulated output of a
string writer; it is valid until the writer is destroyed.

## Text frontend — `lauf/frontend/text.h`

```c
typedef struct lauf_frontend_text_options {
    const lauf_runtime_builtin_library* builtin_libs;
    size_t                              builtin_libs_count;
} lauf_frontend_text_options;

extern const lauf_frontend_text_options lauf_frontend_default_text_options;

lauf_asm_module* lauf_frontend_text(lauf_reader* reader, lauf_frontend_text_options options);
```

`frontend_text` reads a textual lauf module from the reader and produces an
assembled `lauf_asm_module`. On syntax or semantic error it prints
diagnostics to stderr and returns NULL. `builtin_libs` lets the parser
resolve `$lib.name`-prefixed builtin names (see the Text format section
below).

## Dump backend — `lauf/backend/dump.h`

```c
typedef struct lauf_backend_dump_options {
    const lauf_runtime_builtin_library* builtin_libs;
    size_t                              builtin_libs_count;
} lauf_backend_dump_options;

extern const lauf_backend_dump_options lauf_backend_default_dump_options;

void lauf_backend_dump(lauf_writer* writer, lauf_backend_dump_options options,
                       const lauf_asm_module* mod);
void lauf_backend_dump_chunk(lauf_writer* writer, lauf_backend_dump_options options,
                             const lauf_asm_module* mod, const lauf_asm_chunk* chunk);
```

The dump format is human-readable and "subject to change" — it is only used
for eyeball verification, so only the structural marks below are contractual,
not the exact spelling. A module dump begins with a header naming the module
and then renders each defined function with its name and `IN => OUT` signature
(the same `IN_COUNT => OUT_COUNT` notation as the text format below), so the
output contains the module's function names and is non-empty for a module with
a defined function. `lauf_backend_dump_chunk` emits the owning module's header
followed by the chunk's function body, so its output likewise names the module
and renders the chunk's `IN => OUT` signature and its instructions (such as the
`return` terminator).

## QBE backend — `lauf/backend/qbe.h`

A second backend that lowers a lauf module to text in the
[QBE](https://c9x.me/compile/) intermediate language. QBE is a small
SSA-based compiler backend that ingests a simple text IL and produces
native assembly; only the IL text is emitted here (no native codegen and
no dependency on the `qbe` binary).

```c
typedef struct lauf_backend_qbe_extern_function {
    const char*                 name;
    const lauf_runtime_builtin* builtin;
} lauf_backend_qbe_extern_function;

typedef struct lauf_backend_qbe_options {
    const lauf_backend_qbe_extern_function* extern_fns;
    size_t                                  extern_fns_count;
} lauf_backend_qbe_options;

extern const lauf_backend_qbe_options lauf_backend_default_qbe_options;

void lauf_backend_qbe(lauf_writer* writer, lauf_backend_qbe_options options,
                      const lauf_asm_module* mod);
```

`lauf_backend_qbe` walks the module in two passes:

- **Globals.** Each defined global becomes a QBE `data` section of the form
  `data $data_<N> = align <A> { ... }`, where `<N>` is a per-module unique
  index for the global and `<A>` its alignment. Declaration-only globals
  (with no attached data) are skipped.
- **Functions.** Each defined function becomes a QBE `function` definition.
  Declaration-only functions (no builder body) are skipped.

### Function signature mapping

The QBE return type prefix depends on the lauf function's `output_count`:

- **0 outputs** → `function $<name>(<params>)` — no return type, just the
  name and parameter list.
- **1 output** → `function l $<name>(<params>)` — the QBE type `l`
  (64-bit long) is used as the return type for the single output.
- **N > 1 outputs** → `function :tuple_<N> $<name>(<params>)` — an
  aggregate return of N pointer-sized values, declared once at the top of
  the IL as `type :tuple_<N> = { l <N> }`.

Every input parameter is emitted as `l %r<i>` (long, register-numbered by
input index).

### Export

Calling `lauf_asm_export_function(fn)` before invoking the backend causes
an `export` line to be emitted immediately preceding that function's
`function ...` signature line. Non-exported functions produce no such
prefix. The `export` marker applies to at most one function at a time —
each exported function is preceded by its own `export` line.

### Extern function options

Each `lauf_backend_qbe_extern_function` entry maps a QBE-level extern name
to a `lauf_runtime_builtin`. When the module contains a `call_builtin` for
a builtin whose `impl` pointer matches an entry's `builtin->impl`, the
backend emits `call $<extern_name>(<args>)` at that site instead of any
inline codegen path it would otherwise choose (for example, the arithmetic
builtins have inline QBE-level codegen, but a registered extern name wins
over that inline path). This is the mechanism callers use to redirect
allocation, memcpy, or other host-provided functionality to their own
runtime symbols.

The entries in `extern_fns` need not be exhaustive — builtins that are not
covered fall through to whatever the backend's own codegen decides.

### Default options

`lauf_backend_default_qbe_options` provides a fixed extern set for the
allocator and memcpy-family builtins so that a QBE-lowered lauf module can
link against a small host runtime. `extern_fns_count == 7`, and the
entries (in order) are:

| `name` | `builtin` |
|---|---|
| `"lauf_heap_alloc"`       | `&lauf_lib_heap_alloc`       |
| `"lauf_heap_alloc_array"` | `&lauf_lib_heap_alloc_array` |
| `"lauf_heap_free"`        | `&lauf_lib_heap_free`        |
| `"lauf_heap_gc"`          | `&lauf_lib_heap_gc`          |
| `"lauf_memory_copy"`      | `&lauf_lib_memory_copy`      |
| `"lauf_memory_fill"`      | `&lauf_lib_memory_fill`      |
| `"lauf_memory_cmp"`       | `&lauf_lib_memory_cmp`       |

### Usage example

The end-to-end sequence is: build a module, obtain a `lauf_writer`,
invoke `lauf_backend_qbe` with an options struct, then read the IL text
out of the writer. The individual per-function docs elsewhere in this
document don't demonstrate this composition, so a small example follows.

```c
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/backend/qbe.h>
#include <lauf/writer.h>

int main(void) {
    /* Build a module with one exported function `myfn(0 => 1)` that
     * returns the constant 42. */
    lauf_asm_module*   mod = lauf_asm_create_module("m");
    lauf_asm_function* fn  = lauf_asm_add_function(
        mod, "myfn", (lauf_asm_signature){0, 1});
    lauf_asm_export_function(fn);

    lauf_asm_builder* b = lauf_asm_create_builder(
        lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);
    lauf_asm_inst_uint(b, 42);
    lauf_asm_inst_return(b);
    lauf_asm_build_finish(b);
    lauf_asm_destroy_builder(b);

    /* Lower to QBE IL text. */
    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, lauf_backend_default_qbe_options, mod);
    const char* il = lauf_writer_get_string(w);
    /* `il` now points at QBE IL text containing (schematically):
     *     export
     *     function l $myfn()
     *     {
     *     @entry
     *       ...
     *       ret ...
     *     ...
     *     }
     */
    (void)il;

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
    return 0;
}
```

To route a builtin call to a host-provided symbol, construct a custom
options struct rather than using the default:

```c
lauf_backend_qbe_extern_function my_externs[] = {
    {"my_alloc", &lauf_lib_heap_alloc},
};
lauf_backend_qbe_options opts = {my_externs, 1};
lauf_backend_qbe(w, opts, mod);
/* Any `$lauf.heap.alloc` call in the module is now lowered as
 * `call $my_alloc(...)` in the IL. */
```

Register naming for temporaries and intermediates, block naming, folding
of repeated constants, and any other detail of the emitted IL beyond the
structural marks documented above are implementation choices and not part
of the contract.

## Text format (informal)

The text form of a module resembles the C-API structure:

```
module @NAME;

function @NAME(IN_COUNT => OUT_COUNT) {
    block %BLK_NAME(IN => OUT) {
        <instruction>;
        <instruction>;
        <terminator>;
    }
    ...
}
```

If no explicit `block` header is given, everything is placed in the
implicit `%entry` block. Instructions follow the same naming as their
C-API `lauf_asm_inst_*` counterparts (`return`, `jump %blk`,
`branch %if_true %if_false`, `uint N`, `sint N`, `pick N`, `roll N`,
`pop N`, `call @fn`, `call_indirect (IN => OUT)`, `fiber_suspend (IN =>
OUT)`, etc.). Immediate values are literal integers.

Builtin calls use a leading `$` followed by the fully qualified name (for
example `$lauf.int.sadd_wrap`). Names are formed from the builtin library's
`prefix` field followed by `.` and the builtin's `name` field. Overload
selection is by suffix — the `overflow` mode of the overload appears as
part of the builtin name (`sadd_wrap`, `sadd_sat`, `sadd_panic`, etc.).

The default text options do not enable any builtin libraries; the caller
must pass `lauf_libs` (see below) as `builtin_libs` to be able to parse
programs that use any builtin.

## Runtime builtin infrastructure — `lauf/runtime/builtin.h`

```c
#define LAUF_RUNTIME_BUILTIN_IMPL /* implementation-defined attribute or empty */

typedef bool lauf_runtime_builtin_impl(const lauf_asm_inst* ip,
                                       lauf_runtime_value* vstack_ptr,
                                       lauf_runtime_stack_frame* frame_ptr,
                                       lauf_runtime_process* process);

typedef enum lauf_runtime_builtin_flags {
    LAUF_RUNTIME_BUILTIN_DEFAULT       = 0,
    LAUF_RUNTIME_BUILTIN_NO_PANIC      = 1 << 0,
    LAUF_RUNTIME_BUILTIN_NO_PROCESS    = 1 << 1,
    LAUF_RUNTIME_BUILTIN_VM_DIRECTIVE  = 1 << 2,
    LAUF_RUNTIME_BUILTIN_CONSTANT_FOLD = 1 << 3,
    LAUF_RUNTIME_BUILTIN_ALWAYS_PANIC  = 1 << 4,
} lauf_runtime_builtin_flags;

LAUF_RUNTIME_BUILTIN_IMPL bool lauf_runtime_builtin_dispatch(
    const lauf_asm_inst* ip, lauf_runtime_value* vstack_ptr,
    lauf_runtime_stack_frame* frame_ptr, lauf_runtime_process* process);

typedef struct lauf_runtime_builtin {
    lauf_runtime_builtin_impl*  impl;
    uint8_t                     input_count;
    uint8_t                     output_count;
    int                         flags;
    const char*                 name;
    const lauf_runtime_builtin* next;
} lauf_runtime_builtin;

#define LAUF_RUNTIME_BUILTIN(ConstantName, InputCount, OutputCount, Flags, Name, Next) ...
#define LAUF_RUNTIME_BUILTIN_DISPATCH \
    LAUF_TAIL_CALL return lauf_runtime_builtin_dispatch(ip, vstack_ptr, frame_ptr, process)

typedef struct lauf_runtime_builtin_library {
    const char*                 prefix;
    const lauf_runtime_builtin* functions;   /* head of linked list via .next */
    const lauf_asm_type*        types;
} lauf_runtime_builtin_library;
```

A builtin is a C function whose signature matches
`lauf_runtime_builtin_impl`. It must end with `LAUF_RUNTIME_BUILTIN_DISPATCH`
so that the next instruction is invoked via the dispatch loop. The
`LAUF_RUNTIME_BUILTIN` macro defines a builtin record + impl function pair.

Every builtin belongs to a `lauf_runtime_builtin_library` — a named group
that the text frontend and dump backend can look up by prefix. Libraries
also carry a list of types (for `load_field`/`store_field` typing).

## Standard libraries — `lauf/lib.h` and `lauf/lib/*.h`

`lauf/lib.h` re-exports every intrinsic library and declares the umbrella
list:

```c
extern const lauf_runtime_builtin_library* lauf_libs;
extern const size_t                        lauf_libs_count;
```

Any code that wants to parse or dump programs using the intrinsic builtins
passes `lauf_libs` / `lauf_libs_count` as the `builtin_libs` / `_count`
option.

Across these libraries a builtin panics when an operand falls outside the
domain on which its operation is defined; an overflow-mode selector governs
only a result that does not fit the result type, never an operation that has
no mathematical result at all.

The intrinsic libraries are (each in its own `lauf/lib/*.h` header):

- `lauf_lib_int` (`lauf/lib/int.h`) — signed/unsigned arithmetic.
  Builtins that can overflow take an `lauf_lib_int_overflow` mode
  selector (`FLAG`, `WRAP`, `SAT`, `PANIC`) and are exposed as functions
  returning `lauf_runtime_builtin`:
  `sadd`, `ssub`, `smul`, `sdiv`, `sabs`, `stou`,
  `uadd`, `usub`, `umul`, `utos`.
  Builtins whose operation cannot overflow are exposed as
  `extern const lauf_runtime_builtin` (no mode argument):
  `udiv`, `srem`, `urem`, `uabs`, `scmp`, `ucmp`.
  Comparison (`scmp`, `ucmp`) is three-way, returning `sint` −1 / 0 / +1.
  Both `sabs` and `uabs` interpret their single operand as a signed integer
  and yield its absolute value: `sabs` returns a *signed* result and so takes
  an overflow-mode selector (|`INT64_MIN`| does not fit in a signed 64-bit
  integer), whereas `uabs` returns the magnitude as an *unsigned* integer
  (e.g. `uabs(-7)` = 7, `uabs(INT64_MIN)` = 2^63), which is always
  representable and therefore needs no selector.
  Fixed-width integer types `lauf_lib_int_{s,u}{8,16,32,64}` are exposed
  as `extern const lauf_asm_type`; each has a companion `_overflow`
  `extern const lauf_runtime_builtin` (e.g. `lauf_lib_int_s32_overflow`)
  that reports whether a value fits.
- `lauf_lib_memory` (`lauf/lib/memory.h`) — allocation flagging (`poison`,
  `unpoison`, `split`, `merge`), address arithmetic (`addr_add`, `addr_sub`,
  `addr_distance`, `addr_to_int`, `int_to_addr`) and memcpy/memset/memcmp
  (`copy`, `fill`, `cmp`). Following the same value-stack convention (top of
  the stack is the rightmost operand), these three take the byte `count` on
  top: `copy: dest:address src:address count:uint => _` copies `count` bytes
  from `src` into `dest` — the destination address is deepest, matching C
  `memcpy(dest, src, count)` order; `fill: dest:address value:uint
  count:uint => _` sets `count` bytes at `dest` to the low byte of `value`;
  and `cmp: a:address b:address count:uint => sint` returns a three-way
  `memcmp` (`sint` −1 / 0 / +1) of the two regions. Only `addr_add` and
  `addr_sub` are overflow-mode
  selected: they take a `lauf_lib_memory_addr_overflow` enum — whose
  enumerators are `LAUF_LIB_MEMORY_ADDR_OVERFLOW_INVALIDATE`,
  `LAUF_LIB_MEMORY_ADDR_OVERFLOW_PANIC`, and
  `LAUF_LIB_MEMORY_ADDR_OVERFLOW_PANIC_STRICT` — and are exposed as
  `lauf_runtime_builtin lauf_lib_memory_addr_add(lauf_lib_memory_addr_overflow)`
  / `lauf_lib_memory_addr_sub(lauf_lib_memory_addr_overflow)`. Note this
  selector is spelled `..._ADDR_OVERFLOW_...` (not `..._OVERFLOW_...`). The
  remaining address builtins `addr_distance`, `addr_to_int`, and `int_to_addr`
  take no selector and are plain `extern const lauf_runtime_builtin`.
- `lauf_lib_bits` (`lauf/lib/bits.h`) — `and`, `or`, `xor`, `shl`, `ushr`,
  `sshr`. Shifts panic if the shift amount ≥ bit width.
- `lauf_lib_heap` (`lauf/lib/heap.h`) — `alloc`, `alloc_array`, `free`,
  `transfer_local` (heap-lift a local), `gc`, `declare_reachable`,
  `undeclare_reachable`, `declare_weak`, `undeclare_weak`.
- `lauf_lib_fiber` (`lauf/lib/fiber.h`) — `create`, `destroy`, `current`,
  `parent`, `done`.

Each builtin in these libraries is also exposed to C code as a name of the
form `lauf_lib_<mod>_<op>` (for example `lauf_lib_bits_and`,
`lauf_lib_heap_alloc`, `lauf_lib_int_scmp`) that yields a
`lauf_runtime_builtin` record suitable for passing to
`lauf_asm_inst_call_builtin`. Simple builtins are declared as
`extern const lauf_runtime_builtin lauf_lib_<mod>_<op>`; builtins that take
an overflow-mode selector are declared as
`lauf_runtime_builtin lauf_lib_<mod>_<op>(lauf_lib_<mod>_overflow)` and
return the record for the requested mode.

Signatures of individual builtins are described in the corresponding header
comments; every builtin declares its `input_count` / `output_count`
directly in the `lauf_runtime_builtin` record. A builtin's outputs are
exactly the result values its documented operation produces: it reports an
invalid operand by panicking, never by pushing a success/failure status.

## Example usage

The following is a minimal end-to-end program that (1) parses a recursive
`fib` in text form, (2) creates a program, (3) executes it, and (4)
prints the result:

```c
#include <cstdio>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/frontend/text.h>
#include <lauf/lib.h>
#include <lauf/reader.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

int main() {
    auto reader = lauf_create_cstring_reader(R"(
        module @f;
        function @fib(1 => 1) {
            block %entry(1 => 1) {
                pick 0; sint 2; $lauf.int.scmp; cc lt;
                branch %base(1 => 1) %recurse(1 => 1);
            }
            block %base(1 => 1) { return; }
            block %recurse(1 => 1) {
                pick 0; sint 1; $lauf.int.ssub_wrap; call @fib;
                roll 1; sint 2; $lauf.int.ssub_wrap; call @fib;
                $lauf.int.sadd_wrap;
                return;
            }
        }
    )");
    auto opts = lauf_frontend_default_text_options;
    opts.builtin_libs       = lauf_libs;
    opts.builtin_libs_count = lauf_libs_count;
    auto mod = lauf_frontend_text(reader, opts);
    lauf_destroy_reader(reader);

    auto fn   = lauf_asm_find_function_by_name(mod, "fib");
    auto prog = lauf_asm_create_program(mod, fn);

    auto vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value in = {.as_sint = 10}, out;
    lauf_vm_execute_oneshot(vm, prog, &in, &out);
    std::printf("fib(10) = %lld\n", (long long)out.as_sint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}
```

And a bytecode-first example that uses the builder directly to construct a
"push 42, return" function and executes it:

```c
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

int main() {
    auto mod = lauf_asm_create_module("m");
    auto fn  = lauf_asm_add_function(mod, "f",
                                     (lauf_asm_signature){0, 1});
    auto b   = lauf_asm_create_builder(lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);
    lauf_asm_inst_uint(b, 42);
    lauf_asm_inst_return(b);
    lauf_asm_build_finish(b);
    lauf_asm_destroy_builder(b);

    auto prog = lauf_asm_create_program(mod, fn);
    auto vm   = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    /* out.as_uint == 42 */
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}
```
