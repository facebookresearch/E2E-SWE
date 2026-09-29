/* Group: frontend_text — text-format assembly frontend. */
#include "harness.h"
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/frontend/text.h>
#include <lauf/lib.h>
#include <lauf/reader.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* Build text options that expose the full standard library so `$lauf.int.*`
 * etc. resolve. lauf_libs / lauf_libs_count are the umbrella exports. */
static lauf_frontend_text_options make_full_opts(void)
{
    lauf_frontend_text_options o = lauf_frontend_default_text_options;
    o.builtin_libs               = lauf_libs;
    o.builtin_libs_count         = lauf_libs_count;
    return o;
}

/* A minimal well-formed module parses to a non-null module, exposes the named
 * function via find_by_name, and the function executes correctly. */
static void test_parse_and_execute_module(void)
{
    const char* src =
        "module @simple;\n"
        "function @answer(0 => 1) {\n"
        "    uint 42; return;\n"
        "}\n";

    lauf_reader* r = lauf_create_cstring_reader(src);
    lauf_asm_module* mod = lauf_frontend_text(r, make_full_opts());
    lauf_destroy_reader(r);

    CHECK(mod != NULL, "lauf_frontend_text returned NULL for a well-formed module");

    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "answer");
    CHECK(fn != NULL, "find_function_by_name(\"answer\") returned NULL after parse");

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    int ok = lauf_vm_execute_oneshot(vm, prog, NULL, &out);
    CHECK(ok, "execute of parsed function returned false");
    CHECK(out.as_uint == 42, "expected out=42, got %llu", (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* Malformed input returns NULL. Documented behavior in text.h. We use an
 * empty reader (no `module @NAME;` header) which is trivially malformed and
 * predictably fails at the very first parse step, avoiding downstream
 * asserts in the reference implementation's error-recovery path. */
static void test_parse_syntax_error_returns_null(void)
{
    lauf_reader* r = lauf_create_cstring_reader("");
    lauf_asm_module* mod = lauf_frontend_text(r, make_full_opts());
    lauf_destroy_reader(r);
    CHECK(mod == NULL, "expected NULL for empty (malformed) input");
}

/* End-to-end: a recursive fib(N) function parsed from text runs correctly. */
static void test_parse_recursive_fib_and_execute(void)
{
    const char* src =
        "module @fib;\n"
        "function @fib(1 => 1) {\n"
        "    block %entry(1 => 1) {\n"
        "        pick 0; sint 2; $lauf.int.scmp; cc lt;\n"
        "        branch %base(1 => 1) %recurse(1 => 1);\n"
        "    }\n"
        "    block %base(1 => 1) {\n"
        "        return;\n"
        "    }\n"
        "    block %recurse(1 => 1) {\n"
        "        pick 0; sint 1; $lauf.int.ssub_wrap; call @fib;\n"
        "        roll 1; sint 2; $lauf.int.ssub_wrap; call @fib;\n"
        "        $lauf.int.sadd_wrap;\n"
        "        return;\n"
        "    }\n"
        "}\n";

    lauf_reader* r = lauf_create_cstring_reader(src);
    lauf_asm_module* mod = lauf_frontend_text(r, make_full_opts());
    lauf_destroy_reader(r);
    CHECK(mod != NULL, "parse of recursive fib module returned NULL");

    const lauf_asm_function* fn = lauf_asm_find_function_by_name(mod, "fib");
    CHECK(fn != NULL, "find_function_by_name(\"fib\") returned NULL");

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm* vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value in, out;
    in.as_sint = 10;
    int ok     = lauf_vm_execute_oneshot(vm, prog, &in, &out);
    CHECK(ok, "execute of fib(10) returned false");
    /* fib(10) = 55 */
    CHECK(out.as_sint == 55, "expected fib(10)=55, got %lld", (long long)out.as_sint);

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_parse_and_execute_module", test_parse_and_execute_module},
    {"test_parse_syntax_error_returns_null", test_parse_syntax_error_returns_null},
    {"test_parse_recursive_fib_and_execute", test_parse_recursive_fib_and_execute},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_frontend_text.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}
