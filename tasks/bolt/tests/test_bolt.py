"""Hidden pytest suite for the bolt WRG task.

Each test writes a small C driver that embeds the agent's `libbolt.a` via
`bt_open` + `boltstd_open_all` and either:
  * runs a bolt source string with `bt_run` and asserts on the captured
    stdout produced by `core.print` / `core.write` (language + stdlib tests),
  * registers a native module and calls into bolt / from bolt, asserting on
    the round-trip behaviour (embedding-API tests).

The C driver is compiled fresh per test with `gcc -std=c99 ... -lbolt -lm`,
run once, and its stdout compared to the expected output.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
COMPILE_TIMEOUT = 30
RUN_TIMEOUT = 30


def _compile(tmp_path: Path, c_source: str, name: str = "driver") -> Path:
    """Compile a C source string into a binary; return the binary path."""
    src = tmp_path / f"{name}.c"
    src.write_text(c_source)
    bin_path = tmp_path / name
    cmd = [
        "gcc",
        "-std=c99",
        "-Wno-unused-value",
        "-Wno-format",
        str(src),
        "-lbolt",
        "-lm",
        "-o",
        str(bin_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    assert r.returncode == 0, (
        f"compile failed for {name}.c:\n"
        f"CMD: {' '.join(cmd)}\n"
        f"STDOUT:\n{r.stdout}\n"
        f"STDERR:\n{r.stderr}\n"
        f"SOURCE (first 2KB):\n{c_source[:2048]}"
    )
    return bin_path


def _run_binary(bin_path: Path, stdin_input: str | None = None) -> tuple[int, str, str]:
    """Run a compiled test binary; return (returncode, stdout, stderr)."""
    r = subprocess.run(
        [str(bin_path)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
        input=stdin_input,
    )
    return r.returncode, r.stdout, r.stderr


def _c_bolt_wrapper(bolt_source: str) -> str:
    """Build a standard C harness that runs `bolt_source` via bt_run.

    Uses json.dumps to escape the bolt source safely into a C string literal
    (JSON string escaping is a strict subset of C escaping for ASCII input).
    """
    escaped = json.dumps(bolt_source)  # yields e.g. "let x = 10\nprint(x)"
    return textwrap.dedent(
        f"""
        #include <stdio.h>
        #include "bolt.h"
        #include "boltstd/boltstd.h"

        int main(void) {{
            bt_Context* ctx = NULL;
            bt_Handlers h = bt_default_handlers();
            bt_open(&ctx, &h);
            boltstd_open_all(ctx);
            bt_bool ok = bt_run(ctx, {escaped});
            fflush(stdout);
            bt_close(ctx);
            return ok ? 0 : 1;
        }}
    """
    ).lstrip()


def run_bolt(tmp_path: Path, bolt_source: str, name: str = "bolt_test") -> str:
    """Compile + run a bolt program via the standard embedding harness.

    Asserts on a successful (rc == 0) run and returns the captured stdout so
    the caller can make behaviour-specific assertions on the printed output.
    Prefer exact-match assertions on the returned string.
    """
    c_source = _c_bolt_wrapper(bolt_source)
    bin_path = _compile(tmp_path, c_source, name)
    rc, out, err = _run_binary(bin_path)
    assert rc == 0, (
        f"bolt program exited nonzero (rc={rc}):\n"
        f"STDOUT:\n{out}\n"
        f"STDERR:\n{err}\n"
        f"BOLT SOURCE:\n{bolt_source}"
    )
    return out


def run_c(
    tmp_path: Path, c_source: str, name: str = "c_test", stdin_input: str | None = None
) -> tuple[int, str, str]:
    """Compile + run a raw C driver (for embedding-API tests)."""
    bin_path = _compile(tmp_path, c_source, name)
    return _run_binary(bin_path, stdin_input=stdin_input)


# ============================================================================
# LANGUAGE — primitives, literals, arithmetic, control flow
# ============================================================================


class TestNumbersAndArithmetic:
    def test_integer_arithmetic_prints_expected_values(self, tmp_path):
        """Integer add/sub/mul/div/neg with precedence, printed as integers."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            print(1 + 2)
            print(10 - 4)
            print(3 * 7)
            print(20 / 4)
            print(-(-5))
            print(2 + 3 * 4)
            print((2 + 3) * 4)
        """
            ),
        )
        assert out == "3\n6\n21\n5\n5\n14\n20\n"

    def test_float_division_prints_nine_decimals(self, tmp_path):
        """A non-integer number formats with 9 decimal places."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            print(1 / 2)
            print(3 / 4)
        """
            ),
        )
        assert out == "0.500000000\n0.750000000\n"


class TestStringsAndBooleans:
    def test_string_concat_and_bool_logic(self, tmp_path):
        """String `+` concatenates; `and`/`or`/`not` produce true/false."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            print("hello" + " " + "world")
            print(true and false)
            print(true or false)
            print(not true)
            print(10 > 5 and (10 < 20 or false))
        """
            ),
        )
        assert out == "hello world\nfalse\ntrue\nfalse\ntrue\n"


class TestNullOperators:
    def test_null_coalescing_and_forced_unwrap(self, tmp_path):
        """`??` picks non-null; `!` unwraps; `?` tests existence."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            let a: number? = 10
            let b: number? = null
            print(a ?? 100)
            print(b ?? 100)
            print(a!)
            if a? { print("a exists") }
            if b? { print("b exists") }
        """
            ),
        )
        assert out == "10\n100\n10\na exists\n"


# ============================================================================
# LANGUAGE — arrays and tables
# ============================================================================


class TestArrays:
    def test_array_literal_index_and_mutate(self, tmp_path):
        """Bracket-indexed read/write, length via prototype method."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            let a = [10, 20, 30]
            print(a[0])
            print(a[2])
            print(a.length())
            a[1] = a[0] + a[2]
            print(a[1])
        """
            ),
        )
        assert out == "10\n30\n3\n40\n"


class TestTables:
    def test_sealed_table_dot_and_bracket_access(self, tmp_path):
        """Dot access and bracket access on sealed tables both work."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            let t = { x: 10, y: 20, z: 0 }
            print(t.x)
            print(t["y"])
            t.z = t.x + t.y
            print(t.z)
        """
            ),
        )
        assert out == "10\n20\n30\n"

    def test_unsealed_table_accepts_new_keys(self, tmp_path):
        """`unsealed` on a table literal permits writing/reading new keys."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            let t = unsealed { x: 10 }
            t.y = 20
            print(t.x)
            print(t.y)
        """
            ),
        )
        assert out == "10\n20\n"


# ============================================================================
# LANGUAGE — control flow (if / match / for)
# ============================================================================


class TestIfElseAndIfLet:
    def test_if_else_chain_and_if_let_narrowing(self, tmp_path):
        """if / else-if / else chains and if-let narrowing of nullable values."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            fn describe(x: number): string {
                return if x < 0 then "neg"
                    else if x == 0 then "zero"
                    else if x < 10 then "small"
                    else "big"
            }
            print(describe(-5))
            print(describe(0))
            print(describe(5))
            print(describe(50))

            fn maybe(): number? { return 42 }
            fn nope(): number? { return null }
            if let x = maybe() { print(x) }
            if let x = nope() { print("nope") } else { print("no value") }
        """
            ),
        )
        assert out == "neg\nzero\nsmall\nbig\n42\nno value\n"


class TestMatch:
    def test_match_with_is_narrowing_across_union(self, tmp_path):
        """`match ... is Type` narrows the binding inside each branch."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, to_string from core
            fn describe(v: number | bool | string) {
                match v {
                    is number { print("num:" + to_string(v)) }
                    is bool   { print("bool:" + to_string(v)) }
                    is string { print("str:" + v) }
                }
            }
            describe(42)
            describe(true)
            describe("hi")
        """
            ),
        )
        assert out == "num:42\nbool:true\nstr:hi\n"

    def test_match_with_operator_and_literal_branches(self, tmp_path):
        """Comma-separated literals + operator-prefix branches (`< 5`, `> 5`)."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            fn classify(n: number): string {
                return match n {
                    < 0     then "neg",
                    0       then "zero",
                    1, 2, 3 then "small",
                    > 100   then "huge",
                    else "mid"
                }
            }
            print(classify(-3))
            print(classify(0))
            print(classify(2))
            print(classify(50))
            print(classify(500))
        """
            ),
        )
        assert out == "neg\nzero\nsmall\nmid\nhuge\n"


class TestForLoops:
    def test_numeric_and_iterator_and_while_and_for_expr(self, tmp_path):
        """Numeric, iterator, while, and for-expression forms."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core

            // Numeric with to/by
            let mut = 0
            for i in 2 to 10 by 2 { mut += i }
            print(mut) // 2+4+6+8 = 20

            // Iterator
            let arr = [1, 2, 3, 4]
            let sum = 0
            for x in arr.each() { sum += x }
            print(sum) // 10

            // While-style
            let n = 5
            for n > 0 { n -= 1 }
            print(n) // 0

            // for-expression as list comprehension
            let squares: [number] = for i in 5 do i * i
            for x in squares.each() do print(x)
        """
            ),
        )
        assert out == "20\n10\n0\n0\n1\n4\n9\n16\n"


# ============================================================================
# LANGUAGE — functions, closures, recursion
# ============================================================================


class TestFunctionsAndRecursion:
    def test_named_function_recursion_and_closure_state(self, tmp_path):
        """Statement-level `fn` supports recursion; closures capture state."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core

            fn fib(n: number): number {
                return match n {
                    0, 1 then n
                    else fib(n - 1) + fib(n - 2)
                }
            }
            print(fib(10)) // 55
            print(fib(16)) // 987

            fn make_counter {
                let count = 0
                return fn {
                    count += 1
                    return count
                }
            }
            let c = make_counter()
            print(c())
            print(c())
            print(c())
        """
            ),
        )
        assert out == "55\n987\n1\n2\n3\n"


# ============================================================================
# LANGUAGE — prototypes, methods, metamethods, extension
# ============================================================================


class TestPrototypeMethods:
    def test_prototype_method_dispatch_via_dot_call(self, tmp_path):
        """`fn T.method(this)` dispatches via `v.method()` on values of `T`."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core

            type Vec2 = { x: number, y: number }

            fn Vec2.new(x: number, y: number) {
                return Vec2 => { x: x, y: y }
            }

            fn Vec2.sum(this) {
                return this.x + this.y
            }

            let v = Vec2.new(3, 7)
            print(v.sum()) // 10
            print(Vec2.sum(v)) // 10
        """
            ),
        )
        assert out == "10\n10\n"


class TestMetamethods:
    def test_add_and_format_metamethods_drive_operator_and_to_string(self, tmp_path):
        """@add on a tableshape drives `+`; @format drives `to_string`/`print`."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, to_string from core

            type V = { x: number, y: number }
            fn V.@add(this, other: V) {
                return V => { x: this.x + other.x, y: this.y + other.y }
            }
            fn V.@format(this) {
                return "V(" + to_string(this.x) + "," + to_string(this.y) + ")"
            }

            let a = V => { x: 1, y: 2 }
            let b = V => { x: 3, y: 4 }
            let c = a + b
            print(c.x)
            print(c.y)
            print(to_string(c))
        """
            ),
        )
        assert out == "4\n6\nV(4,6)\n"


class TestExtension:
    def test_extended_type_dispatches_overridden_and_inherited_methods(self, tmp_path):
        """`Derived = Base + { ... }` — Derived-overridden methods win, but
        base-only methods remain callable even after downcasting to Base."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, to_string from core

            type Base = { name: string }
            fn Base.greet(this) { print("hello " + this.name) }
            fn Base.shout(this) { print("HEY " + this.name) }

            type Derived = Base + { height: number }
            fn Derived.greet(this) {
                Base.greet(this)
                print("height is " + to_string(this.height))
            }

            let b = Base => { name: "Alice" }
            let d = Derived => { name: "Bob", height: 180 }

            b.greet()
            d.greet()
            b.shout()
            d.shout() // inherited from Base
        """
            ),
        )
        assert out == "hello Alice\nhello Bob\nheight is 180\nHEY Alice\nHEY Bob\n"


# ============================================================================
# LANGUAGE — enums, aliases, unions
# ============================================================================


class TestEnums:
    def test_enum_variant_cast_to_number_and_back(self, tmp_path):
        """Sealed enum options round-trip through `as number`/`as Enum`."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            type Color = enum { Red, Green, Blue }
            let c = Color.Green
            print(c as number!) // 1
            let c2 = 2 as Color!
            print(c2 as number!) // 2 (Blue)
            let bad = 10 as Color
            if bad? then print("bad exists") else print("bad is null")
        """
            ),
        )
        assert out == "1\n2\nbad is null\n"


# ============================================================================
# LANGUAGE — error handling via core.Error / protect
# ============================================================================


class TestErrorHandling:
    def test_error_flows_through_protect_and_pattern_match(self, tmp_path):
        """`error()` produces an `Error` table; `match let` binds and narrows
        an `Error | T` union, dispatching to distinct branches for each side."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, to_string, error, Error from core

            fn safe_divide(a: number, b: number): number | Error {
                if b == 0 { return error("div by zero") }
                return a / b
            }

            match let good = safe_divide(10, 2) {
                is Error  { print("err: " + good.what) }
                is number { print("ok: " + to_string(good)) }
            }

            match let bad_result = safe_divide(10, 0) {
                is Error  { print("err: " + bad_result.what) }
                is number { print("ok: " + to_string(bad_result)) }
            }
        """
            ),
        )
        assert out == "ok: 5\nerr: div by zero\n"


# ============================================================================
# STDLIB — arrays module
# ============================================================================


class TestStdlibArrays:
    def test_map_filter_and_sort_pipeline(self, tmp_path):
        """arrays.map, filter, sort chain produces the expected sorted result."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            import arrays
            import math

            let doubled = [1, 2, 3, 4, 5].map(fn(x: number) { return x * 2 })
            for x in doubled.each() do print(x) // 2 4 6 8 10

            let evens = [1, 2, 3, 4, 5, 6].filter(fn(x: number) { return math.mod(x, 2) == 0 })
            print(evens.length()) // 3
            for x in evens.each() do print(x) // 2 4 6

            let sorted = [3, 1, 4, 1, 5, 9, 2, 6].sort()
            for x in sorted.each() do print(x) // 1 1 2 3 4 5 6 9
        """
            ),
        )
        assert out == ("2\n4\n6\n8\n10\n" "3\n2\n4\n6\n" "1\n1\n2\n3\n4\n5\n6\n9\n")

    def test_slice_reverse_and_concatenate(self, tmp_path):
        """arrays.slice / reverse / concatenate compose correctly."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            import arrays

            let s = [10, 20, 30, 40, 50].slice(1, 3)
            print(s.length())
            for x in s.each() do print(x)

            let r = [1, 2, 3].reverse()
            for x in r.each() do print(x)

            let a = [1, 2]
            let b = [3, 4]
            let c = [5, 6]
            arrays.concatenate(a, b, c)
            print(a.length())
            for x in a.each() do print(x)
        """
            ),
        )
        assert out == ("3\n20\n30\n40\n" "3\n2\n1\n" "6\n1\n2\n3\n4\n5\n6\n")


# ============================================================================
# STDLIB — strings module
# ============================================================================


class TestStdlibStrings:
    def test_length_substring_find_replace_and_starts_ends(self, tmp_path):
        """Non-format string ops: length, substring, find, replace, starts_with,
        reverse. (`ends_with` intentionally not asserted — see summary.md.)"""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core

            print("hello".length()) // 5
            print("hello world".substring(6, 5)) // world
            print("hello world".find("world")) // 6
            print("hello world".find("xyz")) // -1
            print("aaa bbb aaa".replace("aaa", "ZZ")) // ZZ bbb ZZ
            print("foobar".starts_with("foo")) // true
            print("foobar".starts_with("bar")) // false
            print("hello".reverse()) // olleh
        """
            ),
        )
        assert out == "5\nworld\n6\n-1\nZZ bbb ZZ\ntrue\nfalse\nolleh\n"

    def test_format_string_prints_typed_placeholders(self, tmp_path):
        """strings.format handles %d, %s, and multiple typed placeholders."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            print("%d items".format(5))
            print("hello, %s!".format("bolt"))
            print("%s=%d".format("count", 42))
        """
            ),
        )
        assert out == "5 items\nhello, bolt!\ncount=42\n"


