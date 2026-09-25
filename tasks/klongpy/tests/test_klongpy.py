"""
Integration test suite for KlongPy -- the Python implementation of the Klong array language.

Tests exercise the public API (KlongInterpreter.__call__, __getitem__, __setitem__,
exec, and the kgpy CLI) rather than internal implementation details.
"""

import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixture: fresh interpreter per test
# ---------------------------------------------------------------------------


@pytest.fixture
def klong():
    from klongpy import KlongInterpreter

    return KlongInterpreter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arr(klong_result):
    """Normalise a Klong result to a plain list for comparison."""
    if isinstance(klong_result, np.ndarray):
        return klong_result.tolist()
    return klong_result


def _close(a, b, tol=1e-6):
    """Check two numeric values are close."""
    if isinstance(a, np.ndarray):
        a = a.tolist()
    if isinstance(b, np.ndarray):
        b = b.tolist()
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(float(a) - float(b)) < tol


# ===================================================================
# 1. ARITHMETIC AND EVALUATION ORDER
# ===================================================================


class TestArithmetic:
    """Arithmetic, evaluation order, and numeric edge cases."""

    def test_arithmetic_composite(self, klong):
        """Right-to-left evaluation, parentheses, power/negate/reciprocal, min/max."""
        # Right-to-left evaluation chains
        assert klong("5+3*2") == 11  # 3*2=6, 5+6
        assert klong("2*3+4") == 14  # 3+4=7, 2*7
        assert klong("10-2*3") == 4  # 2*3=6, 10-6
        assert klong("2^3+1") == 16  # 3+1=4, 2^4
        assert klong("100-10*2+3") == 50  # 2+3=5, 10*5=50, 100-50
        # Parenthesized nested
        assert klong("(5+3)*2") == 16
        assert klong("(2+3)*(4+1)") == 25
        assert klong("((2+3)*4)+1") == 21
        # Power type and negate/reciprocal
        result = klong("3^2")
        assert result == 9
        assert isinstance(result, (int, np.integer))
        assert _close(klong("2^-1"), 0.5)
        assert klong("-5") == -5
        assert _close(klong("%4"), 0.25)
        assert str(klong("%0")) == ":undefined"
        # Min/max vectorized
        assert klong("3|5") == 5
        assert klong("3&5") == 3
        assert _arr(klong("[1 5 3]|[2 4 6]")) == [2, 5, 6]
        assert _arr(klong("[1 5 3]&[2 4 6]")) == [1, 4, 3]

    def test_division_and_undefined(self, klong):
        """Division always float; div-by-zero -> :undefined; integer-divide truncates."""
        assert _close(klong("10%2"), 5.0)
        assert _close(klong("10%4"), 2.5)
        assert str(klong("1%0")) == ":undefined"
        assert klong("10:%3") == 3
        assert str(klong("1:%0")) == ":undefined"
        # Remainder
        assert klong("7!5") == 2
        r = klong("(-7)!5")
        assert r == -2


# ===================================================================
# 2. DATA TYPES
# ===================================================================


class TestDataTypes:
    """Strings, characters, symbols, arrays, dicts."""

    def test_data_types_composite(self, klong):
        """Strings, characters, symbols, arrays, evaluated arrays."""
        # String operations basics
        assert klong('"hello"') == "hello"
        result = klong('"say ""hi"""')
        assert result == 'say "hi"'
        assert klong('""') == ""
        # Character literal
        c = klong("0cx")
        assert str(c) == "x"
        assert klong("#0cA") == 65
        # Symbol
        result = klong(":foo")
        assert str(result) == "foo"
        result = klong(":{[foo bar]}?:foo")
        assert str(result) == "bar"
        # Array and nested
        assert _arr(klong("[1 2 3]")) == [1, 2, 3]
        assert _arr(klong("[]")) == []
        result = klong("[[1 2] [3 4]]")
        assert _arr(result[0]) == [1, 2]
        assert _arr(result[1]) == [3, 4]
        # Evaluated array
        klong("a::10")
        klong("b::20")
        result = _arr(klong("[;a;b;a+b]"))
        assert result == [10, 20, 30]
        klong("sq::{x^2}")
        result = _arr(klong("[;sq(3);sq(4)]"))
        assert result == [9, 16]

    def test_dictionary_creation(self, klong):
        """Create a dict, then query existing and missing keys."""
        result = klong(':{[1 "one"] [2 "two"]}')
        assert isinstance(result, dict)
        assert result[1] == "one"
        assert result[2] == "two"
        # Query existing key and missing key (-> :undefined)
        assert klong(':{[1 "one"] [2 "two"]}?2') == "two"
        assert str(klong(':{[1 "one"]}?99')) == ":undefined"


# ===================================================================
# 3. CORE LANGUAGE: VARIABLES, FUNCTIONS, SCOPING, CONDITIONALS
# ===================================================================


