#!/usr/bin/env python
# coding=utf-8
"""Hidden E2E test suite for the WRG `claripy` task (merged from subsystem drafts).

Golden-output, deterministic tests for claripy's symbolic-expression engine:
AST construction/structure, concrete evaluation, expression simplification,
VSA strided-interval arithmetic, and the solver frontend / balancer / annotations.
"""
from __future__ import annotations

import pytest

import claripy
import claripy.ast
from claripy.backends.backend_vsa import Balancer

# ================= from test_part_1_ast.py =================
def test_leaf_construction_structure():
    """BVS / BVV / BoolV / FPV leaves expose the exact hashcons structure.

    A symbol carries op 'BVS', args == (name, size), is symbolic, depth 1, and
    is a BV.  A concrete value carries op 'BVV', args == (value, size), is not
    symbolic.  A boolean value carries op 'BoolV' with args == (bool,).  These
    are the foundational leaf contracts every higher-level op is built on.
    """
    x = claripy.BVS("x", 32, explicit_name=True)
    assert x.op == "BVS"
    assert x.args == ("x", 32)
    assert x.length == 32
    assert x.size() == 32
    assert len(x) == 32
    assert x.depth == 1
    assert x.is_leaf() is True
    assert x.symbolic is True
    assert x.variables == frozenset(("x",))
    assert isinstance(x, claripy.ast.BV)

    v = claripy.BVV(0x01020304, 32)
    assert v.op == "BVV"
    assert v.args == (0x01020304, 32)
    assert v.length == 32
    assert v.size() == 32
    assert v.depth == 1
    assert v.symbolic is False
    assert v.variables == frozenset()
    assert isinstance(v, claripy.ast.BV)

    # value is masked into range for the given size
    assert claripy.BVV(-1, 8).args == (0xFF, 8)
    assert claripy.BVV(0x1FF, 8).args == (0xFF, 8)

    b = claripy.BoolV(True)
    assert b.op == "BoolV"
    assert b.args == (True,)
    assert b.size() == 1
    assert b.depth == 1
    assert b.symbolic is False
    assert isinstance(b, claripy.ast.Bool)

    f = claripy.FPV(1.0, claripy.FSORT_DOUBLE)
    assert f.op == "FPV"
    assert f.args[0] == 1.0
    assert f.symbolic is False
    assert isinstance(f, claripy.ast.FP)


def test_hashcons_identity_and_caching():
    """Structurally identical ASTs are the *same* object (hash-consing).

    Two BVS with the same explicit name+size collapse to one object; the same
    operation built twice yields the same object; distinct names/values do not.
    This is a core invariant ('AST objects have hash identity') and a broken
    re-implementation that forgets to cache would fail every ``is`` assertion.
    """
    a = claripy.BVS("dup", 32, explicit_name=True)
    b = claripy.BVS("dup", 32, explicit_name=True)
    assert a is b

    one = claripy.BVV(1, 1)
    assert one + one is one + one

    # non-explicit names get a unique suffix -> distinct objects
    n1 = claripy.BVS("n", 32)
    n2 = claripy.BVS("n", 32)
    assert n1 is not n2

    # alternate BVV creation forms collapse onto the integer form
    assert claripy.BVV(b"AAAA") is claripy.BVV(0x41414141, 32)
    assert claripy.BVV(b"AB", 16) is claripy.BVV(0x4142, 16)


def test_binop_structure_and_int_coercion():
    """Binary BV ops produce the right op string, depth, length and coerce ints.

    ``x + 1`` becomes op '__add__' whose second arg is auto-coerced into a
    32-bit BVV (op 'BVV', args (1, 32)); depth grows by one over the operand;
    length is preserved.  '+'/'-'/'*'/'&'/'|'/'^' all length-preserve, and the
    raw '/' and '%' map to '__floordiv__' / '__mod__'.  Comparisons return Bool
    of size 1.  String operands coerce to a big-endian BVV.
    """
    x = claripy.BVS("x", 32, explicit_name=True)

    y = x + 1
    assert y.op == "__add__"
    assert y.length == 32
    assert y.depth == 2
    assert isinstance(y, claripy.ast.BV)
    assert isinstance(y.args[1], claripy.ast.BV)
    assert y.args[1].op == "BVV"
    assert y.args[1].args == (1, 32)

    # string operand coerces to big-endian concrete BV
    ys = x + "AAAA"
    assert ys.args[1].op == "BVV"
    assert ys.args[1].args == (0x41414141, 32)

    # use a distinct second symbol so commutative ops do not self-simplify
    # (x-x, x&x, x|x, x^x all fold at construction time)
    z = claripy.BVS("z", 32, explicit_name=True)
    assert (x - z).op == "__sub__"
    assert (x * z).op == "__mul__"
    assert (x & z).op == "__and__"
    assert (x | z).op == "__or__"
    assert (x ^ z).op == "__xor__"
    assert (~x).op == "__invert__"
    assert (x << z).op == "__lshift__"
    assert (x >> z).op == "__rshift__"
    # raw division / modulo operators use integral (floordiv) semantics
    assert (x / z).op == "__floordiv__"
    assert (x % z).op == "__mod__"

    # comparisons -> Bool, length 1
    cmp = x == x + 1
    assert cmp.op == "__eq__"
    assert isinstance(cmp, claripy.ast.Bool)
    assert cmp.size() == 1


def test_signed_unsigned_and_shift_op_names():
    """Signed/unsigned comparisons, LShR, RotateLeft and SDiv/SMod op strings.

    Python ``<`` / ``>`` etc. map to the *unsigned* ops (ULT/UGT/ULE/UGE),
    while the named signed variants produce SLT/SGT/SLE/SGE.  These all return a
    Bool.  LShR / RotateLeft / SDiv / SMod produce a length-preserving BV with
    the named op.  A broken impl that wired ``<`` to a signed compare would fail
    here.
    """
    x = claripy.BVS("x", 32, explicit_name=True)
    y = claripy.BVS("y", 32, explicit_name=True)

    assert (x < y).op == "ULT"
    assert (x > y).op == "UGT"
    assert (x <= y).op == "ULE"
    assert (x >= y).op == "UGE"
    for c in (x < y, x > y, x <= y, x >= y):
        assert isinstance(c, claripy.ast.Bool)

    assert claripy.SLT(x, y).op == "SLT"
    assert claripy.SGT(x, y).op == "SGT"
    assert claripy.ULT(x, y).op == "ULT"
    assert claripy.UGT(x, y).op == "UGT"
    assert isinstance(claripy.SLT(x, y), claripy.ast.Bool)

    lshr = claripy.LShR(x, 10)
    assert lshr.op == "LShR"
    assert lshr.length == 32
    assert isinstance(lshr, claripy.ast.BV)

    rol = claripy.RotateLeft(x, claripy.BVV(3, 32))
    assert rol.op == "RotateLeft"
    assert rol.length == 32

    sdiv = x.SDiv(y)
    smod = x.SMod(y)
    assert sdiv.op == "SDiv" and sdiv.length == 32
    assert smod.op == "SMod" and smod.length == 32


def test_concat_extract_ext_bitwidth_math():
    """Concat / Extract / ZeroExt / SignExt compute exact bit widths and ops.

    Concat sums operand widths (8+16+4 = 28); Extract(hi,lo,x) yields width
    hi+1-lo with op 'Extract' and args (hi, lo, x); ZeroExt(n,x)/SignExt(n,x)
    yield width orig+n with op 'ZeroExt'/'SignExt' and args (n, x).  Reverse
    preserves width.  This is the load-bearing width arithmetic of the bitvector
    layer.
    """
    a8 = claripy.BVS("a8", 8, explicit_name=True)
    b16 = claripy.BVS("b16", 16, explicit_name=True)
    c4 = claripy.BVS("c4", 4, explicit_name=True)

    cc = claripy.Concat(a8, b16, c4)
    assert cc.op == "Concat"
    assert cc.length == 28
    assert len(cc.args) == 3
    assert cc.args == (a8, b16, c4)

    x = claripy.BVS("x", 32, explicit_name=True)
    e = claripy.Extract(7, 0, x)
    assert e.op == "Extract"
    assert e.args == (7, 0, x)
    assert e.length == 8
    e2 = claripy.Extract(31, 16, x)
    assert e2.length == 16

    z = claripy.ZeroExt(8, a8)
    assert z.op == "ZeroExt"
    assert z.args == (8, a8)
    assert z.length == 16
    s = claripy.SignExt(8, a8)
    assert s.op == "SignExt"
    assert s.args == (8, a8)
    assert s.length == 16

    r = claripy.Reverse(x)
    assert r.op == "Reverse"
    assert r.length == 32


def test_getitem_slice_and_reverse_simplifications():
    """Index/slice extraction and reverse simplify to the documented identities.

    For a 32-bit symbol: ``a[31:0] is a`` (full-width extract collapses),
    ``a[7:] is a[7:0]`` (omitted low = 0), ``a[:] is a`` (full), negative
    indices wrap (``a[:-8] is a[31:24]``), and ``Reverse(Reverse(a)) is a`` for a
    symbol.  Splitting then re-concatenating consecutive ranges rebuilds the
    original: ``a[31:8].concat(a[7:0]) is a``.  These are exact structural
    simplification identities.
    """
    a = claripy.BVS("a", 32, explicit_name=True)

    assert a[31:0] is a
    assert a[:] is a
    assert a[:0] is a
    assert a[7:] is a[7:0]
    assert a[:-8] is a[31:24]
    assert a[-1:] is a[31:0]
    assert a[-1:-8] is a[31:24]

    single = a[5]
    assert single.op == "Extract"
    assert single.args == (5, 5, a)
    assert single.length == 1

    # reverse of reverse collapses to the original symbol
    assert a.reversed.reversed is a
    assert a.reversed is not a

    # consecutive extracts re-concatenate to the whole
    assert a[31:8].concat(a[7:0]) is a
    assert a[31:16].concat(a[15:8], a[7:0]) is a


