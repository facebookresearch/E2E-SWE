/* Group: reader_writer — string/file/stdin reader + writer public API. */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/backend/dump.h>
#include <lauf/frontend/text.h>
#include <lauf/lib.h>
#include <lauf/reader.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>
#include <lauf/writer.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* A length-prefixed string reader must actually surface its bytes downstream:
 * a module parsed through lauf_create_string_reader(str, size) assembles and
 * then executes to the value its bytecode computes. This exercises the
 * reader's real read path (not just non-null construction) and specifically
 * covers the length-prefixed variant, which the frontend_text / end_to_end
 * groups do not (they parse exclusively through cstring readers). A reader
 * that constructs a handle but returns the wrong bytes fails here. */
static void test_string_reader_reads_bytes(void)
{
    const char* src = "module @m; function @answer(0 => 1) { uint 42; return; }";

    lauf_reader* r = lauf_create_string_reader(src, strlen(src));
    CHECK(r != NULL, "lauf_create_string_reader returned NULL for length-prefixed input");

    /* Naming the reader must not disturb the bytes it hands to the frontend.
     * A string literal has static storage, so the path outlives the reader as
     * the documented contract requires. */
    lauf_reader_set_path(r, "some/path");

    lauf_frontend_text_options opts = lauf_frontend_default_text_options;
    opts.builtin_libs               = lauf_libs;
    opts.builtin_libs_count         = lauf_libs_count;
    lauf_asm_module* mod = lauf_frontend_text(r, opts);
    lauf_destroy_reader(r);
    CHECK(mod != NULL, "frontend_text returned NULL parsing a module from the string reader");

    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "answer");
    CHECK(fn != NULL, "find_function_by_name(\"answer\") returned NULL after parse");

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out),
          "execute of function parsed from string reader returned false");
    CHECK(out.as_uint == 42, "expected 42 from string-reader-parsed module, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* A string writer must accumulate what a backend writes into it. A fresh
 * writer holds "", and after a named module is dumped through it,
 * lauf_writer_get_string returns that content (the function name) — so a
 * writer whose byte-accumulation is broken fails here rather than passing on
 * the empty-init default alone. */
static void test_string_writer_append_and_format(void)
{
    lauf_writer* w = lauf_create_string_writer();
    CHECK(w != NULL, "lauf_create_string_writer returned NULL");

    /* A freshly created string writer holds the empty string. */
    const char* empty = lauf_writer_get_string(w);
    CHECK(empty != NULL, "lauf_writer_get_string returned NULL on empty writer");
    CHECK(strcmp(empty, "") == 0, "expected empty writer to return \"\", got \"%s\"", empty);

    /* Dump a named module into the writer so it receives real content. */
    lauf_asm_module*   mod = lauf_asm_create_module("StrWriterMod");
    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "StrWriterFn", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_backend_dump(w, lauf_backend_default_dump_options, mod);

    const char* s = lauf_writer_get_string(w);
    CHECK(s != NULL, "writer string returned NULL after dump");
    CHECK(s[0] != '\0', "expected non-empty writer content after dump");
    CHECK(strstr(s, "StrWriterFn") != NULL,
          "expected writer to contain the dumped function name 'StrWriterFn', got:\n%s", s);

    lauf_destroy_writer(w);
    lauf_asm_destroy_module(mod);
}

/* file_reader returns null when the file does not exist (documented as such
 * in reader.h). The path is intentionally non-writable to guarantee it doesn't
 * exist regardless of the test's working directory. */
static void test_file_reader_missing_returns_null(void)
{
    lauf_reader* r = lauf_create_file_reader("/nonexistent/definitely/not/there.lauf.txt");
    CHECK(r == NULL, "lauf_create_file_reader returned non-null for a missing path");
}

/* file_writer writes to a path; opening the file for reading afterwards must
 * yield the same content that was written. We use dump_module to produce
 * some real content, write it via file_writer, then read the file back
 * with the standard C stdio to verify non-empty output was persisted. */
static void test_file_writer_roundtrip(void)
{
    /* Use a temp path we know is writable. */
    char path[] = "/tmp/lauf_test_file_writer_XXXXXX";
    int  fd     = mkstemp(path);
    CHECK(fd >= 0, "mkstemp failed for /tmp path: %s", strerror(errno));
    close(fd); /* We'll re-open via file_writer. */

    lauf_writer* w = lauf_create_file_writer(path);
    CHECK(w != NULL, "lauf_create_file_writer returned NULL");

    /* Dump a small module through the file writer so it actually receives
     * non-trivial content. */
    lauf_asm_module*   mod = lauf_asm_create_module("MyFileMod");
    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "MyFnInFile", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_backend_dump(w, lauf_backend_default_dump_options, mod);
    lauf_destroy_writer(w); /* flushes and closes the file. */
    lauf_asm_destroy_module(mod);

    /* Read the file back with stdio; the function name we just dumped must
     * appear somewhere in the file's contents. */
    FILE* f = fopen(path, "r");
    CHECK(f != NULL, "fopen after file_writer returned NULL: %s", strerror(errno));
    char buf[4096];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    unlink(path);
    buf[n] = '\0';
    CHECK(n > 0, "file_writer wrote 0 bytes to %s", path);
    CHECK(strstr(buf, "MyFnInFile") != NULL,
          "expected file to contain function name 'MyFnInFile', got:\n%s", buf);
}

/* stdout_writer must actually emit its content to stdout. We redirect fd 1 to
 * a temp file, dump a named module through the stdout writer, restore fd 1,
 * then read the capture back and assert it contains the function name — so a
 * stdout writer that drops its bytes fails rather than passing on construction
 * alone. `lauf_create_stdin_reader` is not called (it eagerly consumes stdin
 * and would block under the harness); we only take its address to force the
 * linker to resolve the symbol. */
static void test_stdout_writer_created(void)
{
    char path[] = "/tmp/lauf_test_stdout_XXXXXX";
    int  tmpfd  = mkstemp(path);
    CHECK(tmpfd >= 0, "mkstemp failed: %s", strerror(errno));

    /* Redirect fd 1 (stdout) to the temp file for the duration of the dump. */
    fflush(stdout);
    int saved = dup(STDOUT_FILENO);
    CHECK(saved >= 0, "dup(STDOUT_FILENO) failed: %s", strerror(errno));
    CHECK(dup2(tmpfd, STDOUT_FILENO) >= 0, "dup2 onto stdout failed: %s", strerror(errno));

    lauf_writer* w = lauf_create_stdout_writer();
    CHECK(w != NULL, "lauf_create_stdout_writer returned NULL");

    lauf_asm_module*   mod = lauf_asm_create_module("StdoutMod");
    lauf_asm_function* fn
        = lauf_asm_add_function(mod, "StdoutFn", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_return(b);
        (void)lauf_asm_build_finish(b);
        lauf_asm_destroy_builder(b);
    }
    lauf_backend_dump(w, lauf_backend_default_dump_options, mod);
    lauf_destroy_writer(w);
    fflush(stdout); /* flush the dump into the redirected fd before restoring. */

    /* Restore the real stdout. */
    dup2(saved, STDOUT_FILENO);
    close(saved);

    /* Read back what the stdout writer emitted into the temp file. */
    FILE* f = fopen(path, "r");
    CHECK(f != NULL, "fopen of captured stdout returned NULL: %s", strerror(errno));
    char   buf[4096];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    close(tmpfd);
    unlink(path);
    buf[n] = '\0';
    CHECK(n > 0, "stdout writer emitted 0 bytes");
    CHECK(strstr(buf, "StdoutFn") != NULL,
          "expected captured stdout to contain 'StdoutFn', got:\n%s", buf);

    lauf_asm_destroy_module(mod);

    /* Link-time reference to lauf_create_stdin_reader — resolves the symbol
     * without calling it (which would block on stdin). Stashed in a volatile
     * to prevent DCE. */
    volatile lauf_reader* (*stdin_ctor)(void) = lauf_create_stdin_reader;
    (void)stdin_ctor;
}

static const TestEntry TESTS[] = {
    {"test_string_reader_reads_bytes", test_string_reader_reads_bytes},
    {"test_string_writer_append_and_format", test_string_writer_append_and_format},
    {"test_file_reader_missing_returns_null", test_file_reader_missing_returns_null},
    {"test_file_writer_roundtrip", test_file_writer_roundtrip},
    {"test_stdout_writer_created", test_stdout_writer_created},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_reader_writer.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