class TestCoreLang:
    """Variables, functions, conditionals, scoping -- composite tests."""

    def test_variables_scoping_and_interop(self, klong):
        """Variable define, local scope isolation, Python interop."""
        klong("x::42")
        assert klong("x") == 42
        klong("x::99")
        assert klong("x") == 99
        results = klong.exec("a::10;b::20;a+b")
        assert results[-1] == 30
        # Local variables don't leak
        klong("a::2")
        klong("fv::{[a];a::1;a}")
        assert klong("fv()") == 1
        assert klong("a") == 2
        # Python interop
        klong["pvar"] = 123
        assert klong("pvar") == 123
        del klong["pvar"]
        with pytest.raises(Exception):
            klong["pvar"]

    def test_functions_and_scope_composite(self, klong):
        """Monad/dyad/triad/nilad, locals, anonymous recursion, nested scope, higher-order."""
        # Functions all arities and locals
        klong("f::{x+1}")
        assert klong("f(5)") == 6
        klong("g::{x+y}")
        assert klong("g(3;4)") == 7
        klong("h::{x+y+z}")
        assert klong("h(1;2;3)") == 6
        klong("n::{42}")
        assert klong("n()") == 42
        klong("wl::{[a];a::x*2;a+1}")
        assert klong("wl(5)") == 11
        # Anonymous recursion and nested scope
        result = klong("{:[x<2;x;.f(x-1)+.f(x-2)]}(10)")
        assert result == 55
        klong("f::{x*x}")
        klong("g::{f(x)+1}")
        assert klong("g(3)") == 10
        klong("outer::10")
        klong("h::{outer+x}")
        assert klong("h(5)") == 15
        # Higher order and callable
        klong("fn::{x+10}")
        klong("foo::{x(2)}")
        assert klong("foo(fn)") == 12
        klong["pyfn"] = lambda x: x * 10
        assert klong("pyfn(5)") == 50
        # Nested x scope: inner function receives different x
        klong("G::{x}")
        klong("F::{G(4_x)}")
        assert klong('F("hello")') == "o"

    def test_conditionals_chained(self, klong):
        """Basic, falsy values, chained, in functions."""
        assert klong(":[1;10;20]") == 10
        assert klong(":[0;10;20]") == 20
        assert klong(':["";10;20]') == 20
        assert klong(":[[];10;20]") == 20
        assert klong(":[0;1:|0;2;3]") == 3
        assert klong(":[0;1:|1;2;3]") == 2
        klong("abs::{:[x<0;-x;x]}")
        assert klong("abs(-5)") == 5

    def test_variable_mutation_across_calls(self, klong):
        """Mutation of outer variable via function calls accumulates."""
        klong("counter::0")
        klong("inc::{counter::counter+1;counter}")
        assert klong("inc()") == 1
        assert klong("inc()") == 2
        assert klong("inc()") == 3
        assert klong("counter") == 3


# ===================================================================
# 6. MONADIC OPERATORS
# ===================================================================


class TestMonads:
    """Monadic (unary, prefix) operators."""

    def test_monads_basic_composite(self, klong):
        """Atom, enumerate, size, first, reverse, floor."""
        # Atom
        assert klong("@42") == 1
        assert klong("@[1 2 3]") == 0
        assert klong("@[]") == 1
        assert klong('@""') == 1
        assert klong('@"hello"') == 0
        assert klong("@:foo") == 1
        assert klong("@:{[1 2]}") == 1
        # Enumerate
        assert _arr(klong("!5")) == [0, 1, 2, 3, 4]
        assert _arr(klong("!0")) == []
        # Size
        assert klong("#[1 2 3 4 5]") == 5
        assert klong('#"hello"') == 5
        assert klong("#-42") == 42
        assert klong("#0cA") == 65
        assert klong("#:{}") == 0
        assert klong("#:{[1 2]}") == 1
        # First
        assert klong("*[10 20 30]") == 10
        result = klong('*"abc"')
        assert str(result) == "a"
        assert klong("*42") == 42
        # Reverse
        assert _arr(klong("|[1 2 3]")) == [3, 2, 1]
        assert klong('|"hello"') == "olleh"
        # Floor
        assert klong("_3.7") == 3
        assert klong("_-1.5") == -2

    def test_monads_advanced_composite(self, klong):
        """Transpose, unique, expand/where, char-from-code, group."""
        # Transpose
        klong("m::[[1 2 3] [4 5 6]]")
        result = klong("+m")
        assert _arr(result[0]) == [1, 4]
        assert _arr(result[1]) == [2, 5]
        assert _arr(result[2]) == [3, 6]
        # Unique
        assert _arr(klong("?[1 2 1 3 2]")) == [1, 2, 3]
        assert klong('?"aabbc"') == "abc"
        # Expand/where
        assert _arr(klong("&[1 2 3]")) == [0, 1, 1, 2, 2, 2]
        assert _arr(klong("&[0 1 0 1 0]")) == [1, 3]
        # Char from code
        result = klong(":#65")
        assert str(result) == "A"
        # Group
        result = klong("=[1 2 1 3]")
        groups = [_arr(g) for g in result]
        assert [0, 2] in groups
        assert [1] in groups
        assert [3] in groups

    def test_not(self, klong):
        assert klong("~0") == 1
        assert klong("~1") == 0
        assert klong("~[]") == 1

    def test_format(self, klong):
        assert klong("$123") == "123"
        assert klong("$:foo") == ":foo"
        assert klong("$0cx") == "x"
        assert klong("$3.14") == "3.14"

    def test_grade_up_down(self, klong):
        assert _arr(klong("<[3 1 2]")) == [1, 2, 0]
        assert _arr(klong(">[3 1 2]")) == [0, 2, 1]
        assert _arr(klong('<"foobar"')) == [4, 3, 0, 1, 2, 5]
        assert _arr(klong('>"foobar"')) == [5, 2, 1, 0, 3, 4]

    def test_shape(self, klong):
        assert klong("^1") == 0
        assert _arr(klong("^[1 2 3]")) == [3]
        assert _arr(klong("^[[1 2] [3 4] [5 6]]")) == [3, 2]
        assert _arr(klong('^"hello"')) == [5]

    def test_undefined_check(self, klong):
        assert klong(":_1%0") == 1
        assert klong(":_42") == 0

    def test_list_wrap(self, klong):
        result = klong(",42")
        assert _arr(result) == [42]
        result = klong(",0cx")
        assert result == "x"


# ===================================================================
# 7. DYADIC OPERATORS
# ===================================================================