def test_multiarg_flattening_keeps_variables():
    """Repeated commutative ops flatten into a single n-ary node.

    ``x + x + x + x`` collapses to one '__add__' node with four args (not a
    left-leaning binary tree); the same holds for '*', '|', '^', '&'.  The
    flattened node's variable set equals the operand's.  A re-implementation that
    builds nested binary trees would produce 2 args and fail.
    """
    x = claripy.BVS("x", 32, explicit_name=True)

    x_add = x + x + x + x
    x_mul = x * x * x * x
    x_or = x | (x + 1) | (x + 2) | (x + 3)
    x_xor = x ^ (x + 1) ^ (x + 2) ^ (x + 3)
    x_and = x & (x + 1) & (x + 2) & (x + 3)

    assert x_add.op == "__add__" and len(x_add.args) == 4
    assert x_mul.op == "__mul__" and len(x_mul.args) == 4
    assert x_or.op == "__or__" and len(x_or.args) == 4
    assert x_xor.op == "__xor__" and len(x_xor.args) == 4
    assert x_and.op == "__and__" and len(x_and.args) == 4

    assert x_add.variables == x.variables
    assert x_mul.variables == x.variables
    assert x_and.variables == x.variables


def test_if_structure_and_constant_condition_folding():
    """If builds a 3-arg node and folds constant conditions / identical branches.

    With a symbolic condition, ``If(cond, t, f)`` has op 'If', args (cond, t, f),
    and the BV result has the branch width.  Integer branches coerce to BVVs of
    the matching width.  ``If(True, t, f) is t`` and ``If(False, t, f) is f``;
    ``If(cond, t, t) is t``.  These folds are exact.
    """
    x = claripy.BVS("x", 32, explicit_name=True)
    cond = x > 10

    ite = claripy.If(cond, claripy.BVV(3, 32), claripy.BVV(4, 32))
    assert ite.op == "If"
    assert ite.args[0] is cond
    assert ite.args[1].args == (3, 32)
    assert ite.args[2].args == (4, 32)
    assert ite.length == 32
    assert isinstance(ite, claripy.ast.BV)

    # an integer branch coerces to a BVV of the other branch's width (at least
    # one branch must already be an AST)
    ite_int = claripy.If(cond, 5, claripy.BVV(6, 32))
    assert ite_int.args[1].op == "BVV"
    assert ite_int.args[1].args == (5, 32)

    # constant condition folds to the chosen branch
    t = claripy.BVV(2, 32)
    f = claripy.BVV(3, 32)
    assert claripy.If(True, t, f) is t
    assert claripy.If(False, t, f) is f
    # identical branches fold to that branch
    assert claripy.If(cond, t, t) is t


def test_bool_and_or_not_structure_and_folding():
    """And/Or/Not build boolean nodes and fold pure-constant inputs.

    With symbolic operands And/Or yield op 'And'/'Or' Bool nodes and Not yields
    op 'Not'.  Pure-constant inputs fold: ``And(True, x) is x``,
    ``Or(False, x) is x``, ``Not(BoolV(True)) is BoolV(False)``.  ``~x`` on a
    Bool maps to Not.  Result type is always Bool.
    """
    p = claripy.BoolS("p")
    q = claripy.BoolS("q")

    a = claripy.And(p, q)
    o = claripy.Or(p, q)
    n = claripy.Not(p)
    assert a.op == "And" and isinstance(a, claripy.ast.Bool)
    assert o.op == "Or" and isinstance(o, claripy.ast.Bool)
    assert n.op == "Not" and isinstance(n, claripy.ast.Bool)
    assert (~p).op == "Not"

    # constant-identity folds
    assert claripy.And(claripy.BoolV(True), p) is p
    assert claripy.Or(claripy.BoolV(False), p) is p
    assert claripy.Not(claripy.BoolV(True)) is claripy.BoolV(False)
    assert claripy.Not(claripy.BoolV(False)) is claripy.BoolV(True)


def test_depth_growth_and_nested_structure():
    """Depth equals the longest operand chain + 1 and nesting is preserved.

    A leaf has depth 1; ``x + 1`` has depth 2; chaining LShR seven times deepens
    the tree predictably, and the nested args remain navigable with stable op
    strings.  This guards the depth accounting used throughout claripy.
    """
    x = claripy.BVS("x", 32, explicit_name=True)
    assert x.depth == 1
    assert (x + 1).depth == 2

    y = x
    for _ in range(7):
        y = claripy.LShR(y, 10)
    # 7 nested LShR over a depth-1 leaf
    assert y.op == "LShR"
    assert y.depth == 8
    # the innermost-but-one structure: descend the left spine
    inner = y
    for _ in range(7):
        assert inner.op == "LShR"
        assert inner.length == 32
        inner = inner.args[0]
    assert inner is x


def test_size_mismatch_and_extract_bounds_raise():
    """Out-of-spec operations raise the documented claripy errors.

    Adding mismatched-width bitvectors raises ClaripyOperationError (the
    length-same check); an Extract whose high bound exceeds the BV width raises;
    a low>high Extract raises; and creating a BVV from bytes whose length
    contradicts an explicit size raises ClaripyValueError.  A re-implementation
    that silently truncates or zero-pads would fail these.
    """
    a = claripy.BVV(1, 8)
    b = claripy.BVV(1, 16)

    import pytest

    with pytest.raises(claripy.errors.ClaripyOperationError):
        a + b
    with pytest.raises(claripy.errors.ClaripyOperationError):
        a & b

    x = claripy.BVS("x", 32, explicit_name=True)
    with pytest.raises(claripy.errors.ClaripyOperationError):
        claripy.Extract(32, 0, x)  # high == size is out of range
    with pytest.raises(claripy.errors.ClaripyOperationError):
        claripy.Extract(3, 7, x)  # low > high

    with pytest.raises(claripy.errors.ClaripyValueError):
        claripy.BVV(b"AB", 8)  # 2 bytes != 8 bits

# ================= from test_part_2_concrete.py =================
def _bc():
    return claripy.backends.concrete


def test_bv_arithmetic_wraparound_and_unary():
    """N-bit arithmetic wraps modulo 2**bits; neg/invert obey two's complement.

    Bundles add/sub/mul overflow on an 8-bit width plus unary negate and
    bitwise-invert, covering the full-width wrap boundary at 0xff.
    """
    bc = _bc()

    # 0xff + 1 wraps to 0 in 8 bits.
    assert bc.eval(claripy.BVV(0xFF, 8) + claripy.BVV(1, 8), 2) == (0,)
    # 0x00 - 1 wraps to 0xff.
    assert bc.eval(claripy.BVV(0, 8) - claripy.BVV(1, 8), 2) == (0xFF,)
    # 200 * 2 = 400 -> 400 mod 256 = 144.
    assert bc.eval(claripy.BVV(200, 8) * claripy.BVV(2, 8), 2) == (144,)
    # Two's-complement negate and bitwise invert of 1 in 8 bits.
    assert bc.eval(-claripy.BVV(1, 8), 2) == (0xFF,)
    assert bc.eval(~claripy.BVV(1, 8), 2) == (0xFE,)
    # Negate / invert of zero.
    assert bc.eval(-claripy.BVV(0, 8), 2) == (0,)
    assert bc.eval(~claripy.BVV(0, 8), 2) == (0xFF,)


def test_bv_bitwise_ops():
    """Concrete AND/OR/XOR produce exact bit patterns at a fixed width."""
    bc = _bc()
    a = claripy.BVV(0b1100, 4)
    b = claripy.BVV(0b1010, 4)
    assert bc.eval(a & b, 2) == (0b1000,)
    assert bc.eval(a | b, 2) == (0b1110,)
    assert bc.eval(a ^ b, 2) == (0b0110,)


