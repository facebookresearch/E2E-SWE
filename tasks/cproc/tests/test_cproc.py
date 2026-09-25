"""Hidden pytest suite for the cproc WRG task.

Each test writes a small C source file to a temp dir, invokes the agent's
`cproc` driver to compile it end-to-end (cproc frontend -> QBE -> as -> ld),
runs the resulting binary, and asserts on exit code + stdout.

We deliberately do NOT byte-compare against upstream cproc's `.qbe` expected-
output files: two semantically-equivalent QBE emissions can differ in SSA
temp names or basic-block ordering, and rewarding surface form over behaviour
would be unfair. Compile-and-execute checks the observable contract of a C
compiler (produces a working binary with the specified runtime behaviour).

Each test program uses `<assert.h>` internally to check its own invariants;
a failed `assert()` aborts the program (SIGABRT -> exit 134), so we can
report both the C-level assertion failures and the surrounding compile /
link failures in a single subprocess-exit-code check.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


COMPILE_TIMEOUT = 30
RUN_TIMEOUT = 15

# The pre-installed code generator. test.sh copies it aside before it sources
# setup.sh and points us at that copy, so the pipeline-integrity tests always
# measure the emitted IL against the real qbe.
QBE_BIN = os.environ.get("CPROC_QBE_ORIG", "qbe")


def compile_and_run(
    tmp_path: Path,
    c_source: str,
    name: str = "prog",
    argv: list[str] | None = None,
    stdin_input: str | None = None,
    extra_cproc_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Write `c_source` to tmp_path/name.c, compile with `cproc`, run the
    resulting binary, return (returncode, stdout, stderr).

    `extra_cproc_args` lets tests pass additional flags (e.g. `-lm`
    to link libm) that appear between the source file and the `-o` binary
    on the cproc command line.
    """
    src = tmp_path / f"{name}.c"
    src.write_text(c_source)
    binary = tmp_path / name

    compile_cmd = ["cproc", str(src), *(extra_cproc_args or []), "-o", str(binary)]
    cr = subprocess.run(
        compile_cmd,
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert cr.returncode == 0, (
        f"cproc failed to compile {name}.c (rc={cr.returncode}):\n"
        f"CMD: {' '.join(compile_cmd)}\n"
        f"STDOUT:\n{cr.stdout}\n"
        f"STDERR:\n{cr.stderr}\n"
        f"SOURCE (first 4KB):\n{c_source[:4096]}"
    )
    assert (
        binary.exists()
    ), f"expected binary at {binary}, cproc reported success but no file"

    run_argv = [str(binary), *(argv or [])]
    rr = subprocess.run(
        run_argv,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
        input=stdin_input,
    )
    return rr.returncode, rr.stdout, rr.stderr


def run_cproc(
    args: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess:
    """Run `cproc <args>` in `cwd`; return the CompletedProcess.
    Used by the multi-step CLI tests that don't fit the single-file
    compile_and_run shape (e.g. `-c` object emission then link)."""
    return subprocess.run(
        ["cproc", *args],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
        cwd=cwd,
    )


def run_binary(binary: Path) -> tuple[int, str, str]:
    """Run a compiled binary; return (returncode, stdout, stderr)."""
    r = subprocess.run(
        [str(binary)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    return r.returncode, r.stdout, r.stderr


def assert_ok(rc: int, out: str, err: str, expected_stdout: str | None = None) -> None:
    """Common shape for compile-and-run assertions: rc == 0 (no assert()
    failure inside the C program) and, optionally, stdout matches exactly."""
    assert rc == 0, (
        f"program exited nonzero (rc={rc}); usually means an in-C assert()\n"
        f"fired or the binary aborted on an unexpected condition.\n"
        f"STDOUT:\n{out}\nSTDERR:\n{err}"
    )
    if expected_stdout is not None:
        assert out == expected_stdout, (
            f"stdout mismatch.\n"
            f"expected: {expected_stdout!r}\n"
            f"actual:   {out!r}"
        )


# ============================================================================
# ARITHMETIC — integer + float across the fundamental scalar types
# ============================================================================


class TestArithmetic:
    def test_integer_types_and_promotion(self, tmp_path):
        """Signed/unsigned integer types respect sizeof, the usual arithmetic
        conversions promote to a common type, and mixed-type arithmetic on
        char/short/int/long/long long yields the expected values."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <limits.h>
            #include <stdio.h>
            int main(void) {
                assert(sizeof(char)  == 1);
                assert(sizeof(short) == 2);
                assert(sizeof(int)   == 4);
                assert(sizeof(long)  == 8);
                assert(sizeof(long long) == 8);

                /* mixed types promote to a common type */
                signed char sc = -1;
                unsigned int u = 1;
                /* per usual conversions, sc becomes (unsigned int)(-1) here */
                unsigned int r = sc + u;
                assert(r == 0);

                /* short widens to int for arithmetic */
                short a = 10, b = 20;
                int c = a * b;
                assert(c == 200);

                /* long long can hold values > INT_MAX */
                long long big = (long long)INT_MAX + 1LL;
                assert(big == 2147483648LL);
                assert(big > (long long)INT_MAX);
                printf("%lld\\n", big);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="int_types")
        assert_ok(rc, out, err, expected_stdout="2147483648\n")

    def test_unsigned_wrap_and_division_modulo_signs(self, tmp_path):
        """Unsigned arithmetic wraps modulo 2^N as defined by the C spec;
        integer division truncates toward zero; `%` matches C's truncation
        semantics for negative operands."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int main(void) {
                unsigned int u = 0;
                u -= 1;
                /* well-defined wrap: 0 - 1 == UINT_MAX */
                assert(u == 4294967295u);
                u += 2;
                assert(u == 1u);

                /* truncation toward zero for signed / */
                assert((-7) / 2 == -3);
                assert((7) / (-2) == -3);
                /* per C99+: (a/b)*b + a%b == a */
                assert((-7) % 2 == -1);
                assert((7) % (-2) == 1);

                /* unsigned division / modulo */
                unsigned int q = 100u / 7u;   /* 14 */
                unsigned int r = 100u % 7u;   /*  2 */
                assert(q == 14u);
                assert(r == 2u);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="int_div")
        assert_ok(rc, out, err)

    def test_float_and_double_arithmetic(self, tmp_path):
        """float / double add/sub/mul/div work correctly and int<->float
        casts preserve integer values within representable range."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stdio.h>
            static int close(double a, double b) {
                double d = a - b;
                if (d < 0) d = -d;
                return d < 1e-9;
            }
            int main(void) {
                double x = 1.0;
                double y = 3.0;
                double q = x / y;                    /* ~0.333... */
                assert(close(q * 3.0, 1.0));

                float f = 2.5f;
                float g = f * 4.0f;
                assert(close((double)g, 10.0));

                /* int <-> float round-trips */
                int i = 42;
                double d = (double)i;
                int back = (int)d;
                assert(back == 42);

                /* float truncates toward zero when cast to int */
                assert((int)(3.9)  == 3);
                assert((int)(-3.9) == -3);

                printf("%.3f\\n", (double)g);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="float_arith")
        assert_ok(rc, out, err, expected_stdout="10.000\n")

    def test_bitwise_operations(self, tmp_path):
        """&, |, ^, ~, <<, >> on unsigned int / long produce the standard
        bit-level results, including full-width shifts and mask patterns."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int main(void) {
                unsigned int a = 0xF0F0F0F0u;
                unsigned int b = 0x0F0F0F0Fu;
                assert((a & b) == 0u);
                assert((a | b) == 0xFFFFFFFFu);
                assert((a ^ b) == 0xFFFFFFFFu);
                assert((~a) == 0x0F0F0F0Fu);

                assert((1u << 31) == 0x80000000u);
                assert((0x80000000u >> 31) == 1u);

                /* signed right-shift is implementation-defined but on qbe/x86
                   it is arithmetic — sign-preserving. */
                int s = -8;
                assert((s >> 1) == -4);

                unsigned long L = 1UL << 63;
                assert(L == 0x8000000000000000UL);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="bitops")
        assert_ok(rc, out, err)


# ============================================================================
# TYPES — enums, typedefs
# ============================================================================


class TestTypes:
    def test_enum_arithmetic_and_switch(self, tmp_path):
        """Enumeration constants take sequential `int` values by default and
        honour explicit assignments (subsequent enumerators continue from
        the assigned value + 1). Enum values are usable as `int` in
        arithmetic and as `switch` case labels."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            enum Color { RED, GREEN = 5, BLUE };

            static int describe(enum Color c) {
                switch (c) {
                case RED:   return 100;
                case GREEN: return 200;
                case BLUE:  return 300;
                }
                return -1;
            }

            int main(void) {
                /* explicit ordering */
                assert(RED   == 0);
                assert(GREEN == 5);
                assert(BLUE  == 6);       /* continues from GREEN + 1 */

                /* switch dispatch on enum values */
                assert(describe(RED)   == 100);
                assert(describe(GREEN) == 200);
                assert(describe(BLUE)  == 300);

                /* enum usable as int in arithmetic */
                int x = BLUE * 10 + RED;
                assert(x == 60);

                /* enum type is an integer type of the same width as int */
                assert(sizeof(enum Color) == sizeof(int));
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="enum")
        assert_ok(rc, out, err)

    def test_typedef_struct_and_function_pointer(self, tmp_path):
        """`typedef` creates a type alias usable everywhere the underlying
        type would work — including struct types and function-pointer
        types with parenthesised parameter lists."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            typedef struct {
                int x, y;
            } Point;

            typedef int (*BinOp)(int, int);

            static int add(int a, int b) { return a + b; }
            static int mul(int a, int b) { return a * b; }

            static Point translate(Point p, int dx, int dy) {
                Point r = { .x = p.x + dx, .y = p.y + dy };
                return r;
            }

            int main(void) {
                Point p = { .x = 3, .y = 4 };
                assert(p.x == 3);
                assert(p.y == 4);

                Point q = translate(p, 10, 20);
                assert(q.x == 13);
                assert(q.y == 24);
                /* original untouched — struct passed by value */
                assert(p.x == 3);

                BinOp op = add;
                assert(op(10, 20) == 30);
                op = mul;
                assert(op(6, 7) == 42);

                /* typedef stacks with array/pointer types */
                typedef int Row[4];
                Row r = {1, 2, 3, 4};
                assert(sizeof(r) == 4 * sizeof(int));
                assert(r[3] == 4);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="typedef")
        assert_ok(rc, out, err)


# ============================================================================
# POINTERS + ARRAYS — pointer arithmetic, arrays, function pointers
# ============================================================================


class TestPointersArrays:
    def test_pointer_arithmetic_and_dereference(self, tmp_path):
        """pointer + integer advances by sizeof(*p); pointer-pointer yields
        the element distance; deref and address-of round-trip."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stddef.h>
            int main(void) {
                int a[5] = {10, 20, 30, 40, 50};
                int *p = &a[0];
                int *q = p + 3;                 /* &a[3] */
                assert(*q == 40);
                assert(q - p == 3);
                assert((q - p) * (ptrdiff_t)sizeof(int) == (char *)q - (char *)p);

                *q = 400;
                assert(a[3] == 400);

                int x = 99;
                int *r = &x;
                assert(*r == 99);
                *r = 7;
                assert(x == 7);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="ptr_arith")
        assert_ok(rc, out, err)

    def test_arrays_multi_dim_and_array_to_pointer_decay(self, tmp_path):
        """Multi-dimensional arrays flatten in row-major order; indexing
        m[i][j] equals *(*(m+i) + j); an array in an expression decays to
        a pointer to its first element."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stdio.h>
            int main(void) {
                int m[3][4] = {
                    { 0,  1,  2,  3},
                    {10, 11, 12, 13},
                    {20, 21, 22, 23},
                };
                assert(m[2][1] == 21);
                assert(*(*(m + 2) + 1) == 21);

                /* array decay: sizeof(arr) is total, sizeof(arr_as_ptr) is ptr sz */
                int a[10];
                assert(sizeof(a) == 10 * sizeof(int));

                int *p = a;
                assert(sizeof(p) == sizeof(void *));

                /* flat traversal */
                int sum = 0;
                int *flat = &m[0][0];
                for (int i = 0; i < 12; i++) sum += flat[i];
                assert(sum == (0+1+2+3) + (10+11+12+13) + (20+21+22+23));

                printf("%d\\n", sum);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="arrays_multi")
        assert_ok(rc, out, err, expected_stdout="138\n")

    def test_function_pointers(self, tmp_path):
        """A function-pointer variable can be assigned any function of
        matching type, called via `fp(...)`, and passed / returned as a
        first-class value."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            static int add(int a, int b) { return a + b; }
            static int sub(int a, int b) { return a - b; }
            static int mul(int a, int b) { return a * b; }

            static int apply(int (*op)(int, int), int x, int y) {
                return op(x, y);
            }
            int main(void) {
                int (*fp)(int, int) = add;
                assert(fp(3, 4) == 7);
                fp = sub;
                assert(fp(10, 3) == 7);

                assert(apply(add, 20, 22) == 42);
                assert(apply(mul, 6, 7)   == 42);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="fnptr")
        assert_ok(rc, out, err)

    def test_function_pointer_array_dispatch(self, tmp_path):
        """An array of function pointers, indexed at runtime, dispatches to
        the correct callee. Exercises: function-pointer storage layout in an
        array, indirect call through a computed function-pointer value,
        function-address-taking without an explicit `&`."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            static int add(int a, int b) { return a + b; }
            static int sub(int a, int b) { return a - b; }
            static int mul(int a, int b) { return a * b; }

            typedef int (*BinOp)(int, int);

            int main(void) {
                BinOp ops[3] = { add, sub, mul };

                assert(ops[0](10, 3) == 13);   /* add */
                assert(ops[1](10, 3) == 7);    /* sub */
                assert(ops[2](10, 3) == 30);   /* mul */

                /* index computed at runtime — forces genuine indirect call */
                int total = 0;
                for (int i = 0; i < 3; i++) {
                    total += ops[i](100, 4);
                }
                /* add: 104, sub: 96, mul: 400  -->  total 600 */
                assert(total == 600);

                /* verify array of function pointers has expected element size */
                assert(sizeof(ops) == 3 * sizeof(void *));
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="fnptr_array")
        assert_ok(rc, out, err)

    def test_string_literal_and_char_array_initialization(self, tmp_path):
        """`char s[] = "abc"` creates a 4-byte array (3 + terminator); a
        string literal used as a `char *` is a pointer to a non-modifiable
        array; sizeof vs strlen differ predictably."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <string.h>
            int main(void) {
                char s[] = "hello";
                assert(sizeof(s) == 6);        /* 5 chars + '\\0' */
                assert(strlen(s) == 5);
                s[0] = 'H';
                assert(s[0] == 'H');
                assert(strcmp(s, "Hello") == 0);

                const char *p = "world";
                assert(strlen(p) == 5);
                assert(p[4] == 'd');
                assert(p[5] == '\\0');
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="strings")
        assert_ok(rc, out, err)


# ============================================================================
# STRUCTS + UNIONS — value semantics, bit-fields, unions, initializers
# ============================================================================


class TestStructsUnions:
    def test_struct_pass_by_value_and_return(self, tmp_path):
        """A whole struct passed by value is copied at the call boundary
        (callee mutations do not affect caller), and a struct returned by
        value produces a fresh instance."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            struct Point { int x, y; };

            static struct Point scale(struct Point p, int k) {
                p.x *= k;
                p.y *= k;
                return p;      /* returns copy; caller's arg untouched */
            }

            int main(void) {
                struct Point a = {3, 4};
                struct Point b = scale(a, 10);
                /* callee's mutations must not affect caller */
                assert(a.x == 3);
                assert(a.y == 4);
                /* returned copy carries the scaled values */
                assert(b.x == 30);
                assert(b.y == 40);

                struct Point *pp = &a;
                pp->x = 100;
                assert(a.x == 100);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="struct_pass")
        assert_ok(rc, out, err)

    def test_bitfields_signed_and_unsigned(self, tmp_path):
        """Bit-fields of a signed integer type sign-extend on load; unsigned
        bit-fields zero-extend; storage-unit packing preserves independence
        of adjacent fields."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            struct Bits {
                signed   int s : 4;   /* range -8..+7 */
                unsigned int u : 4;   /* range  0..15 */
                unsigned int flag : 1;
            };

            int main(void) {
                struct Bits b = {0};
                b.s = -3;
                b.u = 12;
                b.flag = 1;

                /* signed 4-bit field with value -3 sign-extends on read */
                int rs = b.s;
                assert(rs == -3);

                /* unsigned 4-bit field with 12 stays 12 */
                unsigned int ru = b.u;
                assert(ru == 12u);
                assert(b.flag == 1u);

                /* adjacent fields are independent */
                b.s = 7;
                assert(b.u == 12u);
                assert(b.flag == 1u);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="bitfields")
        assert_ok(rc, out, err)

    def test_bitfields_packing_across_storage_unit_boundaries(self, tmp_path):
        """A struct with bit-fields whose combined width exceeds a single
        storage unit must span additional storage units without losing bits.
        Every field must round-trip its declared value."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            /* 20 + 20 + 4 = 44 bits — cannot fit in one 32-bit storage unit. */
            struct BFPack {
                unsigned a : 20;
                unsigned b : 20;
                unsigned c :  4;
            };

            int main(void) {
                struct BFPack s = { .a = 0xABCDE, .b = 0x12345, .c = 0xF };
                assert(s.a == 0xABCDEu);
                assert(s.b == 0x12345u);
                assert(s.c == 0xFu);

                /* mutate one field; adjacent fields must be undisturbed */
                s.a = 0x77777u;
                assert(s.a == 0x77777u);
                assert(s.b == 0x12345u);
                assert(s.c == 0xFu);

                /* max legal values for each field width */
                s.a = 0xFFFFFu;   /* 20 ones */
                s.b = 0xFFFFFu;
                s.c = 0xFu;       /*  4 ones */
                assert(s.a == 0xFFFFFu);
                assert(s.b == 0xFFFFFu);
                assert(s.c == 0xFu);

                /* struct must occupy at least the two storage units the 44
                   bits require (exact size is implementation-defined). */
                assert(sizeof(s) >= 8);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="bitfield_pack")
        assert_ok(rc, out, err)

    def test_large_struct_return_via_hidden_pointer(self, tmp_path):
        """A struct larger than the two-register SysV return window (16 bytes
        on x86_64) must be returned via a hidden pointer supplied by the
        caller. All fields of the returned struct must carry the callee's
        assigned values."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            /* 5 * 8 = 40 bytes — cannot fit in RAX+RDX; SysV ABI mandates
               return via a hidden first-argument pointer. */
            struct Big { double a, b, c, d, e; };

            static struct Big make(double base) {
                struct Big r = { base, base + 1, base + 2, base + 3, base + 4 };
                return r;
            }

            static double sum(struct Big g) {
                return g.a + g.b + g.c + g.d + g.e;
            }

            int main(void) {
                struct Big g = make(1.0);
                assert(g.a == 1.0);
                assert(g.b == 2.0);
                assert(g.c == 3.0);
                assert(g.d == 4.0);
                assert(g.e == 5.0);

                /* also pass the whole struct by value into a callee — round trip */
                assert(sum(g) == 15.0);

                /* invoke twice to catch clobber bugs in the hidden-pointer save */
                struct Big h = make(10.0);
                assert(h.a == 10.0);
                assert(h.e == 14.0);
                assert(sum(h) == 60.0);

                /* sanity — sizeof matches the ABI expectation */
                assert(sizeof(struct Big) == 40);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="big_struct_ret")
        assert_ok(rc, out, err)

    def test_union_shared_storage_and_type_punning(self, tmp_path):
        """A union's members share the same storage; writing one member and
        reading another exposes the underlying representation (in this case
        the little-endian byte layout of a 32-bit integer on x86_64)."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            union U {
                unsigned int  i;
                unsigned char b[4];
            };

            int main(void) {
                union U u;
                u.i = 0x11223344u;

                /* x86_64 is little-endian: low byte first */
                assert(u.b[0] == 0x44);
                assert(u.b[1] == 0x33);
                assert(u.b[2] == 0x22);
                assert(u.b[3] == 0x11);

                u.b[0] = 0xFF;
                assert((u.i & 0xFFu) == 0xFFu);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="union")
        assert_ok(rc, out, err)

    def test_designated_and_compound_initializers(self, tmp_path):
        """`{ .field = value }` designated initializers set named members;
        omitted members are zero-initialized; compound literals `(T){...}`
        create anonymous struct/array values usable in expressions."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            struct Vec3 { int x, y, z; };

            static int sum(struct Vec3 v) { return v.x + v.y + v.z; }

            int main(void) {
                /* designated init leaves .y == 0 by C zero-fill rule */
                struct Vec3 a = { .x = 1, .z = 3 };
                assert(a.x == 1);
                assert(a.y == 0);
                assert(a.z == 3);

                /* compound literal used inline */
                assert(sum((struct Vec3){ .x = 10, .y = 20, .z = 30 }) == 60);

                /* array with designated indices; other entries zero-init */
                int arr[6] = { [0] = 1, [3] = 4, [5] = 6 };
                assert(arr[0] == 1);
                assert(arr[1] == 0);
                assert(arr[2] == 0);
                assert(arr[3] == 4);
                assert(arr[4] == 0);
                assert(arr[5] == 6);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="designated")
        assert_ok(rc, out, err)


# ============================================================================
# CONTROL FLOW — if/while/do-while/for/switch/goto/break/continue
# ============================================================================


class TestControlFlow:
    def test_if_else_while_and_dowhile_nested(self, tmp_path):
        """Nested if/else chains and while / do-while loops execute in the
        expected order and produce the expected accumulated result."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int classify(int n) {
                if (n < 0) {
                    if (n == -1) return -10;
                    return -20;
                } else if (n == 0) {
                    return 0;
                } else {
                    return n < 10 ? 1 : 2;
                }
            }
            int main(void) {
                assert(classify(-1) == -10);
                assert(classify(-5) == -20);
                assert(classify(0) == 0);
                assert(classify(5) == 1);
                assert(classify(50) == 2);

                /* while: sum 1..10 == 55 */
                int i = 1, s = 0;
                while (i <= 10) { s += i; i++; }
                assert(s == 55);

                /* do-while executes body at least once even when cond initially false */
                int j = 100;
                int k = 0;
                do { k++; j--; } while (j > 100);
                assert(k == 1);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="if_while")
        assert_ok(rc, out, err)

    def test_for_loop_with_break_and_continue(self, tmp_path):
        """A for loop with all three clauses populated iterates over a range;
        `continue` skips the remainder of one iteration; `break` exits the
        enclosing loop early."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int main(void) {
                /* sum even numbers 1..20, break out when running total > 40 */
                int sum = 0;
                int last = 0;
                for (int i = 1; i <= 20; i++) {
                    if (i % 2 != 0) continue;    /* skip odd */
                    sum += i;
                    last = i;
                    if (sum > 40) break;
                }
                /* 2+4+6+8+10+12 = 42; loop stops at i=12 */
                assert(sum == 42);
                assert(last == 12);

                /* nested for: break only breaks innermost */
                int hits = 0;
                for (int a = 0; a < 3; a++)
                    for (int b = 0; b < 3; b++) {
                        if (b == 2) break;
                        hits++;
                    }
                assert(hits == 6);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="for_loop")
        assert_ok(rc, out, err)

    def test_switch_case_fallthrough_and_default(self, tmp_path):
        """`switch` on an integer expression dispatches to matching `case`
        labels; missing `break` produces fallthrough into the next case;
        `default` handles unmatched values."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            static int classify(int n) {
                int out = 0;
                switch (n) {
                case 1:
                case 2:
                    out = 10; break;
                case 3:
                    out = 20;
                    /* fallthrough */
                case 4:
                    out += 30; break;   /* n==3 -> 20+30 = 50; n==4 -> 30 */
                case 5: {
                    int tmp = 100;
                    out = tmp - n;      /* 100 - 5 == 95 */
                    break;
                }
                default:
                    out = -1; break;
                }
                return out;
            }
            int main(void) {
                assert(classify(1) == 10);
                assert(classify(2) == 10);
                assert(classify(3) == 50);
                assert(classify(4) == 30);
                assert(classify(5) == 95);
                assert(classify(100) == -1);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="switch")
        assert_ok(rc, out, err)

    def test_switch_on_long_long_with_64bit_case_values(self, tmp_path):
        """`switch` on a `long long` expression must dispatch case labels
        whose values exceed the range of `int`. A truncated 32-bit compare
        would false-match `0x100000000LL + 42` against `42` (bits above
        bit 31 dropped)."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            static int classify(long long x) {
                switch (x) {
                case 0x100000000LL:      return 1;
                case 0x100000000LL + 42: return 2;
                case 0x100000000LL + 99: return 3;
                case 42:                 return 4;
                case 0:                  return 5;
                default:                 return 0;
                }
            }

            int main(void) {
                assert(classify(0x100000000LL)       == 1);
                assert(classify(0x100000000LL + 42)  == 2);
                assert(classify(0x100000000LL + 99)  == 3);
                assert(classify(42)                  == 4);
                assert(classify(0)                   == 5);
                assert(classify(1000)                == 0);
                /* the critical discriminator: 0x100000000LL + 42 must NOT
                   match the low-32-bits 'case 42' arm */
                assert(classify(0x100000000LL + 42) != 4);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="switch_ll")
        assert_ok(rc, out, err)

    def test_goto_labels_forward_and_backward(self, tmp_path):
        """`goto` jumps to a labeled statement anywhere in the same
        function, forward (skipping code) or backward (looping)."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int main(void) {
                int i = 0;
                int sum = 0;
            loop:                          /* backward target */
                sum += i;
                i++;
                if (i < 5) goto loop;      /* backward goto */
                assert(sum == 0 + 1 + 2 + 3 + 4);

                int x = 10;
                if (x > 0) goto tail;      /* forward goto */
                assert(0 && "unreachable");
            tail:
                assert(x == 10);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="goto_label")
        assert_ok(rc, out, err)


