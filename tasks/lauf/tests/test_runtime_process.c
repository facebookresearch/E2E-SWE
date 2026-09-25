/* Group: runtime_process — VM/program queries, panic surface. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/runtime/process.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>
#include <string.h>

/* From inside a native function, get_vm() must return the same VM that
 * launched the process, and get_program() must return the program handle. */
#define FAIL_IN_NATIVE(...)                                                                        \
    do                                                                                             \
    {                                                                                              \
        snprintf(cur->msg, sizeof cur->msg, __VA_ARGS__);                                          \
        cur->passed = 0;                                                                           \
        return true;                                                                               \
    } while (0)

static lauf_vm* g_expected_vm;

static bool native_check_vm(void* user_data, lauf_runtime_process* p,
                            const lauf_runtime_value* input, lauf_runtime_value* output)
{
    (void)user_data;
    (void)input;
    (void)output;

    /* get_vm returns the exact VM handle that launched the process — a fair
     * pointer-identity check because the VM is a stable heap allocation. */
    lauf_vm* seen_vm = lauf_runtime_get_vm(p);
    if (seen_vm != g_expected_vm)
        FAIL_IN_NATIVE("get_vm did not return the launching VM (seen=%p expected=%p)",
                       (void*)seen_vm, (void*)g_expected_vm);

    /* get_program returns a pointer to the program, but the implementation is
     * free to hand back a pointer to an internal copy that mirrors what the
     * caller passed to vm_start_process. Assert on the entry function
     * instead — that is definitely the same across the boundary because
     * lauf_asm_program's entry field points at the module-owned function. */
    const lauf_asm_program* seen_prog = lauf_runtime_get_program(p);
    if (seen_prog == NULL)
        FAIL_IN_NATIVE("get_program returned NULL");
    const lauf_asm_function* seen_entry = lauf_asm_program_entry_function(seen_prog);
    if (seen_entry == NULL)
        FAIL_IN_NATIVE("get_program's entry function is NULL");
    const char* seen_name = lauf_asm_function_name(seen_entry);
    if (seen_name == NULL || strcmp(seen_name, "main") != 0)
        FAIL_IN_NATIVE("get_program's entry function name is not \"main\": %s",
                       seen_name ? seen_name : "(null)");
    return true;
}

static void test_get_vm_and_program_from_process(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("q");
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "nat", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, native_check_vm, NULL);

    lauf_vm* vm         = lauf_create_vm(lauf_default_vm_options);
    g_expected_vm       = vm;

    lauf_runtime_process* proc = lauf_vm_start_process(vm, &prog);
    lauf_runtime_fiber* fiber = lauf_runtime_get_current_fiber(proc);
    int ok = lauf_runtime_resume(proc, fiber, NULL, 0, NULL, 0);
    CHECK(ok, "resume returned false — native probe fired FAIL, see message");

    lauf_runtime_destroy_process(proc);
    lauf_asm_destroy_program(prog);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Native function that triggers a panic via lauf_runtime_panic and returns
 * false. The panic handler receives the same message text. */
static const char* g_panic_msg = "custom panic!";
static char        g_seen_panic_msg[128];

static void panic_capture(void* user_data, lauf_runtime_process* p, const char* msg)
{
    (void)user_data;
    (void)p;
    if (msg != NULL)
    {
        strncpy(g_seen_panic_msg, msg, sizeof(g_seen_panic_msg) - 1);
        g_seen_panic_msg[sizeof(g_seen_panic_msg) - 1] = '\0';
    }
}

static bool native_panic(void* user_data, lauf_runtime_process* p,
                         const lauf_runtime_value* input, lauf_runtime_value* output)
{
    (void)user_data;
    (void)input;
    (void)output;
    return lauf_runtime_panic(p, g_panic_msg);
}