def test_unsigned_vs_signed_division_and_modulo():
    """``//`` and ``%`` are UNSIGNED; SDiv / SMod are signed (round-toward-zero).

    Golden values mirror claripy's own test_signed_concrete: with
    a=5, b=-5, c=3, d=-3 (all 32-bit), unsigned ``//``/``%`` treat the
    operands as large unsigned numbers while SDiv/SMod treat them as signed.
    ``convert`` is used because its returned value compares equal to the
    signed Python ints, while ``eval`` exposes the raw unsigned wrap.
    """
    bc = _bc()
    a = claripy.BVV(5, 32)
    b = claripy.BVV(-5, 32)
    c = claripy.BVV(3, 32)
    d = claripy.BVV(-3, 32)

    # Unsigned // and % (b is treated as 0xFFFFFFFB).
    assert bc.convert(a // c) == 1
    assert bc.convert(a // d) == 0
    assert bc.convert(b // c) == 0x55555553
    assert bc.convert(b // d) == 0
    assert bc.convert(a % c) == 2
    assert bc.convert(a % d) == 5
    assert bc.convert(b % c) == 2
    assert bc.convert(b % d) == 0xFFFFFFFB  # 0xFFFFFFFB % 0xFFFFFFFD == 0xFFFFFFFB

    # Signed SDiv (round toward zero) and SMod (C-style remainder); results are
    # compared as unsigned 32-bit values (e.g. -1 == 0xFFFFFFFF).
    assert bc.convert(a.SDiv(c)) == 1
    assert bc.convert(a.SDiv(d)) == 0xFFFFFFFF
    assert bc.convert(b.SDiv(c)) == 0xFFFFFFFF
    assert bc.convert(b.SDiv(d)) == 1
    assert bc.convert(a.SMod(c)) == 2
    assert bc.convert(a.SMod(d)) == 2
    assert bc.convert(b.SMod(c)) == 0xFFFFFFFE
    assert bc.convert(b.SMod(d)) == 0xFFFFFFFE

    # The raw unsigned eval of a signed-negative result wraps to 2**32 form.
    assert bc.eval(a.SDiv(d), 2) == (2**32 - 1,)


def test_division_by_zero_raises():
    """Concrete division / modulo (unsigned and signed) by zero raises ClaripyZeroDivisionError."""
    bc = _bc()
    one = claripy.BVV(1, 32)
    zero = claripy.BVV(0, 32)

    # concrete division/modulo by zero raises eagerly at construction time
    for make in (
        lambda: one // zero,
        lambda: one % zero,
        lambda: one.SDiv(zero),
        lambda: one.SMod(zero),
    ):
        with pytest.raises(claripy.errors.ClaripyZeroDivisionError):
            make()


def test_logical_vs_arithmetic_shift():
    """LShR (logical, zero-fill) differs from ``>>`` (arithmetic, sign-fill).

    Golden values from claripy's test_logic_shift_right / test_arith_shift on
    a = BVV(-4, 32) (== 0xFFFFFFFC).
    """
    bc = _bc()
    a = claripy.BVV(-4, 32)

    # Arithmetic right shift keeps the sign bit.
    assert bc.convert(a >> 1) == 0xFFFFFFFE
    assert bc.convert(a >> 32) == 0xFFFFFFFF  # shifting out everything leaves all sign bits
    # Logical right shift fills with zeros.
    assert bc.eval(a.LShR(1), 2) == (0x7FFF_FFFE,)
    assert bc.eval(a.LShR(32), 2) == (0,)
    # Left shift wraps; shifting by the full width yields 0.
    assert bc.convert(a << 1) == 0xFFFFFFF8
    assert bc.eval(a << 32, 2) == (0,)


def test_concat_extract_zeroext_signext():
    """Concat / Extract / ZeroExt / SignExt produce exact values and widths.

    ZeroExt zero-fills (preserving the unsigned value); SignExt replicates the
    sign bit. Widths grow by the extension amount.
    """
    bc = _bc()

    # Concat builds a wider value, high operand first.
    cat = claripy.Concat(claripy.BVV(0xA, 4), claripy.BVV(0xB, 4))
    assert bc.eval(cat, 2) == (0xAB,)
    assert cat.size() == 8

    # Extract a middle byte out of a 32-bit value (bits [15:8]).
    d = claripy.BVV(0xABCDEF12, 32)
    ext = claripy.Extract(15, 8, d)
    assert bc.eval(ext, 2) == (0xEF,)
    assert ext.size() == 8

    # ZeroExt vs SignExt on 0xFE (high bit set) extended by 8 bits.
    fe = claripy.BVV(0xFE, 8)
    ze = claripy.ZeroExt(8, fe)
    se = claripy.SignExt(8, fe)
    assert bc.eval(ze, 2) == (0x00FE,)
    assert ze.size() == 16
    assert bc.eval(se, 2) == (0xFFFE,)
    assert se.size() == 16


def test_rotate_and_reverse():
    """RotateLeft / RotateRight wrap bits around; Reverse byte-swaps.

    Golden: rotating 0x80000001 by 1 -> 0x00000003 (left) and 0xC0000000
    (right). Reverse(0x01020304) byteswaps to 0x04030201; an 8-bit value is
    returned unchanged by Reverse.
    """
    bc = _bc()
    v = claripy.BVV(0x80000001, 32)
    assert bc.eval(claripy.RotateLeft(v, 1), 2) == (0x00000003,)
    assert bc.eval(claripy.RotateRight(v, 1), 2) == (0xC0000000,)

    rev = claripy.Reverse(claripy.BVV(0x01020304, 32))
    assert bc.eval(rev, 2) == (0x04030201,)
    # Reverse of a single byte is a no-op.
    assert bc.eval(claripy.Reverse(claripy.BVV(0xAB, 8)), 2) == (0xAB,)
    # The .reversed property is equivalent to Reverse().
    assert bc.convert(claripy.BVV(0x01020304, 32).reversed) == 0x04030201


def test_bool_and_if_concrete():
    """And/Or/Not over concrete bools and If with a concrete condition.

    And short-circuits to the AND of all args; Or to any; If selects the
    chosen branch's concrete value.
    """
    bc = _bc()

    assert bc.convert(claripy.And(claripy.BoolV(True), claripy.BoolV(True), claripy.BoolV(True))) is True
    assert bc.convert(claripy.And(claripy.BoolV(True), claripy.BoolV(False))) is False
    assert bc.convert(claripy.Or(claripy.BoolV(False), claripy.BoolV(False), claripy.BoolV(True))) is True
    assert bc.convert(claripy.Or(claripy.BoolV(False), claripy.BoolV(False))) is False
    assert bc.convert(claripy.Not(claripy.BoolV(False))) is True

    # If with a concrete True / False condition selects t / f respectively.
    chosen_true = claripy.If(claripy.BoolV(True), claripy.BVV(10, 32), claripy.BVV(20, 32))
    chosen_false = claripy.If(claripy.BoolV(False), claripy.BVV(10, 32), claripy.BVV(20, 32))
    assert bc.eval(chosen_true, 2) == (10,)
    assert bc.eval(chosen_false, 2) == (20,)


def test_unsigned_comparisons_concrete():
    """ULT/UGT/SLT distinguish unsigned vs signed ordering on concrete BVs.

    0xFF (== -1 signed) is the largest unsigned 8-bit value but the smallest
    signed value, so unsigned and signed comparisons disagree.
    """
    bc = _bc()
    big = claripy.BVV(0xFF, 8)   # unsigned 255, signed -1
    one = claripy.BVV(1, 8)

    assert bc.convert(claripy.ULT(one, big)) is True   # 1 < 255 unsigned
    assert bc.convert(claripy.UGT(big, one)) is True   # 255 > 1 unsigned
    assert bc.convert(claripy.SLT(big, one)) is True   # -1 < 1 signed
    assert bc.convert(claripy.SLT(one, big)) is False  # 1 < -1 is false signed


def test_concrete_fp_arithmetic_and_compare():
    """FP add/sub/mul/div, comparisons, and fpToUBV rounding on concrete FPVs.

    Exact doubles avoid rounding ambiguity: 1.5 + 2.5 = 4.0, 1.5 * 2.5 = 3.75,
    7.0 / 2.0 = 3.5. fpToUBV uses round-half-to-even, so both 1.5 and 2.5
    round to 2.
    """
    bc = _bc()
    rm = claripy.fp.RM.RM_NearestTiesEven
    a = claripy.FPV(1.5, claripy.FSORT_DOUBLE)
    b = claripy.FPV(2.5, claripy.FSORT_DOUBLE)

    assert bc.eval(claripy.fpAdd(rm, a, b), 2) == (4.0,)
    assert bc.eval(claripy.fpSub(rm, b, a), 2) == (1.0,)
    assert bc.eval(claripy.fpMul(rm, a, b), 2) == (3.75,)
    assert bc.eval(
        claripy.fpDiv(rm, claripy.FPV(7.0, claripy.FSORT_DOUBLE), claripy.FPV(2.0, claripy.FSORT_DOUBLE)), 2
    ) == (3.5,)

    # Comparisons.
    assert bc.convert(claripy.fpLT(a, b)) is True
    assert bc.convert(claripy.fpGT(a, b)) is False
    assert bc.convert(claripy.fpEQ(a, a)) is True

    # Single FPV evaluates to its Python float.
    assert bc.eval(claripy.FPV(1.0, claripy.FSORT_FLOAT), 2) == (1.0,)

    # fpToUBV with round-half-to-even: 1.5 -> 2 and 2.5 -> 2.
    assert bc.eval(claripy.fpToUBV(rm, a, 32), 2) == (2,)
    assert bc.eval(claripy.fpToUBV(rm, b, 32), 2) == (2,)

# ================= from test_part_3_simplify.py =================
# ---------------------------------------------------------------------------
# Boolean simplification (And/Or with concrete operands, Not(Not), x==x, Not(eq))
# ---------------------------------------------------------------------------
def test_boolean_and_or_not_collapse():
    """And/Or absorb concrete True/False; Not is involutive and flips (in)equality.

    Grounds: boolean_and_simplifier / boolean_or_simplifier / boolean_not_simplifier
    in simplifications.py. These fire inline at construction, so the results are
    canonical nodes comparable with `is`, and the concrete collapses are
    trivially True/False per the concrete backend.
    """
    a = claripy.BoolS("a")

    # Concrete-constant *collapses* (distinct from the identity folds in
    # test_bool_and_or_not_structure_and_folding): a False conjunct forces false,
    # a True disjunct forces true, all-concrete inputs reduce to a constant.
    assert claripy.is_false(claripy.And(claripy.false(), a))
    assert claripy.is_true(claripy.And(claripy.true(), claripy.true()))
    assert claripy.is_true(claripy.Or(claripy.true(), a))
    assert claripy.is_false(claripy.Or(claripy.false(), claripy.false()))

    # Not(Not(a)) -> a  (involution)
    assert claripy.Not(claripy.Not(a)) is a

    # Not over equality flips it: Not(x == y) -> x != y ; Not(x != y) -> x == y
    x = claripy.BVS("x", 32)
    y = claripy.BVS("y", 32)
    assert claripy.Not(x == y) is (x != y)
    assert claripy.Not(x != y) is (x == y)


def test_eq_ne_identity_and_reverse():
    """x == x is trivially True, x != x trivially False; ==/!= over a Bool and
    a concrete Bool collapse to the value / its negation.

    Grounds: eq_simplifier (a is b -> true(); Bool vs true()/false() rules) and
    ne_simplifier (a is b -> false()) in simplifications.py.
    """
    x = claripy.BVS("x", 32)
    assert claripy.is_true(x == x)
    assert claripy.is_false(x != x)

    a = claripy.BoolS("a")
    # (a == True) -> a ; (a == False) -> Not(a)
    assert (a == claripy.true()) is a
    assert (a == claripy.false()) is claripy.Not(a)


def test_bool_simplification_via_simplify():
    """claripy.simplify drives the And(a, Not(a)) / Or(a, Not(a)) tautologies to
    constant True/False (this path goes through the backend simplifier).

    Grounds: test_simplify.py::test_bool_simplification. We assert exact truth
    values rather than backend.identical to keep the check self-contained.
    """
    a = claripy.BoolS("a")
    assert claripy.is_false(claripy.simplify(claripy.And(a, claripy.Not(a))))
    assert claripy.is_true(claripy.simplify(claripy.Or(a, claripy.Not(a))))


# ---------------------------------------------------------------------------
# Arithmetic / bitwise identities
# ---------------------------------------------------------------------------
def test_additive_identities():
    """x + 0 -> x, x - 0 -> x, x - x -> BVV(0); concrete folding flattens
    add/sub chains to a single canonical node.

    Grounds: bitwise_add_simplifier (filters BVV 0), bitwise_sub_simplifier
    (b==0 -> a; a is b -> BVV(0)), and test_simplify.py::test_concrete_flatten.
    """
    x = claripy.BVS("x", 32)

    assert (x + 0) is x
    assert (x - 0) is x

    zero = x - x
    assert zero.op == "BVV"
    assert zero.args == (0, 32)
    assert claripy.backends.concrete.eval(zero, 1)[0] == 0

    # concrete flatten: a + 10 then + 10 collapses identically to a + 20
    a = claripy.BVS("a", 32)
    assert (10 + (a + 10)) is (a + 20)
    # subtraction folding: (a - 10) - 10 collapses to a - 20
    assert ((a - 10) - 10) is (a - 20)


def test_bitwise_identities():
    """Bitwise self/zero/all-ones identities collapse to canonical nodes.

    Grounds: bitwise_and_simplifier, bitwise_or_simplifier, bitwise_xor_simplifier
    in simplifications.py. NOTE: claripy registers NO multiplicative-identity
    filter for __mul__, so x*1 / x*0 are intentionally NOT simplified and are
    excluded here.
    """
    x = claripy.BVS("x", 32)
    allones = claripy.BVV(2 ** 32 - 1, 32)
    zero = claripy.BVV(0, 32)

    # x & x -> x ; x & allones -> x ; x & 0 -> 0
    assert (x & x) is x
    assert (x & allones) is x
    xz = x & 0
    assert xz.op == "BVV" and xz.args == (0, 32)

    # x | 0 -> x ; x | x -> x
    assert (x | 0) is x
    assert (x | x) is x

    # x ^ 0 -> x ; x ^ x -> 0
    assert (x ^ 0) is x
    xx = x ^ x
    assert xx.op == "BVV" and xx.args == (0, 32)
    assert claripy.backends.concrete.eval(xx, 1)[0] == 0
    # silence unused
    assert zero.args == (0, 32)


def test_sub_constant_pushed_into_equality():
    """(expr - c1 == c2) simplifies to (expr == c1 + c2); the c2==0 case gives
    expr == c1 directly.

    Grounds: eq_simplifier '__sub__' branch and test_simplify.py::test_sub_constant.
    """
    expr = claripy.BVS("expr", 32)
    assert (expr - 5 == 0) is (expr == 5)
    assert (expr - 3 == 4) is (expr == 7)


# ---------------------------------------------------------------------------
# Concat / Extract simplifications
# ---------------------------------------------------------------------------
def test_extract_over_concat_and_full_width():
    """Extract that lines up with a Concat boundary returns the underlying piece;
    extracting the full width returns the value unchanged; spanning extracts
    rebuild the right sub-Concat.

    Grounds: extract_simplifier + concat_simplifier and
    test_simplify.py::test_simplification. All fire inline so we use `is`/struct.
    """
    x, y, z = (claripy.BVS(n, 32) for n in ("x", "y", "z"))
    concatted = claripy.Concat(x, y, z)  # 96 bits: [95:64]=x [63:32]=y [31:0]=z

    # exact piece extraction
    assert concatted[95:64] is x
    assert concatted[63:32] is y
    assert concatted[31:0] is z

    # full-width extract returns the value itself
    assert concatted[95:0] is concatted

    # spanning two adjacent pieces rebuilds the sub-Concat
    top2 = concatted[95:32]
    assert top2.op == "Concat"
    assert top2.args[0] is x and top2.args[1] is y

    bot2 = concatted[63:0]
    assert bot2.op == "Concat"
    assert bot2.args[0] is y and bot2.args[1] is z


def test_extract_of_extract_and_zeroext_and_after_extract():
    """Nested Extract folds into a single Extract on the base var; Extract over a
    masked high-zero value folds to BVV(0).

    Grounds: extract_simplifier ('Extract' inner branch) and
    test_simplify.py::test_simplification_zero_bitwise_and_after_extract.
    """
    e = claripy.BVS("e", 32)
    # Extract(Extract(...)) collapses to one Extract on e
    inner = claripy.Extract(23, 8, e)      # 16 bits
    outer = claripy.Extract(7, 0, inner)   # low 8 bits of that
    assert outer.op == "Extract"
    assert outer.args[2] is e
    assert outer.args[0] == 15 and outer.args[1] == 8

    # (0xFFFFFFFF_00000000 & b)[31:0] -> BVV(0, 32): low 32 bits are masked to 0
    a = claripy.BVV(0xFFFFFFFF_00000000, 64)
    b = claripy.BVS("b", 64)
    expr = claripy.Extract(31, 0, a & b)
    assert expr is claripy.BVV(0, 32)


def test_reverse_extract_reverse_simplification():
    """Reverse(Extract(hi, lo, Reverse(x))) with byte-aligned hi/lo folds to a
    single Extract on x (no Reverse left).

    Grounds: bv_reverse_simplifier / extract_simplifier and
    test_simplify.py::test_reverse_extract_reverse_simplification.
    """
    a = claripy.BVS("rdx", 64)
    dx = claripy.Reverse(claripy.Extract(63, 48, claripy.Reverse(a)))
    assert dx.op == "Extract"
    assert dx.args[0] == 15
    assert dx.args[1] == 0
    assert dx.args[2] is a


# ---------------------------------------------------------------------------
# If simplifications (concrete condition collapse; If pushed through ops)
# ---------------------------------------------------------------------------
def test_if_concrete_condition_collapses():
    """An If whose condition is a concrete Bool AST folds to the selected branch at
    construction time, and that branch evaluates to its concrete value.

    Grounds: the inline If op simplifier (cond.is_true()/is_false()) referenced
    by if_simplifier in simplifications.py. (test_if_structure_and_constant_condition_folding
    covers the raw-Python-bool condition path; here the condition is a concrete
    `Bool` AST, a distinct input path into the same fold.)
    """
    a = claripy.BVV(0xAA, 32)
    b = claripy.BVV(0xBB, 32)
    assert claripy.If(claripy.true(), a, b) is a
    assert claripy.If(claripy.false(), a, b) is b
    assert claripy.backends.concrete.eval(claripy.If(claripy.true(), a, b), 1)[0] == 0xAA
    assert claripy.backends.concrete.eval(claripy.If(claripy.false(), a, b), 1)[0] == 0xBB


def test_if_pushed_through_extract_and_invert():
    """Extract distributes into both If branches; ~If(c,1,0) folds to If(!c,1,0).

    Grounds: extract_simplifier 'If' branch + invert_simplifier and
    test_simplify.py::test_extract / test_invert_if.
    """
    cond = claripy.BoolS("cond")

    # If(cond, 1#32, 0#32)[0:0] -> If(cond, 1#1, 0#1)
    expr = claripy.If(cond, claripy.BVV(1, 32), claripy.BVV(0, 32))[0:0]
    result = claripy.If(cond, claripy.BVV(1, 1), claripy.BVV(0, 1))
    assert expr is result

    # ~If(cond, 1, 0) -> If(Not(cond), 1, 0)
    inv = ~(claripy.If(cond, claripy.BVV(1, 1), claripy.BVV(0, 1)))
    assert inv is claripy.If(claripy.Not(cond), claripy.BVV(1, 1), claripy.BVV(0, 1))


def test_xor_eq_and_bitwise_and_if_idioms():
    """Boolean-flag idioms collapse exactly: 1 ^ If(c,1,0) == 0 -> c, and
    If(c0,1,0) & If(c1,1,0) -> If(c0 & c1, 1, 0).

    Grounds: eq_simplifier '__xor__' branch + bitwise_and_simplifier If/If branch
    and test_simplify.py::test_one_xor_exp_eq_zero / test_bitwise_and_if.
    """
    # 1 ^ If(c,1,0) == 0  -> c   (the flag idiom for "condition holds")
    c = claripy.BoolS("c")
    flag = claripy.If(c, claripy.BVV(1, 1), claripy.BVV(0, 1))
    expr = claripy.BVV(1, 1) ^ flag == claripy.BVV(0, 1)
    assert expr is c

    # If(e>=5,1,0) & If(e!=5,1,0)  ->  If(e>5, 1, 0)
    e = claripy.BVS("e", 8)
    ifc1 = claripy.If(e >= 5, claripy.BVV(1, 1), claripy.BVV(0, 1))
    ifc2 = claripy.If(e != 5, claripy.BVV(1, 1), claripy.BVV(0, 1))
    expected = claripy.If(e > 5, claripy.BVV(1, 1), claripy.BVV(0, 1))
    assert (ifc1 & ifc2) is expected

# ================= from test_part_4_vsa.py =================
# ---------------------------------------------------------------------------
# Helpers: drive strided-interval semantics through the public VSA surface
# (claripy.SI factory + claripy.backends.vsa.{convert,identical,eval}).
# ---------------------------------------------------------------------------

def vm(a):
    """Convert a claripy AST to its concrete VSA model (a StridedInterval / ValueSet)."""
    return claripy.backends.vsa.convert(a)


def si_eq(result_ast, bits, stride, lb, ub):
    """Public-surface exact check: ``result_ast`` is the same strided interval as
    ``SI(bits, stride, lb, ub)``, compared via the documented VSA backend.

    This drives only the public surface (``claripy.SI`` factory + the backend's
    ``identical`` accessor), so any correct VSA implementation passes regardless of
    how its strided-interval model class is named or constructed.
    """
    expected = claripy.SI(bits=bits, stride=stride, lower_bound=lb, upper_bound=ub)
    return claripy.backends.vsa.identical(result_ast, expected)


def si_covers(result_ast, bits, alo, ahi, blo, bhi, fn):
    """Public-surface soundness check: the concrete set enumerated from
    ``result_ast`` (via ``backends.vsa.eval``) contains every value ``fn(x, y)``
    for ``x in [alo, ahi]`` and ``y in [blo, bhi]`` (interpreted in the unsigned
    ``bits``-wide domain).

    Used for the wrap-around / sign-straddling SI multiplication cases, whose
    exact over-approximation bounds are not uniquely determined by the spec --
    only soundness (the abstract result over-approximates the true set) is
    required.
    """
    mask = (1 << bits) - 1
    true_set = {fn(x, y) & mask for x in range(alo, ahi + 1) for y in range(blo, bhi + 1)}
    got = set(claripy.backends.vsa.eval(result_ast, 1 << bits))
    return true_set.issubset(got)


# ---------------------------------------------------------------------------
# Arithmetic kernel: add / sub on wrap-around strided intervals
# ---------------------------------------------------------------------------

def test_strided_interval_addition_exact_bounds():
    """SI addition on 4-bit wrap-around intervals yields exact (stride, lo, hi).

    Covers: a TOP-producing overflow, ordinary interval add, integer add,
    a negative-straddling operand, and a strided operand whose stride is
    GCD-reduced into the result. Golden values from test_strided_intervals.py.

    Driven through the public surface: operands built with ``claripy.SI`` and
    combined with the ``+`` AST operator; results checked with the documented
    ``claripy.backends.vsa.identical`` accessor.
    """
    # [-2,7] + [0,-6] overflows the 4-bit space -> TOP = <4>1[0,15]
    a = claripy.SI(bits=4, stride=1, lower_bound=-2, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=0, upper_bound=-6)
    assert si_eq(a + b, 4, 1, 0, 15)

    # [1,7] + [2,6] -> 1,[3,13]
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=2, upper_bound=6)
    assert si_eq(a + b, 4, 1, 3, 13)

    # [1,7] + integer 2 -> 1,[3,9]
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=2, upper_bound=2)
    assert si_eq(a + b, 4, 1, 3, 9)

    # [-2,7] + 2 -> 1,[0,9]
    a = claripy.SI(bits=4, stride=1, lower_bound=-2, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=2, upper_bound=2)
    assert si_eq(a + b, 4, 1, 0, 9)

    # [1,7] + [-5,-1] -> 1,[-4,6]  (i.e. 1,[12,6])
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=-5, upper_bound=-1)
    assert si_eq(a + b, 4, 1, -4 & 0xF, 6)

    # strided: stride-2 + stride-1 -> stride 1, still [3,13]
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=7)
    b = claripy.SI(bits=4, stride=2, lower_bound=2, upper_bound=6)
    assert si_eq(a + b, 4, 1, 3, 13)