# ============================================================================
# STDLIB — tables + math + regex + meta
# ============================================================================


class TestStdlibTables:
    def test_pairs_iterates_key_value_and_length(self, tmp_path):
        """tables.pairs iterates the k/v pairs; tables.length counts them."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            import tables

            let t: { ..string: number } = { a: 1, b: 2, c: 3 }
            print(tables.length(t))
            let sum = 0
            for const pair in tables.pairs(t) {
                sum += pair.value
            }
            print(sum)
        """
            ),
        )
        assert out == "3\n6\n"


class TestStdlibMath:
    def test_pi_sqrt_pow_abs_floor_ceil(self, tmp_path):
        """math constants and common functions produce expected results."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            import math

            print(math.sqrt(16))
            print(math.pow(2, 10))
            print(math.abs(-3.5))
            print(math.floor(3.9))
            print(math.ceil(3.1))
            print(math.min(5, 2, 9, 1))
            print(math.max(5, 2, 9, 1))
            print(math.mod(10, 3))
        """
            ),
        )
        assert out == ("4\n1024\n3.500000000\n3\n4\n1\n9\n1\n")


class TestStdlibRegex:
    def test_compile_eval_and_groups(self, tmp_path):
        """regex.compile returns a Regex; eval returns full+group captures."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, assert from core
            import regex

            let r = assert(regex.compile("([a-z]+)=([0-9]+)"), "compile failed")
            print(r.groups()) // 3 (full match + 2 captures)
            let m = r.eval("name=42")
            if let matches = m {
                print(matches.length())
                print(matches[0])
                print(matches[1])
                print(matches[2])
            }
        """
            ),
        )
        assert out == "3\n3\nname=42\nname\n42\n"


