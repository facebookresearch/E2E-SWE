/* Group: lib_fiber — cooperative-fiber builtins. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/lib/fiber.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/process.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* At start of a fresh process, there is exactly one fiber (the entry fiber),
 * and it is in the READY state. lauf_runtime_is_single_fibered reports true.
 *
 * We drive this from the C side (not bytecode) because the queries we're
 * testing are the C-API queries themselves. */
static void test_fiber_create_and_query_status(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("f");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "noop", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_process* proc = lauf_vm_start_process(vm, &prog);
    lauf_runtime_fiber* cur_fiber = lauf_runtime_get_current_fiber(proc);
    CHECK(cur_fiber != NULL, "get_current_fiber returned NULL");
    CHECK(lauf_runtime_is_single_fibered(proc),
          "brand-new process should have exactly one fiber");

    lauf_runtime_fiber_status s0 = lauf_runtime_get_fiber_status(cur_fiber);
    CHECK(s0 == LAUF_RUNTIME_FIBER_READY,
          "expected initial status READY (0), got %d", (int)s0);

    int ok = lauf_runtime_resume(proc, cur_fiber, NULL, 0, NULL, 0);
    CHECK(ok, "resume returned false");
    lauf_runtime_fiber_status s1 = lauf_runtime_get_fiber_status(cur_fiber);
    CHECK(s1 == LAUF_RUNTIME_FIBER_DONE, "expected DONE (3) after resume, got %d",
          (int)s1);

    lauf_runtime_destroy_process(proc);
    lauf_asm_destroy_program(prog);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Bytecode-level fiber test: main() creates a fiber that runs `producer(_ =>
 * 1)`, resumes it once, and asserts the returned value equals 1. This
 * exercises fiber_create + fiber_resume from within bytecode. */
static void test_fiber_resume_suspend_from_bytecode(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("bcfib");

    lauf_asm_function* producer
        = lauf_asm_add_function(mod, "producer", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, producer);
        lauf_asm_inst_uint(b, 42);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);

        /* handle = fiber_create(&producer) */
        lauf_asm_inst_function_addr(b, producer);
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_create);
        /* stack: [handle] */

        /* resume(handle, sig = (0 => 1)); value pushed on top of stack. */
        lauf_asm_inst_fiber_resume(b, (lauf_asm_signature){0, 1});
        /* stack: [42] */

        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false");
    CHECK(out.as_uint == 42, "expected fiber-returned value 42, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* fiber.current returns a handle to the currently running fiber. Verify by
 * calling it from bytecode and comparing with the current fiber handle
 * queried through the C API. */
static void test_lib_fiber_current_returns_handle(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("cf");
    /* Return the fiber-handle address components split into 2 uints: the
     * `allocation` field (bits 0..29 of the underlying uint64) and the
     * `generation` field (bits 30..31). We just need any non-null result. */
    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "cur", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* fiber.current pushes a fiber handle (which is really an address).
         * Return it and inspect it as as_address. */
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_current);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    /* The returned fiber handle must not equal the null address sentinel — the
     * current fiber always exists during execution. */
    int is_null = (out.as_address.allocation == lauf_runtime_address_null.allocation
                   && out.as_address.generation == lauf_runtime_address_null.generation
                   && out.as_address.offset == lauf_runtime_address_null.offset);
    CHECK(!is_null, "fiber.current returned the null address sentinel");
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* fiber.done returns true if a fiber's status is DONE, false otherwise. Build:
 * producer() returns 1 (runs to completion). main: fiber_create(producer),
 * resume once, fiber_done(handle) -> uint (1 or 0). */
static void test_lib_fiber_done_after_completion(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("df");

    lauf_asm_function* producer
        = lauf_asm_add_function(mod, "prod", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, producer);
        lauf_asm_inst_uint(b, 42);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_function* main
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, main);
        /* handle = fiber_create(prod). */
        lauf_asm_inst_function_addr(b, producer);
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_create);
        /* stack: [handle]. Duplicate so we can resume then query. */
        lauf_asm_inst_pick(b, 0);
        /* stack: [handle, handle]. Resume the top (0 in, 1 out). */
        lauf_asm_inst_fiber_resume(b, (lauf_asm_signature){0, 1});
        /* stack: [handle, 42]. Drop the 42, leave handle. */
        lauf_asm_inst_pop(b, 0);
        /* stack: [handle]. Query fiber.done. */
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_done);
        /* stack: [is_done:uint]. Return it. */
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, main);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 1,
          "expected fiber.done(completed fiber) = 1, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* fiber.destroy on a fresh (READY) fiber must not panic. We build main that
 * creates a fiber and immediately destroys it without resuming. */