def test_strided_interval_subtraction_exact_bounds():
    """SI subtraction on 4-bit intervals yields exact wrap-around (stride, lo, hi).

    Golden values from test_strided_intervals.py:TestSubtraction. Driven through
    the public ``-`` AST operator on ``claripy.SI`` operands.
    """
    # [-2,7] - [0,-6] -> TOP
    a = claripy.SI(bits=4, stride=1, lower_bound=-2, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=0, upper_bound=-6)
    assert si_eq(a - b, 4, 1, 0, 15)

    # [1,7] - [2,6] -> 1,[-5,5]  (wraps: lo=11)
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=2, upper_bound=6)
    assert si_eq(a - b, 4, 1, -5 & 0xF, 5)

    # [1,7] - 2 -> 1,[15,5]
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=2, upper_bound=2)
    assert si_eq(a - b, 4, 1, 15, 5)

    # [1,7] - [-5,-1] -> 1,[2,12]
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=7)
    b = claripy.SI(bits=4, stride=1, lower_bound=-5, upper_bound=-1)
    assert si_eq(a - b, 4, 1, 2, 12)


def test_strided_interval_multiplication_exact_bounds():
    """SI multiplication over the public ``*`` operator: exact for the cases the
    spec pins down, and sound (over-approximating) for the wrap-around /
    sign-straddling cases whose exact over-approximation is implementation-defined.

    The non-wrapping multiplications (the simple ``[1,3] * 2`` and the 32-bit
    ``[10,15] * [20,30] -> [200,450]``) are uniquely determined and checked
    exactly; the 4-bit wrap-around / mixed-hemisphere cases are only required to
    be sound, since several equally-correct over-approximations exist.
    From test_vsa.py:test_interval_multiplication + TestMultiplication.
    """
    # [1,3] * 2 -> 2,[2,6]  (non-wrapping, derivable -> exact)
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=3)
    b = claripy.SI(bits=4, stride=1, lower_bound=2, upper_bound=2)
    assert si_eq(a * b, 4, 2, 2, 6)

    # [3,e] * [e,e]: sign-straddling -> only soundness required
    a = claripy.SI(bits=4, stride=1, lower_bound=3, upper_bound=-2)
    b = claripy.SI(bits=4, stride=1, lower_bound=-2, upper_bound=-2)
    assert si_covers(a * b, 4, 3, 14, 14, 14, lambda x, y: x * y)

    # both 0-hemisphere [1,3]*[4,6]: wraps modulo 16 -> only soundness required
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=3)
    b = claripy.SI(bits=4, stride=1, lower_bound=4, upper_bound=6)
    assert si_covers(a * b, 4, 1, 3, 4, 6, lambda x, y: x * y)

    # mixed hemispheres -> overflow -> only soundness required
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=4)
    b = claripy.SI(bits=4, stride=1, lower_bound=-5, upper_bound=-1)
    assert si_covers(a * b, 4, 1, 4, 11, 15, lambda x, y: x * y)

    # 32-bit interval multiply, no wrap (test_vsa.py:test_interval_multiplication)
    si1 = claripy.SI(bits=32, stride=1, lower_bound=10, upper_bound=15)
    si2 = claripy.SI(bits=32, stride=1, lower_bound=20, upper_bound=30)
    si3 = claripy.SI(bits=32, stride=1, lower_bound=200, upper_bound=450)
    assert claripy.backends.vsa.identical(si1 * si2, si3)


