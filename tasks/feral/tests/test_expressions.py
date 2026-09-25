"""Expression-evaluation tests: arithmetic precedence, comparison + logical
short-circuit, bitwise, ternary / nil-coalesce, string + vector ops."""

from _helpers import run_feral


def test_arithmetic_operator_precedence():
    """`*`,`/`,`%`,`**` bind tighter than `+`,`-`. All level-4 operators
    (including `**`) are left-associative in Feral: `2 ** 3 ** 2` parses as
    `(2 ** 3) ** 2 = 8 ** 2 = 64`."""
    src = """
let io = import('std/io');
io.println(1 + 2 * 3);              # 1 + 6 = 7
io.println((1 + 2) * 3);            # 9
io.println(20 - 4 / 2);             # 20 - 2 = 18
io.println(2 ** 3 ** 2);            # (2**3)**2 = 8**2 = 64 (left-assoc)
io.println(17 % 5);                 # 2
io.println(-3 + 10);                # 7
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "7\n9\n18\n64\n2\n7\n"


def test_comparison_and_logical_short_circuit():
    """`&&` and `||` short-circuit: the RHS is not evaluated when the LHS
    already determines the outcome. `assert.eq(false, true)` on the RHS
    would raise -- so if the RHS is reached, the program exits non-zero."""
    src = """
let io = import('std/io');
let assert = import('std/assert');
# `||` short-circuit: 1==1 wins, RHS assert never runs.
if 1 == 1 || assert.eq(false, true) { io.println('or-short'); }
# `&&` short-circuit: 1==2 fails, RHS assert never runs.
if 1 == 2 && assert.eq(false, true) { io.println('unreachable'); }
else { io.println('and-short'); }
# Chained comparisons produce booleans.
io.println(1 < 2);
io.println(3 == 3);
io.println(5 >= 6);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "or-short\nand-short\ntrue\ntrue\nfalse\n"


def test_bitwise_operators_and_shifts():
    """Bitwise `&`,`|`,`^`,`~` and shift `<<`,`>>` operate on integers."""
    src = """
let io = import('std/io');
io.println(10 & 12);           # 0b1010 & 0b1100 = 0b1000 = 8
io.println(10 | 5);            # 0b1010 | 0b0101 = 0b1111 = 15
io.println(10 ^ 12);           # 0b1010 ^ 0b1100 = 0b0110 = 6
io.println(1 << 3);            # 8
io.println(16 >> 2);           # 4
io.println(~5);                # -6 (two's complement)
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "8\n15\n6\n8\n4\n-6\n"


def test_ternary_and_nil_coalesce():
    """Ternary `a ? b : c` and nil-coalesce `a ?? b` (`b` is returned only
    when `a` is `nil`)."""
    src = """
let io = import('std/io');
let x = 5;
io.println(x > 0 ? 'pos' : 'nonpos');
io.println(x < 0 ? 'neg' : 'nonneg');
let y = nil;
io.println(y ?? 'fallback');
let z = 42;
io.println(z ?? 'fallback');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "pos\nnonneg\nfallback\n42\n"


def test_string_and_vector_operations():
    """String `+` concatenates, `*` repeats. Vectors are built via the
    prelude's variadic `feral.vecNew(items...)` and support `len`,
    indexing, `push`, and `back`."""
    src = """
let io = import('std/io');
io.println('ab' + 'cd');
io.println('ha' * 3);
let v = feral.vecNew(1, 2, 3);
io.println(v.len());
io.println(v[0], ',', v[1], ',', v[2]);
v.push(4);
io.println(v.len());
io.println(v.back());
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "abcd\nhahaha\n3\n1,2,3\n4\n4\n"


def test_or_block_catches_raised_error_and_returns_recovery_value():
    """`expr or ident { block }` at expression level 16 wraps `block` as an
    anonymous handler. If `expr` raises, `block` runs with the raised value
    bound to `ident` and the block's return value replaces the original
    expression. If `expr` does NOT raise, the block is skipped and the
    expression's value passes through unchanged."""
    src = """
let io = import('std/io');
let safe = fn(n) {
    if n < 0 { raise('neg:', n.str()); }
    return n * 10;
};
# No-raise path: block skipped, expression value flows through.
let good = safe(3) or e { io.println('unreachable'); return -1; };
# Raise path: block runs with `e` bound, return value replaces expression.
let bad = safe(-5) or e { io.println('caught:', e.str()); return 999; };
io.println('good=', good);
io.println('bad=', bad);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    # Three contract points from the spec (§4, §8):
    #   1. On no-raise, the block is skipped -> 'unreachable' never printed.
    assert "unreachable" not in r.stdout
    #   2. On raise, the block ran and `e.str()` carried the concatenated
    #      raised text. Exact wrapper wording is impl-defined; the raised
    #      text itself is what §7.1 pins down.
    lines = r.stdout.splitlines()
    caught = [ln for ln in lines if ln.startswith("caught:")]
    assert len(caught) == 1, r.stdout
    assert "neg:-5" in caught[0], caught
    #   3. The block's return value replaced the expression; the no-raise
    #      expression value flowed through unchanged.
    assert "good=30" in r.stdout
    assert "bad=999" in r.stdout


def test_string_type_methods_transform_and_search():
    """The built-in Str type exposes searching (`find`, `startsWith`,
    `endsWith`), slicing (`substrNative`), transforming (`trim`, `upper`,
    `lower`, `replace`), and length (`len`) methods. `find` returns the byte
    offset of the first occurrence on hit (7 for 'World' in 'Hello, World!'),
    or -1 on miss."""
    src = """