class TestStdlibMeta:
    def test_gc_and_union_introspection(self, tmp_path):
        """meta.gc runs safely; meta.get_union_size + get_union_entry inspect unions."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print from core
            import meta

            let collected = meta.gc()
            print(collected >= 0)

            print(meta.get_union_size(type(number | string | bool)))
            print(meta.get_union_entry(type(number | string | bool), 0))
            print(meta.get_union_entry(type(number | string | bool), 1))
        """
            ),
        )
        assert out == "true\n3\nnumber\nstring\n"


# ============================================================================
# STDLIB — io module (offline via tmp files)
# ============================================================================


class TestStdlibIO:
    def test_open_write_read_close_round_trips(self, tmp_path):
        """io.open+write+close then re-open+read+close round-trips content."""
        fpath = tmp_path / "boltio.txt"
        fpath_json = json.dumps(str(fpath))
        # Note: inject `let const fpath = <path>` into bolt via string
        # concatenation of the literal.
        bolt_src = textwrap.dedent(
            f"""
            import print, assert from core
            import io

            let const path = {fpath_json}
            let f = assert(io.open(path, "w"), "open-write failed")
            io.write(f, "line1\\nline2")
            io.close(f)

            let g = assert(io.open(path, "r"), "open-read failed")
            let size = assert(io.get_size(g), "size failed")
            print(size)
            let content = assert(io.read(g, size), "read failed")
            print(content)
            io.close(g)
        """
        )
        out = run_bolt(tmp_path, bolt_src)
        assert out == "11\nline1\nline2\n"


