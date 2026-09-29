/* Group: vm_execute — high-level vm_execute[_oneshot] API. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/runtime/process.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>
#include <stdlib.h>

static lauf_asm_module* build_module_helpers(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("t");

    /* noop() -> () */
    lauf_asm_function* noop = lauf_asm_add_function(mod, "noop", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, noop);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* id2(a, b) -> a, b */
    lauf_asm_function* id2 = lauf_asm_add_function(mod, "id2", (lauf_asm_signature){2, 2});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, id2);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* out3() -> 10, 20, 30 (top-of-stack last) */
    lauf_asm_function* out3 = lauf_asm_add_function(mod, "out3", (lauf_asm_signature){0, 3});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, out3);
        lauf_asm_inst_uint(b, 10);
        lauf_asm_inst_uint(b, 20);
        lauf_asm_inst_uint(b, 30);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* panicker() -> unconditional panic */
    lauf_asm_function* panicker
        = lauf_asm_add_function(mod, "panicker", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, panicker);
        /* Push a null address as the message, then panic. */
        lauf_asm_inst_null(b);
        lauf_asm_inst_panic(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    return mod;
}

static void test_execute_oneshot_noop(void)
{
    lauf_asm_module* mod = build_module_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "noop");
    CHECK(fn != NULL, "find noop returned null");

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    CHECK(ok, "execute_oneshot(noop) returned false");
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static void test_execute_oneshot_identity_2args(void)
{
    lauf_asm_module* mod = build_module_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "id2");
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_value input[2], output[2];
    input[0].as_uint = 111;
    input[1].as_uint = 222;

    int ok = lauf_vm_execute_oneshot(vm, prog, input, output);
    CHECK(ok, "execute_oneshot(id2) returned false");
    CHECK(output[0].as_uint == 111, "output[0] expected 111, got %llu",
          (unsigned long long)output[0].as_uint);
    CHECK(output[1].as_uint == 222, "output[1] expected 222, got %llu",
          (unsigned long long)output[1].as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static void test_execute_oneshot_returns_multiple_outputs(void)
{
    lauf_asm_module* mod = build_module_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "out3");
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_value output[3];
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, output);
    CHECK(ok, "execute_oneshot(out3) returned false");

    /* The doc contract says output[0] = stack-bottom-first, output[N] = top.
     * We pushed 10, 20, 30 in that order (30 is top), so output[0]=10,
     * output[1]=20, output[2]=30. */
    CHECK(output[0].as_uint == 10, "output[0] expected 10, got %llu",
          (unsigned long long)output[0].as_uint);
    CHECK(output[1].as_uint == 20, "output[1] expected 20, got %llu",
          (unsigned long long)output[1].as_uint);
    CHECK(output[2].as_uint == 30, "output[2] expected 30, got %llu",
          (unsigned long long)output[2].as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Test that a panic invokes the installed handler and vm_execute returns
 * false. The handler receives the exact same message that was on top of the
 * value stack at the point of the panic instruction. */
struct panic_ctx
{
    int called;
    int msg_was_null;
};

static void panic_capture(void* user_data, lauf_runtime_process* p, const char* msg)
{
    (void)p;
    struct panic_ctx* c = (struct panic_ctx*)user_data;
    c->called           = 1;
    c->msg_was_null     = (msg == NULL || msg[0] == '\0');
}

static void test_execute_panic_handler_invoked(void)
{
    lauf_asm_module* mod = build_module_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "panicker");
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    struct panic_ctx ctx = {0, 0};
    lauf_vm_panic_handler h = {&ctx, panic_capture};
    lauf_vm_set_panic_handler(vm, h);

    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    CHECK(!ok, "execute_oneshot(panicker) returned true — expected false on panic");
    CHECK(ctx.called == 1, "panic handler was not invoked (called=%d)", ctx.called);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* vm_execute (non-oneshot) leaves the program alive after execution — the
 * caller destroys it separately. Verify that we can execute a program twice
 * on the same VM+program pair by using vm_execute instead of oneshot. */
static void test_vm_execute_non_oneshot_can_reexecute(void)
{
    lauf_asm_module* mod = build_module_helpers();
    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "out3");
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_runtime_value out[3];
    for (int i = 0; i < 3; ++i) /* re-execute the same program 3 times */
    {
        out[0].as_uint = 0;
        out[1].as_uint = 0;
        out[2].as_uint = 0;
        int ok = lauf_vm_execute(vm, &prog, NULL, out);
        CHECK(ok, "vm_execute iteration %d returned false", i);
        CHECK(out[0].as_uint == 10, "iter %d out[0]=%llu", i, (unsigned long long)out[0].as_uint);
        CHECK(out[1].as_uint == 20, "iter %d out[1]=%llu", i, (unsigned long long)out[1].as_uint);
        CHECK(out[2].as_uint == 30, "iter %d out[2]=%llu", i, (unsigned long long)out[2].as_uint);
    }

    lauf_asm_destroy_program(prog);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* vm_set_user_data / vm_get_user_data roundtrip the arbitrary void* the
 * caller supplies. vm_set_user_data returns the previous value. */
static void test_vm_user_data_roundtrip(void)
{
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    /* Default user_data comes from lauf_default_vm_options, which we don't
     * pin here — but a freshly-set pointer must be readable back, and
     * setting to a new value must return the previous one. */
    static int a = 111, b = 222;
    void* prev1 = lauf_vm_set_user_data(vm, &a);
    (void)prev1; /* default value is not specified by the API */
    void* got_a = lauf_vm_get_user_data(vm);
    CHECK(got_a == &a, "vm_get_user_data after setting &a returned %p, expected %p",
          got_a, (void*)&a);

    void* prev2 = lauf_vm_set_user_data(vm, &b);
    CHECK(prev2 == &a, "vm_set_user_data(&b) should have returned prior &a, got %p",
          prev2);
    void* got_b = lauf_vm_get_user_data(vm);
    CHECK(got_b == &b, "vm_get_user_data after setting &b returned %p, expected %p",
          got_b, (void*)&b);

    lauf_destroy_vm(vm);
}

/* vm_set_allocator / vm_get_allocator swap the allocator on a live VM.
 * vm_set_allocator returns the previous allocator so callers can restore. */
static int g_alloc_count = 0;

static void* count_alloc(void* u, size_t sz, size_t align)
{
    (void)u;
    (void)align;
    ++g_alloc_count;
    return malloc(sz);
}
static void count_free(void* u, void* ptr, size_t sz)
{
    (void)u;
    (void)sz;
    free(ptr);
}

static void test_vm_allocator_swap(void)
{
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    lauf_vm_allocator custom = {NULL, count_alloc, count_free};
    lauf_vm_allocator prev   = lauf_vm_set_allocator(vm, custom);
    /* prev.free_alloc / heap_alloc must be non-null for the default (malloc
     * allocator). */
    CHECK(prev.heap_alloc != NULL, "prior allocator's heap_alloc should be non-null");

    lauf_vm_allocator got = lauf_vm_get_allocator(vm);
    CHECK(got.heap_alloc == custom.heap_alloc,
          "vm_get_allocator did not return the just-set allocator");
    CHECK(got.free_alloc == custom.free_alloc, "vm_get_allocator free_alloc mismatch");

    /* Restore prior. */
    (void)lauf_vm_set_allocator(vm, prev);

    /* Also verify the two pre-defined allocators are usable. */
    lauf_vm_allocator nul_a = lauf_vm_null_allocator;
    lauf_vm_allocator mal_a = lauf_vm_malloc_allocator;
    /* malloc allocator must have non-null callbacks; null allocator may or
     * may not — but calling get_allocator after setting one must reflect it. */
    CHECK(mal_a.heap_alloc != NULL, "lauf_vm_malloc_allocator.heap_alloc must be non-null");
    (void)nul_a;

    lauf_destroy_vm(vm);
}

/* Force the runtime's vstack-grow path: build a callee whose local pushes
 * exceed a deliberately-tiny initial_vstack_size, so entering the call at
 * runtime must reallocate the vstack rather than pushing into pre-reserved
 * capacity. Sum verifies every pushed value is preserved across the grow. */
static void test_vstack_grow_under_pressure(void)
{
    enum { N_PUSH = 100 };

    lauf_asm_module* mod = lauf_asm_create_module("m");

    /* big() pushes 1..N_PUSH, pops down to just the first (=1). Signature
     * (0 => 1) so the caller sees exactly one output. */
    lauf_asm_function* big = lauf_asm_add_function(mod, "big", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, big);
        for (unsigned i = 1; i <= N_PUSH; ++i)
            lauf_asm_inst_uint(b, i);
        /* Pop the top N_PUSH-1 values so the survivor is the FIRST push (=1). */
        for (unsigned i = 0; i < N_PUSH - 1; ++i)
            lauf_asm_inst_pop(b, 0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* Thin entry that just calls big — the call is the point at which the
     * runtime checks whether big's max_vstack_size fits the remaining
     * vstack capacity and, if not, triggers allocate_more_vstack_space. */
    lauf_asm_function* entry = lauf_asm_add_function(mod, "e", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, big);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    /* initial_vstack_size deliberately smaller than big's need to force a
     * grow. max_vstack_size stays large so the grow succeeds. */
    lauf_vm_options opts               = lauf_default_vm_options;
    opts.initial_vstack_size_in_elements = 8;

    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_vm*         vm   = lauf_create_vm(opts);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute returned false — vstack grow path likely failed");
    /* After push 1..N then pop N-1 from top, the survivor is the FIRST push,
     * which is 1. Any smaller/larger value indicates the grow copied wrong. */
    CHECK(out.as_uint == 1, "expected survivor=1, got %llu", (unsigned long long)out.as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Exercise the runtime pick and roll opcodes (as opposed to their
 * build-only counterparts in test_asm_inst). pick(idx>=1) must NOT lower to
 * a dup — it needs to hit the pick dispatch that copies from depth idx.
 * roll(idx>=1) rotates the value at depth idx to the top. */
static void test_pick_and_roll_execute(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("pr");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "s", (lauf_asm_signature){0, 4});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* Stack: []. */
        lauf_asm_inst_uint(b, 10);
        lauf_asm_inst_uint(b, 20);
        lauf_asm_inst_uint(b, 30);
        /* Stack: [10, 20, 30] (top=30). pick(1) copies depth-1 (=20) to
         * the top → [10, 20, 30, 20]. */
        lauf_asm_inst_pick(b, 1);
        /* roll(3) moves depth-3 (=10) to the top → [20, 30, 20, 10]. */
        lauf_asm_inst_roll(b, 3);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*         vm   = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out[4];
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, out), "execute returned false");
    /* Output convention: out[0] = bottom, out[3] = top. */
    CHECK(out[0].as_uint == 20, "out[0] expected 20, got %llu",
          (unsigned long long)out[0].as_uint);
    CHECK(out[1].as_uint == 30, "out[1] expected 30, got %llu",
          (unsigned long long)out[1].as_uint);
    CHECK(out[2].as_uint == 20, "out[2] expected 20, got %llu",
          (unsigned long long)out[2].as_uint);
    CHECK(out[3].as_uint == 10, "out[3] expected 10, got %llu",
          (unsigned long long)out[3].as_uint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_execute_oneshot_noop", test_execute_oneshot_noop},
    {"test_execute_oneshot_identity_2args", test_execute_oneshot_identity_2args},
    {"test_execute_oneshot_returns_multiple_outputs", test_execute_oneshot_returns_multiple_outputs},
    {"test_execute_panic_handler_invoked", test_execute_panic_handler_invoked},
    {"test_vm_execute_non_oneshot_can_reexecute", test_vm_execute_non_oneshot_can_reexecute},
    {"test_vm_user_data_roundtrip", test_vm_user_data_roundtrip},
    {"test_vm_allocator_swap", test_vm_allocator_swap},
    {"test_vstack_grow_under_pressure", test_vstack_grow_under_pressure},
    {"test_pick_and_roll_execute", test_pick_and_roll_execute},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_vm_execute.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