class TestDyads:
    """Dyadic (binary, infix) operators."""

    def test_dyads_basic_composite(self, klong):
        """Join, take, drop, at-index/apply."""
        # Join all types
        assert _arr(klong("[1 2],[3 4]")) == [1, 2, 3, 4]
        assert klong('"abc","def"') == "abcdef"
        assert _arr(klong("1,[2 3]")) == [1, 2, 3]
        assert _arr(klong("1,2")) == [1, 2]
        assert klong('0ca,"bc"') == "abc"
        # Take
        assert _arr(klong("2#[1 2 3 4 5]")) == [1, 2]
        assert _arr(klong("(-2)#[1 2 3 4 5]")) == [4, 5]
        assert _arr(klong("5#[1 2 3]")) == [1, 2, 3, 1, 2]
        assert klong('3#"abcdef"') == "abc"
        assert _arr(klong("0#[1 2 3]")) == []
        # Drop
        assert _arr(klong("2_[1 2 3 4 5]")) == [3, 4, 5]
        assert _arr(klong("(-2)_[1 2 3 4 5]")) == [1, 2, 3]
        assert _arr(klong("10_[1 2 3]")) == []
        # At index and apply
        assert klong("[10 20 30]@1") == 20
        assert _arr(klong("[10 20 30 40]@[0 2]")) == [10, 30]
        assert klong("{x*x}@5") == 25

    def test_dyads_structural_composite(self, klong):
        """Equal/match, less/more, split, cut, amend, index-in-depth, amend-in-depth, form, deep-index-chain, cut-with-positions."""
        # Equal and match
        assert _arr(klong("[1 2 3]=[1 0 3]")) == [1, 0, 1]
        assert klong("[1 2 3]~[1 2 3]") == 1
        assert klong("[1 2 3]~[1 2 4]") == 0
        # Less/more
        assert klong("1<2") == 1
        assert klong("2<1") == 0
        assert klong("5>3") == 1
        assert _arr(klong("[1 5 3]<[2 4 6]")) == [1, 0, 1]
        # Split
        result = klong("2:#[1 2 3 4]")
        assert _arr(result[0]) == [1, 2]
        assert _arr(result[1]) == [3, 4]
        # Cut
        result = klong("2:_[1 2 3 4]")
        assert _arr(result[0]) == [1, 2]
        assert _arr(result[1]) == [3, 4]
        # Amend
        result = klong("[1 2 3]:=0,1")
        assert _arr(result) == [1, 0, 3]
        # Index in depth
        assert klong("[[1 2] [3 4]]:@[0 1]") == 2
        # Amend in depth
        result = klong("[[1 2] [3 4]]:-42,[0 1]")
        assert _arr(result[0]) == [1, 42]
        # Form
        assert klong('1:$"42"') == 42
        result = klong('1.0:$"3.14"')
        assert _close(result, 3.14)
        assert klong('1:$"-99"') == -99
        # Deep index chain
        klong("m::[[10 20 30] [40 50 60] [70 80 90]]")
        assert klong("m:@[1 2]") == 60
        assert klong("m:@[0 0]") == 10
        assert klong("m:@[2 1]") == 80
        # Cut with positions
        result = klong("[1 3]:_[10 20 30 40 50]")
        assert _arr(result[0]) == [10]
        assert _arr(result[1]) == [20, 30]
        assert _arr(result[2]) == [40, 50]

    def test_at_string(self, klong):
        assert klong('"hello"@[0 4 1]') == "hoe"
        assert klong('"hello world"@[3 7 2]') == "lol"
        # Single index returns char type
        r = klong('"hello"@0')
        assert str(r) == "h"

    def test_find(self, klong):
        """Find returns list of all matching positions."""
        assert _arr(klong("[1 2 3 1 2 1]?1")) == [0, 3, 5]
        result = _arr(klong('"hello"?0cl'))
        assert result == [2, 3]
        result = klong(":{[1 10] [2 20]}?1")
        assert result == 10
        result = klong(":{[1 10]}?99")
        assert str(result) == ":undefined"

    def test_reshape(self, klong):
        result = klong("[2 3]:^!6")
        assert _arr(result[0]) == [0, 1, 2]
        assert _arr(result[1]) == [3, 4, 5]
        result = klong("5:^1")
        assert _arr(result) == [1, 1, 1, 1, 1]
        assert _arr(klong("0:^[1 2 3]")) == [1, 2, 3]
        result = klong("[-1 2]:^!10")
        assert len(result) == 5
        assert _arr(result[0]) == [0, 1]
        # Multi-axis shape with a source too small for it: the source is tiled
        result = klong("[2 3]:^1")
        assert _arr(result[0]) == [1, 1, 1]
        assert _arr(result[1]) == [1, 1, 1]
        result = klong("[2 3]:^[1 2]")
        assert _arr(result[0]) == [1, 2, 1]
        assert _arr(result[1]) == [2, 1, 2]

    def test_rotate(self, klong):
        assert _arr(klong("1:+[1 2 3 4 5]")) == [5, 1, 2, 3, 4]
        assert _arr(klong("(-1):+[1 2 3 4 5]")) == [2, 3, 4, 5, 1]
        assert klong('2:+"abcde"') == "deabc"

    def test_format2_width_and_precision(self, klong):
        """Format with padding, right-align, and float precision."""
        result = klong('5$"hi"')
        assert result == "hi   "
        result = klong('(-5)$"hi"')
        assert result == "   hi"
        result = klong("5.3$123.45")
        assert "123.450" in result
        # Right-align numbers
        result = klong('8$"test"')
        assert len(result) == 8
        assert result == "test    "
        result = klong('(-8)$"test"')
        assert len(result) == 8
        assert result == "    test"
        # Float precision
        result = klong("8.2$42.0")
        assert "42.00" in result
        result = klong("10.2$3.14159")
        assert "3.14" in result

    def test_dict_operations(self, klong):
        """Dict drop (remove key), merge (add pair), and entry count."""
        result = klong("1_:{[1 10] [2 20]}")
        assert isinstance(result, dict)
        assert 1 not in result
        result = klong(":{[1 10]},[3 30]")
        assert isinstance(result, dict)
        assert result[1] == 10
        assert result[3] == 30
        # Entry count
        assert klong("#:{[1 10] [2 20] [3 30]}") == 3

    def test_string_amend_multi(self, klong):
        """String amend with multi-char replacement and string growth."""
        assert klong('"-----":=0cx,[1 3]') == "-x-x-"
        assert klong('"-------":="xx",[1 4]') == "-xx-xx-"
        assert klong('"abc":="def",3') == "abcdef"


