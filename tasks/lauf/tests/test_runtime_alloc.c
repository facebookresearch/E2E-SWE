/* Group: runtime_alloc — heap allocation, poison/split/merge, gc, address
 * queries. These probes run inside a native function so the tests have a
 * live lauf_runtime_process*; the outer bytecode is a trivial `call native;
 * return;` scaffold. */
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

#define FAIL_IN_NATIVE(...)                                                                        \
    do                                                                                             \
    {                                                                                              \
        snprintf(cur->msg, sizeof cur->msg, __VA_ARGS__);                                          \
        cur->passed = 0;                                                                           \
        return true;                                                                               \
    } while (0)

/* Small helper: build a module "call nfn; return", install nfn as the native
 * fn, then execute. `nfn` gets a live process. */
static void run_native(lauf_asm_native_function nf)
{
    lauf_asm_module*   mod = lauf_asm_create_module("m");
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
    lauf_asm_define_native_function(&prog, nfn, nf, NULL);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* add_heap_allocation registers a heap allocation over host memory. The
 * resulting address must be usable via get_mut_ptr and via get_allocation
 * (which fills in the allocation metadata: source=HEAP, permission=RW,
 * ptr=given, size=given).
 *
 * The memory MUST be malloc'd (not static) because the VM will pass it to
 * the allocator's free() at process teardown. To keep test isolation clean
 * we then leak_heap_allocation so the VM stops tracking it, and free it
 * ourselves inside the native. */
static bool nat_add_heap_and_query(void* u, lauf_runtime_process* p,
                                   const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    void* backing = malloc(64);
    if (backing == NULL)
        FAIL_IN_NATIVE("malloc failed");
    memset(backing, 'X', 64);

    lauf_runtime_address addr = lauf_runtime_add_heap_allocation(p, backing, 64);

    void* mut = lauf_runtime_get_mut_ptr(p, addr, (lauf_asm_layout){64, 1});
    if (mut == NULL)
    {
        free(backing);
        FAIL_IN_NATIVE("get_mut_ptr on freshly-registered heap allocation returned NULL");
    }
    if (mut != backing)
    {
        free(backing);
        FAIL_IN_NATIVE("get_mut_ptr returned a different pointer than the host backing");
    }

    lauf_runtime_allocation info;
    if (!lauf_runtime_get_allocation(p, addr, &info))
    {
        free(backing);
        FAIL_IN_NATIVE("get_allocation returned false for a valid heap allocation");
    }
    if (info.source != LAUF_RUNTIME_HEAP_ALLOCATION)
    {
        free(backing);
        FAIL_IN_NATIVE("expected allocation.source == LAUF_RUNTIME_HEAP_ALLOCATION, got %d",
                       (int)info.source);
    }
    if ((info.permission & LAUF_RUNTIME_PERM_READ_WRITE) != LAUF_RUNTIME_PERM_READ_WRITE)
    {
        free(backing);
        FAIL_IN_NATIVE("expected heap allocation to have READ_WRITE permission, got %d",
                       (int)info.permission);
    }
    if (info.ptr != backing)
    {
        free(backing);
        FAIL_IN_NATIVE("expected allocation.ptr to match host backing");
    }
    if (info.size != 64)
    {
        free(backing);
        FAIL_IN_NATIVE("expected allocation.size == 64, got %zu", info.size);
    }

    /* Leak from VM tracking + free ourselves — avoids the VM double-freeing
     * (or trying to free with the wrong allocator) at process teardown. */
    lauf_runtime_leak_heap_allocation(p, addr);
    free(backing);
    return true;
}

static void test_add_heap_allocation_and_get_metadata(void)
{
    run_native(nat_add_heap_and_query);
}

/* poison_allocation makes an allocation temporarily inaccessible.
 * get_const_ptr / get_mut_ptr must return NULL for a poisoned allocation.
 * unpoison_allocation restores access. */
static char g_poison_backing[16];

static bool nat_poison_unpoison(void* u, lauf_runtime_process* p,
                                const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    lauf_runtime_address addr
        = lauf_runtime_add_static_mut_allocation(p, g_poison_backing, sizeof(g_poison_backing));
    if (lauf_runtime_get_mut_ptr(p, addr, (lauf_asm_layout){16, 1}) == NULL)
        FAIL_IN_NATIVE("baseline: mut ptr should exist on fresh allocation");

    if (!lauf_runtime_poison_allocation(p, addr))
        FAIL_IN_NATIVE("poison_allocation returned false on a valid allocation");
    if (lauf_runtime_get_mut_ptr(p, addr, (lauf_asm_layout){16, 1}) != NULL)
        FAIL_IN_NATIVE("expected NULL mut ptr on poisoned allocation");
    if (lauf_runtime_get_const_ptr(p, addr, (lauf_asm_layout){16, 1}) != NULL)
        FAIL_IN_NATIVE("expected NULL const ptr on poisoned allocation");

    if (!lauf_runtime_unpoison_allocation(p, addr))
        FAIL_IN_NATIVE("unpoison_allocation returned false");
    if (lauf_runtime_get_mut_ptr(p, addr, (lauf_asm_layout){16, 1}) == NULL)
        FAIL_IN_NATIVE("expected mut ptr to be restored after unpoison");
    return true;
}

static void test_poison_unpoison_gates_access(void)
{
    run_native(nat_poison_unpoison);
}

/* split_allocation splits at an offset; merge_allocation glues them back.
 * Verify that after split, the two returned addresses point to disjoint
 * regions, and after merge we can access the full original range again. */
static char g_split_backing[32];

static bool nat_split_merge(void* u, lauf_runtime_process* p,
                            const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    memset(g_split_backing, 0, sizeof(g_split_backing));
    lauf_runtime_address addr
        = lauf_runtime_add_static_mut_allocation(p, g_split_backing, sizeof(g_split_backing));
    /* Split at offset 16 — but split takes an address that already has the
     * offset applied. Build an offset address by taking the base address and
     * setting offset to 16. */
    lauf_runtime_address split_at = addr;
    split_at.offset               = 16;

    lauf_runtime_address addr1, addr2;
    if (!lauf_runtime_split_allocation(p, split_at, &addr1, &addr2))
        FAIL_IN_NATIVE("split_allocation returned false");

    /* Both halves must be accessible in isolation. */
    void* p1 = lauf_runtime_get_mut_ptr(p, addr1, (lauf_asm_layout){16, 1});
    void* p2 = lauf_runtime_get_mut_ptr(p, addr2, (lauf_asm_layout){16, 1});
    if (p1 == NULL || p2 == NULL)
        FAIL_IN_NATIVE("expected both halves of split allocation to be accessible");
    if (p1 == p2)
        FAIL_IN_NATIVE("split halves returned the same pointer");

    /* Now merge. After merge, the original address should span the full 32
     * bytes again (via allocation 1's base). */
    if (!lauf_runtime_merge_allocation(p, addr1, addr2))
        FAIL_IN_NATIVE("merge_allocation returned false");
    void* pm = lauf_runtime_get_mut_ptr(p, addr1, (lauf_asm_layout){32, 1});
    if (pm == NULL)
        FAIL_IN_NATIVE("expected full 32-byte access after merge");
    return true;
}

static void test_split_merge_roundtrip(void)
{
    run_native(nat_split_merge);
}

/* gc reports the number of bytes freed. After we register a heap allocation
 * with a backing that we then let go unreachable, gc must return >0 bytes
 * (specifically it should free that allocation since nothing references it). */
static void gc_free(void* u, void* ptr, size_t size)
{
    (void)u;
    (void)size;
    free(ptr);
}
static void* gc_alloc(void* u, size_t size, size_t alignment)
{
    (void)u;
    (void)alignment;
    return malloc(size);
}

static bool nat_gc(void* u, lauf_runtime_process* p,
                   const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;
    /* Allocate via lauf's allocator, register with add_heap_allocation, then
     * gc. We drop our local var so the allocation is unreachable. */
    void* mem = malloc(48);
    if (mem == NULL)
        FAIL_IN_NATIVE("malloc failed");
    lauf_runtime_address addr = lauf_runtime_add_heap_allocation(p, mem, 48);
    (void)addr;
    /* Force gc; expect non-zero freed count. */
    size_t freed = lauf_runtime_gc(p);
    if (freed == 0)
        FAIL_IN_NATIVE("gc returned 0 bytes freed for an unreachable heap allocation");
    /* The bytes returned by gc are conservative — it may report at least the
     * allocation size we registered. */
    if (freed < 48)
        FAIL_IN_NATIVE("expected gc to report >= 48 bytes freed, got %zu", freed);
    return true;
}

static void test_gc_frees_unreachable_bytes(void)
{
    /* Use a VM with the malloc allocator so gc frees via free(). Wrap in a
     * quick program that installs the native + calls it. */
    lauf_vm_options opts = lauf_default_vm_options;
    lauf_vm_allocator alloc = {NULL, gc_alloc, gc_free};
    opts.allocator = alloc;
    lauf_vm* vm = lauf_create_vm(opts);

    lauf_asm_module*   mod = lauf_asm_create_module("gc");
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
    lauf_asm_define_native_function(&prog, nfn, nat_gc, NULL);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* get_cstr returns a valid C string pointer for a NUL-terminated allocation.
 * get_address translates a raw pointer back into an address handle. */
static char g_cstr_backing[] = "hello lauf";

static bool nat_get_cstr_and_get_address(void* u, lauf_runtime_process* p,
                                         const lauf_runtime_value* in,
                                         lauf_runtime_value*       out)
{
    (void)u;
    (void)in;
    (void)out;
    /* Register as mut so get_cstr can read. */
    lauf_runtime_address addr = lauf_runtime_add_static_mut_allocation(
        p, g_cstr_backing, sizeof(g_cstr_backing));
    const char* s = lauf_runtime_get_cstr(p, addr);
    if (s == NULL)
        FAIL_IN_NATIVE("get_cstr returned NULL on NUL-terminated allocation");
    if (strcmp(s, "hello lauf") != 0)
        FAIL_IN_NATIVE("get_cstr returned wrong content: \"%s\"", s);

    /* Round-trip: translate an INTERIOR native pointer back into an address and
     * verify the COMPUTED offset. Seeding roundtrip = addr identifies the target
     * allocation; get_address must fill in the byte offset of the pointer within
     * it. Using g_cstr_backing + 6 (a non-zero offset) means a no-op that merely
     * returns true without computing anything — leaving offset at the seeded 0 —
     * is caught. */
    lauf_runtime_address roundtrip = addr;
    if (!lauf_runtime_get_address(p, &roundtrip, g_cstr_backing + 6))
        FAIL_IN_NATIVE("get_address returned false for a valid interior host pointer");
    if (roundtrip.offset != 6)
        FAIL_IN_NATIVE("expected get_address to compute offset 6, got %u",
                       (unsigned)roundtrip.offset);
    if (roundtrip.allocation != addr.allocation)
        FAIL_IN_NATIVE("get_address changed the allocation of the input address");
    /* An out-of-range native pointer must be rejected. */
    lauf_runtime_address oob = addr;
    if (lauf_runtime_get_address(p, &oob, g_cstr_backing + sizeof(g_cstr_backing)))
        FAIL_IN_NATIVE("expected get_address to return false for an out-of-bounds pointer");
    return true;
}

static void test_get_cstr_and_get_address(void)
{
    run_native(nat_get_cstr_and_get_address);
}

/* declare/undeclare reachable have an observable GC effect, not just a return
 * flag: a heap allocation nothing references would normally be swept by gc,
 * but while it is declared reachable gc must leave it alone (0 bytes freed),
 * and once undeclared it must be reclaimed (its bytes counted as freed). The
 * weak flag setters + leak_heap_allocation are exercised for their success
 * contract on a separate allocation. */
static bool nat_reachability(void* u, lauf_runtime_process* p,
                             const lauf_runtime_value* in, lauf_runtime_value* out)
{
    (void)u;
    (void)in;
    (void)out;

    void* mem = malloc(16);
    if (mem == NULL)
        FAIL_IN_NATIVE("malloc failed");
    memset(mem, 0, 16); /* zero so gc can't read stray bytes as live addresses */
    lauf_runtime_address addr = lauf_runtime_add_heap_allocation(p, mem, 16);

    /* Declared reachable → survives gc. */
    if (!lauf_runtime_declare_reachable(p, addr))
        FAIL_IN_NATIVE("declare_reachable returned false");
    size_t freed_reachable = lauf_runtime_gc(p);
    if (freed_reachable != 0)
        FAIL_IN_NATIVE("expected gc to free 0 bytes while reachable, got %zu", freed_reachable);

    /* Undeclared → gc reclaims it. gc frees `mem` via the VM allocator, so we
     * must not touch it afterwards. */
    if (!lauf_runtime_undeclare_reachable(p, addr))
        FAIL_IN_NATIVE("undeclare_reachable returned false");
    size_t freed_unreachable = lauf_runtime_gc(p);
    if (freed_unreachable < 16)
        FAIL_IN_NATIVE("expected gc to reclaim the now-unreachable allocation (>=16), got %zu",
                       freed_unreachable);

    /* Weak flags + leak succeed on a valid heap allocation. Leak this one so
     * the VM stops tracking it, then free it ourselves. */
    void* mem2 = malloc(16);
    if (mem2 == NULL)
        FAIL_IN_NATIVE("malloc failed");
    lauf_runtime_address addr2 = lauf_runtime_add_heap_allocation(p, mem2, 16);
    if (!lauf_runtime_declare_weak(p, addr2))
        FAIL_IN_NATIVE("declare_weak returned false");
    if (!lauf_runtime_undeclare_weak(p, addr2))
        FAIL_IN_NATIVE("undeclare_weak returned false");
    if (!lauf_runtime_leak_heap_allocation(p, addr2))
        FAIL_IN_NATIVE("leak_heap_allocation returned false");
    free(mem2);
    return true;
}

static void test_reachability_and_leak_flags(void)
{
    /* Use malloc allocator so add_heap_allocation is a well-formed slot. */
    lauf_vm_options opts    = lauf_default_vm_options;
    lauf_vm_allocator alloc = {NULL, gc_alloc, gc_free};
    opts.allocator          = alloc;
    lauf_vm* vm             = lauf_create_vm(opts);

    lauf_asm_module*   mod = lauf_asm_create_module("r");
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
    lauf_asm_define_native_function(&prog, nfn, nat_reachability, NULL);
    (void)lauf_vm_execute_oneshot(vm, prog, NULL, NULL);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_add_heap_allocation_and_get_metadata", test_add_heap_allocation_and_get_metadata},
    {"test_poison_unpoison_gates_access", test_poison_unpoison_gates_access},
    {"test_split_merge_roundtrip", test_split_merge_roundtrip},
    {"test_gc_frees_unreachable_bytes", test_gc_frees_unreachable_bytes},
    {"test_get_cstr_and_get_address", test_get_cstr_and_get_address},
    {"test_reachability_and_leak_flags", test_reachability_and_leak_flags},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_runtime_alloc.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