let io = import('std/io');
let s = 'Hello, World!';
io.println(s.substrNative(7, 5));                  # 'World'
io.println(s.startsWith('Hello'));                 # true
io.println(s.endsWith('!'));                       # true
io.println(s.find('World'));                       # 7  (byte offset of first occurrence)
io.println(s.find('missing'));                     # -1 (miss -> -1 sentinel)
io.println('  padded  '.trim());                   # 'padded'
io.println('abc'.upper());                         # 'ABC'
io.println('ABC'.lower());                         # 'abc'
io.println('12345'.replace('234', 'XY'));          # '1XY5'
io.println('abcdef'.len());                        # 6
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "World\n"
        "true\n"
        "true\n"
        "7\n"
        "-1\n"
        "padded\n"
        "ABC\n"
        "abc\n"
        "1XY5\n"
        "6\n"
    )


def test_vec_type_methods_front_back_insert_erase_reverse_pop():
    """The built-in Vec type exposes front/back accessors, push/pop stack
    ops, positional insert/erase, and in-place reverse. Together these are
    the minimum surface needed to use Vec as a mutable ordered list."""
    src = """
let io = import('std/io');
let v = feral.vecNew(1, 2, 3, 4, 5);
io.println(v.front(), ',', v.back(), ',', v.len());   # '1,5,5'
v.push(6);
io.println(v.back(), ',', v.len());                   # '6,6'
v.pop();
io.println(v.back(), ',', v.len());                   # '5,5'
v.insert(0, 99);
io.println(v[0], ',', v[1], ',', v.len());            # '99,1,6'
v.erase(0);
io.println(v[0], ',', v.len());                       # '1,5'
v.reverse();
io.println(v[0], ',', v[4]);                          # '5,1'
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "1,5,5\n6,6\n5,5\n99,1,6\n1,5\n5,1\n"


def test_compound_assignment_bitwise_and_shift():
    """§4 level 16 lists compound-assignment operators for bitwise-AND (`&=`),
    bitwise-OR (`|=`), bitwise-XOR (`^=`), left-shift (`<<=`), and right-shift
    (`>>=`) on Int. Each rewrites `x <op>= y` to `x = x <op> y` semantically,
    so a chained walk through all five must land on the arithmetically-derived
    value at every step. This test exercises the compound forms specifically
    (the plain bitwise `& | ^ << >>` are covered separately) because §4 pins
    them as first-class operators, not sugar the parser silently rejects."""
    src = """
let io = import('std/io');
let assert = import('std/assert');

let x = 12;                 # 0b1100
x <<= 2;                    # 12 << 2 = 48
assert.eq(x, 48);
x >>= 1;                    # 48 >> 1 = 24
assert.eq(x, 24);
x &= 0x1F;                  # 24 & 31 = 24
assert.eq(x, 24);
x |= 5;                     # 24 | 5 = 29
assert.eq(x, 29);
x ^= 0xFF;                  # 29 XOR 255 = 226
assert.eq(x, 226);

io.println('ok');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "ok\n"


def test_universal_introspection_type_and_isType():
    """Every value carries the Universal introspection triple documented in
    the §7.3 Universal row (root type `All`):
      - `._typeName_()` returns the type's textual name as a Str.
      - `._type_()` returns the value's TypeID (Feral's runtime type token).
      - `._isType_(t)` returns Bool: whether the value's TypeID equals `t`.
    TypeIDs are shared across all instances of the same built-in type -- two
    different Int values return the SAME TypeID from `._type_()` and compare
    equal. Numeric-literal dot syntax like `5._typeName_()` is a tokenizer
    ambiguity with float literals, so parenthesise the receiver: `(5)._x_()`.
    """
    src = """
let io = import('std/io');
let assert = import('std/assert');

# Type-name is the documented textual label for each built-in type.
assert.eq((5)._typeName_(), 'Int');
assert.eq((3.14)._typeName_(), 'Flt');
assert.eq('hi'._typeName_(), 'Str');
assert.eq((true)._typeName_(), 'Bool');
assert.eq((nil)._typeName_(), 'Nil');

# TypeIDs are shared per-type: two Ints share ONE TypeID.
let intT = (1)._type_();
let intT2 = (99)._type_();
assert.eq(intT, intT2);
# TypeIDs distinguish across types.
let strT = 'x'._type_();
assert.ne(intT, strT);

# _isType_(t) returns Bool matching the value's TypeID against t.
assert.eq((5)._isType_(intT), true);
assert.eq('y'._isType_(intT), false);
assert.eq('y'._isType_(strT), true);

# TypeID is itself a type; its _typeName_ is 'TypeID'.
assert.eq(intT._typeName_(), 'TypeID');

io.println('ok');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "ok\n"
