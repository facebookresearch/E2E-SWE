/* Group: asm_builder — building function bodies + query results via
 * observable side effects (execution or dump). The builder's internal
 * instruction encoding is not part of the public API, so we verify the
 * builder by:
 *   1. Making it build a function.
 *   2. Executing the function on the VM.
 *   3. Checking the output value / process status.
 * or
 *   1. Building a chunk.
 *   2. Dumping the module.
 *   3. Checking that the resulting text contains the expected function name.
 */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/backend/dump.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>
#include <lauf/writer.h>
#include <string.h>

/* Build a trivial function `add1(x) => x + 1` using inst_uint + inst_call_builtin
 * — but we don't need any builtins to add. Instead: `pick 0; sint 1;
 * call_builtin uadd_wrap; return`. To avoid depending on lib_int here we test
 * something even more minimal: a function that pushes a literal and returns
 * it, verifying by execution on the VM. */
static void test_build_simple_function(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("m");
    lauf_asm_function* fn = lauf_asm_add_function(mod, "return42", (lauf_asm_signature){0, 1});

    lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);
    lauf_asm_inst_uint(b, 42);
    lauf_asm_inst_return(b);
    int ok = lauf_asm_build_finish(b);
    CHECK(ok, "lauf_asm_build_finish returned false for a well-formed function");
    lauf_asm_destroy_builder(b);

    CHECK(lauf_asm_function_has_definition(fn),
          "function has_definition=false after build_finish returned true");

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int exec_ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(exec_ok, "lauf_vm_execute_oneshot returned false");
    CHECK(out.as_uint == 42, "expected out=42, got %llu", (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* build_string_literal deduplicates equal strings within the same builder
 * session, but distinct strings produce distinct globals. The behavior is
 * documented in builder.h: "returns [existing global's] address" on collision.
 */
static void test_build_string_literal_dedup(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("s");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "f", (lauf_asm_signature){0, 0});

    lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);

    lauf_asm_global* a1 = lauf_asm_build_string_literal(b, "hello");
    lauf_asm_global* a2 = lauf_asm_build_string_literal(b, "hello");
    lauf_asm_global* b1 = lauf_asm_build_string_literal(b, "world");
    CHECK(a1 != NULL, "build_string_literal returned NULL");
    CHECK(b1 != NULL, "build_string_literal returned NULL for distinct literal");
    CHECK(a1 == a2, "two build_string_literal(\"hello\") calls returned different globals");
    CHECK(a1 != b1, "build_string_literal(\"hello\") and (\"world\") returned the same global");

    lauf_asm_inst_return(b);
    lauf_asm_build_finish(b);
    lauf_asm_destroy_builder(b);
    lauf_asm_destroy_module(mod);
}

/* Build a function `cmp0(x) => x_is_zero:uint` using a two-way branch. Then
 * execute and check that the correct branch runs. */