# ============================================================================
# FUNCTIONS — recursion, varargs, void return
# ============================================================================


class TestFunctions:
    def test_recursion_fibonacci(self, tmp_path):
        """A direct recursive function computes correct results across
        multiple recursion depths."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stdio.h>
            static long fib(int n) {
                if (n < 2) return n;
                return fib(n - 1) + fib(n - 2);
            }
            int main(void) {
                assert(fib(0)  == 0);
                assert(fib(1)  == 1);
                assert(fib(2)  == 1);
                assert(fib(10) == 55);
                assert(fib(20) == 6765);
                printf("%ld\\n", fib(15));
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="fib")
        assert_ok(rc, out, err, expected_stdout="610\n")

    def test_varargs_va_list_int_and_double(self, tmp_path):
        """`<stdarg.h>` (`va_list`, `va_start`, `va_arg`, `va_end`) lets a
        function consume variable-length argument lists of int and double."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stdarg.h>
            #include <stdio.h>
            static int sum_ints(int count, ...) {
                va_list ap;
                va_start(ap, count);
                int total = 0;
                for (int i = 0; i < count; i++) total += va_arg(ap, int);
                va_end(ap);
                return total;
            }
            static double avg_doubles(int count, ...) {
                va_list ap;
                va_start(ap, count);
                double total = 0.0;
                for (int i = 0; i < count; i++) total += va_arg(ap, double);
                va_end(ap);
                return total / (double)count;
            }
            int main(void) {
                assert(sum_ints(5, 1, 2, 3, 4, 5) == 15);
                assert(sum_ints(3, 100, -50, 50) == 100);

                double a = avg_doubles(4, 1.0, 2.0, 3.0, 4.0);
                double d = a - 2.5;
                if (d < 0) d = -d;
                assert(d < 1e-9);
                printf("%d\\n", sum_ints(4, 10, 20, 30, 40));
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="varargs")
        assert_ok(rc, out, err, expected_stdout="100\n")

    def test_mutual_recursion(self, tmp_path):
        """Two functions that call each other mutually resolve their
        cross-references via forward declarations (a function prototype
        for `is_odd` before the body of `is_even`)."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            static int is_odd(int n);           /* forward declaration */

            static int is_even(int n) {
                if (n == 0) return 1;
                return is_odd(n - 1);
            }

            static int is_odd(int n) {
                if (n == 0) return 0;
                return is_even(n - 1);
            }

            int main(void) {
                assert(is_even(0)  == 1);
                assert(is_odd(0)   == 0);
                assert(is_even(1)  == 0);
                assert(is_odd(1)   == 1);
                assert(is_even(10) == 1);
                assert(is_odd(11)  == 1);
                assert(is_even(7)  == 0);
                assert(is_odd(8)   == 0);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="mutual_rec")
        assert_ok(rc, out, err)

    def test_void_return_and_early_return(self, tmp_path):
        """A `void` function returns via `return;` or falling off the end;
        an int function can `return` from multiple locations."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            static int side_effect_counter = 0;

            static void bump(int n) {
                if (n <= 0) return;      /* early return */
                for (int i = 0; i < n; i++) side_effect_counter++;
                /* implicit return at end */
            }

            static int classify(int n) {
                if (n < 0)  return -1;
                if (n == 0) return 0;
                if (n < 10) return 1;
                return 2;
            }

            int main(void) {
                bump(-5);
                assert(side_effect_counter == 0);
                bump(3);
                assert(side_effect_counter == 3);
                bump(0);
                assert(side_effect_counter == 3);
                bump(7);
                assert(side_effect_counter == 10);

                assert(classify(-3) == -1);
                assert(classify(0)  == 0);
                assert(classify(5)  == 1);
                assert(classify(99) == 2);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="void_return")
        assert_ok(rc, out, err)


