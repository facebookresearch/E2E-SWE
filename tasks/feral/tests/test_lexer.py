"""Lexer-level tests: comments, string literals, number bases, atoms."""

from _helpers import run_feral


def test_line_and_block_comments():
    """Line comments (`# ...`) and nestable block comments (`/* /* ... */ */`) are
    tokenized as whitespace: the enclosing program must run to completion and
    produce the exact stdout below."""
    src = """
let io = import('std/io');
# a top-level line comment
/* a top-level
   block comment */
/* outer /* inner nested */ still outer */
io.println('a'); # trailing line comment
io.println(/* mid-expression block */ 'b');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "a\nb\n"


def test_string_literals_and_escape_sequences():
    """All three string quoting styles ('/"/`) accept identical escape sequences.
    Concatenation preserves the escaped characters."""
    src = r"""
let io = import('std/io');
let a = 'single';
let b = "double";
let c = `back`;
let esc = 'line1\nline2\t\'quote\'\\';
io.println(a, '|', b, '|', c);
io.println(esc);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "single|double|back\nline1\nline2\t'quote'\\\n"


def test_integer_literals_decimal_hex_octal():
    """Integer literals in three supported bases evaluate to the same canonical
    decimal value. Feral uses a leading `0x`/`0X` for hex and a bare leading
    `0` (C-style, no prefix letter) for octal; each yields 255 here."""
    src = """
let io = import('std/io');
io.println(255);        # decimal
io.println(0xFF);       # hex
io.println(0377);       # octal (377 base 8 = 255)
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "255\n255\n255\n"


def test_float_literals():
    """Float literals require both an integer part and a fractional part
    (`3.14`, not `.14` or `3.`). Arithmetic on floats is IEEE 754 double."""
    src = """
let io = import('std/io');
let pi = 3.14;
let half = 0.5;
let sum = pi + half;
io.println(pi);
io.println(half);
io.println(sum);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].startswith("3.14")
    assert lines[1].startswith("0.5")
    # 3.14 + 0.5 = 3.64
    assert lines[2].startswith("3.64")


def test_atoms_as_string_literals():
    """A leading `.` on an identifier (at token boundaries) produces a string
    literal whose value is the identifier text (the `.` is stripped)."""
    src = """
let io = import('std/io');
let a = .hello;
let b = .world;
io.println(a, ' ', b);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "hello world\n"


def test_prefixed_string_literal_desugars_to_call():
    """A bare identifier immediately adjacent (no whitespace) to a string
    literal desugars to a function call taking that string as the sole
    argument: `bin"1011"` -> `bin("1011")`, `ref"x"` -> `ref("x")`. The
    identifier must resolve to a callable in the current scope."""
    src = """
let io = import('std/io');
let bin = fn(s) { return 'bin<' + s + '>'; };
let ref = fn(s) { return 'ref<' + s + '>'; };
let tag = fn(s) { return 'T:' + s; };
io.println(bin"1011");
io.println(ref"hello");
io.println(tag'single quoted');
io.println(tag`backtick`);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "bin<1011>\nref<hello>\nT:single quoted\nT:backtick\n"


def test_src_path_and_src_dir_compile_time_identifiers():
    """`__SRC_PATH__` and `__SRC_DIR__` are compile-time-substituted string
    identifiers evaluating to the absolute source path and its parent
    directory, respectively. Both are string values usable with the standard
    string type methods."""
    src = """
let io = import('std/io');
io.println(__SRC_PATH__.endsWith('.fer'));
io.println(__SRC_DIR__.startsWith('/'));
io.println(__SRC_PATH__.startsWith(__SRC_DIR__));
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "true\ntrue\ntrue\n"
