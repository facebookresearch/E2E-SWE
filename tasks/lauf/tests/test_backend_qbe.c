/* Group: backend_qbe — QBE IL emission from a lauf module.
 *
 * The QBE backend emits QBE IL text to a lauf_writer. Register naming, block
 * ordering, and intermediate-value layout are implementation details, so each
 * test below asserts on documented structural marks of the IL — the presence
 * of a function definition line, the export prefix, the return-type-vs-
 * output-count mapping, the tuple-type declaration for N>1 outputs, the
 * data-section prefix for defined globals, and the substitution of a
 * registered extern name at a builtin call site.
 */
#include "harness.h"
/* Include order matters here. `lauf_runtime_builtin` is used both by qbe.h
 * (as an opaque pointer type inside its options struct) and by builtin.h
 * itself (self-referentially inside the struct definition, `const
 * lauf_runtime_builtin* next`). In C mode the typedef alias isn't visible
 * inside its own struct body, so builtin.h relies on a prior
 * `typedef struct lauf_runtime_builtin lauf_runtime_builtin;` forward-typedef
 * being in scope. `<lauf/lib/heap.h>` supplies that forward-typedef; every
 * lib/* header does. So include heap.h BEFORE builtin.h, and both BEFORE
 * backend/qbe.h. */
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/type.h>
#include <lauf/lib/heap.h>
#include <lauf/runtime/builtin.h>
#include <lauf/backend/qbe.h>
#include <lauf/writer.h>
#include <stddef.h>
#include <string.h>

/* The default option struct exposes the built-in heap/memory allocator names
 * as QBE externs. The spec pins the count at 7 and lists every name; this test
 * verifies the constant matches AND that the emission actually consults the
 * table: a module calling lauf_lib_heap_alloc, lowered with the default
 * options, must reference the default extern name '$lauf_heap_alloc' at the
 * call site (a backend that hardcodes the table but never uses it would still
 * pass the constant checks alone). */
