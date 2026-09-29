/* Group: asm_program — program creation, chunk-based programs, link_module. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/lib/int.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* Both `create_program(mod, fn)` and `create_program_from_chunk(mod, chunk)`
 * produce a valid program that runs on the VM. The chunk path is meaningful
 * because chunks are the "reusable temporary code" analogue of functions. */
static void test_create_program_from_function_and_chunk(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("p");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "ret7", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 7);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "function build_finish returned false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog_fn = lauf_asm_create_program(mod, fn);
    const lauf_asm_function* entry = lauf_asm_program_entry_function(&prog_fn);
    CHECK(entry == fn, "program_entry_function returned wrong pointer");

    /* Now build a chunk that yields 9 and create a program from it. */
    lauf_asm_chunk* chunk = lauf_asm_create_chunk(mod);
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build_chunk(b, mod, chunk, (lauf_asm_signature){0, 1});
        lauf_asm_inst_uint(b, 9);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "chunk build_finish returned false");
        lauf_asm_destroy_builder(b);
    }
    CHECK(!lauf_asm_chunk_is_empty(chunk), "built chunk still reports empty");

    lauf_asm_signature csig = lauf_asm_chunk_signature(chunk);
    CHECK(csig.input_count == 0 && csig.output_count == 1,
          "chunk signature: got (%u => %u), expected (0 => 1)",
          (unsigned)csig.input_count, (unsigned)csig.output_count);

    lauf_asm_program prog_chunk = lauf_asm_create_program_from_chunk(mod, chunk);

    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog_fn, NULL, &out), "execute prog_fn returned false");
    CHECK(out.as_uint == 7, "prog_fn out expected 7, got %llu", (unsigned long long)out.as_uint);

    CHECK(lauf_vm_execute_oneshot(vm, prog_chunk, NULL, &out),
          "execute prog_chunk returned false");
    CHECK(out.as_uint == 9, "prog_chunk out expected 9, got %llu",
          (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Cross-module resolution: build a function in module A that calls an extern
 * `helper` (signature 0 => 1). Then build module B with a `helper` definition
 * returning 5. `lauf_asm_link_module` should resolve the extern so that
 * executing the program from A returns 5. */
static void test_link_modules_and_resolve_extern(void)
{
    lauf_asm_module*   modA = lauf_asm_create_module("A");
    lauf_asm_function* entry
        = lauf_asm_add_function(modA, "main", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, modA, entry);
        /* Call extern "helper" that returns 1 value; return it. */
        lauf_asm_inst_call_extern(b, "helper", (lauf_asm_signature){0, 1});
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "A build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_module*   modB = lauf_asm_create_module("B");
    lauf_asm_function* helper
        = lauf_asm_add_function(modB, "helper", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, modB, helper);
        lauf_asm_inst_uint(b, 5);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "B build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(modA, entry);
    lauf_asm_link_module(&prog, modB);

    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute after link_module returned false");
    CHECK(out.as_uint == 5, "expected linked helper to return 5, got %llu",
          (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(modB);
    lauf_asm_destroy_module(modA);
}

/* link_modules (plural) accepts an array of modules and links them all in
 * one call. Same shape as link_module: build A referencing "helperA" and
 * "helperB", plus modules B and C each defining one of them. After
 * link_modules(A, [B, C], 2), execution of A must resolve both externs. */
static void test_link_modules_plural(void)
{
    lauf_asm_module*   modA = lauf_asm_create_module("A");
    lauf_asm_function* entry
        = lauf_asm_add_function(modA, "main", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, modA, entry);
        /* helperA() -> 3, helperB() -> 4, add them via uadd(WRAP) -> 7. */
        lauf_asm_inst_call_extern(b, "helperA", (lauf_asm_signature){0, 1});
        lauf_asm_inst_call_extern(b, "helperB", (lauf_asm_signature){0, 1});
        lauf_asm_inst_call_builtin(b, lauf_lib_int_uadd(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "A build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_module*   modB = lauf_asm_create_module("B");
    lauf_asm_function* hA
        = lauf_asm_add_function(modB, "helperA", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, modB, hA);
        lauf_asm_inst_uint(b, 3);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "B helperA build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_module*   modC = lauf_asm_create_module("C");
    lauf_asm_function* hB
        = lauf_asm_add_function(modC, "helperB", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, modC, hB);
        lauf_asm_inst_uint(b, 4);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "C helperB build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(modA, entry);
    const lauf_asm_module* mods[] = {modB, modC};
    lauf_asm_link_modules(&prog, mods, 2);

    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute after link_modules false");
    CHECK(out.as_uint == 7, "expected helperA()+helperB()=3+4=7, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(modC);
    lauf_asm_destroy_module(modB);
    lauf_asm_destroy_module(modA);
}

/* define_native_global overlays a program global with host memory. Read the
 * global from bytecode; the value seen must be whatever the host memory
 * contains at that moment. */
static void test_define_native_global_overlays(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("ng");
    lauf_asm_global* g   = lauf_asm_add_global(mod, LAUF_ASM_GLOBAL_READ_WRITE);
    /* Declared but not defined via define_data_global — we'll define via
     * define_native_global instead so has_definition is unaffected. */

    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "read", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_global_addr(b, g);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "read build_finish false");
        lauf_asm_destroy_builder(b);
    }

    static lauf_uint host_backing = 0xC0DEC0DEULL;
    lauf_asm_program prog         = lauf_asm_create_program(mod, fn);
    lauf_asm_define_native_global(&prog, g, &host_backing, sizeof(host_backing));

    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 0xC0DEC0DEULL,
          "expected native-backed global read to see 0xC0DEC0DE, got 0x%llx",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_create_program_from_function_and_chunk", test_create_program_from_function_and_chunk},
    {"test_link_modules_and_resolve_extern", test_link_modules_and_resolve_extern},
    {"test_link_modules_plural", test_link_modules_plural},
    {"test_define_native_global_overlays", test_define_native_global_overlays},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_asm_program.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
