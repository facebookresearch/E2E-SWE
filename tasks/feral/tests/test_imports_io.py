"""Module import + std/io + std/assert + error-propagation tests."""

from _helpers import run_feral


def test_import_std_io_println_writes_line():
    """`io.println(...)` writes its stringified args to stdout then appends a
    single trailing newline character."""
    src = """
let io = import('std/io');
io.println('one');
io.println('two', ' ', 'and', ' ', 'three');
io.println();  # empty println still emits one newline
io.println('done');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "one\ntwo and three\n\ndone\n"


def test_import_std_io_print_no_newline():
    """`io.print(...)` writes stringified args to stdout WITHOUT a trailing
    newline; multiple `print` calls concatenate. `println` after `print`
    finishes the line."""
    src = """
let io = import('std/io');
io.print('a');
io.print('b');
io.print('c');
io.println();
io.print('x', 'y', 'z');
io.println('!');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "abc\nxyz!\n"


def test_import_std_assert_eq_passes_on_equal_values():
    """`assert.eq(lhs, rhs)` is a no-op (returns nil) when `lhs == rhs`;
    the surrounding program continues normally to termination."""
    src = """
let io = import('std/io');
let assert = import('std/assert');
assert.eq(1 + 1, 2);
assert.eq('abc', 'a' + 'bc');
assert.eq(true, 1 < 2);
io.println('all-passed');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "all-passed\n"


def test_import_std_assert_eq_fails_on_unequal_values():
    """`assert.eq(lhs, rhs)` raises when `lhs != rhs`; an unhandled raise
    terminates the program with a non-zero exit code, and the raised
    message (which includes the two compared values and the word
    'assertion') is reported by the interpreter's error handler."""
    src = """
let io = import('std/io');
let assert = import('std/assert');
io.println('before');
assert.eq(1, 2);
io.println('after');  # must NOT run
"""
    r = run_feral(src)
    assert r.returncode != 0
    # The stdout MUST include 'before' (executed before assertion) and MUST
    # NOT include 'after' (never reached: raise aborts).
    assert "before" in r.stdout
    assert "after" not in r.stdout
    # The assertion message text must surface somewhere in the interpreter's
    # combined output (spec of `assert.eq`: raised text mentions both compared
    # values and the word `assertion`).
    combined = r.stdout + r.stderr
    assert "assertion" in combined
    assert "1" in combined and "2" in combined


def test_raise_at_top_level_aborts_with_message():
    """`raise(...)` concatenates its args (via `.str()` on each) into a single
    string and raises it as an error. An unhandled raise at top level exits
    non-zero and surfaces the raised message text."""
    src = """
let io = import('std/io');
io.println('starting');
raise('boom: something ', 'went ', 'wrong');
io.println('unreachable');
"""
    r = run_feral(src)
    assert r.returncode != 0
    assert "starting" in r.stdout
    assert "unreachable" not in r.stdout
    combined = r.stdout + r.stderr
    assert "boom: something went wrong" in combined


def test_raise_concatenates_mixed_type_args_via_str():
    """`raise(args...)` calls `.str()` on each argument and concatenates the
    results into a single message string. Mixed types (Str, Int, Flt, Bool)
    are all supported because every built-in type has an `.str()` method.
    The concatenated message is what an `or e { ... }` block sees on
    `e.str()`."""
    src = """
let io = import('std/io');
let f = fn(code, name) { raise('error ', code, ' at ', name, ' ok=', true); };
f(42, 'main') or e {
    io.println(e.str());
};
f(-1, 'init') or e {
    io.println(e.str());
};
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    # §7.1 pins down concatenation of `.str()` on each arg. The exact wrapper
    # form around the concatenated text is impl-defined; the signal is that
    # every arg's stringified value appears in the resulting message text,
    # in order, across Str + Int + Str + Str + Str + Bool.
    lines = r.stdout.splitlines()
    assert len(lines) == 2, r.stdout
    assert "error 42 at main ok=true" in lines[0], lines[0]
    assert "error -1 at init ok=true" in lines[1], lines[1]


def test_map_construction_key_lookup_and_insert():
    """`feral.mapNew(k1, v1, k2, v2, ...)` builds a Map from alternating
    key/value pairs. Values are read via subscript `[key]` for present
    keys. `.insert(key, value)` adds a new binding or replaces an existing
    one. `.len()` reports the current number of bindings."""
    src = """
let io = import('std/io');
let m = feral.mapNew('a', 1, 'b', 2, 'c', 3);
io.println(m.len());              # 3
io.println(m['a']);               # 1
io.println(m['b']);               # 2
io.println(m['c']);               # 3
m.insert('d', 4);
io.println(m.len());              # 4
io.println(m['d']);               # 4
m.insert('a', 99);                # overwrite existing key
io.println(m['a']);               # 99
io.println(m.len());              # still 4
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "3\n1\n2\n3\n4\n4\n99\n4\n"