# ============================================================================
# EMBEDDING API — native functions, thread invocation, upvalues
# ============================================================================


class TestEmbeddingNativeFunctions:
    def test_native_function_registered_in_module_callable_from_bolt(self, tmp_path):
        """A native `add(a,b)` registered as `demo.add` is invokable in bolt."""
        c_source = textwrap.dedent(
            r"""
            #include <stdio.h>
            #include "bolt.h"
            #include "boltstd/boltstd.h"
            #include "bt_embedding.h"

            static void native_add(bt_Context* ctx, bt_Thread* thr) {
                double a = bt_get_number(bt_arg(thr, 0));
                double b = bt_get_number(bt_arg(thr, 1));
                bt_return(thr, bt_make_number(a + b));
            }

            static void open_demo(bt_Context* ctx) {
                bt_Module* mod = bt_make_module(ctx);
                bt_Type* num = bt_type_number(ctx);
                bt_Type* args[] = { num, num };
                bt_module_export_native(ctx, mod, "add", native_add, num, args, 2);
                bt_register_module(ctx, BT_VALUE_CSTRING(ctx, "demo"), mod);
            }

            int main(void) {
                bt_Context* ctx = NULL;
                bt_Handlers h = bt_default_handlers();
                bt_open(&ctx, &h);
                boltstd_open_all(ctx);
                open_demo(ctx);
                bt_bool ok = bt_run(ctx,
                    "import print from core\n"
                    "import add from demo\n"
                    "print(add(3, 4))\n"
                    "print(add(100, 250))\n");
                fflush(stdout);
                bt_close(ctx);
                return ok ? 0 : 1;
            }
        """
        )
        rc, out, err = run_c(tmp_path, c_source, name="native_add")
        assert rc == 0, f"nonzero rc={rc}\nSTDOUT={out}\nSTDERR={err}"
        assert out == "7\n350\n"