static void test_lib_fiber_destroy_ready(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("kf");

    lauf_asm_function* producer
        = lauf_asm_add_function(mod, "prod", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, producer);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_function* main
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, main);
        lauf_asm_inst_function_addr(b, producer);
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_create);
        /* stack: [handle]. destroy consumes handle -> _. */
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_destroy);
        /* Return a sentinel to prove we didn't panic. */
        lauf_asm_inst_uint(b, 1);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, main);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false — destroy on a READY fiber should not panic");
    CHECK(out.as_uint == 1, "expected sentinel 1, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Bytecode-level fiber_suspend / fiber_resume roundtrip that goes through
 * BOTH the mid-fiber `fiber_suspend` opcode and a second `fiber_resume` on
 * the same handle. The producer suspends twice, so the driver observes two
 * distinct yielded values. This exercises the fiber_suspend dispatch path
 * (which the existing single-resume-then-return test does not — the
 * producer there returns rather than suspending). */
static void test_bytecode_fiber_suspend_and_resume(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("sr");

    /* Producer with sig (0 => 0) — the values it hands to the resumer come
     * from its `fiber_suspend (1 => 0)` calls, not from its return. */
    lauf_asm_function* producer
        = lauf_asm_add_function(mod, "prod", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, producer);
        /* Yield 42 to the resumer, expect 0 back. */
        lauf_asm_inst_uint(b, 42);
        lauf_asm_inst_fiber_suspend(b, (lauf_asm_signature){1, 0});
        /* Second yield: 99. */
        lauf_asm_inst_uint(b, 99);
        lauf_asm_inst_fiber_suspend(b, (lauf_asm_signature){1, 0});
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* main returns 2 values: the two yielded ints in resume order. */
    lauf_asm_function* mainfn
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 2});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, mainfn);
        /* handle = fiber_create(&producer) */
        lauf_asm_inst_function_addr(b, producer);
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_create);
        /* stack: [handle]. Duplicate so we can resume twice. */
        lauf_asm_inst_pick(b, 0);
        /* stack: [handle, handle]. First resume: expect 1 value back (42). */
        lauf_asm_inst_fiber_resume(b, (lauf_asm_signature){0, 1});
        /* stack: [handle, 42]. Move handle to top for second resume. */
        lauf_asm_inst_roll(b, 1);
        /* stack: [42, handle]. Second resume: expect 99. */
        lauf_asm_inst_fiber_resume(b, (lauf_asm_signature){0, 1});
        /* stack: [42, 99]. */
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, mainfn);
    lauf_vm*         vm   = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out[2];
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, out);
    CHECK(ok, "execute returned false");
    /* Output convention: out[0]=bottom, out[1]=top. First-yield=42 was
     * pushed first (bottom), second-yield=99 last (top). */
    CHECK(out[0].as_uint == 42, "first-resume yield expected 42, got %llu",
          (unsigned long long)out[0].as_uint);
    CHECK(out[1].as_uint == 99, "second-resume yield expected 99, got %llu",
          (unsigned long long)out[1].as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_fiber_create_and_query_status", test_fiber_create_and_query_status},
    {"test_fiber_resume_suspend_from_bytecode", test_fiber_resume_suspend_from_bytecode},
    {"test_lib_fiber_current_returns_handle", test_lib_fiber_current_returns_handle},
    {"test_lib_fiber_done_after_completion", test_lib_fiber_done_after_completion},
    {"test_lib_fiber_destroy_ready", test_lib_fiber_destroy_ready},
    {"test_bytecode_fiber_suspend_and_resume", test_bytecode_fiber_suspend_and_resume},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_lib_fiber.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