# ============================================================================
# STORAGE — static, extern, block scope
# ============================================================================


class TestStorage:
    def test_static_local_persists_across_calls(self, tmp_path):
        """A `static` variable declared inside a function retains its value
        between successive calls and is initialised only once."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            static int counter(void) {
                static int n = 0;       /* initialised once */
                return ++n;
            }
            int main(void) {
                assert(counter() == 1);
                assert(counter() == 2);
                assert(counter() == 3);
                assert(counter() == 4);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="static_local")
        assert_ok(rc, out, err)

    def test_extern_global_and_definition(self, tmp_path):
        """A file-scope declaration `extern int g;` refers to a global
        defined elsewhere; a bare `int g;` at file scope tentatively
        defines it and is compatible with a matching later definition."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            /* forward extern declaration — refers to the definition below */
            extern int global_x;
            static int read_x(void) { return global_x; }
            static void set_x(int v) { global_x = v; }

            int global_x = 42;      /* definition later in the same TU */

            int main(void) {
                assert(read_x() == 42);
                set_x(100);
                assert(read_x() == 100);
                assert(global_x == 100);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="extern_global")
        assert_ok(rc, out, err)

    def test_block_scope_shadowing(self, tmp_path):
        """A variable declared in an inner block shadows any outer
        declaration of the same name for the extent of that block;
        the outer variable is restored on block exit."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int main(void) {
                int x = 1;
                {
                    int x = 2;          /* shadows outer */
                    assert(x == 2);
                    {
                        int x = 3;      /* shadows middle */
                        assert(x == 3);
                    }
                    assert(x == 2);     /* middle restored */
                }
                assert(x == 1);         /* outer restored */

                /* also for loop induction variable is block-scoped */
                for (int x = 100; x < 105; x++) {
                    /* inner x is the loop counter, not the outer */
                }
                assert(x == 1);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="block_scope")
        assert_ok(rc, out, err)


# ============================================================================
# OPERATORS — sizeof/_Alignof, ternary/comma, compound assignments
# ============================================================================


class TestOperators:
    def test_sizeof_and_alignof(self, tmp_path):
        """`sizeof` returns the number of bytes in the operand's type;
        `_Alignof` returns the required alignment. Both work on primitives,
        expressions, and struct types."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stdalign.h>
            #include <stddef.h>

            struct S { char c; int i; double d; };

            int main(void) {
                assert(sizeof(char)   == 1);
                assert(sizeof(int)    == 4);
                assert(sizeof(long)   == 8);
                assert(sizeof(double) == 8);
                assert(sizeof(void *) == 8);

                /* sizeof on an expression evaluates the type, not the value */
                int arr[10];
                assert(sizeof(arr)     == 10 * sizeof(int));
                assert(sizeof(arr[0])  == sizeof(int));

                /* struct sizeof includes inter-member alignment padding:
                   char@0, pad[1..3], int@4, double@8 -> 16 bytes total. An
                   unpadded/packed layout (13 bytes) must NOT pass. */
                assert(sizeof(struct S) == 16);
                assert(offsetof(struct S, i) == 4);
                assert(offsetof(struct S, d) == 8);

                /* alignment */
                assert(_Alignof(int)    == 4);
                assert(_Alignof(double) == 8);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="sizeof_alignof")
        assert_ok(rc, out, err)

    def test_ternary_and_comma(self, tmp_path):
        """The conditional operator `c ? a : b` selects between two
        expressions of a common type; the comma operator evaluates its left
        operand and yields the value of its right."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int main(void) {
                int x = 10, y = 20;
                int a = (x < y) ? x : y;
                assert(a == 10);

                int b = (x > y) ? x : y;
                assert(b == 20);

                /* chained ternary right-associative */
                int score = 75;
                const char *grade = score >= 90 ? "A"
                                    : score >= 80 ? "B"
                                    : score >= 70 ? "C" : "F";
                assert(grade[0] == 'C');

                /* comma operator: evaluate left for side effects, yield right */
                int c = 0;
                int r = (c = 1, c = c + 5, c);
                assert(c == 6);
                assert(r == 6);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="ternary_comma")
        assert_ok(rc, out, err)

    def test_compound_assignments(self, tmp_path):
        """All compound assignment operators (`+=`, `-=`, `*=`, `/=`,
        `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`) compute (a op= b) as
        (a = a op b) but evaluate `a` only once."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            int main(void) {
                int x = 10;
                x += 5;   assert(x == 15);
                x -= 3;   assert(x == 12);
                x *= 4;   assert(x == 48);
                x /= 6;   assert(x == 8);
                x %= 3;   assert(x == 2);

                unsigned int u = 0xF0u;
                u &= 0x33u; assert(u == 0x30u);
                u |= 0x0Fu; assert(u == 0x3Fu);
                u ^= 0xFFu; assert(u == 0xC0u);
                u <<= 1;    assert(u == 0x180u);
                u >>= 2;    assert(u == 0x60u);

                /* a op= b must evaluate a only once — verify with side effect */
                int arr[3] = {10, 20, 30};
                int i = 1;
                arr[i++] += 5;              /* arr[1] becomes 25; i becomes 2 */
                assert(arr[0] == 10);
                assert(arr[1] == 25);
                assert(arr[2] == 30);
                assert(i == 2);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="compound_assign")
        assert_ok(rc, out, err)


