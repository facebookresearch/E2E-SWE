/* Group: lib_memory — memory-manipulation builtins (copy / fill / cmp). */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/lib/int.h>
#include <lauf/lib/memory.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* Build:
 *   local %src : {8, 8} = 0xCAFEBABE
 *   local %dst : {8, 8}
 *   memcpy(dst, src, 8)
 *   return load_field %dst
 *
 * Verifies memory_copy transfers bytes correctly between two local
 * allocations. */
static void test_memory_copy_between_locals(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("mem");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "cp", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_local* src = lauf_asm_build_local(b, (lauf_asm_layout){8, 8});
        lauf_asm_local* dst = lauf_asm_build_local(b, (lauf_asm_layout){8, 8});

        /* src = 0xCAFEBABE (stored as a lauf_uint field) */
        lauf_asm_inst_uint(b, 0xCAFEBABEULL);
        lauf_asm_inst_local_addr(b, src);
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);

        /* memory.copy(dest=dst, src=src, count=8) */
        lauf_asm_inst_local_addr(b, dst);
        lauf_asm_inst_local_addr(b, src);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_call_builtin(b, lauf_lib_memory_copy);

        /* Load dst and return. */
        lauf_asm_inst_local_addr(b, dst);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false");
    CHECK(out.as_uint == 0xCAFEBABEULL,
          "expected 0xCAFEBABE, got 0x%llx", (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Fill an 8-byte local with 0xAB and cmp against a second local filled with
 * 0xAB. cmp should return 0 (memcmp equal). */
static void test_memory_fill_and_cmp(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("fillcmp");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "fc", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_local* a = lauf_asm_build_local(b, (lauf_asm_layout){8, 8});
        lauf_asm_local* c = lauf_asm_build_local(b, (lauf_asm_layout){8, 8});

        /* memory.fill(a, 0xAB, 8) */
        lauf_asm_inst_local_addr(b, a);
        lauf_asm_inst_uint(b, 0xAB);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_call_builtin(b, lauf_lib_memory_fill);

        /* memory.fill(c, 0xAB, 8) */
        lauf_asm_inst_local_addr(b, c);
        lauf_asm_inst_uint(b, 0xAB);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_call_builtin(b, lauf_lib_memory_fill);

        /* memory.cmp(a, c, 8) -> sint (== 0 if equal) */
        lauf_asm_inst_local_addr(b, a);
        lauf_asm_inst_local_addr(b, c);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_call_builtin(b, lauf_lib_memory_cmp);

        /* Push 0 and compare — if a == c the cmp result is 0, so top of
         * stack is 0. But since the assertion is just on the raw sint
         * result, return it directly. */
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false");
    CHECK(out.as_sint == 0,
          "expected memcmp result 0 (equal), got %lld", (long long)out.as_sint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* addr_add adds an offset in bytes to an address. Build a 16-byte local, get
 * its address, addr_add(8) — the resulting address must point to byte 8 of
 * the same allocation, which we verify by writing a value there and reading
 * it back through an aggregate_member access to member 1 of {u64, u64}. */
static void test_addr_add_offsets_within_allocation(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("aa");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "aa", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_layout members[2] = {{8, 8}, {8, 8}};
        lauf_asm_layout agg        = lauf_asm_aggregate_layout(members, 2);
        lauf_asm_local* loc        = lauf_asm_build_local(b, agg);

        /* Write 0xDEAD to loc+8 via addr_add. */
        lauf_asm_inst_uint(b, 0xDEAD);            /* [val] */
        lauf_asm_inst_local_addr(b, loc);         /* [val, addr] */
        lauf_asm_inst_sint(b, 8);                 /* [val, addr, 8] */
        lauf_asm_inst_call_builtin(b, lauf_lib_memory_addr_add(
                                          LAUF_LIB_MEMORY_ADDR_OVERFLOW_PANIC));
        /* stack: [val, addr+8] */
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);
        /* stack: [] */

        /* Read via aggregate_member(1) to prove the write landed at member 1. */
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_aggregate_member(b, 1, members, 2);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 0xDEAD,
          "expected 0xDEAD at member 1 via addr_add(8), got 0x%llx",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* memory.poison + memory.unpoison via builtins. Signature per lib/memory.h:
 * `addr:address => _`. Poison then unpoison a local should not panic; a
 * subsequent load is safe. */
static void test_lib_memory_poison_and_unpoison(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("pu");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "pu", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_local* loc = lauf_asm_build_local(b, (lauf_asm_layout){8, 8});
        /* Store 5 into loc so we can load it after unpoisoning. */
        lauf_asm_inst_uint(b, 5);
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);
        /* Poison loc. */
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_call_builtin(b, lauf_lib_memory_poison);
        /* Unpoison loc. */
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_call_builtin(b, lauf_lib_memory_unpoison);
        /* Load and return. */
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 5, "expected 5 after poison/unpoison roundtrip, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_memory_copy_between_locals", test_memory_copy_between_locals},
    {"test_memory_fill_and_cmp", test_memory_fill_and_cmp},
    {"test_addr_add_offsets_within_allocation", test_addr_add_offsets_within_allocation},
    {"test_lib_memory_poison_and_unpoison", test_lib_memory_poison_and_unpoison},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_lib_memory.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