class TestEmbeddingCallBoltFromC:
    def test_bt_execute_with_args_invokes_exported_bolt_function(self, tmp_path):
        """C compiles a bolt module then invokes one of its exported functions
        via bt_execute_with_args with typed numeric arguments; the function
        prints internally (through the default write handler) and the C driver
        captures that output on stdout."""
        c_source = textwrap.dedent(
            r"""
            #include <stdio.h>
            #include "bolt.h"
            #include "boltstd/boltstd.h"
            #include "bt_embedding.h"

            int main(void) {
                bt_Context* ctx = NULL;
                bt_Handlers h = bt_default_handlers();
                bt_open(&ctx, &h);
                boltstd_open_all(ctx);

                // Compile a small module that prints `a * b` when called.
                bt_Module* mod = bt_compile_module(ctx,
                    "import print from core\n"
                    "export fn multiply(a: number, b: number) {\n"
                    "    print(a * b)\n"
                    "}\n",
                    "mymodule");
                if (!mod) { fflush(stdout); bt_close(ctx); return 1; }

                // Run the module body so its `export` populates the exports table.
                bt_execute(ctx, (bt_Callable*)mod);

                // Look up the exported function.
                bt_Value callable = bt_module_get_export(mod, BT_VALUE_CSTRING(ctx, "multiply"));
                if (callable == BT_VALUE_NULL) { fflush(stdout); bt_close(ctx); return 1; }

                // Invoke it twice with distinct numeric argument pairs.
                bt_Thread* thr = bt_make_thread(ctx);
                bt_Value args1[] = { bt_make_number(6), bt_make_number(7) };
                if (!bt_execute_with_args(ctx, thr, (bt_Callable*)BT_AS_OBJECT(callable), args1, 2)) {
                    fflush(stdout); bt_destroy_thread(ctx, thr); bt_close(ctx); return 1;
                }
                bt_Value args2[] = { bt_make_number(12), bt_make_number(3) };
                if (!bt_execute_with_args(ctx, thr, (bt_Callable*)BT_AS_OBJECT(callable), args2, 2)) {
                    fflush(stdout); bt_destroy_thread(ctx, thr); bt_close(ctx); return 1;
                }

                fflush(stdout);
                bt_destroy_thread(ctx, thr);
                bt_close(ctx);
                return 0;
            }
        """
        )
        rc, out, err = run_c(tmp_path, c_source, name="call_bolt")
        assert rc == 0, f"nonzero rc={rc}\nSTDOUT={out}\nSTDERR={err}"
        assert out == "42\n36\n"