# ============================================================================
# PREPROCESSOR — the external cpp does the work; check driver passthrough
# ============================================================================


class TestPreprocessor:
    def test_object_and_function_like_macros(self, tmp_path):
        """`#define NAME value` and `#define ID(args) body` create text-
        substitution macros; parenthesized macro args prevent precedence
        surprises."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            #define ANSWER 42
            #define SQUARE(x) ((x) * (x))
            #define MAX(a, b) ((a) > (b) ? (a) : (b))

            int main(void) {
                assert(ANSWER == 42);
                assert(SQUARE(5) == 25);
                assert(SQUARE(1 + 2) == 9);   /* would be 5 without inner parens */
                assert(MAX(10, 20) == 20);
                assert(MAX(-3, -8) == -3);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="macros")
        assert_ok(rc, out, err)

    def test_conditional_compilation(self, tmp_path):
        """`#if / #ifdef / #ifndef / #else / #elif / #endif` and `-D` flags
        control which text reaches the compiler frontend."""
        src = textwrap.dedent(
            """
            #include <assert.h>

            #define VERSION 3

            int main(void) {
            #if VERSION >= 2
                int a = 100;
            #else
                int a = 999;    /* not compiled */
            #endif
                assert(a == 100);

            #ifdef VERSION
                int b = 1;
            #else
                int b = 0;
            #endif
                assert(b == 1);

            #ifndef NOT_DEFINED
                int c = 7;
            #else
                int c = 8;
            #endif
                assert(c == 7);

            #if VERSION == 1
                int d = 1;
            #elif VERSION == 2
                int d = 2;
            #elif VERSION == 3
                int d = 3;
            #else
                int d = 0;
            #endif
                assert(d == 3);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="conditional_pp")
        assert_ok(rc, out, err)

    def test_predefined_line_and_file_macros(self, tmp_path):
        """`__LINE__` expands to the source line number at which the token
        appears; `__FILE__` expands to a string literal naming the source
        file. Values must be usable in arithmetic (`__LINE__`) and string
        operations (`__FILE__`) at runtime."""
        # Line-numbered source so the exact __LINE__ value is predictable.
        # Lines: 1 <stdio.h>, 2 <string.h>, 3 <assert.h>, 4 blank,
        # 5 `int main`, 6 `int here = __LINE__;` <-- __LINE__ == 6
        src = (
            "#include <stdio.h>\n"  # 1
            "#include <string.h>\n"  # 2
            "#include <assert.h>\n"  # 3
            "\n"  # 4
            "int main(void) {\n"  # 5
            "    int here = __LINE__;\n"  # 6 <- expected value
            "    const char *f = __FILE__;\n"  # 7
            '    printf("%d %s\\n", here, f);\n'  # 8
            "    /* __LINE__ must be a positive integer */\n"  # 9
            "    assert(here > 0);\n"  # 10
            "    /* __FILE__ must end in .c */\n"  # 11
            "    size_t n = strlen(f);\n"  # 12
            "    assert(n >= 2);\n"  # 13
            "    assert(f[n - 2] == '.');\n"  # 14
            "    assert(f[n - 1] == 'c');\n"  # 15
            "    return 0;\n"  # 16
            "}\n"  # 17
        )
        rc, out, err = compile_and_run(tmp_path, src, name="line_file")
        assert rc == 0, (
            f"program exited nonzero (rc={rc}); usually means an in-C\n"
            f"assert() fired.\nSTDOUT:\n{out}\nSTDERR:\n{err}"
        )
        parts = out.strip().split(" ", 1)
        assert len(parts) == 2, f"expected '<line> <file>' on one line; got: {out!r}"
        line_str, file_str = parts
        assert line_str == "6", (
            f"__LINE__ mismatch: expected 6 (line of `int here = __LINE__;`),\n"
            f"actual={line_str!r}"
        )
        assert Path(file_str).name == "line_file.c", (
            f"__FILE__ should name this source file (line_file.c); got: {file_str!r}"
        )


