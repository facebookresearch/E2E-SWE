/* Group: end_to_end — several APIs composed into realistic programs. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/frontend/text.h>
#include <lauf/lib.h>
#include <lauf/lib/int.h>
#include <lauf/reader.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* Build the classic recursive fib through the C builder API (two self-calls,
 * a branch, and inter-call stack management via roll) and execute it. The
 * text-frontend path to the same algorithm is covered by frontend_text's
 * test_parse_recursive_fib_and_execute; this drives the builder-side lowering
 * instead. fib(12) = 144. */
static void test_recursive_fib_builder(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("f");
    lauf_asm_function* fib = lauf_asm_add_function(mod, "fib", (lauf_asm_signature){1, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fib);

        lauf_asm_block* base_b    = lauf_asm_declare_block(b, 1);
        lauf_asm_block* recurse_b = lauf_asm_declare_block(b, 1);

        /* entry: [n]. Compute (n < 2) and branch. */
        lauf_asm_inst_pick(b, 0);                         /* [n, n] */
        lauf_asm_inst_sint(b, 2);                         /* [n, n, 2] */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_scmp); /* [n, cmp] */
        lauf_asm_inst_cc(b, LAUF_ASM_INST_CC_LT);         /* [n, n<2] */
        lauf_asm_inst_branch(b, base_b, recurse_b);

        /* base: n < 2 → return n. */
        lauf_asm_build_block(b, base_b);
        lauf_asm_inst_return(b);

        /* recurse: return fib(n-1) + fib(n-2). */
        lauf_asm_build_block(b, recurse_b);
        lauf_asm_inst_pick(b, 0);                         /* [n, n] */
        lauf_asm_inst_sint(b, 1);                         /* [n, n, 1] */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_ssub(LAUF_LIB_INT_OVERFLOW_WRAP));
                                                          /* [n, n-1] */
        lauf_asm_inst_call(b, fib);                       /* [n, fib(n-1)] */
        lauf_asm_inst_roll(b, 1);                         /* [fib(n-1), n] */
        lauf_asm_inst_sint(b, 2);                         /* [fib(n-1), n, 2] */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_ssub(LAUF_LIB_INT_OVERFLOW_WRAP));
                                                          /* [fib(n-1), n-2] */
        lauf_asm_inst_call(b, fib);                       /* [fib(n-1), fib(n-2)] */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_sadd(LAUF_LIB_INT_OVERFLOW_WRAP));
                                                          /* [fib(n-1)+fib(n-2)] */
        lauf_asm_inst_return(b);

        CHECK(lauf_asm_build_finish(b), "build_finish on fib failed");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program   prog = lauf_asm_create_program(mod, fib);
    lauf_vm*           vm   = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value in, out;
    in.as_sint = 12;
    CHECK(lauf_vm_execute_oneshot(vm, prog, &in, &out), "execute returned false");
    CHECK(out.as_sint == 144, "expected fib(12)=144, got %lld", (long long)out.as_sint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Build sum_to_n(n) = n + (n-1) + ... + 1 via recursion. n = 100 -> 5050.
 * Uses branch + call to exercise the C-API builder end-to-end. */
static void test_iterative_sum_builder(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("sum");
    lauf_asm_function* rec
        = lauf_asm_add_function(mod, "sum", (lauf_asm_signature){1, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, rec);

        lauf_asm_block* base_b    = lauf_asm_declare_block(b, 1);
        lauf_asm_block* recurse_b = lauf_asm_declare_block(b, 1);

        /* Entry: [n]. Compute (n < 1) and branch. */
        lauf_asm_inst_pick(b, 0);                          /* [n, n] */
        lauf_asm_inst_sint(b, 1);                          /* [n, n, 1] */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_scmp);  /* [n, cmp] */
        lauf_asm_inst_cc(b, LAUF_ASM_INST_CC_LT);          /* [n, cmp<0] */
        lauf_asm_inst_branch(b, base_b, recurse_b);

        /* base: [n]. return n directly. */
        lauf_asm_build_block(b, base_b);
        lauf_asm_inst_return(b);

        /* recurse: [n] -> [n, n-1] -> call sum -> [n, sum(n-1)] -> add. */
        lauf_asm_build_block(b, recurse_b);
        lauf_asm_inst_pick(b, 0);                          /* [n, n] */
        lauf_asm_inst_sint(b, 1);                          /* [n, n, 1] */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_ssub(LAUF_LIB_INT_OVERFLOW_WRAP));
                                                           /* [n, n-1] */
        lauf_asm_inst_call(b, rec);                        /* [n, sum(n-1)] */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_sadd(LAUF_LIB_INT_OVERFLOW_WRAP));
                                                           /* [n + sum(n-1)] */
        lauf_asm_inst_return(b);

        int ok = lauf_asm_build_finish(b);
        CHECK(ok, "build_finish on sum failed");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program   prog = lauf_asm_create_program(mod, rec);
    lauf_vm*           vm   = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value in, out;
    in.as_sint = 100;
    CHECK(lauf_vm_execute_oneshot(vm, prog, &in, &out), "execute sum(100) false");
    CHECK(out.as_sint == 5050, "expected sum(100)=5050, got %lld", (long long)out.as_sint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Global variable write + read via bytecode: define a RW global with a
 * default value; a function reads the global (should be its default),
 * overwrites it with 99, then reads again and returns 99. */
static void test_global_variable_read_write(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("g");

    lauf_asm_global* g = lauf_asm_add_global(mod, LAUF_ASM_GLOBAL_READ_WRITE);
    lauf_uint init = 7;
    lauf_asm_define_data_global(mod, g, (lauf_asm_layout){8, 8}, &init);

    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "rw", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* Write 99 to global. */
        lauf_asm_inst_uint(b, 99);
        lauf_asm_inst_global_addr(b, g);
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);

        /* Read it back and return. */
        lauf_asm_inst_global_addr(b, g);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 99, "expected 99 after write+read, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_recursive_fib_builder", test_recursive_fib_builder},
    {"test_iterative_sum_builder", test_iterative_sum_builder},
    {"test_global_variable_read_write", test_global_variable_read_write},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_end_to_end.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
