/* Group: lib_int — integer arithmetic + comparison builtins. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/lib/int.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* 2 + 3 via uadd(WRAP) = 5. */
static void test_uadd_wrap_bytecode(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("i");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "add", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 2);
        lauf_asm_inst_uint(b, 3);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_uadd(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false");
    CHECK(out.as_uint == 5, "expected 2 + 3 = 5, got %llu", (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* sdiv panics on divide-by-zero regardless of overflow mode (documented). */
static int g_panic_called;
static void panic_capture(void* u, lauf_runtime_process* p, const char* msg)
{
    (void)u;
    (void)p;
    (void)msg;
    g_panic_called = 1;
}

static void test_sdiv_by_zero_panics(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("div");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "d0", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_sint(b, 42);
        lauf_asm_inst_sint(b, 0);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_sdiv(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    g_panic_called = 0;
    lauf_vm_panic_handler h = {NULL, panic_capture};
    lauf_vm_set_panic_handler(vm, h);

    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(!ok, "expected sdiv-by-zero to panic (execute=false), got true");
    CHECK(g_panic_called == 1, "panic handler was not invoked on divide-by-zero");

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* scmp returns -1/0/+1; cc lt converts that comparison to 1 (true) if the
 * top value is negative. We push (3, 7), scmp gives -1 (since 3 < 7), then
 * `cc lt` returns 1. */
static void test_scmp_less_than_via_cc(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("cmp");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "lt", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_sint(b, 3);
        lauf_asm_inst_sint(b, 7);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_scmp);
        lauf_asm_inst_cc(b, LAUF_ASM_INST_CC_LT);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false");
    CHECK(out.as_uint == 1, "expected 3 < 7 to yield 1, got %llu",
          (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Cover more arithmetic — smul, ssub_wrap. Push (7, 5); smul(WRAP) -> 35;
 * push 20; ssub(WRAP) -> 15. */
static void test_smul_and_ssub_wrap(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("smulssub");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "op", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_sint(b, 7);
        lauf_asm_inst_sint(b, 5);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_smul(LAUF_LIB_INT_OVERFLOW_WRAP));
        /* stack: [35] */
        lauf_asm_inst_sint(b, 20);
        /* stack: [35, 20]. ssub is `a b => a - b` in the natural stack convention. */
        lauf_asm_inst_call_builtin(b, lauf_lib_int_ssub(LAUF_LIB_INT_OVERFLOW_WRAP));
        /* stack: [15] */
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_sint == 15, "expected 7*5 - 20 = 15, got %lld",
          (long long)out.as_sint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* uabs of a signed -5 (as bits) gives 5 as unsigned. sabs of -5 gives 5. */
static void test_sabs_and_uabs(void)
{
    /* sabs first. sint -3, sabs -> sint 3. */
    lauf_asm_module*   mod = lauf_asm_create_module("abs");
    lauf_asm_function* fns
        = lauf_asm_add_function(mod, "s", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fns);
        lauf_asm_inst_sint(b, -3);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_sabs(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_function* fnu
        = lauf_asm_add_function(mod, "u", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fnu);
        lauf_asm_inst_sint(b, -7);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_uabs);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;

    lauf_asm_program progs = lauf_asm_create_program(mod, fns);
    CHECK(lauf_vm_execute_oneshot(vm, progs, NULL, &out), "sabs execute returned false");
    CHECK(out.as_sint == 3, "sabs(-3) expected 3, got %lld", (long long)out.as_sint);

    lauf_asm_program progu = lauf_asm_create_program(mod, fnu);
    CHECK(lauf_vm_execute_oneshot(vm, progu, NULL, &out), "uabs execute returned false");
    CHECK(out.as_uint == 7, "uabs(-7) expected 7, got %llu",
          (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* udiv is exposed as `extern const lauf_runtime_builtin lauf_lib_int_udiv`
 * (no overflow-mode selector, since unsigned division cannot overflow) and
 * is documented to panic on divisor==0. Mirrors sdiv_by_zero_panics. */
static int g_panic_udiv;
static void panic_udiv(void* u, lauf_runtime_process* p, const char* msg)
{
    (void)u;
    (void)p;
    (void)msg;
    g_panic_udiv = 1;
}
static void test_udiv_by_zero_panics(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("udv");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "d0", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 100);
        lauf_asm_inst_uint(b, 0);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_udiv);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*         vm   = lauf_create_vm(lauf_default_vm_options);
    g_panic_udiv          = 0;
    lauf_vm_panic_handler h = {NULL, panic_udiv};
    lauf_vm_set_panic_handler(vm, h);

    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(!ok, "udiv by 0 should panic — execute returned true");
    CHECK(g_panic_udiv == 1, "panic handler not invoked on udiv-by-zero");

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* umul with SAT and WRAP overflow modes on the same overflowing inputs.
 * SAT clamps to UINT64_MAX on overflow; WRAP produces the truncated
 * low-64-bit result of the true product. Uses two functions in the same
 * module because each requires a different builtin selection. */
static void test_umul_saturating_and_wrap(void)
{
    /* UINT64_MAX * 2 overflows. Wrap: UINT64_MAX * 2 mod 2^64 = 2^64 - 2
     * = UINT64_MAX - 1. Saturate: UINT64_MAX (clamp). */
    lauf_asm_module*   mod = lauf_asm_create_module("umul");
    lauf_asm_function* fw
        = lauf_asm_add_function(mod, "w", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fw);
        lauf_asm_inst_uint(b, 0xFFFFFFFFFFFFFFFFULL);
        lauf_asm_inst_uint(b, 2);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_umul(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_function* fs
        = lauf_asm_add_function(mod, "s", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fs);
        lauf_asm_inst_uint(b, 0xFFFFFFFFFFFFFFFFULL);
        lauf_asm_inst_uint(b, 2);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_umul(LAUF_LIB_INT_OVERFLOW_SAT));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;

    lauf_asm_program pw = lauf_asm_create_program(mod, fw);
    CHECK(lauf_vm_execute_oneshot(vm, pw, NULL, &out), "umul WRAP execute returned false");
    CHECK(out.as_uint == 0xFFFFFFFFFFFFFFFEULL,
          "umul(WRAP)(UINT64_MAX,2) expected UINT64_MAX-1 (=0xFF..FE), got %llx",
          (unsigned long long)out.as_uint);

    lauf_asm_program ps = lauf_asm_create_program(mod, fs);
    CHECK(lauf_vm_execute_oneshot(vm, ps, NULL, &out), "umul SAT execute returned false");
    CHECK(out.as_uint == 0xFFFFFFFFFFFFFFFFULL,
          "umul(SAT)(UINT64_MAX,2) expected UINT64_MAX, got %llx",
          (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* srem / urem: divisor-remainder builtins. spec docs both as extern const
 * builtins with no overflow-mode selector. srem's result carries the sign
 * of the dividend (C-style truncated division). urem is standard unsigned
 * modulo. Two functions in the same module — one per builtin. */
static void test_srem_and_urem(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("rem");
    lauf_asm_function* fs
        = lauf_asm_add_function(mod, "sr", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fs);
        /* srem(-7, 3): -7 = -2*3 + (-1) → remainder -1 (sign of dividend). */
        lauf_asm_inst_sint(b, -7);
        lauf_asm_inst_sint(b, 3);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_srem);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_function* fu
        = lauf_asm_add_function(mod, "ur", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fu);
        /* urem(17, 5) = 2. */
        lauf_asm_inst_uint(b, 17);
        lauf_asm_inst_uint(b, 5);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_urem);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;

    lauf_asm_program ps = lauf_asm_create_program(mod, fs);
    CHECK(lauf_vm_execute_oneshot(vm, ps, NULL, &out), "srem execute returned false");
    CHECK(out.as_sint == -1, "srem(-7,3) expected -1, got %lld", (long long)out.as_sint);

    lauf_asm_program pu = lauf_asm_create_program(mod, fu);
    CHECK(lauf_vm_execute_oneshot(vm, pu, NULL, &out), "urem execute returned false");
    CHECK(out.as_uint == 2, "urem(17,5) expected 2, got %llu",
          (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* uadd with PANIC overflow mode panics when the sum overflows UINT64_MAX.
 * spec: "PANIC — Operations panic on overflow" for the overflow-mode
 * selector. */
static int g_panic_uadd;
static void panic_uadd(void* u, lauf_runtime_process* p, const char* msg)
{
    (void)u;
    (void)p;
    (void)msg;
    g_panic_uadd = 1;
}
static void test_uadd_panic_overflow(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("up");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "ov", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* UINT64_MAX + 1 overflows; PANIC mode must panic. */
        lauf_asm_inst_uint(b, 0xFFFFFFFFFFFFFFFFULL);
        lauf_asm_inst_uint(b, 1);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_uadd(LAUF_LIB_INT_OVERFLOW_PANIC));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*         vm   = lauf_create_vm(lauf_default_vm_options);
    g_panic_uadd          = 0;
    lauf_vm_panic_handler h = {NULL, panic_uadd};
    lauf_vm_set_panic_handler(vm, h);

    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(!ok, "uadd(PANIC) on overflow should return false (panic), got true");
    CHECK(g_panic_uadd == 1, "panic handler not invoked on uadd(PANIC) overflow");

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* stou and utos: sign conversion builtins (spec: "Signed to unsigned
 * conversion" / "Unsigned to signed conversion", each taking an overflow
 * mode). With WRAP mode the bit pattern passes through unchanged, so
 * sint -1 → uint 0xFFFFFFFFFFFFFFFF (two's complement), and uint
 * 0x8000000000000000 → sint INT64_MIN. Two functions in the same module. */
static void test_stou_and_utos_conversion(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("cvt");
    lauf_asm_function* fs
        = lauf_asm_add_function(mod, "s2u", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fs);
        lauf_asm_inst_sint(b, -1);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_stou(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_function* fu
        = lauf_asm_add_function(mod, "u2s", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fu);
        lauf_asm_inst_uint(b, 0x8000000000000000ULL);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_utos(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;

    lauf_asm_program ps = lauf_asm_create_program(mod, fs);
    CHECK(lauf_vm_execute_oneshot(vm, ps, NULL, &out), "stou execute returned false");
    /* sint -1 → uint UINT64_MAX = 0xFFFFFFFFFFFFFFFF. */
    CHECK(out.as_uint == 0xFFFFFFFFFFFFFFFFULL,
          "stou(WRAP)(-1) expected UINT64_MAX, got %llx", (unsigned long long)out.as_uint);

    lauf_asm_program pu = lauf_asm_create_program(mod, fu);
    CHECK(lauf_vm_execute_oneshot(vm, pu, NULL, &out), "utos execute returned false");
    /* uint 0x8000...0 → sint INT64_MIN under WRAP. */
    CHECK(out.as_sint == (long long)0x8000000000000000LL,
          "utos(WRAP)(0x8000..0) expected INT64_MIN, got %lld", (long long)out.as_sint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_uadd_wrap_bytecode", test_uadd_wrap_bytecode},
    {"test_sdiv_by_zero_panics", test_sdiv_by_zero_panics},
    {"test_scmp_less_than_via_cc", test_scmp_less_than_via_cc},
    {"test_smul_and_ssub_wrap", test_smul_and_ssub_wrap},
    {"test_sabs_and_uabs", test_sabs_and_uabs},
    {"test_udiv_by_zero_panics", test_udiv_by_zero_panics},
    {"test_umul_saturating_and_wrap", test_umul_saturating_and_wrap},
    {"test_srem_and_urem", test_srem_and_urem},
    {"test_uadd_panic_overflow", test_uadd_panic_overflow},
    {"test_stou_and_utos_conversion", test_stou_and_utos_conversion},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_lib_int.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