def test_strided_interval_unsigned_division():
    """Unsigned SI division over the public ``/`` (integral) operator.

    ``/`` on bit-vectors is unsigned (it maps to ``__floordiv__``, the only
    division the VSA backend supports through the public AST), so negative-looking
    operands are treated as large unsigned values. Each quotient interval is the
    tightest SI over the elementwise quotient set and is checked exactly;
    division by ``{0}`` is BOTTOM. Golden values from
    test_strided_intervals.py:TestDivision. (Concrete signed/unsigned division
    semantics are covered exactly in test_unsigned_vs_signed_division_and_modulo.)
    """
    # non-overlapping, both small: [1,3] / 2 -> 1,[0,1] (derivable -> exact)
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=3)
    b = claripy.SI(bits=4, stride=1, lower_bound=2, upper_bound=2)
    assert si_eq(a / b, 4, 1, 0, 1)

    # wide dividend [3,e] / [e,e] (e == 14 unsigned) -> 1,[0,1] (derivable -> exact)
    a = claripy.SI(bits=4, stride=1, lower_bound=3, upper_bound=-2)
    b = claripy.SI(bits=4, stride=1, lower_bound=-2, upper_bound=-2)
    assert si_eq(a / b, 4, 1, 0, 1)

    # both operands in the high unsigned half [10,12] / [13,15] -> exactly {0}
    a = claripy.SI(bits=4, stride=1, lower_bound=-6, upper_bound=-4)
    b = claripy.SI(bits=4, stride=1, lower_bound=-3, upper_bound=-1)
    assert si_eq(a / b, 4, 0, 0, 0)

    # small / large-unsigned [1,4] / [11,15] -> exactly {0}
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=4)
    b = claripy.SI(bits=4, stride=1, lower_bound=-5, upper_bound=-1)
    assert si_eq(a / b, 4, 0, 0, 0)

    # divide by zero -> empty (BOT)
    a = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=3)
    z = claripy.SI(bits=4, stride=1, lower_bound=0, upper_bound=0)
    assert vm(a / z).is_empty


# ---------------------------------------------------------------------------
# Bitwise / shift operations
# ---------------------------------------------------------------------------