# ===================================================================
# 8. ADVERBS
# ===================================================================


class TestAdverbs:
    """Adverb modifiers (each, over, scan, etc.)."""

    def test_adverbs_basic_composite(self, klong):
        """Each monadic/dyadic, over, over-neutral, scan, scan-min/max, each-index, each-on-dict."""
        # Each monadic
        klong("f::{x*x}")
        assert _arr(klong("f'[1 2 3 4]")) == [1, 4, 9, 16]
        assert _arr(klong("-'[1 2 3]")) == [-1, -2, -3]
        # Each dyadic
        assert _arr(klong("[1 2 3]+'[10 20 30]")) == [11, 22, 33]
        # Over
        assert klong("+/[1 2 3 4]") == 10
        assert klong("*/[1 2 3 4]") == 24
        assert klong("|/[3 1 4 1 5 9]") == 9
        assert klong("&/[3 1 4 1 5 9]") == 1
        # Over neutral
        assert klong("0+/[1 2 3]") == 6
        assert klong("0+/[]") == 0
        assert klong("1*/[]") == 1
        assert klong("100+/[1 2 3]") == 106
        # Scan
        assert _arr(klong("+\\[1 2 3 4]")) == [1, 3, 6, 10]
        assert _arr(klong("*\\[1 2 3 4]")) == [1, 2, 6, 24]
        # Scan min/max
        assert _arr(klong("|\\[3 1 4 1 5 9]")) == [3, 3, 4, 4, 5, 9]
        assert _arr(klong("&\\[3 1 4 1 5 9]")) == [3, 1, 1, 1, 1, 1]
        # Each index
        result = klong("{x@0}@'[10 20 30]")
        assert _arr(result) == [0, 1, 2]
        result = klong("{x@1}@'[10 20 30]")
        assert _arr(result) == [10, 20, 30]
        result = klong("{(x@0)*(x@1)}@'[10 20 30]")
        assert _arr(result) == [0, 20, 60]
        # Each on dict
        klong("D:::{[1 10] [2 20] [3 30]}")
        result = klong("{(x@0)+(x@1)}'D")
        assert _arr(result) == [11, 22, 33]

    def test_adverbs_each_pair_composite(self, klong):
        """Each-pair, each-pair sum/diff, each-left/right, sum-of-consecutive-diffs."""
        # Each pair
        result = klong(",:'[1 2 3 4]")
        assert _arr(result[0]) == [1, 2]
        assert _arr(result[1]) == [2, 3]
        assert _arr(result[2]) == [3, 4]
        assert _arr(klong("-:'[1 3 6 10]")) == [-2, -3, -4]
        # Each pair sum/diff
        assert _arr(klong("+:'[1 2 3 4]")) == [3, 5, 7]
        assert _arr(klong("-:'[5 3 8 1]")) == [2, -5, 7]
        # Each left/right
        result = klong("1,:\\[2 3 4]")
        assert _arr(result[0]) == [1, 2]
        assert _arr(result[1]) == [1, 3]
        assert _arr(result[2]) == [1, 4]
        result = klong("1,:/[2 3 4]")
        assert _arr(result[0]) == [2, 1]
        assert _arr(result[1]) == [3, 1]
        assert _arr(result[2]) == [4, 1]
        # Sum of consecutive diffs
        result = klong("+/-:'[1 4 9 16]")
        assert result == -15

    def test_adverbs_convergence_composite(self, klong):
        """Converge, while, iterate, scan-iterate, scan-concat."""
        # Converge
        result = klong("{(x+2%x)%2}:~2")
        assert _close(result, math.sqrt(2), tol=1e-4)
        # While
        result = klong("{x<1000}{x*2}:~1")
        assert result == 1024
        # Iterate
        result = klong("3{1,x}:*[]")
        assert _arr(result) == [1, 1, 1]
        result = klong("5{x+1}:*0")
        assert result == 5
        # Scan iterate
        result = klong("3{1,x}\\*[]")
        assert len(result) == 4
        result = klong("4{x*2}\\*1")
        assert _arr(result) == [1, 2, 4, 8, 16]
        # Scan concat
        result = klong(",\\[1 2 3]")
        assert _arr(result[0]) == 1 or _arr(result[0]) == [1]
        assert _arr(result[2]) == [1, 2, 3]

    def test_each_dyadic_custom(self, klong):
        """Dyadic each with custom function."""
        klong("f::{x*100+y}")
        result = _arr(klong("[1 2 3]f'[4 5 6]"))
        assert result == [104, 210, 318]

    def test_each_left_right_custom(self, klong):
        """Each-left/right with custom function."""
        klong("f::{x*10+y}")
        # each-left: f(5,1), f(5,2), f(5,3) -- right-to-left: x*(10+y)
        result = _arr(klong("5f:\\[1 2 3]"))
        assert result == [55, 60, 65]
        # each-right: f(1,5), f(2,5), f(3,5) -- right-to-left: x*(10+y)
        result = _arr(klong("5f:/[1 2 3]"))
        assert result == [15, 30, 45]

    def test_chained_adverb(self, klong):
        """Chained adverbs: +/' is sum-each."""
        result = klong("+/'[[1 2 3] [4 5 6] [7 8 9]]")
        assert _arr(result) == [6, 15, 24]
        result = klong("|/'[[3 1 4] [1 5 9] [2 6 5]]")
        assert _arr(result) == [4, 9, 6]

    def test_flatten_via_converge(self, klong):
        result = klong(",/:~[1 [2 [3 [4] 5] 6] 7]")
        assert _arr(result) == [1, 2, 3, 4, 5, 6, 7]

    def test_scan_while(self, klong):
        result = klong("{x<100}{x*2}\\~1")
        assert _arr(result) == [1, 2, 4, 8, 16, 32, 64]

    def test_scan_converge(self, klong):
        result = klong("{_x%2}\\~100")
        arr = _arr(result)
        assert arr[0] == 100
        assert arr[-1] == 0
        assert arr == [100, 50, 25, 12, 6, 3, 1, 0]

    def test_join_over(self, klong):
        assert _arr(klong(",/[[1 2] [3 4] [5 6]]")) == [1, 2, 3, 4, 5, 6]
        assert _arr(klong(",/[]")) == []