# ============================================================================
# STDLIB — compiled programs linking against libc must actually work
# ============================================================================


class TestStdlib:
    def test_printf_and_sprintf_formatting(self, tmp_path):
        """`printf` writes formatted output to stdout; `sprintf` writes the
        same into a caller-provided buffer. Format specifiers cover the
        common integer, string, and pointer forms."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stdio.h>
            #include <string.h>

            int main(void) {
                char buf[64];
                int n = sprintf(buf, "name=%s age=%d hex=%x", "alice", 30, 0xBEEF);
                assert(n > 0);
                assert(strcmp(buf, "name=alice age=30 hex=beef") == 0);

                /* signed vs unsigned */
                sprintf(buf, "%d %u %ld", -1, (unsigned int)-1, -1L);
                assert(strcmp(buf, "-1 4294967295 -1") == 0);

                /* width + zero-pad */
                sprintf(buf, "%05d", 42);
                assert(strcmp(buf, "00042") == 0);

                /* printf visible on stdout — sanity check driver linkage */
                printf("go\\n");
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="printf_sprintf")
        assert_ok(rc, out, err, expected_stdout="go\n")

    def test_string_ops_strlen_strcmp_strcpy(self, tmp_path):
        """`<string.h>` functions (`strlen`, `strcmp`, `strcpy`, `strncmp`,
        `strchr`) operate on null-terminated char arrays with the standard
        C library semantics."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <string.h>

            int main(void) {
                assert(strlen("") == 0);
                assert(strlen("hi") == 2);
                assert(strlen("hello, world") == 12);

                assert(strcmp("abc", "abc") == 0);
                assert(strcmp("abc", "abd") <  0);
                assert(strcmp("abd", "abc") >  0);

                char dst[16];
                strcpy(dst, "hello");
                assert(strcmp(dst, "hello") == 0);
                assert(strlen(dst) == 5);

                /* first 6 chars of both are "hello " (with trailing space) */
                assert(strncmp("hello world", "hello there", 6) == 0);
                /* first 7 chars differ at index 6: 'w' (119) > 't' (116) */
                assert(strncmp("hello world", "hello there", 7) > 0);

                /* Use a named array so `p - base` subtracts within one
                   object (pointer subtraction between separate string-literal
                   instances is UB per the C standard). */
                char base[] = "abcdef";
                const char *p = strchr(base, 'd');
                assert(p != NULL);
                assert(*p == 'd');
                assert(p - base == 3);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="string_ops")
        assert_ok(rc, out, err)

    def test_math_h_sqrt_sin_cos(self, tmp_path):
        """`<math.h>` `sqrt`, `sin`, `cos`, `pow`, `fabs` give the standard
        IEEE-754 results. Compiled programs that call these functions must
        be linked against libm (`-lm`)."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <math.h>
            #include <stdio.h>
            static int close(double a, double b) {
                double d = a - b;
                if (d < 0) d = -d;
                return d < 1e-9;
            }
            int main(void) {
                assert(close(sqrt(16.0), 4.0));
                assert(close(sqrt(2.0) * sqrt(2.0), 2.0));

                assert(close(sin(0.0), 0.0));
                assert(close(cos(0.0), 1.0));

                assert(close(pow(2.0, 10.0), 1024.0));
                assert(close(fabs(-3.5), 3.5));

                printf("%.3f\\n", sqrt(9.0));
                return 0;
            }
            """
        )
        # -lm is required — cproc's default link command includes -lc but not
        # -lm, mirroring the behaviour of every mainstream POSIX C driver.
        rc, out, err = compile_and_run(
            tmp_path, src, name="math_h", extra_cproc_args=["-lm"]
        )
        assert_ok(rc, out, err, expected_stdout="3.000\n")

    def test_inttypes_h_PRId64_SCNd64_roundtrip(self, tmp_path):
        """`<inttypes.h>` `PRId64` / `SCNd64` format-specifier macros work
        end-to-end for a printf-then-scanf round-trip of an `int64_t`
        value; the input and parsed output must be bit-equal."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <inttypes.h>
            #include <stdio.h>
            int main(void) {
                int64_t val = 1234567890123LL;
                char buf[64];
                int n = sprintf(buf, "%" PRId64, val);
                assert(n > 0);

                int64_t parsed = 0;
                int m = sscanf(buf, "%" SCNd64, &parsed);
                assert(m == 1);
                assert(parsed == val);

                /* also negative values */
                val = -9223372036854775800LL;
                sprintf(buf, "%" PRId64, val);
                sscanf(buf, "%" SCNd64, &parsed);
                assert(parsed == val);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="inttypes")
        assert_ok(rc, out, err)

    def test_malloc_free_and_memcpy(self, tmp_path):
        """Heap allocation via `malloc` + `free`; `memcpy` copies raw bytes
        between buffers; the allocation is usable for reads and writes up
        to (but not beyond) the requested size."""
        src = textwrap.dedent(
            """
            #include <assert.h>
            #include <stdlib.h>
            #include <string.h>

            int main(void) {
                int *arr = (int *)malloc(10 * sizeof(int));
                assert(arr != NULL);

                for (int i = 0; i < 10; i++) arr[i] = i * i;
                int sum = 0;
                for (int i = 0; i < 10; i++) sum += arr[i];
                assert(sum == 0 + 1 + 4 + 9 + 16 + 25 + 36 + 49 + 64 + 81);

                int copy[10];
                memcpy(copy, arr, 10 * sizeof(int));
                for (int i = 0; i < 10; i++) assert(copy[i] == arr[i]);

                /* mutate original; copy stays fixed */
                arr[5] = -1;
                assert(copy[5] == 25);

                free(arr);
                return 0;
            }
            """
        )
        rc, out, err = compile_and_run(tmp_path, src, name="malloc_memcpy")
        assert_ok(rc, out, err)


# ============================================================================
# CLI — driver flags: -c (compile to object), -D (define macro), -I (include path)
# ============================================================================


class TestCLI:
    def test_dash_c_produces_object_and_links_across_translation_units(self, tmp_path):
        """`cproc -c foo.c -o foo.o` compiles a translation unit to an ELF
        relocatable object without linking. The driver then accepts one or
        more `.o` inputs and links them into an executable, resolving
        cross-TU symbol references."""
        # Two translation units — a math module defines `add`, main uses it.
        math_c = tmp_path / "mathmod.c"
        math_c.write_text("int add(int a, int b) { return a + b; }\n")

        main_c = tmp_path / "mainmod.c"
        main_c.write_text(
            textwrap.dedent(
                """
            #include <assert.h>
            #include <stdio.h>
            int add(int, int);           /* extern from mathmod.o */
            int main(void) {
                assert(add(2, 3) == 5);
                assert(add(-4, 4) == 0);
                assert(add(100, 200) == 300);
                printf("linked\\n");
                return 0;
            }
            """
            )
        )

        # Compile each unit to an object.
        r1 = run_cproc(["-c", "mathmod.c", "-o", "mathmod.o"], cwd=tmp_path)
        assert r1.returncode == 0, (
            f"cproc -c mathmod.c failed (rc={r1.returncode}):\n"
            f"STDOUT:\n{r1.stdout}\nSTDERR:\n{r1.stderr}"
        )
        assert (tmp_path / "mathmod.o").exists(), "mathmod.o not produced"

        r2 = run_cproc(["-c", "mainmod.c", "-o", "mainmod.o"], cwd=tmp_path)
        assert r2.returncode == 0, (
            f"cproc -c mainmod.c failed (rc={r2.returncode}):\n"
            f"STDOUT:\n{r2.stdout}\nSTDERR:\n{r2.stderr}"
        )
        assert (tmp_path / "mainmod.o").exists(), "mainmod.o not produced"

        # Link the two objects.
        r3 = run_cproc(["mathmod.o", "mainmod.o", "-o", "out"], cwd=tmp_path)
        assert r3.returncode == 0, (
            f"cproc link failed (rc={r3.returncode}):\n"
            f"STDOUT:\n{r3.stdout}\nSTDERR:\n{r3.stderr}"
        )
        binary = tmp_path / "out"
        assert binary.exists(), "linked binary not produced"

        rc, out, err = run_binary(binary)
        assert rc == 0, (
            f"linked binary exited nonzero (rc={rc}).\n"
            f"STDOUT:\n{out}\nSTDERR:\n{err}"
        )
        assert out == "linked\n", f"unexpected stdout: {out!r}"

    def test_dash_D_defines_macro_at_command_line(self, tmp_path):
        """`cproc -D name=value input.c` defines the preprocessor macro
        `name` with value `value` for the compilation. The macro is
        visible to `#ifdef` and to plain macro expansion."""
        src_c = tmp_path / "dflag.c"
        src_c.write_text(
            textwrap.dedent(
                """
            #include <stdio.h>
            int main(void) {
            #ifdef FEATURE_X
                printf("feature-x=%d\\n", FEATURE_X);
            #else
                printf("no feature\\n");
            #endif
                return 0;
            }
            """
            )
        )
        binary = tmp_path / "dflag"
        r = run_cproc(["-DFEATURE_X=42", "dflag.c", "-o", "dflag"], cwd=tmp_path)
        assert r.returncode == 0, (
            f"cproc -D compile failed (rc={r.returncode}):\n"
            f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
        assert binary.exists(), "dflag binary not produced"

        rc, out, err = run_binary(binary)
        assert rc == 0, f"dflag binary exited nonzero (rc={rc}). stderr={err}"
        assert (
            out == "feature-x=42\n"
        ), f"expected 'feature-x=42\\n' (the -D branch), got {out!r}"

    def test_dash_I_finds_header_in_subdirectory(self, tmp_path):
        """`cproc -I dir` adds `dir` to the preprocessor's include search
        path so `#include "name.h"` finds `dir/name.h`."""
        sub = tmp_path / "sub"
        sub.mkdir()
        header = sub / "myheader.h"
        header.write_text('#define MY_VALUE 123\n#define MY_STR "from-header"\n')

        src_c = tmp_path / "main.c"
        src_c.write_text(
            textwrap.dedent(
                """
            #include <assert.h>
            #include <string.h>
            #include <stdio.h>
            #include "myheader.h"
            int main(void) {
                assert(MY_VALUE == 123);
                assert(strcmp(MY_STR, "from-header") == 0);
                printf("%d %s\\n", MY_VALUE, MY_STR);
                return 0;
            }
            """
            )
        )
        binary = tmp_path / "iflag"
        r = run_cproc(["-Isub", "main.c", "-o", "iflag"], cwd=tmp_path)
        assert r.returncode == 0, (
            f"cproc -I compile failed (rc={r.returncode}):\n"
            f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
        assert binary.exists(), "iflag binary not produced"

        rc, out, err = run_binary(binary)
        assert rc == 0, f"iflag binary exited nonzero (rc={rc}). stderr={err}"
        assert out == "123 from-header\n", f"unexpected stdout: {out!r}"

    def test_default_output_name_is_a_out(self, tmp_path):
        """With no `-o`, the driver links the executable to the default
        output name `a.out` in the current directory."""
        src_c = tmp_path / "prog.c"
        src_c.write_text(
            textwrap.dedent(
                """
            #include <stdio.h>
            int main(void) {
                printf("default-out\\n");
                return 0;
            }
            """
            )
        )
        r = run_cproc(["prog.c"], cwd=tmp_path)
        assert r.returncode == 0, (
            f"cproc with no -o failed (rc={r.returncode}):\n"
            f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
        binary = tmp_path / "a.out"
        assert binary.exists(), "expected default output binary 'a.out' in the cwd"

        rc, out, err = run_binary(binary)
        assert rc == 0, f"a.out exited nonzero (rc={rc}). stderr={err}"
        assert out == "default-out\n", f"unexpected stdout: {out!r}"


# ============================================================================
# PIPELINE INTEGRITY — cproc-qbe really is a C-to-QBE-IL frontend
# ============================================================================


PIPELINE_PROBE_SOURCE = """\
int mul(int a, int b) { return a * b; }

