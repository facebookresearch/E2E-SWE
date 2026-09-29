/* Group: asm_module — module lifecycle + globals + functions + chunks. */
#include "harness.h"
#include <lauf/asm/module.h>
#include <lauf/asm/type.h>
#include <string.h>

/* Modules must roundtrip their name and debug path via the query getters. */
static void test_module_create_and_query(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("mymod");
    CHECK(mod != NULL, "lauf_asm_create_module returned NULL");

    const char* name = lauf_asm_module_name(mod);
    CHECK(name != NULL, "lauf_asm_module_name returned NULL");
    CHECK(strcmp(name, "mymod") == 0, "expected module name \"mymod\", got \"%s\"", name);

    lauf_asm_set_module_debug_path(mod, "src/foo.lauf");
    const char* p = lauf_asm_module_debug_path(mod);
    CHECK(p != NULL, "lauf_asm_module_debug_path returned NULL after set");
    CHECK(strcmp(p, "src/foo.lauf") == 0, "expected debug path \"src/foo.lauf\", got \"%s\"", p);

    lauf_asm_destroy_module(mod);
}

/* add_global returns a distinct global; define_data_global registers layout
 * and the corresponding queries reflect it. Permissions are metadata only —
 * they don't fail creation, but has_definition must be false before
 * lauf_asm_define_data_global and true after. */
static void test_add_globals_permissions_and_layout(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("g");

    lauf_asm_global* ro = lauf_asm_add_global(mod, LAUF_ASM_GLOBAL_READ_ONLY);
    CHECK(ro != NULL, "add_global(READ_ONLY) returned NULL");
    CHECK(!lauf_asm_global_has_definition(ro), "undefined global reported as defined");

    lauf_asm_global* rw = lauf_asm_add_global(mod, LAUF_ASM_GLOBAL_READ_WRITE);
    CHECK(rw != NULL, "add_global(READ_WRITE) returned NULL");
    CHECK(ro != rw, "two add_global calls returned the same pointer");

    /* Define ro with a 3-byte, 1-align constant "abc". */
    lauf_asm_define_data_global(mod, ro, (lauf_asm_layout){3, 1}, "abc");
    CHECK(lauf_asm_global_has_definition(ro), "defined global still reports has_definition=false");

    lauf_asm_layout l = lauf_asm_global_layout(ro);
    CHECK(l.size == 3, "expected global layout size 3, got %zu", l.size);
    CHECK(l.alignment == 1, "expected global layout alignment 1, got %zu", l.alignment);

    /* debug name: default is null; set + read back. */
    CHECK(lauf_asm_global_debug_name(ro) == NULL,
          "unset debug name should be null, got \"%s\"", lauf_asm_global_debug_name(ro));
    lauf_asm_set_global_debug_name(mod, ro, "abc_global");
    const char* dn = lauf_asm_global_debug_name(ro);
    CHECK(dn != NULL && strcmp(dn, "abc_global") == 0,
          "expected debug name \"abc_global\", got \"%s\"", dn ? dn : "(null)");

    lauf_asm_destroy_module(mod);
}

/* add_function returns a queryable function; find_by_name resolves it back;
 * create_chunk yields a distinct chunk with the queried signature and empty
 * flag set. */
static void test_add_functions_lookup_and_chunks(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("f");

    lauf_asm_function* fn = lauf_asm_add_function(mod, "compute", (lauf_asm_signature){2, 1});
    CHECK(fn != NULL, "add_function returned NULL");

    const char* fname = lauf_asm_function_name(fn);
    CHECK(fname != NULL && strcmp(fname, "compute") == 0,
          "expected function name \"compute\", got \"%s\"", fname ? fname : "(null)");

    lauf_asm_signature sig = lauf_asm_function_signature(fn);
    CHECK(sig.input_count == 2, "expected input_count=2, got %u", (unsigned)sig.input_count);
    CHECK(sig.output_count == 1, "expected output_count=1, got %u", (unsigned)sig.output_count);

    /* Function has no body yet. */
    CHECK(!lauf_asm_function_has_definition(fn),
          "un-built function reports has_definition=true");

    /* find_function_by_name resolves the same function. */
    const lauf_asm_function* found = lauf_asm_find_function_by_name(mod, "compute");
    CHECK(found == fn, "find_function_by_name returned a different pointer than add_function");

    const lauf_asm_function* missing = lauf_asm_find_function_by_name(mod, "nope");
    CHECK(missing == NULL, "find_function_by_name(missing) returned non-null");

    /* Chunks. */
    lauf_asm_chunk* c = lauf_asm_create_chunk(mod);
    CHECK(c != NULL, "lauf_asm_create_chunk returned NULL");
    CHECK(lauf_asm_chunk_is_empty(c), "fresh chunk should be empty");

    lauf_asm_destroy_module(mod);
}

/* Layout helpers: array_layout returns a layout that holds `count` elements
 * of the given per-element layout (respecting alignment); aggregate_layout
 * returns the layout of a struct whose members are the given layouts in order.
 *
 * The exact size can be computed from standard layout rules — array size is
 * padded_stride * count, aggregate size accounts for member alignment. This
 * test asserts on values that fall out of the standard rules for two well-
 * behaved cases: array_layout({8, 8}, 4) → {32, 8}; aggregate_layout of
 * {u32, u64} → {size >= 16, alignment 8} (u64 alignment dominates). */
static void test_layout_array_and_aggregate(void)
{
    lauf_asm_layout u64  = {8, 8};
    lauf_asm_layout arr4 = lauf_asm_array_layout(u64, 4);
    CHECK(arr4.size == 32, "array_layout({8,8},4) size expected 32, got %zu", arr4.size);
    CHECK(arr4.alignment == 8, "array_layout alignment expected 8, got %zu",
          arr4.alignment);

    lauf_asm_layout members[2] = {{4, 4}, {8, 8}};
    lauf_asm_layout agg        = lauf_asm_aggregate_layout(members, 2);
    /* alignment of the aggregate is the max member alignment. */
    CHECK(agg.alignment == 8,
          "aggregate_layout({u32,u64}) alignment expected 8, got %zu", agg.alignment);
    /* size is sum-with-padding: 4 + 4 pad + 8 = 16, already a multiple of the
     * alignment (8), so exactly 16 under standard layout rules. */
    CHECK(agg.size == 16, "aggregate_layout size expected 16, got %zu", agg.size);
    /* size must be a multiple of the alignment. */
    CHECK(agg.size % agg.alignment == 0,
          "aggregate_layout size %zu is not a multiple of alignment %zu",
          agg.size, agg.alignment);
}

static const TestEntry TESTS[] = {
    {"test_module_create_and_query", test_module_create_and_query},
    {"test_add_globals_permissions_and_layout", test_add_globals_permissions_and_layout},
    {"test_add_functions_lookup_and_chunks", test_add_functions_lookup_and_chunks},
    {"test_layout_array_and_aggregate", test_layout_array_and_aggregate},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_asm_module.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