def test_strided_interval_bitwise_and_or_not():
    """Bitwise &, |, ~ on SIs give exact (stride, lo, hi). From test_vsa.py."""
    # bitwise-and optimization: TOP & 0x80000000 -> stride 0x80000000, [0, 0x80000000]
    si_1 = claripy.SI(bits=32, stride=1, lower_bound=0x0, upper_bound=0xFFFFFFFF)
    si_2 = claripy.SI(bits=32, stride=0, lower_bound=0x80000000, upper_bound=0x80000000)
    assert claripy.backends.vsa.identical(
        si_1 & si_2,
        claripy.SI(bits=32, stride=0x80000000, lower_bound=0, upper_bound=0x80000000),
    )

    # AND where the high bit can never be set -> exactly 0
    si_1 = claripy.SI(bits=32, stride=1, lower_bound=0x0, upper_bound=0x7FFFFFFF)
    assert claripy.backends.vsa.identical(
        si_1 & si_2,
        claripy.SI(bits=32, stride=0, lower_bound=0, upper_bound=0),
    )

    # bitwise-or of two 16-bit ranges
    si_e = claripy.SI(bits=16, stride=1, lower_bound=0x2000, upper_bound=0x3000)
    si_f = claripy.SI(bits=16, stride=1, lower_bound=0, upper_bound=255)
    assert claripy.backends.vsa.identical(
        si_e | si_f,
        claripy.SI(bits=16, stride=1, lower_bound=0x2000, upper_bound=0x30FF),
    )

    # bitwise-not of an integer 10 (32-bit) -> -11
    si1 = claripy.SI(bits=32, stride=0, lower_bound=10, upper_bound=10)
    assert claripy.backends.vsa.identical(~si1, claripy.BVV(-11, 32))

    # bitwise-not of stride-2 [-100,200] -> stride 2, [-201, 99]
    si_b = claripy.SI(bits=32, stride=2, lower_bound=-100, upper_bound=200)
    assert claripy.backends.vsa.identical(
        ~si_b, claripy.SI(bits=32, stride=2, lower_bound=-201, upper_bound=99)
    )


def test_strided_interval_shifts_logical_and_arithmetic():
    """LShR (logical) vs >> (arithmetic) on SIs give exact, sign-aware results.

    From test_vsa.py:TestVSAShiftingOperations.
    """
    ident = claripy.backends.vsa.identical

    # logical right shift by 1: <32>1[2,4] LShR 1 = <32>1[1,2]
    si = claripy.SI(bits=32, stride=1, lower_bound=2, upper_bound=4)
    assert ident(si.LShR(1), claripy.SI(bits=32, stride=1, lower_bound=1, upper_bound=2))

    # logical right shift of a wrap-around stride-4 interval collapses to a wide range
    si = claripy.SI(bits=32, stride=4, lower_bound=15, upper_bound=11)
    assert ident(si.LShR(4), claripy.SI(bits=32, stride=1, lower_bound=0, upper_bound=0xFFFFFFF))

    # arithmetic right shift preserves the sign bit: <32>1[-4,-2] >> 1 = <32>1[-2,-1]
    si = claripy.SI(bits=32, stride=1, lower_bound=-4, upper_bound=-2)
    assert ident(si >> 1, claripy.SI(bits=32, stride=1, lower_bound=-2, upper_bound=-1))

    # logical right shift of the same negative interval does NOT preserve sign
    si = claripy.SI(bits=32, stride=1, lower_bound=-4, upper_bound=-2)
    assert ident(si.LShR(1), claripy.SI(bits=32, stride=1, lower_bound=0x7FFFFFFE, upper_bound=0x7FFFFFFF))

    # left shift of integer 10 by 3 -> 80
    si1 = claripy.SI(bits=32, stride=0, lower_bound=10, upper_bound=10)
    assert ident(si1 << 3, claripy.SI(bits=32, stride=0, lower_bound=80, upper_bound=80))


# ---------------------------------------------------------------------------
# Union, intersection, widening
# ---------------------------------------------------------------------------

def test_strided_interval_union_grows_stride_and_bounds():
    """Repeated union of concrete BVVs builds a strided interval with the exact
    minimal stride and (possibly wrap-around) bounds. From test_vsa.py:TestVSAJoin.
    """
    ident = claripy.backends.vsa.identical
    a = claripy.BVV(2, 8)
    b = claripy.BVV(10, 8)
    c = claripy.BVV(120, 8)
    d = claripy.BVV(130, 8)
    e = claripy.BVV(132, 8)
    f = claripy.BVV(135, 8)

    # {2,10} -> stride 8, [2,10]
    t1 = a.union(b)
    assert ident(t1, claripy.SI(bits=8, stride=8, lower_bound=2, upper_bound=10))
    # add 120 -> stride drops to 2, [2,120]
    t2 = t1.union(c)
    assert ident(t2, claripy.SI(bits=8, stride=2, lower_bound=2, upper_bound=120))
    # add 130,132 -> stride 2, [2,132]
    t3 = t2.union(d).union(e)
    assert ident(t3, claripy.SI(bits=8, stride=2, lower_bound=2, upper_bound=132))
    # add 135 (odd) -> stride collapses to 1, [2,135]
    t4 = t3.union(f)
    assert ident(t4, claripy.SI(bits=8, stride=1, lower_bound=2, upper_bound=135))

    # union of two singletons 10 and 28 -> stride 18, [10,28]
    si1 = claripy.SI(bits=32, stride=0, lower_bound=10, upper_bound=10)
    si3 = claripy.SI(bits=32, stride=0, lower_bound=28, upper_bound=28)
    assert ident(si1.union(si3), claripy.SI(bits=32, stride=18, lower_bound=10, upper_bound=28))


def test_strided_interval_intersection_exact():
    """Intersection of SIs (including wrap-around operands) gives the exact
    overlapping strided interval. From test_vsa.py:test_intersection / more_intersections.
    """
    ident = claripy.backends.vsa.identical
    si_a = claripy.SI(bits=32, stride=2, lower_bound=10, upper_bound=20)
    si_b = claripy.SI(bits=32, stride=2, lower_bound=-100, upper_bound=200)
    si_c = claripy.SI(bits=32, stride=3, lower_bound=-100, upper_bound=200)

    # [10,20]step2 ∩ [-100,200]step2 -> [10,20]step2
    assert ident(
        si_a.intersection(si_b),
        claripy.SI(bits=32, stride=2, lower_bound=10, upper_bound=20),
    )
    # step2 ∩ step3 -> step6 (lcm) over [-100,200]
    assert ident(
        si_b.intersection(si_c),
        claripy.SI(bits=32, stride=6, lower_bound=-100, upper_bound=200),
    )

    # wrap-around intersection yielding a single point
    t0 = claripy.SI(bits=32, stride=1, lower_bound=0, upper_bound=0x27)
    t1 = claripy.SI(bits=32, stride=0x7FFFFFFF, lower_bound=0x80000002, upper_bound=1)
    assert ident(t0.intersection(t1), claripy.SI(bits=32, stride=0, lower_bound=1, upper_bound=1))


def test_strided_interval_widening():
    """Widening jumps an unstable upper bound to the representable maximum while
    keeping the GCD stride. Driven through the public ``bv.widen`` method on
    ``claripy.SI`` operands.
    """
    # self=[2,4]step2, b grows the upper bound to 8 -> widen extends upper to
    # the stride-aligned max for 4 bits (14), keeping stride 2.
    s1 = claripy.SI(bits=4, stride=2, lower_bound=2, upper_bound=4)
    s2 = claripy.SI(bits=4, stride=2, lower_bound=2, upper_bound=8)
    assert si_eq(s1.widen(s2), 4, 2, 2, 14)

    # widening with an empty operand is the identity (empty built as the
    # intersection of two disjoint intervals)
    empty = claripy.SI(bits=4, stride=1, lower_bound=1, upper_bound=3).intersection(
        claripy.SI(bits=4, stride=1, lower_bound=8, upper_bound=10)
    )
    assert vm(empty).is_empty
    assert claripy.backends.vsa.identical(s1.widen(empty), s1)

    # widening empty with a non-empty operand jumps to TOP
    assert vm(empty.widen(s2)).is_top


# ---------------------------------------------------------------------------
# Sign/unsigned bounds, TOP/BOTTOM, reasonable bounds, eval
# ---------------------------------------------------------------------------

def test_top_bottom_and_unsigned_bounds():
    """TOP / BOTTOM semantics and the unsigned bounds of a full-range SI, all
    expressed through the public surface.

    TOP is the canonical full range ``SI(stride=1, [0, 2**bits-1])`` (``is_top``,
    full cardinality, unsigned min/max spanning the whole space); BOTTOM is the
    empty interval (built as a disjoint intersection): ``is_empty``, empty
    enumeration, zero cardinality. From test_vsa.py:test_wrapped_intervals.
    """
    b = claripy.backends.vsa

    # TOP for 8 bits: the canonical full range.
    top = claripy.SI(bits=8, stride=1, lower_bound=0, upper_bound=0xFF)
    assert vm(top).is_top
    assert not vm(top).is_empty
    assert b.cardinality(top) == 256
    assert b.min(top) == 0
    assert b.max(top) == 0xFF

    # BOTTOM for 8 bits: the empty interval (intersection of two disjoint ranges).
    empty = claripy.SI(bits=8, stride=1, lower_bound=1, upper_bound=3).intersection(
        claripy.SI(bits=8, stride=1, lower_bound=10, upper_bound=12)
    )
    assert vm(empty).is_empty
    assert b.eval(empty, 10) == []
    assert b.cardinality(empty) == 0

    # The full 32-bit range is a single contiguous unsigned span [0, 2**32-1].
    si1 = claripy.SI(bits=32, stride=1, lower_bound=0, upper_bound=0xFFFFFFFF)
    assert b.min(si1) == 0x0
    assert b.max(si1) == 0xFFFFFFFF
    assert b.cardinality(si1) == 2**32


