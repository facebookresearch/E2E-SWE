/* Group: lib_heap — heap allocation builtins. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/lib/heap.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* Allocate 8 bytes on the heap and write a lauf_uint into them, then read
 * the value back and return it. This exercises alloc + get_mut_ptr semantics
 * transitively through store/load. */
static void test_heap_alloc_returns_writable_address(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("heap");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "alloc", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);

        /* heap.alloc(alignment=8, size=8) -> addr */
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_call_builtin(b, lauf_lib_heap_alloc);
        /* stack: [addr] */

        /* Duplicate addr, push value, swap so store_field sees (value, addr).
         * store_field's signature is: value ptr:address => _ */
        lauf_asm_inst_pick(b, 0);     /* [addr, addr] */
        lauf_asm_inst_uint(b, 0xDEADBEEFULL); /* [addr, addr, value] */
        lauf_asm_inst_roll(b, 1);              /* [addr, value, addr] */
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);
        /* stack: [addr] */

        /* Load back. */
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
    CHECK(out.as_uint == 0xDEADBEEFULL, "expected 0xDEADBEEF, got 0x%llx",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Alloc + free roundtrip: allocate 16 bytes, free the address. The successful
 * completion of the function (no panic) is the test — freeing a valid heap
 * addr must not panic. Returns 1 as an assertion sentinel. */
static void test_heap_alloc_free_roundtrip(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("heap2");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "af", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_uint(b, 16);
        lauf_asm_inst_call_builtin(b, lauf_lib_heap_alloc);
        /* stack: [addr] */
        lauf_asm_inst_call_builtin(b, lauf_lib_heap_free);
        /* stack: [] */
        lauf_asm_inst_uint(b, 1);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false — free of a fresh alloc should not panic");
    CHECK(out.as_uint == 1, "expected sentinel 1, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* heap_alloc_array signature (per lib/heap.h): alignment size count => addr.
 * Verify allocation succeeds and the returned address is usable to write
 * one uint at the base. */
static void test_heap_alloc_array_writable(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("aa");
    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "aa", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* alloc_array(alignment=8, size=8, count=4) -> [addr] */
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_uint(b, 8);
        lauf_asm_inst_uint(b, 4);
        lauf_asm_inst_call_builtin(b, lauf_lib_heap_alloc_array);
        /* stack: [addr]. Write 0x1234 to *addr, then load back. */
        lauf_asm_inst_pick(b, 0);              /* [addr, addr] */
        lauf_asm_inst_uint(b, 0x1234);         /* [addr, addr, val] */
        lauf_asm_inst_roll(b, 1);              /* [addr, val, addr] */
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);
        /* stack: [addr]. */
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 0x1234, "expected 0x1234, got 0x%llx",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* heap_gc signature: `_ => total_bytes_freed:uint`. In a clean VM with no
 * unreachable heap, gc returns 0. Verify it executes and yields a uint. */
static void test_heap_gc_returns_uint(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("gc");
    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "g", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* gc pops nothing, pushes total bytes freed. */
        lauf_asm_inst_call_builtin(b, lauf_lib_heap_gc);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    /* With no heap allocations, gc should report 0 freed. */
    CHECK(out.as_uint == 0, "expected clean gc to report 0 freed bytes, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_heap_alloc_returns_writable_address", test_heap_alloc_returns_writable_address},
    {"test_heap_alloc_free_roundtrip", test_heap_alloc_free_roundtrip},
    {"test_heap_alloc_array_writable", test_heap_alloc_array_writable},
    {"test_heap_gc_returns_uint", test_heap_gc_returns_uint},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_lib_heap.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