static void test_qbe_default_options_expose_default_externs(void)
{
    lauf_backend_qbe_options opts = lauf_backend_default_qbe_options;

    CHECK(opts.extern_fns_count == 7,
          "expected default extern_fns_count=7, got %zu", opts.extern_fns_count);
    CHECK(opts.extern_fns != NULL, "default extern_fns pointer was NULL");

    const char* expected[] = {"lauf_heap_alloc",   "lauf_heap_alloc_array",
                              "lauf_heap_free",    "lauf_heap_gc",
                              "lauf_memory_copy",  "lauf_memory_fill",
                              "lauf_memory_cmp"};
    for (size_t i = 0; i < sizeof(expected) / sizeof(expected[0]); ++i)
    {
        int found = 0;
        for (size_t j = 0; j < opts.extern_fns_count; ++j)
        {
            if (opts.extern_fns[j].name != NULL
                && strcmp(opts.extern_fns[j].name, expected[i]) == 0)
            {
                found = 1;
                break;
            }
        }
        CHECK(found, "default extern set missing name \"%s\"", expected[i]);
    }

    /* Emission must use the default extern name at a heap_alloc call site. */
    lauf_asm_module*   mod = lauf_asm_create_module("m");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "caller", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 8);  /* alignment */
        lauf_asm_inst_uint(b, 16); /* size */
        lauf_asm_inst_call_builtin(b, lauf_lib_heap_alloc);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish returned false for caller");
        lauf_asm_destroy_builder(b);
    }

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, opts, mod);
    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "QBE writer returned NULL string");
    CHECK(strstr(s, "$lauf_heap_alloc") != NULL,
          "expected default-options IL to reference '$lauf_heap_alloc' at the heap_alloc call "
          "site, got:\n%s",
          s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* A defined function must produce a `function ... $<name>(...)` line in the
 * IL. Asserts on the QBE-mangled name prefix `$` + the function name. */
static void test_qbe_defined_function_name_appears(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("m");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "myfunc", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, lauf_backend_default_qbe_options, mod);
    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "QBE writer returned NULL string");
    CHECK(strstr(s, "$myfunc") != NULL,
          "expected QBE IL to contain '$myfunc', got:\n%s", s);
    CHECK(strstr(s, "function") != NULL,
          "expected QBE IL to contain a 'function' keyword, got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* Declaration-only functions (no body built) must NOT appear in the emitted
 * IL — the QBE backend only emits code for functions with definitions. */
static void test_qbe_undefined_function_is_not_emitted(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("m");
    lauf_asm_function* declared_only
        = lauf_asm_add_function(mod, "declared_only_fn", (lauf_asm_signature){0, 0});
    (void)declared_only;
    lauf_asm_function* defined_fn
        = lauf_asm_add_function(mod, "defined_fn", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, defined_fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, lauf_backend_default_qbe_options, mod);
    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "QBE writer returned NULL string");
    CHECK(strstr(s, "$defined_fn") != NULL,
          "expected QBE IL to contain '$defined_fn', got:\n%s", s);
    CHECK(strstr(s, "$declared_only_fn") == NULL,
          "expected QBE IL to NOT contain '$declared_only_fn' (no body), got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* lauf_asm_export_function on a function must cause `export\n` to be emitted
 * before that function's `function ...` signature line. A second, non-exported
 * function verifies that the export marker is scoped and not spurious. */
static void test_qbe_export_marker_for_exported_function(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("m");

    lauf_asm_function* pub  = lauf_asm_add_function(mod, "foopub", (lauf_asm_signature){0, 0});
    lauf_asm_function* priv = lauf_asm_add_function(mod, "barpriv", (lauf_asm_signature){0, 0});
    lauf_asm_export_function(pub);
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, pub);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_build(b, mod, priv);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, lauf_backend_default_qbe_options, mod);
    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "QBE writer returned NULL string");

    const char* pub_line = strstr(s, "$foopub");
    CHECK(pub_line != NULL, "expected '$foopub' in IL, got:\n%s", s);

    /* An `export\n` line must precede $foopub's signature. */
    const char* export_mark = strstr(s, "export\n");
    CHECK(export_mark != NULL, "expected 'export' line in IL, got:\n%s", s);
    CHECK(export_mark < pub_line,
          "expected 'export' to appear BEFORE '$foopub', got:\n%s", s);

    /* Verify the priv function's signature was emitted but is NOT preceded by
     * a second 'export' — count occurrences to be sure. */
    int export_count = 0;
    for (const char* p = s; (p = strstr(p, "export\n")) != NULL; ++p, ++export_count)
        ;
    CHECK(export_count == 1,
          "expected exactly one 'export' line, got %d in:\n%s", export_count, s);
    CHECK(strstr(s, "$barpriv") != NULL, "expected '$barpriv' in IL, got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* The QBE return-type prefix depends on the function's output count:
 *   0 outputs → `function $<name>(`          (no return type)
 *   1 output  → `function l $<name>(`         (l = QBE 64-bit long)
 *   N > 1     → `function :tuple_<N> $<name>(` + a `type :tuple_<N>` decl
 * This test builds one of each and asserts the exact prefix appears. */
static void test_qbe_function_signature_matches_output_count(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("m");

    lauf_asm_function* f0 = lauf_asm_add_function(mod, "f0", (lauf_asm_signature){0, 0});
    lauf_asm_function* f1 = lauf_asm_add_function(mod, "f1", (lauf_asm_signature){0, 1});
    lauf_asm_function* f2 = lauf_asm_add_function(mod, "f2", (lauf_asm_signature){0, 2});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);

        lauf_asm_build(b, mod, f0);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);

        lauf_asm_build(b, mod, f1);
        lauf_asm_inst_uint(b, 42);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);

        lauf_asm_build(b, mod, f2);
        lauf_asm_inst_uint(b, 1);
        lauf_asm_inst_uint(b, 2);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);

        lauf_asm_destroy_builder(b);
    }

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, lauf_backend_default_qbe_options, mod);
    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "QBE writer returned NULL");

    CHECK(strstr(s, "function $f0(") != NULL,
          "expected 'function $f0(' (no return type for 0 outputs), got:\n%s", s);
    CHECK(strstr(s, "function l $f1(") != NULL,
          "expected 'function l $f1(' (l return type for 1 output), got:\n%s", s);
    CHECK(strstr(s, "function :tuple_2 $f2(") != NULL,
          "expected 'function :tuple_2 $f2(' (aggregate return for 2 outputs), got:\n%s",
          s);
    CHECK(strstr(s, "type :tuple_2") != NULL,
          "expected 'type :tuple_2' declaration for the 2-output tuple, got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* A defined global variable must produce a QBE `data $data_<N> = align <A>`
 * section. Declaration-only globals are skipped, so we define one explicitly.
 */
static void test_qbe_global_produces_data_section(void)
{
    lauf_asm_module* mod = lauf_asm_create_module("m");
    lauf_asm_global* g   = lauf_asm_add_global(mod, LAUF_ASM_GLOBAL_READ_ONLY);
    lauf_asm_define_data_global(mod, g, (lauf_asm_layout){4, 1}, "abcd");

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, lauf_backend_default_qbe_options, mod);
    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "QBE writer returned NULL");
    CHECK(strstr(s, "data $data_") != NULL,
          "expected 'data $data_' section prefix for defined global, got:\n%s", s);
    CHECK(strstr(s, "align ") != NULL,
          "expected an 'align ' prefix in the data section header, got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* When lauf_backend_qbe_options.extern_fns registers a name for a builtin,
 * every call to that builtin in the module must emit `call $<extern_name>`
 * at the call site — replacing whatever inline codegen the backend would
 * otherwise use. We drive heap_alloc, whose default extern is
 * `lauf_heap_alloc`, and override it with `my_custom_alloc` via a locally-
 * constructed options struct. */
static void test_qbe_custom_extern_replaces_builtin_call(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("m");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "caller", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 8);  /* alignment */
        lauf_asm_inst_uint(b, 16); /* size */
        lauf_asm_inst_call_builtin(b, lauf_lib_heap_alloc);
        lauf_asm_inst_return(b);
        int ok = lauf_asm_build_finish(b);
        CHECK(ok, "build_finish returned false for caller");
        lauf_asm_destroy_builder(b);
    }

    lauf_backend_qbe_extern_function externs[]
        = {{"my_custom_alloc", &lauf_lib_heap_alloc}};
    lauf_backend_qbe_options opts = {externs, 1};

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_qbe(w, opts, mod);
    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "QBE writer returned NULL");
    CHECK(strstr(s, "$my_custom_alloc") != NULL,
          "expected IL to contain the registered extern name '$my_custom_alloc' at the "
          "heap_alloc call site, got:\n%s",
          s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_qbe_default_options_expose_default_externs",
     test_qbe_default_options_expose_default_externs},
    {"test_qbe_defined_function_name_appears", test_qbe_defined_function_name_appears},
    {"test_qbe_undefined_function_is_not_emitted", test_qbe_undefined_function_is_not_emitted},
    {"test_qbe_export_marker_for_exported_function",
     test_qbe_export_marker_for_exported_function},
    {"test_qbe_function_signature_matches_output_count",
     test_qbe_function_signature_matches_output_count},
    {"test_qbe_global_produces_data_section", test_qbe_global_produces_data_section},
    {"test_qbe_custom_extern_replaces_builtin_call",
     test_qbe_custom_extern_replaces_builtin_call},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_backend_qbe.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