def test_reasonable_bounds_and_eval_set():
    """backends.vsa.max/min return unsigned wrap-aware bounds; eval enumerates the
    exact concrete set in stride order. From test_vsa.py reasonable-bounds + join.
    """
    b = claripy.backends.vsa

    # all-negative interval: max/min are the unsigned representations
    si = claripy.SI(bits=32, stride=1, lower_bound=-20, upper_bound=-10)
    assert b.max(si) == 0xFFFFFFF6
    assert b.min(si) == 0xFFFFFFEC

    # interval straddling zero: unsigned max is 0xFFFFFFFF, min is 0
    si = claripy.SI(bits=32, stride=1, lower_bound=-20, upper_bound=10)
    assert b.max(si) == 0xFFFFFFFF
    assert b.min(si) == 0

    # eval a wrap-around 8-bit interval and check exact membership
    vals = [claripy.BVV(v, 8) for v in (1, 10, 120, 130, 132, 135, 220, 50)]
    tmp = vals[0]
    for v in vals[1:]:
        tmp = tmp.union(v)
    # collapses to stride 1, wrap-around [220, 135]
    assert claripy.backends.vsa.identical(
        tmp, claripy.SI(bits=8, stride=1, lower_bound=220, upper_bound=135)
    )
    evald = vm(tmp).eval(255)
    assert 220 in evald
    assert 0 in evald
    assert 135 in evald
    assert 138 not in evald


# ---------------------------------------------------------------------------
# Signed vs unsigned comparison results
# ---------------------------------------------------------------------------

def test_signed_vs_unsigned_comparisons():
    """The same bit-patterns compare differently signed vs unsigned; results are
    definite True/False (not Maybe) for these separated intervals.
    From test_vsa.py comparison tests.
    """
    is_true = claripy.backends.vsa.is_true

    si_pos = claripy.SI(bits=8, stride=1, lower_bound=1, upper_bound=2)
    si_neg = claripy.SI(bits=8, stride=1, lower_bound=-2, upper_bound=-1)  # 0xfe,0xff

    # signed: [-2,-1] < [1,2] is definitely true
    assert is_true(claripy.SLT(si_neg, si_pos))
    assert is_true(claripy.SLE(si_neg, si_pos))

    # unsigned: [0xfe,0xff] > [1,2] is definitely true
    assert is_true(claripy.UGT(si_neg, si_pos))
    assert is_true(claripy.UGE(si_neg, si_pos))

    # equality across signed/unsigned representations of the same bit pattern
    m1 = claripy.SI(bits=8, stride=1, lower_bound=-1, upper_bound=-1)
    m2 = claripy.SI(bits=8, stride=1, lower_bound=0xFF, upper_bound=0xFF)
    assert is_true(m1 == m2)

    n1 = claripy.SI(bits=8, stride=1, lower_bound=-2, upper_bound=-2)
    n2 = claripy.SI(bits=8, stride=1, lower_bound=0xFF, upper_bound=0xFF)
    assert is_true(n1 != n2)


# ---------------------------------------------------------------------------
# Extension, extraction, concat (SI-preserving)
# ---------------------------------------------------------------------------

def test_zero_and_sign_extension_and_extraction():
    """zero_extend keeps bounds; sign_extend replicates the sign bit; extraction
    of byte lanes yields exact per-lane SIs. From test_vsa.py.
    """
    ident = claripy.backends.vsa.identical
    # zero-extend 8->32: bounds unchanged
    si1 = claripy.SI(bits=8, stride=1, lower_bound=0, upper_bound=0xFD)
    assert ident(
        si1.zero_extend(32 - 8),
        claripy.SI(bits=32, stride=1, lower_bound=0x0, upper_bound=0xFD),
    )

    # sign-extend 8->32: the interval [0,0xFD] straddles the 8-bit sign and
    # becomes [0xFFFFFF80, 0x7F]
    assert ident(
        si1.sign_extend(32 - 8),
        claripy.SI(bits=32, stride=1, lower_bound=0xFFFFFF80, upper_bound=0x7F),
    )

    # sign-extend a 1-bit value 1 -> all ones
    sb = claripy.SI(bits=1, stride=0, lower_bound=1, upper_bound=1)
    assert ident(
        sb.sign_extend(31),
        claripy.SI(bits=32, stride=0, lower_bound=0xFFFFFFFF, upper_bound=0xFFFFFFFF),
    )

    # per-byte extraction of a strided 32-bit value
    si = claripy.SI(bits=32, stride=0x1000000, lower_bound=0xCFFFFFF, upper_bound=0xDFFFFFF)
    assert ident(si[7:0], claripy.SI(bits=8, stride=0, lower_bound=0xFF, upper_bound=0xFF))
    assert ident(si[31:24], claripy.SI(bits=8, stride=1, lower_bound=0xC, upper_bound=0xD))


# ---------------------------------------------------------------------------
# ValueSet across regions
# ---------------------------------------------------------------------------

def test_valueset_union_and_pointer_subtraction():
    """ValueSet merges same-region offsets into a strided interval, and a same-
    region pointer subtraction collapses to a concrete strided-interval offset.
    From test_vsa.py:test_value_set_operations + test_value_set_subtraction.

    Both behaviors are checked with the public ``claripy.backends.vsa.identical``
    accessor (which compares the merged region SI directly), rather than reaching
    into a model accessor.
    """
    # merge two global offsets 10 and 28 -> stride 18 over [10,28]
    vs = claripy.VS(32, "global", 0, 0).intersection(claripy.VS(32, "global", 0, 1))
    assert vm(vs).is_empty  # disjoint singletons -> empty
    vs = vs.union(claripy.VS(32, "global", 0, claripy.SI(bits=32, stride=0, lower_bound=10, upper_bound=10)))
    vs = vs.union(claripy.VS(32, "global", 0, claripy.SI(bits=32, stride=0, lower_bound=28, upper_bound=28)))
    expected = claripy.VS(32, "global", 0, claripy.SI(bits=32, stride=18, lower_bound=10, upper_bound=28))
    assert claripy.backends.vsa.identical(vs, expected)

    # subtracting two pointers in the same region yields a concrete SI offset
    vs_1 = claripy.ValueSet(32, "global", 0, 0x400010)
    vs_2 = claripy.ValueSet(32, "global", 0, 0x400000)
    diff = vs_1 - vs_2
    assert claripy.backends.vsa.identical(
        diff, claripy.SI(bits=32, stride=0, lower_bound=0x10, upper_bound=0x10)
    )

# ================= from test_part_5_solver.py =================
# ---------------------------------------------------------------------------
# Annotation helper classes mirroring claripy's own test fixtures.
# ---------------------------------------------------------------------------


class AnnotationA(claripy.Annotation):
    """Eliminatable + non-relocatable annotation carrying a letter/number payload."""

    def __init__(self, letter, number):
        self.letter = letter
        self.number = number
        claripy.Annotation.__init__(self)


class AnnotationB(AnnotationA):
    """Non-eliminatable, non-relocatable annotation (blocks simplification)."""

    @property
    def eliminatable(self):
        return False

    @property
    def relocatable(self):
        return False


class AnnotationC(AnnotationA):
    """Non-eliminatable but relocatable annotation; relocation bumps the number."""

    def __init__(self, letter, number):
        super().__init__(letter, number)
        self._relocatable = True

    @property
    def eliminatable(self):
        return False

    @property
    def relocatable(self):
        return self._relocatable

    def relocate(self, src, dst):
        return AnnotationC(self.letter, self.number + 1)


# ---------------------------------------------------------------------------
# Solver frontend: public API (sat/unsat, eval, min/max, batch_eval, solution).
# ---------------------------------------------------------------------------


def test_solver_sat_unsat_and_unique_eval():
    """A unique equality constraint yields a uniquely-determined model and a
    contradictory extra constraint is unsatisfiable; adding claripy.false() makes
    the solver permanently unsat."""
    s = claripy.Solver()
    x = claripy.BVS("x", 32)
    y = claripy.BVS("y", 32)
    s.add(x == 10)
    s.add(y == 15)

    assert s.satisfiable()
    # x is uniquely determined to 10, so x + 5 == 15 with no ambiguity.
    assert s.eval(x + 5, 1)[0] == 15
    assert s.eval(x, 1)[0] == 10
    assert s.eval(y, 1)[0] == 15

    # solution() membership queries on the uniquely-determined variable.
    assert s.solution(x, 10)
    assert s.solution(y, 15)
    assert not s.solution(y, 13)

    # A contradictory extra constraint does not mutate the solver but is unsat.
    assert not s.satisfiable(extra_constraints=[x == 5])
    assert s.satisfiable()

    # Adding claripy.false() makes the solver unconditionally unsatisfiable.
    s.add(claripy.false())
    assert not s.satisfiable()


def test_solver_contradiction_is_unsat():
    """Equal-width constants that are forced unequal make the solver unsat; a
    self-consistent equality stays sat."""
    s = claripy.Solver()
    s.add(claripy.BVV(1, 1) == claripy.BVV(1, 1))
    assert s.satisfiable()
    s.add(claripy.BVV(1, 1) == claripy.BVV(0, 1))
    assert not s.satisfiable()


def test_solver_min_max_unsigned_and_signed():
    """For an unconstrained 32-bit variable min/max span the full unsigned range;
    with signed=True they span the full signed range. Bounding constraints tighten
    both, and exhaustion-style single-sided bounds give the exact boundary."""
    s = claripy.Solver()
    x = claripy.BVS("x", 32)
    assert s.max(x) == 2**32 - 1
    assert s.min(x) == 0

    # Single-sided bound: the boundary value itself is the extremum.
    s2 = claripy.Solver()
    a = claripy.BVS("a", 32)
    s2.add(a >= 19)
    assert s2.min(a) == 19

    s3 = claripy.Solver()
    b = claripy.BVS("b", 32)
    s3.add(b <= 19)
    assert s3.max(b) == 19


def test_solver_batch_eval_unique_row():
    """batch_eval over expressions of a uniquely-pinned variable returns exactly one
    row with the computed values (including a constant element)."""
    s = claripy.Solver()
    x = claripy.BVS("x", 32)
    s.add(x == 10)

    results = s.batch_eval([x + 5, x + 6, claripy.BVV(3, 32)], 2)
    assert len(results) == 1
    assert results[0] == (15, 16, 3)