# ===================================================================
# 9. ARRAY OPERATIONS
# ===================================================================


class TestArrayOperations:
    """Vector operations, sorting, reshaping."""

    def test_array_operations_composite(self, klong):
        """Vectorized arithmetic, sort-via-grade, dot-product, average, matrix operations."""
        # Vectorized arithmetic
        assert _arr(klong("[1 2 3]+[10 20 30]")) == [11, 22, 33]
        assert _arr(klong("[1 2 3]*10")) == [10, 20, 30]
        # Sort via grade
        klong("a::[3 1 4 1 5 9]")
        result = _arr(klong("a@<a"))
        assert result == [1, 1, 3, 4, 5, 9]
        result = _arr(klong("a@>a"))
        assert result == [9, 5, 4, 3, 1, 1]
        # Dot product
        result = klong("+/[1 2 3]*[4 5 6]")
        assert result == 32
        # Average
        klong("avg::{(+/x)%#x}")
        result = klong("avg([2 4 6 8 10])")
        assert _close(result, 6.0)
        # Matrix operations
        result = klong("[3 3]:^!9")
        assert _arr(result[0]) == [0, 1, 2]
        assert _arr(result[2]) == [6, 7, 8]
        klong("m::[[1 2] [3 4]]")
        result = klong("+m")
        assert _arr(result[0]) == [1, 3]
        assert _arr(result[1]) == [2, 4]

    def test_where_filter(self, klong):
        klong("a::[1 5 2 8 3 7]")
        result = _arr(klong("a@&a>3"))
        assert result == [5, 8, 7]

    def test_scan_each_rows(self, klong):
        """Scan-each: running sum per row."""
        result = klong("+\\'[[1 2 3] [10 20 30]]")
        assert _arr(result[0]) == [1, 3, 6]
        assert _arr(result[1]) == [10, 30, 60]


# ===================================================================
# 10. SYSTEM FUNCTIONS
# ===================================================================


class TestSystemFunctions:
    """System functions (.p, .d, .E, .rn, .pc, .rs, .py, .pyf, .bkf, etc.)."""

    def test_system_misc_composite(self, klong):
        """Random, clock, read-string-complex, exit-raises."""
        # Random and clock
        result = klong(".rn()")
        assert 0 <= result < 1
        result = klong(".pc()")
        assert result >= 0
        # Read string complex
        assert _arr(klong('.rs("[1 2 3]")')) == [1, 2, 3]
        assert klong('.rs("42")') == 42
        assert str(klong('.rs(":foo")')) == "foo"
        assert klong('.rs("-7")') == -7
        assert _close(klong('.rs("3.14")'), 3.14)
        # Exit raises
        with pytest.raises(SystemExit):
            klong(".x(0)")

    def test_evaluate_with_side_effects(self, klong):
        """.E evaluates string as Klong code, including mutations."""
        result = klong('.E("1+2")')
        assert result == 3
        klong('.E("gvar::99")')
        assert klong("gvar") == 99
        # .E can mutate a global it previously defined
        klong('.E("counter::5")')
        klong('.E("counter::counter+1")')
        assert klong("counter") == 6

    def test_print_and_display(self, klong):
        result = klong('.p("hello")')
        assert result == "hello"
        result = klong(".d(42)")
        assert result == "42"
        # .d on various types exercises writer display paths
        result = klong(".d(:foo)")
        assert result == "foo"
        result = klong(".d(0cx)")
        assert result == "x"
        result = klong(".d(3.14)")
        assert result == "3.14"
        result = klong('.d("say ""hi""")')
        assert 'say "hi"' in result
        result = klong(".d(:{[1 2]})")
        assert result == ":{[1 2]}"
        result = klong(".d([10 20 30])")
        assert result == "[10 20 30]"
        # Display a function -- returns its arity-tagged representation
        klong("myfn::{x+1}")
        result = klong(".d(myfn)")
        assert result == ":monad"

    def test_write_readable_representation(self, klong):
        """
        .w writes readable representation (display=False) -- different from .d/.p
        for strings and chars. Verifies writer formatting branches.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            fname = f.name
        try:
            # Write various types using .w (readable format)
            klong(f'.tc(.oc("{fname}"))')
            klong('.w("hello")')  # readable string: "hello"
            klong(".w(0cx)")  # readable char: 0cx
            klong(".w(:foo)")  # readable symbol: :foo
            klong(".w(42)")  # integer
            klong(".w(3.14)")  # float
            klong(".w([1 2 3])")  # list
            klong(".w(:{[1 2]})")  # dict
            klong('qstr::"say ""hi"""')
            klong(".w(qstr)")  # string with quotes (exercises doubling)
            klong("fn::{x+1}")
            klong(".w(fn)")  # function
            klong(".cc(.tc(0))")
            # Read back the ENTIRE written file (agnostic to how .w frames
            # successive objects -- inter-object separators are unspecified).
            with open(fname) as fh:
                content = fh.read()
            # .w on strings wraps in quotes, .w on chars prefixes with 0c
            assert '"hello"' in content
            assert "0cx" in content
            assert ":foo" in content
        finally:
            os.unlink(fname)

    def test_python_import_and_use(self, klong):
        """.py imports module; .pyf imports specific names."""
        klong('.py("math")')
        result = klong("sqrt(4)")
        assert _close(result, 2.0)
        klong('.pyf("os.path";"exists")')
        result = klong('exists("/")')
        assert result == True

    def test_backend_function_usage(self, klong):
        """.bkf imports and uses backend math functions."""
        klong('.bkf(["exp"])')
        result = klong("exp(1.0)")
        assert _close(result, math.e, tol=1e-4)
        klong('.bkf(["sqrt"])')
        result = _arr(klong("sqrt([4 9 16])"))
        assert _close(result, [2.0, 3.0, 4.0])