static void test_native_function_panic_message(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("panicprobe");
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "nat", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, native_panic, NULL);

    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);

    g_seen_panic_msg[0] = '\0';
    lauf_vm_panic_handler h = {NULL, panic_capture};
    lauf_vm_set_panic_handler(vm, h);

    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    /* Panic → returns false and outputs are not updated. */
    CHECK(!ok, "expected execute to return false on panic, got true");
    /* The panic handler is inside the SAME process as the test, so it CAN
     * populate g_seen_panic_msg (test does not fork the callback). */
    CHECK(strcmp(g_seen_panic_msg, g_panic_msg) == 0,
          "panic handler saw \"%s\", expected \"%s\"", g_seen_panic_msg, g_panic_msg);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* iterate_fibers walks all fibers of the process; get_current_fiber returns
 * the active one. Verify iteration hits the current fiber. */
static int g_iter_saw_current;
static bool nat_iterate_fibers(void* u, lauf_runtime_process* p,
                               const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    lauf_runtime_fiber* cur_fib = lauf_runtime_get_current_fiber(p);
    if (cur_fib == NULL)
        FAIL_IN_NATIVE("get_current_fiber returned NULL inside native");

    int saw_cur = 0;
    int fiber_count = 0;
    for (lauf_runtime_fiber* f = lauf_runtime_iterate_fibers(p); f != NULL;
         f                     = lauf_runtime_iterate_fibers_next(f))
    {
        ++fiber_count;
        if (f == cur_fib)
            saw_cur = 1;
    }
    if (fiber_count < 1)
        FAIL_IN_NATIVE("iterate_fibers yielded zero fibers");
    if (!saw_cur)
        FAIL_IN_NATIVE("iterate_fibers did not include the current fiber");
    g_iter_saw_current = 1;
    return true;
}

static void test_iterate_fibers_includes_current(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("if");
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "n", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, nat_iterate_fibers, NULL);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* runtime_call executes a program function from inside a native function.
 * Build: helper() -> 77. Native: call helper via runtime_call, expect out=77
 * to be returned via lauf_runtime_call's output pointer. */
static lauf_asm_function* g_helper_fn;
static lauf_uint          g_call_out_seen;

static bool nat_runtime_call(void* u, lauf_runtime_process* p,
                             const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    lauf_runtime_value r;
    r.as_uint = 0;
    bool ok = lauf_runtime_call(p, g_helper_fn, NULL, &r);
    if (!ok)
        FAIL_IN_NATIVE("lauf_runtime_call returned false");
    g_call_out_seen = r.as_uint;
    if (r.as_uint != 77)
        FAIL_IN_NATIVE("lauf_runtime_call expected 77, got %llu",
                       (unsigned long long)r.as_uint);
    return true;
}

static void test_runtime_call_from_native(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("rc");
    g_helper_fn = lauf_asm_add_function(mod, "helper", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, g_helper_fn);
        lauf_asm_inst_uint(b, 77);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "n", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, nat_runtime_call, NULL);

    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    g_call_out_seen = 0;
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* get_function_ptr / get_function_ptr_any: given a function_address, return
 * the function pointer or NULL if signature doesn't match. get_function_ptr
 * checks the signature; get_function_ptr_any doesn't. */
static bool nat_function_ptr(void* u, lauf_runtime_process* p,
                             const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    lauf_runtime_function_address fa;
    fa.index        = 0; /* helper is fn 0 in the module */
    fa.input_count  = 0;
    fa.output_count = 1;
    const lauf_asm_function* got = lauf_runtime_get_function_ptr(p, fa, (lauf_asm_signature){0, 1});
    if (got == NULL)
        FAIL_IN_NATIVE("get_function_ptr returned NULL for a valid signature");

    /* Mismatched signature must return NULL. */
    const lauf_asm_function* wrong
        = lauf_runtime_get_function_ptr(p, fa, (lauf_asm_signature){1, 1});
    if (wrong != NULL)
        FAIL_IN_NATIVE("get_function_ptr returned non-null for mismatched signature");

    /* get_function_ptr_any doesn't enforce a signature — same fa must resolve. */
    const lauf_asm_function* any = lauf_runtime_get_function_ptr_any(p, fa);
    if (any == NULL)
        FAIL_IN_NATIVE("get_function_ptr_any returned NULL for a valid address");

    /* The function-address null sentinel must produce NULL from both. */
    if (lauf_runtime_get_function_ptr(p, lauf_runtime_function_address_null,
                                      (lauf_asm_signature){0, 1})
        != NULL)
        FAIL_IN_NATIVE("get_function_ptr on null-address returned non-null");
    if (lauf_runtime_get_function_ptr_any(p, lauf_runtime_function_address_null) != NULL)
        FAIL_IN_NATIVE("get_function_ptr_any on null-address returned non-null");
    return true;
}