class TestEmbeddingCustomHandlers:
    def test_custom_write_handler_captures_bolt_output(self, tmp_path):
        """Replacing the default `write` handler routes core.print / core.write
        output through the user-supplied callback (used for output capture,
        logging, etc.)."""
        c_source = textwrap.dedent(
            r"""
            #include <stdio.h>
            #include <string.h>
            #include <stdlib.h>
            #include "bolt.h"
            #include "boltstd/boltstd.h"

            #define BUF 4096
            static char g_capture[BUF];
            static int g_len = 0;

            static void capture_write(bt_Context* ctx, const char* msg) {
                int n = (int)strlen(msg);
                if (g_len + n < BUF) {
                    memcpy(g_capture + g_len, msg, (size_t)n);
                    g_len += n;
                }
            }

            int main(void) {
                bt_Context* ctx = NULL;
                bt_Handlers h = bt_default_handlers();
                h.write = capture_write;
                bt_open(&ctx, &h);
                boltstd_open_all(ctx);
                bt_bool ok = bt_run(ctx,
                    "import print from core\n"
                    "print(\"captured!\")\n"
                    "print(1 + 2)\n");
                bt_close(ctx);

                // Emit the captured buffer to real stdout via printf so the
                // parent test can assert against it.
                fwrite(g_capture, 1, (size_t)g_len, stdout);
                fflush(stdout);
                return ok ? 0 : 1;
            }
        """
        )
        rc, out, err = run_c(tmp_path, c_source, name="capture_out")
        assert rc == 0, f"nonzero rc={rc}\nSTDOUT={out}\nSTDERR={err}"
        assert out == "captured!\n3\n"


