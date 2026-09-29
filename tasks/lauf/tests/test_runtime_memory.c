/* Group: runtime_memory — static allocation, address<->pointer, globals.
 *
 * These tests need a running process (add_static_*_allocation and
 * get_global_address both take lauf_runtime_process*). We drive that by
 * defining a native function on the program and calling it from bytecode —
 * inside the native function we have a live `lauf_runtime_process*`.
 *
 * IMPORTANT: harness.h forks each test into its own process, so any static
 * global set inside a child does NOT propagate back to the parent. Instead
 * the native callback writes directly into the shared-memory `cur` Result
 * pointer that the harness sets up. On failure the child exits non-zero and
 * the harness reads the message + failed flag from shared memory. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/runtime/memory.h>
#include <lauf/runtime/process.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>
#include <string.h>

/* Set cur (the shared-memory Result the harness uses) into a fail state with
 * a formatted message. Safe to call from inside a native function that is
 * itself called from within a forked child. */
#define FAIL_IN_NATIVE(...)                                                                        \
    do                                                                                             \
    {                                                                                              \
        snprintf(cur->msg, sizeof cur->msg, __VA_ARGS__);                                          \
        cur->passed = 0;                                                                           \
        return true;                                                                               \
    } while (0)

static char g_const_data[16];
static char g_mut_data[8];

static bool native_check_static_const(void* user_data, lauf_runtime_process* p,
                                      const lauf_runtime_value* input,
                                      lauf_runtime_value*       output)
{
    (void)user_data;
    (void)input;
    (void)output;

    for (int i = 0; i < 16; ++i)
        g_const_data[i] = (char)('a' + i);

    lauf_runtime_address addr
        = lauf_runtime_add_static_const_allocation(p, g_const_data, 16);
    const void* ptr = lauf_runtime_get_const_ptr(p, addr, (lauf_asm_layout){16, 1});
    if (ptr == NULL)
        FAIL_IN_NATIVE("get_const_ptr returned NULL for a fresh static const allocation");
    if (memcmp(ptr, g_const_data, 16) != 0)
        FAIL_IN_NATIVE("get_const_ptr returned a buffer that did not match the source bytes");

    void* mut = lauf_runtime_get_mut_ptr(p, addr, (lauf_asm_layout){16, 1});
    if (mut != NULL)
        FAIL_IN_NATIVE("get_mut_ptr on a static const allocation returned non-null");
    return true;
}

static bool native_check_static_mut(void* user_data, lauf_runtime_process* p,
                                    const lauf_runtime_value* input,
                                    lauf_runtime_value*       output)
{
    (void)user_data;
    (void)input;
    (void)output;

    memset(g_mut_data, 0, sizeof(g_mut_data));
    lauf_runtime_address addr
        = lauf_runtime_add_static_mut_allocation(p, g_mut_data, 8);

    void* mut = lauf_runtime_get_mut_ptr(p, addr, (lauf_asm_layout){8, 1});
    if (mut == NULL)
        FAIL_IN_NATIVE("get_mut_ptr returned NULL for a fresh static mut allocation");
    memcpy(mut, "ABCDEFGH", 8);

    const void* con = lauf_runtime_get_const_ptr(p, addr, (lauf_asm_layout){8, 1});
    if (con == NULL)
        FAIL_IN_NATIVE("get_const_ptr on a mut allocation returned NULL");
    if (memcmp(con, "ABCDEFGH", 8) != 0)
        FAIL_IN_NATIVE("write via mut ptr not visible through const ptr");
    return true;
}

static lauf_asm_global* g_captured_global;

static bool native_check_global(void* user_data, lauf_runtime_process* p,
                                const lauf_runtime_value* input, lauf_runtime_value* output)
{
    (void)user_data;
    (void)input;
    (void)output;

    lauf_runtime_address addr = lauf_runtime_get_global_address(p, g_captured_global);
    if (addr.allocation == lauf_runtime_address_null.allocation
        && addr.generation == lauf_runtime_address_null.generation
        && addr.offset == lauf_runtime_address_null.offset)
        FAIL_IN_NATIVE("get_global_address returned the null address for a defined global");
    return true;
}

/* Build a module: `main() { call native; return; }`. Install the native fn
 * on the program, then execute — the native fn runs inside a live process. */
static void run_native_probe(const char* fname_native, const char* fname_entry,
                             lauf_asm_native_function nf, int need_global)
{
    lauf_asm_module*   mod = lauf_asm_create_module("mm");
    lauf_asm_function* nfn = lauf_asm_add_function(mod, fname_native, (lauf_asm_signature){0, 0});
    lauf_asm_function* entry
        = lauf_asm_add_function(mod, fname_entry, (lauf_asm_signature){0, 0});

    if (need_global)
    {
        g_captured_global = lauf_asm_add_global(mod, LAUF_ASM_GLOBAL_READ_WRITE);
        lauf_asm_define_data_global(mod, g_captured_global, (lauf_asm_layout){8, 8}, NULL);
    }

    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, entry);
        lauf_asm_inst_call(b, nfn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, entry);
    lauf_asm_define_native_function(&prog, nfn, nf, NULL);

    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static void test_static_const_allocation_readable(void)
{
    run_native_probe("nat", "entry", native_check_static_const, 0);
}

static void test_static_mut_allocation_writable(void)
{
    run_native_probe("nat", "entry", native_check_static_mut, 0);
}

static void test_get_global_address_of_program_global(void)
{
    g_captured_global = NULL;
    run_native_probe("nat", "entry", native_check_global, 1);
}

static const TestEntry TESTS[] = {
    {"test_static_const_allocation_readable", test_static_const_allocation_readable},
    {"test_static_mut_allocation_writable", test_static_mut_allocation_writable},
    {"test_get_global_address_of_program_global", test_get_global_address_of_program_global},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_runtime_memory.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