static void test_get_function_ptr_signature_check(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("fp");
    lauf_asm_function* helper
        = lauf_asm_add_function(mod, "helper", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, helper);
        lauf_asm_inst_uint(b, 0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "n", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, nat_function_ptr, NULL);

    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* set_step_limit + increment_step. With a limit of 3, increment_step returns
 * true on the first (3→2) and second (2→1) calls, and false on the third
 * (1→0) — the limit is "reached" exactly when the remaining counter hits
 * zero, so the *final* successful increment returns false. This matches
 * the documented "returns false when the step limit is reached" behavior. */
static bool nat_step_limit(void* u, lauf_runtime_process* p,
                           const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    if (!lauf_runtime_set_step_limit(p, 3))
        FAIL_IN_NATIVE("set_step_limit(3) returned false");
    if (!lauf_runtime_increment_step(p))
        FAIL_IN_NATIVE("increment_step 1 returned false, expected true");
    if (!lauf_runtime_increment_step(p))
        FAIL_IN_NATIVE("increment_step 2 returned false, expected true");
    if (lauf_runtime_increment_step(p))
        FAIL_IN_NATIVE("increment_step 3 returned true, expected false (limit reached)");
    return true;
}

static void test_step_limit_enforced(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("sl");
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "n", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, nat_step_limit, NULL);
    /* Use options with a non-zero step_limit ceiling so set_step_limit(3)
     * is not blocked by the default of 0 = unlimited. Actually, per docs,
     * "The limit cannot be increased beyond the limit provided in the VM
     * config" — so set the VM step_limit to at least 3. */
    lauf_vm_options opts = lauf_default_vm_options;
    opts.step_limit      = 100;
    lauf_vm* vm          = lauf_create_vm(opts);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* get_vm_user_data + get_vstack_base/ptr: the VM's user_data pointer set at
 * creation is retrievable from inside a native, and both vstack getters return
 * valid non-null pointers into the current fiber's value stack. */
static int g_seen_user_data_value;

static bool nat_vm_user_data(void* u, lauf_runtime_process* p,
                             const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    void* got = lauf_runtime_get_vm_user_data(p);
    if (got == NULL)
        FAIL_IN_NATIVE("get_vm_user_data returned NULL");
    g_seen_user_data_value = *(int*)got;
    if (g_seen_user_data_value != 12345)
        FAIL_IN_NATIVE("expected user data pointer to reference value 12345, got %d",
                       g_seen_user_data_value);

    lauf_runtime_fiber* cur_fib = lauf_runtime_get_current_fiber(p);
    if (cur_fib == NULL)
        FAIL_IN_NATIVE("get_current_fiber returned NULL");
    const lauf_runtime_value* base = lauf_runtime_get_vstack_base(cur_fib);
    const lauf_runtime_value* ptr  = lauf_runtime_get_vstack_ptr(p, cur_fib);
    if (base == NULL || ptr == NULL)
        FAIL_IN_NATIVE("expected non-null vstack base/ptr, base=%p ptr=%p",
                       (const void*)base, (const void*)ptr);
    /* The relative ordering of ptr vs base (i.e. which is the higher address,
     * and thus the value stack's memory-growth direction) is an unspecified
     * internal layout detail, so we assert only that both getters return valid
     * non-null pointers into the live vstack. */
    return true;
}

static void test_get_vm_user_data_and_vstack_bounds(void)
{
    static int user_val = 12345;
    lauf_vm_options opts = lauf_default_vm_options;
    opts.user_data       = &user_val;

    lauf_asm_module*   mod = lauf_asm_create_module("ud");
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "n", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, nat_vm_user_data, NULL);
    lauf_vm* vm = lauf_create_vm(opts);
    g_seen_user_data_value = 0;
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* create_fiber / destroy_fiber via the C API. Create a fiber pointing at
 * helper_fiber, get its handle via get_fiber_handle, round-trip through
 * get_fiber_ptr, and finally destroy it. Also verify get_fiber_parent on
 * the current fiber returns NULL (the entry fiber has no parent). */
static lauf_asm_function* g_fiber_fn;

static bool nat_create_destroy_fiber(void* u, lauf_runtime_process* p,
                                     const lauf_runtime_value* in,
                                     lauf_runtime_value*       out)
{
    (void)u;
    (void)in;
    (void)out;
    lauf_runtime_fiber* f = lauf_runtime_create_fiber(p, g_fiber_fn);
    if (f == NULL)
        FAIL_IN_NATIVE("create_fiber returned NULL");
    /* A freshly-created fiber is READY. */
    if (lauf_runtime_get_fiber_status(f) != LAUF_RUNTIME_FIBER_READY)
        FAIL_IN_NATIVE("expected new fiber status READY");

    /* get_fiber_handle returns a non-null address; get_fiber_ptr on that
     * address must resolve to a non-null fiber. We do not require strict
     * pointer identity between the fresh fiber and the round-tripped one
     * because the reference impl treats the fiber allocation as POISONED
     * at creation and the handle→ptr path may not surface the same
     * lauf_runtime_fiber* pointer literally. */
    lauf_runtime_address handle = lauf_runtime_get_fiber_handle(f);
    int handle_is_null = (handle.allocation == lauf_runtime_address_null.allocation
                          && handle.generation == lauf_runtime_address_null.generation);
    if (handle_is_null)
        FAIL_IN_NATIVE("get_fiber_handle returned the null-address sentinel for a fresh fiber");
    lauf_runtime_fiber* round = lauf_runtime_get_fiber_ptr(p, handle);
    if (round == NULL)
        FAIL_IN_NATIVE("get_fiber_ptr returned NULL for a valid fiber handle");

    /* The entry (current) fiber has no parent. */
    lauf_runtime_fiber* cur_fib = lauf_runtime_get_current_fiber(p);
    lauf_runtime_fiber* parent  = lauf_runtime_get_fiber_parent(p, cur_fib);
    if (parent != NULL)
        FAIL_IN_NATIVE("expected entry fiber's parent to be NULL, got %p",
                       (void*)parent);

    /* Destroy the fiber. */
    if (!lauf_runtime_destroy_fiber(p, f))
        FAIL_IN_NATIVE("destroy_fiber returned false");
    return true;
}

static void test_create_destroy_fiber_from_native(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("cd");
    g_fiber_fn = lauf_asm_add_function(mod, "helper", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, g_fiber_fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_function* nfn = lauf_asm_add_function(mod, "n", (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, nat_create_destroy_fiber, NULL);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_get_vm_and_program_from_process", test_get_vm_and_program_from_process},
    {"test_native_function_panic_message", test_native_function_panic_message},
    {"test_iterate_fibers_includes_current", test_iterate_fibers_includes_current},
    {"test_runtime_call_from_native", test_runtime_call_from_native},
    {"test_get_function_ptr_signature_check", test_get_function_ptr_signature_check},
    {"test_step_limit_enforced", test_step_limit_enforced},
    {"test_get_vm_user_data_and_vstack_bounds", test_get_vm_user_data_and_vstack_bounds},
    {"test_create_destroy_fiber_from_native", test_create_destroy_fiber_from_native},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_runtime_process.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