int main(void) {
    int total = 0;
    for (int i = 1; i <= 4; i++)
        total += mul(i, i);
    return total == 30 ? 0 : 1;
}
"""

# A translation unit with no `main`, plus a second one that calls into it.
# Both are already preprocessed, so they go straight to the frontend.
PIPELINE_LIB_SOURCE = """\
int addmul(int a, int b) { return a * b + 1; }

long sum_to(int n) {
    long total = 0;
    for (int i = 1; i <= n; i++)
        total += i;
    return total;
}
"""

PIPELINE_MAIN_SOURCE = """\
int printf(const char *fmt, ...);
int addmul(int a, int b);
long sum_to(int n);

int main(void) {
    printf("%d %ld\\n", addmul(6, 7), sum_to(10));
    return 0;
}
"""

STANDALONE_SOURCE = """\
#include <stdio.h>

static int triple(int x) { return x * 3; }

int main(void) {
    printf("standalone %d\\n", triple(7));
    return 0;
}
"""


def frontend_il(tmp_path: Path, c_source: str, name: str) -> str:
    """Run `cproc-qbe` on one preprocessed translation unit; return its stdout.

    The spec pins the frontend's output (QBE IL on stdout) but allows the
    translation unit to arrive either as a file argument or on stdin, so try
    both conventions."""
    src = tmp_path / f"{name}.c"
    src.write_text(c_source)

    attempts = []
    for args in (["cproc-qbe", str(src)], ["cproc-qbe", "-"], ["cproc-qbe"]):
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
            input=c_source,
            cwd=tmp_path,
        )
        attempts.append(
            f"`{' '.join(args)}` -> rc={r.returncode}, "
            f"{len(r.stdout)} bytes on stdout, stderr={r.stderr[:300]!r}"
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    raise AssertionError(
        f"cproc-qbe did not emit anything on stdout for the preprocessed\n"
        f"translation unit {name}.c. Tried:\n  " + "\n  ".join(attempts)
    )


def lower_il(tmp_path: Path, il_text: str, name: str) -> Path:
    """Lower QBE IL with the pre-installed `qbe` + `as`; return the object file."""
    il = tmp_path / f"{name}.ssa"
    il.write_text(il_text)
    asm = tmp_path / f"{name}.s"
    q = subprocess.run(
        [QBE_BIN, "-o", str(asm), str(il)],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert q.returncode == 0, (
        f"the pre-installed qbe rejected cproc-qbe's output for {name} "
        f"(rc={q.returncode}), so it is not QBE IL.\n"
        f"QBE STDERR:\n{q.stderr}\n"
        f"cproc-qbe OUTPUT (first 2KB):\n{il_text[:2048]}"
    )
    assert asm.exists() and asm.stat().st_size > 0, f"qbe produced no assembly for {name}"

    obj = tmp_path / f"{name}.o"
    a = subprocess.run(
        ["as", "-o", str(obj), str(asm)],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert a.returncode == 0, (
        f"assembling qbe's output for {name} failed (rc={a.returncode}):\n"
        f"STDERR:\n{a.stderr}"
    )
    return obj


class TestPipelineIntegrity:
    def test_frontend_emits_qbe_il_that_qbe_accepts(self, tmp_path):
        """`cproc-qbe` translates a preprocessed translation unit into QBE IL
        on stdout, and that IL is real QBE IL: the pre-installed `qbe`
        accepts it and lowers it to assembly that links into a binary with
        the source program's behaviour.

        `qbe` rejects assembly and object files, so this fails for a
        `cproc-qbe` that hands its input to another C compiler in the image
        instead of translating it."""
        il_text = frontend_il(tmp_path, PIPELINE_PROBE_SOURCE, "probe")

        il = tmp_path / "probe.ssa"
        il.write_text(il_text)
        asm = tmp_path / "probe.s"
        q = subprocess.run(
            [QBE_BIN, "-o", str(asm), str(il)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert q.returncode == 0, (
            f"the pre-installed qbe rejected cproc-qbe's output (rc={q.returncode}),\n"
            f"so it is not QBE IL.\nQBE STDERR:\n{q.stderr}\n"
            f"cproc-qbe OUTPUT (first 2KB):\n{il_text[:2048]}"
        )
        assert asm.exists() and asm.stat().st_size > 0, "qbe produced no assembly"

        # Assemble + link qbe's output with the system toolchain (used here
        # only as an assembler/linker) and check the program still behaves.
        binary = tmp_path / "probe"
        link = subprocess.run(
            ["cc", str(asm), "-o", str(binary)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert link.returncode == 0, (
            f"assembling/linking qbe's output failed (rc={link.returncode}):\n"
            f"STDERR:\n{link.stderr}"
        )
        rc, out, err = run_binary(binary)
        assert rc == 0, (
            f"the program built from cproc-qbe's IL exited nonzero (rc={rc}); "
            f"the emitted IL does not implement the source.\n"
            f"STDOUT:\n{out}\nSTDERR:\n{err}"
        )

    def test_frontend_il_defines_the_translation_units_functions(self, tmp_path):
        """The IL the frontend emits for a translation unit carries that
        unit's own definitions: lower a `main`-less unit and a second unit
        that calls into it through `qbe` + `as`, link the two objects, and
        the program runs.

        A frontend that emits a self-contained program instead of translating
        its input cannot satisfy the link: the caller's references to the
        other unit's functions stay undefined."""
        lib_obj = lower_il(
            tmp_path, frontend_il(tmp_path, PIPELINE_LIB_SOURCE, "libunit"), "libunit"
        )
        main_obj = lower_il(
            tmp_path, frontend_il(tmp_path, PIPELINE_MAIN_SOURCE, "mainunit"), "mainunit"
        )

        binary = tmp_path / "twounit"
        link = subprocess.run(
            ["cc", str(lib_obj), str(main_obj), "-o", str(binary)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert link.returncode == 0, (
            f"linking the two frontend-produced objects failed (rc={link.returncode}); "
            f"the IL for one unit does not define the functions it declares.\n"
            f"STDERR:\n{link.stderr}"
        )
        rc, out, err = run_binary(binary)
        assert rc == 0, (
            f"the two-unit program exited nonzero (rc={rc}).\n"
            f"STDOUT:\n{out}\nSTDERR:\n{err}"
        )
        assert out == "43 55\n", f"unexpected stdout: {out!r}"

    def test_produced_binary_is_a_standalone_executable(self, tmp_path):
        """What `cproc` writes is a linked ELF executable that runs on its
        own: same output from an unrelated working directory and with an
        empty environment, with no compiler or interpreter to fall back on."""
        src = tmp_path / "standalone.c"
        src.write_text(STANDALONE_SOURCE)
        binary = tmp_path / "standalone"
        r = subprocess.run(
            ["cproc", str(src), "-o", str(binary)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert r.returncode == 0, (
            f"cproc failed to compile standalone.c (rc={r.returncode}):\n"
            f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
        assert binary.read_bytes()[:4] == b"\x7fELF", (
            "cproc's output is not an ELF executable; the driver is expected to "
            "assemble and link the program it compiled."
        )

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        run = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
            cwd=elsewhere,
            env={},
        )
        assert run.returncode == 0, (
            f"the compiled binary exited nonzero (rc={run.returncode}) when run "
            f"from another directory with an empty environment.\n"
            f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
        )
        assert run.stdout == "standalone 21\n", f"unexpected stdout: {run.stdout!r}"
