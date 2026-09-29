/* Group: lib_bits — bitwise builtins. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/lib/bits.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* Evaluate `(0xFF & 0x0F) | 0x30 ^ 0x03`. Because operators are left-fold on
 * the stack via consecutive builtin calls, the value is computed as:
 *   ((0xFF & 0x0F) | 0x30) ^ 0x03 = (0x0F | 0x30) ^ 0x03 = 0x3F ^ 0x03 = 0x3C. */
static void test_bits_and_or_xor(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("bits");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "compute", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 0xFF);
        lauf_asm_inst_uint(b, 0x0F);
        lauf_asm_inst_call_builtin(b, lauf_lib_bits_and);
        lauf_asm_inst_uint(b, 0x30);
        lauf_asm_inst_call_builtin(b, lauf_lib_bits_or);
        lauf_asm_inst_uint(b, 0x03);
        lauf_asm_inst_call_builtin(b, lauf_lib_bits_xor);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false");
    CHECK(out.as_uint == 0x3C, "expected 0x3C, got 0x%llx", (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Test shl / ushr / sshr in one program by composing them:
 *   ((0x01 shl 8) ushr 4) sshr 2  =  ((0x100) >> 4) >> 2 = 0x10 >> 2 = 0x04. */
static void test_bits_shl_ushr_sshr(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("shift");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "compute", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* 0x01 shl 8 -> 0x100 */
        lauf_asm_inst_uint(b, 0x01);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_call_builtin(b, lauf_lib_bits_shl);
        /* .. ushr 4 -> 0x10 */
        lauf_asm_inst_uint(b, 4);
        lauf_asm_inst_call_builtin(b, lauf_lib_bits_ushr);
        /* .. sshr 2 -> 0x04 (positive value, sign extension does nothing) */
        lauf_asm_inst_uint(b, 2);
        lauf_asm_inst_call_builtin(b, lauf_lib_bits_sshr);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false");
    CHECK(out.as_uint == 0x04, "expected 0x04, got 0x%llx",
          (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_bits_and_or_xor", test_bits_and_or_xor},
    {"test_bits_shl_ushr_sshr", test_bits_shl_ushr_sshr},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_lib_bits.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