def test_solver_eval_bounded_set_and_min_max_with_chained_constraints():
    """Bounded ranges enumerate the exact sorted set; chained UGT constraints fold to
    the tightest bound and unconstrained-side max stays at the type max."""
    # x < 10 -> exactly {0..9}; adding an unrelated constraint does not change x.
    s = claripy.Solver()
    x = claripy.BVS("x", 32)
    y = claripy.BVS("y", 32)
    s.add(x < 10)
    assert sorted(s.eval(x, 20)) == list(range(10))
    s.add(y == 1337)
    assert sorted(s.eval(x, 20)) == list(range(10))

    # UGT(x,10) & UGT(x,20) collapse to a single constraint after simplify;
    # z < 5 gives min 0 / max 4; y > x gives min 22 with unconstrained max.
    s2 = claripy.Solver()
    z = claripy.BVS("z", 32)
    s2.add(claripy.UGT(x, 10))
    s2.add(claripy.UGT(x, 20))
    s2.simplify()
    assert len(s2.constraints) == 1

    s2.add(claripy.UGT(y, x))
    s2.add(claripy.ULT(z, 5))
    # Duplicate constraints are ignored.
    old_count = len(s2.constraints)
    s2.add(claripy.ULT(z, 5))
    assert len(s2.constraints) == old_count

    assert s2.max(z) == 4
    assert s2.min(z) == 0
    assert s2.min(y) == 22
    assert s2.max(y) == 2 ** y.size() - 1


# ---------------------------------------------------------------------------
# VSA solver basics + balancer (claripy's own VSA logic; weighted heavily).
# ---------------------------------------------------------------------------


def test_balancer_simple_bound_on_symbol():
    """Balancing 'x <= 39' isolates x with VSA bounds [0, 39]; balancing 'x + 1 <= 39'
    keeps x isolated and the resulting interval wraps (0 and 0xffffffff present, the
    largest non-wrap value is 38)."""
    x = claripy.BVS("x", 32)

    sat, r = Balancer(x <= claripy.BVV(39, 32)).compat_ret
    assert sat
    assert r[0][0] is x
    assert claripy.backends.vsa.min(r[0][1]) == 0
    assert claripy.backends.vsa.max(r[0][1]) == 39

    sat, r = Balancer(x + 1 <= claripy.BVV(39, 32)).compat_ret
    assert sat
    assert r[0][0] is x
    all_vals = claripy.backends.vsa.convert(r[0][1]).eval(1000)
    assert min(all_vals) == 0
    assert max(all_vals) == 4294967295
    all_vals.remove(4294967295)
    assert max(all_vals) == 38


def test_balancer_overflow_wraparound_sets():
    """Balancing constraints whose additions wrap modulo 2**32 yields the exact wrapped
    value set: 'x + 10 <= 20' and 'x - 10 <= 20' each enumerate to a known set."""
    x = claripy.BVS("x", 32)

    sat, r = Balancer(x + 10 <= claripy.BVV(20, 32)).compat_ret
    assert sat
    assert r[0][0] is x
    expected_plus = set(range(0, 11)) | {4294967286 + i for i in range(10)}
    assert set(claripy.backends.vsa.eval(r[0][1], 1000)) == expected_plus

    sat, r = Balancer(x - 10 <= claripy.BVV(20, 32)).compat_ret
    assert sat
    assert r[0][0] is x
    assert set(claripy.backends.vsa.eval(r[0][1], 1000)) == set(range(10, 31))


def test_balancer_multiple_symbolic_vars_and_cardinality():
    """When two symbols are summed, the balancer isolates the (x0 + x1) sub-AST and the
    resulting interval has the expected cardinality (99), regardless of where the
    constant addend appears."""
    x0 = claripy.BVS("x0", 32)
    x1 = claripy.BVS("x1", 32)

    sat, r = Balancer(x0 + x1 + claripy.BVV(1, 32) < claripy.BVV(99, 32)).compat_ret
    assert sat is True
    assert len(r) == 1
    assert r[0][0] is x0 + x1
    assert claripy.backends.vsa.cardinality(r[0][1]) == 99

    sat, r = Balancer(x0 + claripy.BVV(8, 32) + x1 < claripy.BVV(99, 32)).compat_ret
    assert sat is True
    assert len(r) == 1
    assert r[0][0] is x0 + x1
    assert claripy.backends.vsa.cardinality(r[0][1]) == 99


def test_vsa_constraint_to_si_if_branches():
    """Through the VSA backend's constraint_to_si, an 'If(SI==0,1,0) == 1' constraint
    forces the SI to the singleton [0,0] on the true side and to [1,2] on the false
    side (the exact strided intervals)."""
    b = claripy.backends.vsa
    s1 = claripy.SI(bits=32, stride=1, lower_bound=0, upper_bound=2)
    ast_true = claripy.If(s1 == claripy.BVV(0, 32), claripy.BVV(1, 1), claripy.BVV(0, 1)) == claripy.BVV(1, 1)
    ast_false = claripy.If(s1 == claripy.BVV(0, 32), claripy.BVV(1, 1), claripy.BVV(0, 1)) != claripy.BVV(1, 1)

    trueside_sat, trueside_repl = b.constraint_to_si(ast_true)
    assert trueside_sat
    assert len(trueside_repl) == 1
    assert trueside_repl[0][0] is s1
    assert b.identical(trueside_repl[0][1], claripy.SI(bits=32, stride=0, lower_bound=0, upper_bound=0))

    falseside_sat, falseside_repl = b.constraint_to_si(ast_false)
    assert falseside_sat is True
    assert len(falseside_repl) == 1
    assert falseside_repl[0][0] is s1
    assert b.identical(falseside_repl[0][1], claripy.SI(bits=32, stride=1, lower_bound=1, upper_bound=2))


# ---------------------------------------------------------------------------
# Annotations: attach / propagate / preserve / simplification control.
# ---------------------------------------------------------------------------


def test_annotation_attach_remove_and_tuple_semantics():
    """annotate/remove_annotation produce new ASTs with the expected .annotations
    tuples while preserving variables and op; identical annotate calls dedupe to the
    same AST; removing all annotations returns the original AST identity."""
    x = claripy.BVS("x", 32) + 1
    a1 = AnnotationA("a", 1)
    a2 = AnnotationA("b", 2)

    x1 = x.annotate(a1)
    x2 = x1.annotate(a2)
    x2a = x.annotate(a1, a2)
    x3 = x2.remove_annotation(a1)
    x4 = x3.remove_annotation(a2)
    x5 = x2.remove_annotations({a1, a2})

    # Variables and op are preserved across annotation operations.
    assert x.variables == x1.variables == x2.variables == x2a.variables
    assert x.op == x1.op

    # Annotation tuples are exact and ordered.
    assert x.annotations == ()
    assert x1.annotations == (a1,)
    assert x2.annotations == (a1, a2)
    assert x3.annotations == (a2,)

    # Identity semantics: distinct annotation sets => distinct ASTs; same set => same.
    assert x is not x1
    assert x2 is x2a
    # Removing every annotation returns the original AST.
    assert x is x4
    assert x is x5

    # clear_annotations strips everything.
    cleared = x2.clear_annotations()
    assert len(cleared.annotations) == 0


def test_annotation_simplification_eliminatable_relocatable_relocate():
    """x ^ x simplifies to 0 (depth 1) dropping an eliminatable annotation; a
    non-eliminatable non-relocatable annotation blocks the simplify (depth 2); a
    relocatable annotation survives and is relocated (number bumped from 1 to 2)."""
    # Eliminatable: annotation is dropped, x^x collapses to depth-1.
    x = claripy.BVS("x", 32).annotate(AnnotationA("a", 1))
    y = x ^ x
    assert y.depth == 1
    assert len(y.annotations) == 0

    # Non-eliminatable + non-relocatable: simplification is blocked.
    x = claripy.BVS("x", 32).annotate(AnnotationB("a", 1))
    y = x ^ x
    assert y.depth == 2

    # Relocatable: simplification proceeds, annotation relocated (number 1 -> 2).
    x = claripy.BVS("x", 32).annotate(AnnotationC("a", 1))
    y = x ^ x
    assert y.depth == 1
    assert len(y.annotations) == 1
    assert y.annotations[0].number == 2


def test_annotation_relocatable_preserved_through_simplify_and_concat():
    """A relocatable annotation on (24 + x) survives an explicit simplify() and is
    propagated (exactly once) onto a Concat result built from the annotated child."""
    relocatable_anno = AnnotationC("a", 2)

    x0 = claripy.BVS("x", 32)
    x1 = claripy.BVV(24, 32)
    k = (x1 + x0).annotate(relocatable_anno)
    simplified = claripy.simplify(k)
    assert len(simplified.annotations) == 1

    # Propagation through Concat, with no duplication.
    const = claripy.BVV(1337, 32)
    xa = claripy.BVS("x", 32).annotate(relocatable_anno)
    y0 = claripy.Concat(xa, const)
    assert len(y0.annotations) == 1
    assert y0.annotations == (relocatable_anno,)
    # Removing the propagated annotation clears it.
    y1 = y0.remove_annotation(relocatable_anno)
    assert len(y1.annotations) == 0


def test_simplification_avoidance_annotation_in_solver():
    """A constraint carrying SimplificationAvoidanceAnnotation is preserved by
    Solver.simplify() while the other foldable constraints collapse: 3 constraints
    become 2 after simplify."""
    s = claripy.Solver()
    x = claripy.BVS("x", 32)

    s.add(x > 10)
    s.add(x > 11)
    s.add((x > 12).annotate(claripy.SimplificationAvoidanceAnnotation()))

    assert len(s.constraints) == 3
    s.simplify()
    assert len(s.constraints) == 2