static void test_build_branch_and_jump(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("br");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "cmp0", (lauf_asm_signature){1, 1});

    lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);

    lauf_asm_block* if_zero    = lauf_asm_declare_block(b, 0);
    lauf_asm_block* if_nonzero = lauf_asm_declare_block(b, 0);
    lauf_asm_inst_branch(b, if_nonzero, if_zero);

    /* if_zero: push 1, return */
    lauf_asm_build_block(b, if_zero);
    lauf_asm_inst_uint(b, 1);
    lauf_asm_inst_return(b);

    /* if_nonzero: push 0, return */
    lauf_asm_build_block(b, if_nonzero);
    lauf_asm_inst_uint(b, 0);
    lauf_asm_inst_return(b);

    int ok = lauf_asm_build_finish(b);
    CHECK(ok, "build_finish false");
    lauf_asm_destroy_builder(b);

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_value in, out;
    in.as_uint = 0;
    CHECK(lauf_vm_execute_oneshot(vm, prog, &in, &out), "execute(0) returned false");
    CHECK(out.as_uint == 1, "cmp0(0) expected 1, got %llu", (unsigned long long)out.as_uint);

    lauf_asm_program prog2 = lauf_asm_create_program(mod, fn);
    in.as_uint             = 7;
    CHECK(lauf_vm_execute_oneshot(vm, prog2, &in, &out), "execute(7) returned false");
    CHECK(out.as_uint == 0, "cmp0(7) expected 0, got %llu", (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* build_data_literal is the raw-bytes counterpart of build_string_literal:
 * two calls with the same bytes in the same session must return the same
 * global. Distinct byte sequences produce distinct globals. */
static void test_build_data_literal_dedup(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("dl");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "f", (lauf_asm_signature){0, 0});
    lauf_asm_builder*  b   = lauf_asm_create_builder(lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);

    const unsigned char payload_a[] = {0x01, 0x02, 0x03, 0x04};
    const unsigned char payload_b[] = {0xFE, 0xED};

    lauf_asm_global* a1
        = lauf_asm_build_data_literal(b, payload_a, sizeof(payload_a));
    lauf_asm_global* a2
        = lauf_asm_build_data_literal(b, payload_a, sizeof(payload_a));
    lauf_asm_global* bb
        = lauf_asm_build_data_literal(b, payload_b, sizeof(payload_b));

    CHECK(a1 != NULL, "build_data_literal returned NULL for payload_a");
    CHECK(bb != NULL, "build_data_literal returned NULL for payload_b");
    CHECK(a1 == a2, "two build_data_literal(payload_a) returned different globals");
    CHECK(a1 != bb, "distinct payloads returned the same global");

    lauf_asm_inst_return(b);
    (void)lauf_asm_build_finish(b);
    lauf_asm_destroy_builder(b);
    lauf_asm_destroy_module(mod);
}

/* build_get_function returns the current fn; build_get_vstack_size tracks how
 * many values are on the value stack at the current insertion point. */
static void test_build_get_function_and_vstack_size(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("q");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "f", (lauf_asm_signature){0, 0});
    lauf_asm_builder*  b   = lauf_asm_create_builder(lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);

    /* build_get_function is documented to return the current function under
     * construction — the very function we just started to build.
     * (Note: we deliberately don't name this local `cur` because the harness
     * uses a global `Result* cur` for its per-test shared-memory Result, and
     * the FAIL/CHECK macros expand to `cur->msg = ...` — a local `cur` of
     * any other pointer type would shadow it and break compilation.) */
    lauf_asm_function* got_fn = lauf_asm_build_get_function(b);
    CHECK(got_fn == fn, "build_get_function returned a different function than build set");

    /* vstack starts at 0. Push a uint → 1. Push another → 2. Pop → 1. */
    size_t s0 = lauf_asm_build_get_vstack_size(b);
    CHECK(s0 == 0, "expected vstack size 0 at entry, got %zu", s0);
    lauf_asm_inst_uint(b, 1);
    size_t s1 = lauf_asm_build_get_vstack_size(b);
    CHECK(s1 == 1, "expected vstack size 1 after one push, got %zu", s1);
    lauf_asm_inst_uint(b, 2);
    size_t s2 = lauf_asm_build_get_vstack_size(b);
    CHECK(s2 == 2, "expected vstack size 2 after two pushes, got %zu", s2);
    lauf_asm_inst_pop(b, 0);
    size_t s3 = lauf_asm_build_get_vstack_size(b);
    CHECK(s3 == 1, "expected vstack size 1 after pop, got %zu", s3);

    lauf_asm_inst_pop(b, 0);
    lauf_asm_inst_return(b);
    (void)lauf_asm_build_finish(b);
    lauf_asm_destroy_builder(b);
    lauf_asm_destroy_module(mod);
}

/* entry_block returns the entry block of the function; local_layout returns
 * the layout of a declared local. */
static void test_entry_block_and_local_layout(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("eb");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "f", (lauf_asm_signature){0, 0});
    lauf_asm_builder*  b   = lauf_asm_create_builder(lauf_asm_default_build_options);
    lauf_asm_build(b, mod, fn);

    lauf_asm_block* entry = lauf_asm_entry_block(b);
    CHECK(entry != NULL, "entry_block returned NULL");

    /* Declare a local with a known layout, query it back. */
    lauf_asm_local* loc = lauf_asm_build_local(b, (lauf_asm_layout){24, 8});
    CHECK(loc != NULL, "build_local returned NULL");
    lauf_asm_layout ll = lauf_asm_local_layout(b, loc);
    CHECK(ll.size == 24, "expected local size 24, got %zu", ll.size);
    CHECK(ll.alignment == 8, "expected local alignment 8, got %zu", ll.alignment);

    lauf_asm_inst_return(b);
    (void)lauf_asm_build_finish(b);
    lauf_asm_destroy_builder(b);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_build_simple_function", test_build_simple_function},
    {"test_build_string_literal_dedup", test_build_string_literal_dedup},
    {"test_build_branch_and_jump", test_build_branch_and_jump},
    {"test_build_data_literal_dedup", test_build_data_literal_dedup},
    {"test_build_get_function_and_vstack_size", test_build_get_function_and_vstack_size},
    {"test_entry_block_and_local_layout", test_entry_block_and_local_layout},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_asm_builder.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
