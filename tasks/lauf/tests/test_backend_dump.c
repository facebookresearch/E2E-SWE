/* Group: backend_dump — human-readable module/chunk dump. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/backend/dump.h>
#include <lauf/writer.h>
#include <string.h>

/* Dumping a module with a named function produces a non-empty string that
 * contains the function name. The exact format is documented as
 * "subject to change" so we deliberately only assert semantic marks the
 * agent has to reproduce: the module + function names appearing somewhere in
 * the output. */
static void test_dump_module_produces_output(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("MyModuleName");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "MyFnName", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_dump(w, lauf_backend_default_dump_options, mod);

    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "writer string returned NULL after dump");
    CHECK(s[0] != '\0', "dump output was empty");
    CHECK(strstr(s, "MyFnName") != NULL,
          "expected dump output to contain function name \"MyFnName\", got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* dump_chunk on a built chunk emits a human-readable rendering. As with the
 * module-dump sibling we assert semantic marks of the chunk's real content
 * rather than mere non-emptiness: the owning module's header names the module,
 * and the chunk's function body renders its `IN => OUT` signature and a
 * `return` terminator. The exact spelling is documented "subject to change"
 * so these stay loose substring checks. */
static void test_dump_chunk_produces_output(void)
{
    lauf_asm_module* mod   = lauf_asm_create_module("chunkmod");
    lauf_asm_chunk*  chunk = lauf_asm_create_chunk(mod);

    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build_chunk(b, mod, chunk, (lauf_asm_signature){0, 1});
        lauf_asm_inst_uint(b, 123);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }

    lauf_writer* w = lauf_create_string_writer();
    lauf_backend_dump_chunk(w, lauf_backend_default_dump_options, mod, chunk);

    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "writer string returned NULL after dump_chunk");
    CHECK(s[0] != '\0', "dump_chunk output was empty");
    CHECK(strstr(s, "chunkmod") != NULL,
          "expected dump_chunk output to name the owning module \"chunkmod\", got:\n%s", s);
    CHECK(strstr(s, "0 => 1") != NULL,
          "expected dump_chunk output to render the chunk signature \"0 => 1\", got:\n%s", s);
    CHECK(strstr(s, "return") != NULL,
          "expected dump_chunk output to render the chunk body's return terminator, got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_dump_module_produces_output", test_dump_module_produces_output},
    {"test_dump_chunk_produces_output", test_dump_chunk_produces_output},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_backend_dump.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