# ===================================================================
# 11. FILE I/O
# ===================================================================


class TestFileIO:
    """File channel operations."""

    def test_file_io_composite(self, klong):
        """Write/read file and load .kg file."""
        # Write and read file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            fname = f.name
        try:
            klong(f'.tc(.oc("{fname}"))')
            klong('.w("hello")')
            klong(".cc(.tc(0))")
            klong(f'.fc(.ic("{fname}"))')
            result = klong(".rl()")
            klong(".cc(.fc(0))")
            assert "hello" in result
        finally:
            os.unlink(fname)
        # Load .kg file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".kg", delete=False) as f:
            f.write("loadedvar::999\n")
            fname = f.name
        try:
            klong(f'.l("{fname}")')
            assert klong("loadedvar") == 999
        finally:
            os.unlink(fname)

    def test_read_write_array(self, klong):
        """Channel roundtrip (.oc/.tc/.w/.cc/.fc/.ic/.r) for a flat array and a nested array."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False) as f:
            fname = f.name
        try:
            # Flat array
            klong("data::!100")
            klong(f'.tc(.oc("{fname}"));.w(data);.cc(.tc(0))')
            klong(f'.fc(.ic("{fname}"));readback::.r();.cc(.fc(0))')
            assert klong("readback~data") == 1
            # Nested array (exercises writer/reader recursion)
            klong("nested::[[1 2] [3 4]]")
            klong(f'.tc(.oc("{fname}"));.w(nested);.cc(.tc(0))')
            klong(f'.fc(.ic("{fname}"));got::.r();.cc(.fc(0))')
            assert klong("got~nested") == 1
        finally:
            os.unlink(fname)


# ===================================================================
# 12. STRING OPERATIONS
# ===================================================================


class TestStringOperations:
    """String-specific operations."""

    def test_string_operations_composite(self, klong):
        """Concatenation, take/drop, split, cut-with-positions."""
        # String concatenation
        assert klong('"hello",", ","world"') == "hello, world"
        # String take/drop
        assert klong('3#"abcdef"') == "abc"
        assert klong('3_"abcdef"') == "def"
        assert klong('0#"abc"') == ""
        # String split into 3 (nearly equal) segments: "abcdefg" -> ["abc","de","fg"]
        result = klong('3:#"abcdefg"')
        assert len(result) == 3
        assert result[0] == "abc"
        assert result[1] == "de"
        assert result[2] == "fg"
        # String cut with positions
        result = klong('[2 3 5]:_"abcdef"')
        assert result[0] == "ab"
        assert result[1] == "c"
        assert result[2] == "de"
        assert result[3] == "f"

    def test_string_find_char_and_substr(self, klong):
        """Find substring positions in strings (multi-char needle)."""
        assert _arr(klong('"banana"?"an"')) == [1, 3]
        assert _arr(klong('"hello world"?"o"')) == [4, 7]
        assert _arr(klong('"abc"?0ca')) == [0]


# ===================================================================
# 13. DICTIONARY OPERATIONS
# ===================================================================


class TestDictionary:
    """Dictionary creation and operations."""

    def test_dict_in_situ_mutation(self, klong):
        klong("D:::{}")
        klong("{D,x,x}'!5")
        result = klong("D")
        assert isinstance(result, dict)
        assert result[0] == 0
        assert result[4] == 4

    def test_dict_each_extracts_pairs(self, klong):
        """Identity-each on dict yields list of [key,val] pairs."""
        klong('D:::{["a" 1] ["b" 2]}')
        result = klong("{x}'D")
        assert len(result) == 2
        pairs = [_arr(x) for x in result]
        assert ["a", 1] in pairs
        assert ["b", 2] in pairs


# ===================================================================
# 14. PROJECTIONS (PARTIAL APPLICATION)
# ===================================================================


class TestProjections:
    """Projections: omitting arguments creates partial application."""

    def test_projections_composite(self, klong):
        """Dyad projection right/left, triad projection, operator projection, projection with adverb, right-to-left eval."""
        # Dyad projection right
        klong("f2::{x-y}")
        result = klong("f2(1;)@2")
        assert result == -1
        # Dyad projection left
        result = klong("f2(;2)@3")
        assert result == 1
        # Triad projection
        klong("f3::{x-y*z}")
        assert klong("f3(1;2;)@4") == -7
        assert klong("f3(1;;3)@4") == -11
        assert klong("f3(;2;3)@4") == -2
        # Operator projection
        klong("add3::{x+y}(;3)")
        assert klong("add3@5") == 8
        # Projection with adverb
        klong("f::{x,y}")
        result = klong("f(;0)'[1 2 3]")
        assert _arr(result[0]) == [1, 0]
        assert _arr(result[1]) == [2, 0]
        assert _arr(result[2]) == [3, 0]
        # Projection right-to-left eval
        klong("f::{x*y+z}")
        result = klong("f(2;3;)@10")
        assert result == 26

    def test_triad_projection_two_args(self, klong):
        klong("f3::{x-y*z}")
        result = klong("f3(1;;)@[4 5]")
        assert result == -19
        result = klong("f3(;2;)@[4 5]")
        assert result == -6

    def test_projection_dyad_context_each(self, klong):
        klong("g::{x,y,z}")
        result = klong("[1 2 3]g(;0;)'[4 5 6]")
        assert _arr(result[0]) == [1, 0, 4]
        assert _arr(result[1]) == [2, 0, 5]
        assert _arr(result[2]) == [3, 0, 6]


# ===================================================================
# 15. MODULES
# ===================================================================


class TestModules:
    """Module scoping via .module()."""

    def test_modules_composite(self, klong):
        """Module creates scope, module mutation, module stack implementation."""
        # Module creates scope
        klong("a::0")
        klong(".module(:test)")
        klong("a::1")
        klong("g::{a}")
        klong("f::{g()}")
        klong(".module(0)")
        assert klong("g()") == 1
        assert klong("f()") == 1
        # Reassigning the outer name after the module closes must not disturb the
        # module-scoped binding the module's functions captured
        klong("a::7")
        assert klong("g()") == 1
        assert klong("f()") == 1
        # Module mutation (use fresh module name)
        klong(".module(:test2)")
        klong("a::1")
        klong("s::{a::x}")
        klong("g2::{a}")
        klong(".module(0)")
        klong("s(2)")
        assert klong("g2()") == 2
        # Module stack implementation (use fresh module name)
        klong(".module(:stack)")
        klong("S::[]")
        klong("push::{S::x,S;S}")
        klong("pop::{[r];r::*S;S::1_S;r}")
        klong("peek::{*S}")
        klong(".module(0)")
        _arr(klong("push(1)"))
        _arr(klong("push(2)"))
        _arr(klong("push(3)"))
        assert klong("peek()") == 3
        assert klong("pop()") == 3
        assert klong("peek()") == 2
        assert klong("pop()") == 2
        assert klong("pop()") == 1


# ===================================================================
# 16. COMMENTS AND MULTILINE
# ===================================================================


class TestCommentsAndMultiline:
    """Comment handling and multiline parsing."""

    def test_comments_and_multiline_composite(self, klong):
        """Comments, multiline constructs, newlines-as-semicolons at toplevel."""
        # Comments
        assert klong('1+2 :" this is a comment"') == 3
        assert klong('a::10 :" set a"; b::20; a+b') == 30
        # Multiline constructs
        with tempfile.NamedTemporaryFile(mode="w", suffix=".kg", delete=False) as f:
            f.write("arr::[1\n      2\n      3]\n")
            f.write('ift:::[1;\n       "true";\n       "false"]\n')
            f.write("fn::{x+\n     1}\n")
            fname = f.name
        try:
            klong(f'.l("{fname}")')
            assert _arr(klong("arr")) == [1, 2, 3]
            assert klong("ift") == "true"
            assert klong("fn(5)") == 6
        finally:
            os.unlink(fname)
        # Newlines as semicolons at toplevel
        with tempfile.NamedTemporaryFile(mode="w", suffix=".kg", delete=False) as f:
            f.write("a2::10\nb2::20\nc2::a2+b2\n")
            fname = f.name
        try:
            klong(f'.l("{fname}")')
            assert klong("c2") == 30
        finally:
            os.unlink(fname)


# ===================================================================
# 17. NUMERIC DIFFERENTIATION (AUTOGRAD)
# ===================================================================


class TestAutograd:
    """Numeric differentiation via :> operator."""

    def test_autograd_composite(self, klong):
        """Gradient simple, cubic, vector."""
        # Gradient simple
        result = klong("{x^2}:>3.0")
        assert _close(result, 6.0, tol=0.01)
        # Gradient cubic
        result = klong("{x^3}:>2.0")
        assert _close(result, 12.0, tol=0.1)
        # Gradient vector
        result = klong("{+/x^2}:>[1.0 2.0 3.0]")
        assert _close(_arr(result), [2.0, 4.0, 6.0], tol=0.01)

    def test_multi_param_gradient(self, klong):
        klong("w::2.0")
        klong("b::3.0")
        klong("loss::{(w^2)+(b^2)}")
        result = klong("loss:>[w b]")
        grads = [float(g) for g in result]
        assert _close(grads[0], 4.0, tol=0.1)
        assert _close(grads[1], 6.0, tol=0.1)


# ===================================================================
# 18. CLI (kgpy command)
# ===================================================================


class TestCLI:
    """Test the kgpy command-line interface."""

    def test_cli_expr_and_file(self):
        """kgpy -e evaluates expressions; runs .kg files."""
        r1 = subprocess.run(
            [sys.executable, "-m", "klongpy.cli", "-e", "1+2"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert r1.returncode == 0
        assert "3" in r1.stdout.strip()
        r2 = subprocess.run(
            [sys.executable, "-m", "klongpy.cli", "-e", "!5"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert r2.returncode == 0
        assert "0" in r2.stdout and "4" in r2.stdout
        # Run a .kg file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".kg", delete=False) as f:
            f.write("a::10\nb::20\n.p(a+b)\n")
            fname = f.name
        try:
            result = subprocess.run(
                [sys.executable, "-m", "klongpy.cli", fname],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 0
            assert "30" in result.stdout
        finally:
            os.unlink(fname)


# ===================================================================
# 21. BROADCASTING AND VECTORIZATION
# ===================================================================


class TestBroadcasting:
    """Atomic operators broadcast across nested structures."""

    def test_broadcasting_composite(self, klong):
        """Nested add, nested min/max."""
        # Nested add
        assert _arr(klong("[1]+[2]")) == [3]
        result = klong("[[1]]+[2]")
        assert _arr(result[0]) == [3]
        # Nested min/max
        assert _arr(klong("[1]&[2]")) == [1]
        result = klong("[[1]]&[2]")
        assert _arr(result[0]) == [1]
        assert _arr(klong("[1]|[2]")) == [2]

    def test_vectorized_function_each(self, klong):
        assert _arr(klong("{2*x}'!1000")) == [2 * i for i in range(1000)]

    def test_format2_broadcasting(self, klong):
        result = klong("[1 2]$[3 4]")
        assert _arr(result) == ["3", "4 "]

    def test_form_broadcasting(self, klong):
        result = klong('[1]:$["-123"]')
        assert _arr(result) == [-123]


# ===================================================================
# 22. EDGE CASES AND ERROR HANDLING
# ===================================================================


class TestEdgeCases:
    """Edge cases and error conditions."""

    def test_edge_cases_composite(self, klong):
        """First-of-empty, chained-joins, large-array, undefined-variable, symbol-identity, over-single-element, list-wrap-array."""
        # First of empty
        result = klong("*[]")
        assert _arr(result) == []
        assert klong('*""') == ""
        # Chained joins
        assert _arr(klong("1,2,3,4")) == [1, 2, 3, 4]
        # Large array
        klong("a::!1000")
        result = klong("+/a")
        assert result == 499500
        # Undefined variable returns symbol
        result = klong("nonexistent")
        assert str(result) == "nonexistent"
        # Symbol identity
        assert klong(":test~:test") == 1
        assert klong(":{[foo bar]}?:foo") == klong(":bar")
        # Over single element
        assert klong("+/[5]") == 5
        assert klong("*/[7]") == 7
        # List wrap array
        result = klong(",[1 2 3]")
        assert len(result) == 1
        assert _arr(result[0]) == [1, 2, 3]


# ===================================================================
# 23. COMPLEX PROGRAMS
# ===================================================================


class TestComplexPrograms:
    """Multi-line programs exercising multiple features together."""

    def test_complex_programs_composite(self, klong):
        """Fibonacci, factorial, GCD, map-reduce, VWAP, running-max, de-mean, unique-count, multiline-function, autograd-composed."""
        # Fibonacci
        klong("fib::{:[x<2;x;.f(x-1)+.f(x-2)]}")
        assert klong("fib(0)") == 0
        assert klong("fib(1)") == 1
        assert klong("fib(10)") == 55
        # Factorial
        klong("fact::{:[x<2;1;x*.f(x-1)]}")
        assert klong("fact(5)") == 120
        assert klong("fact(0)") == 1
        # GCD
        klong("gcd::{:[y=0;x;.f(y;x!y)]}")
        assert klong("gcd(12;8)") == 4
        assert klong("gcd(100;75)") == 25
        assert klong("gcd(17;13)") == 1
        # Map reduce
        klong("data::[1 2 3 4 5]")
        klong("sq::{x^2}")
        result = klong("+/sq'data")
        assert result == 55
        # VWAP
        klong("prices::[10.0 11.0 12.0]")
        klong("volumes::[100 200 150]")
        klong("vwap::{(+/x*y)%+/y}")
        result = klong("vwap(prices;volumes)")
        expected = (10 * 100 + 11 * 200 + 12 * 150) / (100 + 200 + 150)
        assert _close(result, expected)
        # Running max
        result = _arr(klong("|\\[3 1 4 1 5 9 2 6]"))
        assert result == [3, 3, 4, 4, 5, 9, 9, 9]
        # De-mean
        klong("a::[1.0 2.0 3.0 4.0 5.0]")
        result = klong("a-(+/a)%#a")
        expected_dm = [-2.0, -1.0, 0.0, 1.0, 2.0]
        assert _close(_arr(result), expected_dm)
        # Unique count pipeline
        assert klong("#?[1 1 2 2 3]") == 3
        assert klong("+/!100") == 4950
        # Multiline function with locals
        with tempfile.NamedTemporaryFile(mode="w", suffix=".kg", delete=False) as f:
            f.write("stats::{[mn;mx;sm];mn::&/x;mx::|/x;sm::+/x;[;mn;mx;sm]}\n")
            f.write("result::stats([3 1 4 1 5 9])\n")
            fname = f.name
        try:
            klong(f'.l("{fname}")')
            r = klong("result")
            assert _arr(r) == [1, 9, 23]
        finally:
            os.unlink(fname)
        # Autograd composed functions
        klong("f::{x^2}")
        klong("g::{f(x)+3*x}")
        result = klong("g:>2.0")
        assert _close(result, 7.0, tol=0.5)

    def test_matrix_multiply_manual(self, klong):
        klong("a::[[1 2] [3 4]]")
        klong("b::[[5 6] [7 8]]")
        r00 = klong("+/(a@0)*(+b)@0")
        r01 = klong("+/(a@0)*(+b)@1")
        assert r00 == 19
        assert r01 == 22

    def test_gradient_descent(self, klong):
        klong("f::{(x-3)^2}")
        klong("s::10.0")
        klong("lr::0.1")
        klong("{s::s-(lr*f:>s)}'!50")
        result = klong("s")
        assert _close(result, 3.0, tol=0.5)

    def test_uniq_via_dict(self, klong):
        klong("uniq::{[d];d:::{};{d,x,x}'x;d@<d::*'d}")
        result = _arr(klong("uniq(!5)"))
        assert result == [0, 1, 2, 3, 4]

    def test_nested_scoping_complex(self, klong):
        klong("FL:::{}")
        klong("FL,0,{.p(,x@1)}")
        klong("F::{f::FL?0;f(x)}")
        result = klong('F("hello")')
        assert result == "e"

    def test_file_based_program(self, klong):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".kg", delete=False) as f:
            f.write("sq::{x^2}\n")
            f.write("data::!10\n")
            f.write("total::+/sq'data\n")
            fname = f.name
        try:
            klong(f'.l("{fname}")')
            assert klong("total") == 285
        finally:
            os.unlink(fname)

    def test_eval_defines_global_from_function(self, klong):
        """.E inside a function defines globals, not locals."""
        klong('maker::{.E("created::" , $x)}')
        klong("maker(42)")
        assert klong("created") == 42
        # Chained .E with variable dependency
        klong('.E("ea::10;eb::20;ec::ea+eb")')
        assert klong("ec") == 30

    def test_split_cycling_sizes(self, klong):
        """Split with a list of sizes that cycles."""
        result = klong("[1 2]:#[1 2 3 4 5 6]")
        assert _arr(result[0]) == [1]
        assert _arr(result[1]) == [2, 3]
        assert _arr(result[2]) == [4]
        assert _arr(result[3]) == [5, 6]
        # Split where size >= length returns whole
        result = klong("10:#[1 2 3]")
        assert _arr(result[0]) == [1, 2, 3]

    def test_take_negative_cycling(self, klong):
        """Take from end with cycling."""
        result = klong("(-5)#[1 2 3]")
        assert _arr(result) == [2, 3, 1, 2, 3]
        assert klong('(-3)#"ab"') == "bab"
