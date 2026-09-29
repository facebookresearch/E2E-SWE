/* Group: vm_process — start_process, resume, resume_until_completion. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/runtime/process.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

static lauf_asm_module* build_helpers(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("proc");

    /* noop() -> () */
    lauf_asm_function* noop = lauf_asm_add_function(mod, "noop", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, noop);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* id(x) -> x */
    lauf_asm_function* id = lauf_asm_add_function(mod, "id", (lauf_asm_signature){1, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, id);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* pair() -> (100, 200) */
    lauf_asm_function* pair = lauf_asm_add_function(mod, "pair", (lauf_asm_signature){0, 2});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, pair);
        lauf_asm_inst_uint(b, 100);
        lauf_asm_inst_uint(b, 200);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    return mod;
}

static void test_start_process_resume_noop(void)
{
    lauf_asm_module* mod = build_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "noop");
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_process* proc = lauf_vm_start_process(vm, &prog);
    CHECK(proc != NULL, "start_process returned NULL");

    lauf_runtime_fiber* fiber = lauf_runtime_get_current_fiber(proc);
    CHECK(fiber != NULL, "get_current_fiber returned NULL");
    CHECK(lauf_runtime_get_fiber_status(fiber) == LAUF_RUNTIME_FIBER_READY,
          "expected initial fiber status READY");

    int ok = lauf_runtime_resume(proc, fiber, NULL, 0, NULL, 0);
    CHECK(ok, "resume(noop) returned false");
    CHECK(lauf_runtime_get_fiber_status(fiber) == LAUF_RUNTIME_FIBER_DONE,
          "expected fiber status DONE after resume of noop");

    lauf_runtime_destroy_process(proc);
    lauf_asm_destroy_program(prog);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static void test_start_process_resume_with_input_output(void)
{
    lauf_asm_module* mod = build_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "id");
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_process* proc = lauf_vm_start_process(vm, &prog);
    lauf_runtime_fiber* fiber  = lauf_runtime_get_current_fiber(proc);

    lauf_runtime_value in  = {.as_uint = 55};
    lauf_runtime_value out = {.as_uint = 0};
    int ok = lauf_runtime_resume(proc, fiber, &in, 1, &out, 1);
    CHECK(ok, "resume(id, 55) returned false");
    CHECK(out.as_uint == 55, "expected out=55, got %llu", (unsigned long long)out.as_uint);

    lauf_runtime_destroy_process(proc);
    lauf_asm_destroy_program(prog);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* `resume_until_completion` is documented to keep resuming until the current
 * fiber is DONE (it drives multi-suspend fibers to completion). Test the
 * single-fiber degenerate case: after one resume the fiber is done, so the
 * function returns cleanly with the outputs collected from the last suspend
 * point (here: the function's return values). */
static void test_resume_until_completion_finishes(void)
{
    lauf_asm_module* mod = build_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "pair");
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_process* proc = lauf_vm_start_process(vm, &prog);
    lauf_runtime_fiber* fiber  = lauf_runtime_get_current_fiber(proc);

    lauf_runtime_value out[2] = {{.as_uint = 0}, {.as_uint = 0}};
    int ok = lauf_runtime_resume_until_completion(proc, fiber, NULL, 0, out, 2);
    CHECK(ok, "resume_until_completion returned false");
    CHECK(out[0].as_uint == 100, "out[0] expected 100, got %llu",
          (unsigned long long)out[0].as_uint);
    CHECK(out[1].as_uint == 200, "out[1] expected 200, got %llu",
          (unsigned long long)out[1].as_uint);

    /* resume_until_completion is documented to destroy the final fiber; we
     * do NOT explicitly destroy `fiber` after this. */

    lauf_runtime_destroy_process(proc);
    lauf_asm_destroy_program(prog);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_start_process_resume_noop", test_start_process_resume_noop},
    {"test_start_process_resume_with_input_output", test_start_process_resume_with_input_output},
    {"test_resume_until_completion_finishes", test_resume_until_completion_finishes},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_vm_process.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