# ============================================================================
# LANGUAGE — annotations (compile-time metadata + reflection)
# ============================================================================


class TestAnnotationsOnType:
    def test_marker_and_bracket_forms_retrievable_via_meta_annotations(self, tmp_path):
        """`#name` and `#[a, b]` annotations on type declarations round-trip
        through `meta.annotations(T)` as `[meta.Annotation]` in source order."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, to_string from core
            import meta

            #deprecated
            type Session = { id: number }

            #[public, cached]
            type Cache = { size: number }

            let const s = meta.annotations(Session)
            print(s.length())
            for a in s.each() { print(a.name) }

            let const c = meta.annotations(Cache)
            print(c.length())
            for a in c.each() { print(a.name) }
        """
            ),
        )
        assert out == "1\ndeprecated\n2\npublic\ncached\n"


class TestAnnotationsOnField:
    def test_field_annotations_reachable_via_meta_field_annotations(self, tmp_path):
        """Per-field annotations inside a tableshape are retrievable via
        `meta.field_annotations(T, field_key)` with the same `[meta.Annotation]`
        shape as type-level annotations, including arguments."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, to_string from core
            import meta

            type Endpoint = {
                #route("/users")
                path: string,

                #[public, cached]
                handler: number
            }

            let const p = meta.field_annotations(Endpoint, "path")
            print(p.length())
            print(p[0].name)
            print(p[0].args.length())
            print(p[0].args[0])

            let const h = meta.field_annotations(Endpoint, "handler")
            print(h.length())
            for a in h.each() { print(a.name) }
        """
            ),
        )
        assert out == "1\nroute\n1\n/users\n2\npublic\ncached\n"


class TestAnnotationsWithArgs:
    def test_annotation_args_preserve_literal_values(self, tmp_path):
        """Annotation arguments (`#name(a, b, c)`) preserve their literal
        values across the parser → compiler → `meta.Annotation.args`
        round-trip, and multiple annotations from mixed marker-and-bracket
        forms merge into a single ordered annotation list."""
        out = run_bolt(
            tmp_path,
            textwrap.dedent(
                """
            import print, to_string from core
            import meta

            #version(2, 0)
            #[owner("alice"), stable(true)]
            type Api = { name: string }

            let const annos = meta.annotations(Api)
            print(annos.length())
            for a in annos.each() {
                print(a.name)
                for arg in a.args.each() { print(to_string(arg)) }
            }
        """
            ),
        )
        assert out == "3\nversion\n2\n0\nowner\nalice\nstable\ntrue\n"
