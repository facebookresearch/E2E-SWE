"""Hidden test suite for the grappa WRG task.

These tests exercise grappa's behavior-oriented, fluent assertion DSL strictly
through its public API (``from grappa import ...``).  Each test models a
realistic user workflow that combines several public operators and chaining
constructs.  Both the success path (assertion holds) and the failure path
(assertion raises ``AssertionError``) are validated for every capability.
"""

# pyre-ignore-all-errors
import re

import pytest

import grappa
from grappa import (
    Operator,
    Test,
    attribute,
    config,
    expect,
    operator,
    register,
    should,
    use,
)


# ---------------------------------------------------------------------------
# Identity / equality / truthiness / none / empty
# ---------------------------------------------------------------------------


def test_equality_assertions_pass_and_fail():
    """``equal`` (and its ``to``/``of`` chain aliases) compares with ``==``.

    Successful equality should be silent; mismatch must raise
    ``AssertionError``.  Both ``should`` and ``expect`` styles must support
    the same surface.  Negation via ``not_be``/``to_not`` must invert.
    Failure messages must surface both the actual subject and the expected
    value so users can diagnose the mismatch.

    Every matcher must also accept a ``msg=`` keyword that is surfaced
    verbatim in the rendered ``AssertionError`` message, so users can label
    failures with domain-specific context.  ``msg=`` is universal across
    operators (verified here on both ``equal`` and ``contain``).
    """
    # Should-style, success
    "foo" | should.be.equal.to("foo")
    "foo" | should.be.equal("foo")
    [1, 2, 3] | should.be.equal.to([1, 2, 3])
    {"a": 1, "b": 2} | should.be.equal.to({"a": 1, "b": 2})

    # Expect-style, success
    "foo" | expect.to.be.equal.to("foo")
    [1, 2, 3] | expect.to.be.equal.to([1, 2, 3])

    # Negation
    "foo" | should.not_be.equal.to("bar")
    "foo" | expect.to_not.be.equal.to("bar")
    [1, 2, 3] | should.not_be.equal.to([1, 2])

    # Failure — both subject and expected appear in the message
    with pytest.raises(AssertionError) as exc_info:
        "foo" | should.be.equal.to("bar")
    msg = str(exc_info.value)
    assert "foo" in msg, "subject value must appear in failure message"
    assert "bar" in msg, "expected value must appear in failure message"

    with pytest.raises(AssertionError):
        [1, 2, 3] | should.be.equal.to([1, 2, 4])
    with pytest.raises(AssertionError):
        "foo" | expect.to.be.equal.to("BAR")
    with pytest.raises(AssertionError):
        "foo" | should.not_be.equal.to("foo")

    # Custom error message via msg= keyword — must surface verbatim.  This
    # is a UNIVERSAL keyword: a working implementation supports it on every
    # matcher.  We verify on both `equal` and `contain` here so a broken
    # `msg=` plumbing fails this test (rather than getting partial credit
    # via a separate test).
    sentinel = "UNIQUE-SENTINEL-XYZ-9181"
    with pytest.raises(AssertionError) as exc_info:
        "foo" | should.be.equal.to("bar", msg=sentinel)
    assert sentinel in str(exc_info.value)

    with pytest.raises(AssertionError) as exc_info:
        [1, 2, 3] | should.contain(99, msg="MY-CONTAIN-LABEL-AAA")
    assert "MY-CONTAIN-LABEL-AAA" in str(exc_info.value)


def test_truthiness_none_empty_and_present_accessors():
    """``true`` / ``false`` / ``none`` / ``empty`` / ``present`` accessor ops.

    Accessor operators take no argument and assert directly on the subject's
    type/value semantics.  Empty matches ``None``, ``0``, ``''``, ``[]``,
    ``()``, exhausted iterators, etc.  Bool checks must be strict (only
    ``True`` is truthy for ``true``; integers do not satisfy it).
    ``present`` / ``exists`` is the opposite of ``empty``.  Negation of
    ``true`` / ``false`` must allow non-bool subjects (since the strict
    type check only fires in the positive direction).
    """
    # true / false: STRICTLY bool (per source: not isinstance(x, bool) -> fail)
    True | should.be.true
    False | should.be.false
    True | expect.to.be.true
    False | expect.to.be.false

    with pytest.raises(AssertionError):
        False | should.be.true
    with pytest.raises(AssertionError):
        1 | should.be.true  # ints do not satisfy `true`
    with pytest.raises(AssertionError):
        "yes" | should.be.true
    with pytest.raises(AssertionError):
        True | should.be.false

    # Negation of true/false must not enforce strict-bool — any non-bool subject
    # satisfies `not_be.true` / `not_be.false`.
    "foo" | should.not_be.true
    1 | should.not_be.true
    [1] | should.not_be.false
    None | should.not_be.true

    # none
    None | should.be.none
    None | expect.to.be.none
    "x" | should.not_be.none

    with pytest.raises(AssertionError):
        False | should.be.none  # False is NOT None
    with pytest.raises(AssertionError):
        0 | should.be.none
    with pytest.raises(AssertionError):
        "x" | should.be.none

    # empty: None, 0, '', [], (), exhausted iters, exhausted generators
    None | should.be.empty
    0 | should.be.empty
    "" | should.be.empty
    [] | should.be.empty
    tuple() | should.be.empty
    iter([]) | should.be.empty
    {} | should.be.empty
    set() | should.be.empty

    "foo" | should.not_be.empty
    [1, 2, 3] | should.not_be.empty
    {"a": 1} | should.not_be.empty
    42 | should.not_be.empty  # non-zero numbers are not empty

    with pytest.raises(AssertionError):
        "foo" | should.be.empty
    with pytest.raises(AssertionError):
        [1] | should.be.empty
    with pytest.raises(AssertionError):
        True | should.be.empty  # True/False are NOT empty per source
    with pytest.raises(AssertionError):
        False | should.be.empty
    with pytest.raises(AssertionError):
        42 | should.be.empty  # non-zero number is not empty

    # present / exists: opposite of empty
    "foo" | should.be.present
    [1, 2] | should.be.present
    {"a": 1} | should.be.present
    "foo" | should.be.exists  # alias
    [1, 2] | should.be.exists

    "" | should.not_be.present
    [] | should.not_be.present
    None | should.not_be.present
    0 | should.not_be.present  # 0 is not present (treated like empty)

    with pytest.raises(AssertionError):
        "" | should.be.present
    with pytest.raises(AssertionError):
        [] | should.be.present
    with pytest.raises(AssertionError):
        None | should.be.present
    with pytest.raises(AssertionError):
        "foo" | should.not_be.present


# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------


def test_numeric_comparisons_and_within_range():
    """``below``/``lower``/``less``, ``above``/``higher``, ``within``/``between``.

    Numeric comparators must accept ``int``/``float`` subjects and support
    the documented aliases (``most``, ``least``, ``higher_or_equal``,
    ``lower_or_equal``).  Inclusive/exclusive boundary semantics:
    ``within`` is INCLUSIVE on both ends; ``above_or_equal``/``below_or_equal``
    (and their ``most``/``least`` aliases) accept equality; ``above``/``below``
    are strict.  Non-numeric subjects must fail (not crash).
    """
    # Strict inequalities
    3 | should.be.below(5)
    3 | should.be.lower.than(5)
    3 | should.be.less.than(5)
    5 | should.be.above(3)
    5 | should.be.higher.than(3)

    # Or-equal forms — every documented alias for each direction
    3 | should.be.below_or_equal(3)
    3 | should.be.below_or_equal(5)
    3 | should.be.lower_or_equal(3)
    3 | should.be.most(3)  # alias of below_or_equal
    3 | should.be.most(5)
    3 | should.be.above_or_equal(3)
    3 | should.be.above_or_equal(2)
    3 | should.be.higher_or_equal(3)
    3 | should.be.least(3)  # alias of above_or_equal
    3 | should.be.least(2)

    # within / between is inclusive
    4 | should.be.within(2, 5)
    2 | should.be.within(2, 5)  # left boundary inclusive
    5 | should.be.between(2, 5)  # right boundary inclusive
    4.5 | should.be.within(4, 5)

    # Negation
    3 | should.not_be.above(5)
    10 | should.not_be.within(0, 5)
    3 | should.not_be.most(2)  # 3 > 2, so not <= 2
    3 | should.not_be.least(5)  # 3 < 5, so not >= 5

    # Failures
    with pytest.raises(AssertionError):
        5 | should.be.below(3)
    with pytest.raises(AssertionError):
        3 | should.be.above(5)
    with pytest.raises(AssertionError):
        10 | should.be.within(0, 5)
    with pytest.raises(AssertionError):
        # `below` is strict, equality must fail
        3 | should.be.below(3)
    with pytest.raises(AssertionError):
        # `above` is strict, equality must fail
        3 | should.be.above(3)
    with pytest.raises(AssertionError):
        # `most` (below_or_equal) — strict greater-than must fail
        5 | should.be.most(3)
    with pytest.raises(AssertionError):
        # `least` (above_or_equal) — strict less-than must fail
        3 | should.be.least(5)
    with pytest.raises(AssertionError):
        # within rejects non-numeric subjects
        None | should.be.within(0, 10)
    with pytest.raises(AssertionError):
        # below rejects non-numeric subjects
        "abc" | should.be.below(5)


# ---------------------------------------------------------------------------
# Length
# ---------------------------------------------------------------------------


def test_length_assertions_use_len_semantics():
    """``length`` / ``size`` operators assert ``len(subject) == expected``.

    Must work on strings, lists, tuples, dicts, sets, and any
    ``__len__``-bearing object.  Generators and iterators are also valid
    subjects (length is measured by consuming them).  ``size`` is an alias
    for ``length``.  Chain aliases ``of``, ``equal.to`` should be accepted;
    the ``length.between.range(low, high)`` chain composes with within and
    inclusive bounds.
    """
    "" | should.have.length(0)
    "foo" | should.have.length(3)
    "foo" | should.have.length.of(3)
    "foo" | should.have.length.equal.to(3)
    [1, 2, 3, 4] | should.have.length.of(4)
    (1, 2) | should.have.length.of(2)
    {"a": 1, "b": 2, "c": 3} | should.have.length.of(3)
    {1, 2, 3, 4, 5} | should.have.length.of(5)

    # `size` is an alias for `length`
    "foo" | should.have.size(3)
    [1, 2] | should.have.size.of(2)

    # iter() and generators are valid length subjects (consumed)
    iter([1, 2, 3, 4]) | should.have.length.of(4)

    def gen():
        yield 1
        yield 2
        yield 3

    gen() | should.have.length.of(3)

    # length composes with within via chain (inclusive bounds)
    "abcd" | should.have.length.between.range(2, 5)
    "ab" | should.have.length.between.range(2, 5)  # left inclusive
    "abcde" | should.have.length.between.range(2, 5)  # right inclusive

    # Negation
    "foo" | should.not_have.length.of(99)
    "foo" | should.not_have.length(5)

    # Failure — message mentions both actual and expected length
    with pytest.raises(AssertionError) as exc_info:
        "foo" | should.have.length.of(5)
    msg = str(exc_info.value)
    assert "5" in msg, "expected length must appear in failure message"
    assert "3" in msg, "actual length must appear in failure message"

    with pytest.raises(AssertionError):
        [1, 2, 3] | should.have.length.of(2)
    with pytest.raises(AssertionError):
        "foo" | should.not_have.length.of(3)
    with pytest.raises(AssertionError):
        # length.between range failure
        "abcdefg" | should.have.length.between.range(2, 5)
    with pytest.raises(AssertionError):
        # generator length mismatch
        gen() | should.have.length.of(99)

    # length on subject without __len__ and that isn't iterable must
    # fail gracefully (not raise an unrelated exception). This exercises
    # the "cannot measure length" code path.
    class _NoLen:
        pass

    with pytest.raises(AssertionError):
        _NoLen() | should.have.length.of(0)

    # A numeric subject is its own "length" — `length.below`/`length.above`
    # compose with the numeric comparators on a plain number subject, and
    # `length.within(lo, hi)` is the inclusive numeric-range form. This
    # ensures the length operator's "already a number" fast path remains
    # accessible (not just len()-bearing containers).
    5 | should.have.length.below(10)
    5 | should.have.length.above(2)
    5 | should.have.length.within(2, 10)
    with pytest.raises(AssertionError):
        5 | should.have.length.above(99)
    with pytest.raises(AssertionError):
        5 | should.have.length.within(10, 20)


# ---------------------------------------------------------------------------
# Contain (and contain.only)
# ---------------------------------------------------------------------------


def test_contain_works_on_sequences_and_strings():
    """``contain`` / ``contains`` / ``includes`` (and ``contain.only``).

    Substring containment for strings; item containment for lists / tuples /
    sets / dict values / arrays.  Variadic arguments and a single
    list/tuple/set wrapper both behave as multi-value asserts.  ``only``
    additionally checks the container has nothing besides those items.
    """
    # Strings
    "hello world" | should.contain("world")
    "hello world" | should.contain("hello", "world")
    "hello world" | should.contain(("hello", "world"))

    # Lists, tuples, sets
    [1, 2, 3] | should.contain(2)
    [1, 2, 3] | should.contain(1, 3)
    ("a", "b", "c") | should.contain("b")
    {"x", "y", "z"} | should.contain("x")

    # Dict containment compares against the values (per source)
    {"k1": "foo", "k2": "bar"} | should.contain("foo")
    {"k1": "foo", "k2": "bar"} | should.contain("bar", "foo")

    # contain.only — must contain exactly the given set
    ["foo", "bar"] | should.contain.only("foo", "bar")
    ["foo", "bar"] | should.contain.only("bar", "foo")  # order-insensitive
    ("foo", "bar") | should.contain.only("foo", "bar")  # tuples too

    # Negation
    [1, 2, 3] | should.do_not.contain(99)
    "hello" | should.do_not.contain("z")
    ["foo", "bar", "baz"] | should.do_not.contain.only("foo", "bar")  # extra item

    # Failures — both subject and missing item should appear in message
    with pytest.raises(AssertionError) as exc_info:
        "hello" | should.contain("planet")
    msg = str(exc_info.value)
    assert "hello" in msg, "subject must appear in contain-failure message"
    assert "planet" in msg, "missing item must appear in contain-failure message"

    with pytest.raises(AssertionError):
        [1, 2, 3] | should.contain(99)
    with pytest.raises(AssertionError):
        # contain.only failure: extra item present
        ["foo", "bar", "baz"] | should.contain.only("foo", "bar")
    with pytest.raises(AssertionError):
        # non-sequence subject
        1 | should.contain("x")


def test_startswith_and_endswith_on_strings_and_sequences():
    """``start_with`` / ``starts_with`` / ``startswith`` and the ``ends_with``
    family must work on strings, lists, tuples, iterators, and ordered dicts.
    Negation via ``do_not`` must invert.  An unordered mapping has no
    well-defined start, so the operator should reject it.
    """
    from collections import OrderedDict

    "hello" | should.startswith("he")
    "hello" | should.endswith("lo")
    [1, 2, 3] | should.startswith(1)
    [1, 2, 3] | should.endswith(3)
    [1, 2, 3] | should.startswith(1, 2)
    [1, 2, 3] | should.endswith(2, 3)

    # OrderedDict is a valid ordered sequence-like subject
    od = OrderedDict([("foo", 1), ("bar", 2), ("baz", 3)])
    od | should.startswith("foo")
    od | should.endswith("baz")
    od | should.do_not.startswith("baz")

    # Negation
    "hello" | should.do_not.startswith("zz")
    "hello" | should.do_not.endswith("zz")

    with pytest.raises(AssertionError):
        "hello" | should.startswith("zz")
    with pytest.raises(AssertionError):
        "hello" | should.endswith("zz")
    with pytest.raises(AssertionError):
        [1, 2, 3] | should.startswith(2)

    # A plain (unordered) dict has no well-defined "first" key and so the
    # operator must reject it rather than guess. This exercises the
    # unordered-mapping rejection branch.
    with pytest.raises(AssertionError):
        {"foo": 1, "bar": 2} | should.startswith("foo")


# ---------------------------------------------------------------------------
# Regex match
# ---------------------------------------------------------------------------


def test_regex_match_uses_re_search_semantics():
    """``match`` / ``matches`` assert that ``re.search(pattern, subject)``
    is not ``None``.  Additional positional args are forwarded as flags.
    Non-string subjects must fail (not crash).
    """
    "Hello World" | should.match(r"Hello \w+")
    "Hello World" | should.match(r"world", re.I)
    "abc-123-def" | should.match(r"\d+")

    # Negation
    "Hello World" | should.do_not.match(r"^\d")

    with pytest.raises(AssertionError):
        "Hello World" | should.match(r"^XYZ$")
    with pytest.raises(AssertionError):
        # non-string subject must fail, not crash
        123 | should.match(r"\d+")
    with pytest.raises(AssertionError):
        # non-string expected pattern must fail, not crash (mirrors the
        # non-string-subject rejection branch)
        "hello" | should.match(123)


# ---------------------------------------------------------------------------
# Type assertions
# ---------------------------------------------------------------------------


def test_type_assertions_with_aliases_and_type_objects():
    """``a`` / ``an`` / ``type`` / ``types`` / ``instance`` accept either a
    type object (``str``, ``list``, ...) or a string alias
    (``'string'``, ``'list'``, ``'lambda'``, ``'generator'`` ...).
    The full alias surface includes ``'string'``, ``'int'``, ``'integer'``,
    ``'number'`` (== int), ``'float'``, ``'bool'``/``'boolean'``,
    ``'complex'``, ``'list'``, ``'dict'``/``'dictionary'``, ``'tuple'``,
    ``'set'``, ``'array'``, ``'function'``, ``'method'``, ``'class'``,
    ``'module'``, ``'lambda'``, ``'generator'``, ``'coroutine'``,
    ``'generatorfunction'``, ``'coroutinefunction'``.  Unsupported aliases
    must cause the assertion to fail (not crash).
    """
    from array import array

    "foo" | should.be.a(str)
    "foo" | should.be.a("string")
    1 | should.be.an(int)
    1 | should.be.an("int")
    1 | should.be.an("integer")
    1 | should.be.an("number")
    1.5 | should.be.a(float)
    1.5 | should.be.a("float")
    [1, 2] | should.be.a(list)
    [1, 2] | should.be.a("list")
    (1, 2) | should.be.a("tuple")
    {"a": 1} | should.be.a("dict")
    {"a": 1} | should.be.a("dictionary")  # alias for dict
    {1, 2} | should.be.a("set")
    (1 + 2j) | should.be.a(complex)
    (1 + 2j) | should.be.a("complex")
    True | should.be.a("bool")
    True | should.be.a("boolean")  # alias for bool
    True | should.be.a(bool)
    (lambda x: x) | should.be.a("lambda")
    array("i", [1, 2, 3]) | should.be.a("array")

    def my_func():
        pass

    my_func | should.be.a("function")

    class MyClass:
        pass

    MyClass | should.be.a("class")

    import os

    os | should.be.a("module")

    def gen():
        yield 1

    gen() | should.be.a("generator")
    gen | should.be.a("generatorfunction")

    async def acoro():
        return 1

    acoro | should.be.a("coroutinefunction")
    co = acoro()
    try:
        co | should.be.a("coroutine")
    finally:
        co.close()

    # `type`/`types`/`instance` keyword aliases (alternates to `a`/`an`)
    "foo" | should.be.type(str)
    [1, 2] | should.have.type.of(list)
    "foo" | should.be.instance.of(str)

    # Negation
    "foo" | should.not_be.a("int")
    [1] | should.not_be.a("tuple")
    1.5 | should.not_be.a("number")  # 'number' is int alias, not float
    "foo" | should.not_be.a("array")
    my_func | should.not_be.a("coroutinefunction")
    my_func | should.not_be.a("generatorfunction")

    with pytest.raises(AssertionError):
        "foo" | should.be.a(int)
    with pytest.raises(AssertionError):
        "foo" | should.be.an("int")
    with pytest.raises(AssertionError):
        [1, 2] | should.be.a("tuple")
    with pytest.raises(AssertionError):
        1.5 | should.be.an("number")  # 'number' = int per source
    with pytest.raises(AssertionError):
        [1, 2] | should.be.a("array")  # plain list is not array.array
    with pytest.raises(AssertionError):
        my_func | should.be.a("coroutinefunction")  # sync def, not async
    with pytest.raises(AssertionError):
        # Unsupported alias must fail (not crash with KeyError or similar)
        "foo" | should.be.a("totally_bogus_type_alias_xyz")


# ---------------------------------------------------------------------------
# Mappings / sequences: key / keys / index / property / properties / implement
# ---------------------------------------------------------------------------


def test_dict_keys_and_index_operators():
    """``key``/``keys`` for dicts; ``index`` / ``index.at`` for sequences.

    Both expose the indexed/keyed value as the new subject when the
    assertion succeeds, enabling ``>`` chaining onto it.  Index ``-1`` is
    interpreted as the last element.  Tuples are also valid index subjects.
    Keys accepts a single iterable argument (list/tuple/set) as the keys
    collection equivalently to variadic arguments.
    """
    {"foo": "bar"} | should.have.key("foo")
    {"foo": "bar", "baz": 1} | should.have.keys("foo", "baz")
    {"foo": "bar", "baz": 1} | should.have.keys(["foo", "baz"])
    {"foo": "bar", "baz": 1} | should.have.keys(("foo", "baz"))

    {"a": 1} | should.not_have.key("z")

    [10, 20, 30] | should.have.index(0)
    [10, 20, 30] | should.have.index.at(2)
    [10, 20, 30] | should.have.index(-1)  # last element via -1
    (10, 20, 30) | should.have.index(1)  # tuples too
    (10, 20, 30) | should.have.index.at(0)

    # `>` chain rebinds subject to the indexed/keyed value
    {"foo": "bar"} | should.have.key("foo") > should.be.equal.to("bar")
    [10, 20, 30] | should.have.index.at(1) > should.be.equal.to(20)
    [10, 20, 30] | should.have.index(-1) > should.be.equal.to(30)

    with pytest.raises(AssertionError):
        {"a": 1} | should.have.key("z")
    with pytest.raises(AssertionError):
        {"a": 1, "b": 2} | should.have.keys("a", "z")
    with pytest.raises(AssertionError):
        [10, 20, 30] | should.have.index(99)
    with pytest.raises(AssertionError):
        # non-mapping subject
        ["x"] | should.have.key("x")
    with pytest.raises(AssertionError):
        # non-list/tuple subject for index
        "abc" | should.have.index(0)
    with pytest.raises(AssertionError):
        # value mismatch through > chain
        {"foo": "bar"} | should.have.key("foo") > should.be.equal.to("WRONG")


def test_object_property_and_implement_operators():
    """``property`` / ``properties`` (also aliased as ``attribute`` /
    ``attributes``) check for the existence of object attributes, and
    expose the attribute value as the new subject for ``>`` chaining.

    ``implement`` / ``implements`` / ``interface`` check that an object
    exposes the given method names with method-or-function semantics.
    """

    class Foo:
        name = "alice"
        age = 30

        def greet(self):
            return "hi"

        def shout(self):
            return "HI"

    f = Foo()
    f | should.have.property("name")
    f | should.have.properties("name", "age")
    f | should.have.attribute("name")  # singular alias
    f | should.have.attributes("name", "age")  # plural alias

    Foo | should.implement.methods("greet", "shout")
    Foo | should.implement.method("greet")
    Foo | should.implements.method("greet")  # alias
    Foo | should.implement.interface("greet", "shout")  # interface alias

    # implement works on instances too, not just classes
    f | should.implement.method("greet")
    f | should.implements.method("shout")

    # `>` chain rebinds subject to the property value
    f | should.have.property("name") > should.be.equal.to("alice")
    f | should.have.property("age") > should.be.above(20)

    # Negation
    f | should.not_have.property("missing")
    Foo | should.do_not.implement.method("missing")

    with pytest.raises(AssertionError):
        f | should.have.property("missing")
    with pytest.raises(AssertionError):
        f | should.have.properties("name", "missing")
    with pytest.raises(AssertionError):
        Foo | should.implement.methods("missing")
    with pytest.raises(AssertionError):
        # name exists as a class attribute but is not a method
        Foo | should.implement.method("name")
    with pytest.raises(AssertionError):
        # property value mismatch through > chain
        f | should.have.property("name") > should.be.equal.to("WRONG")


# ---------------------------------------------------------------------------
# Callable / raises
# ---------------------------------------------------------------------------


def test_callable_and_raises_operators():
    """``callable`` accessor; ``raises`` / ``raise_error`` / ``raise_errors``.

    A callable subject is anything that ``callable(x)`` returns true for —
    functions, methods, lambdas, classes, ``__call__``-bearing objects.
    ``raise_error(ExceptionType)`` asserts the supplied zero-arg callable
    raises an exception of that type when invoked.
    """
    (lambda x: x) | should.be.callable
    test_callable_and_raises_operators | should.be.callable

    class C:
        def __call__(self):
            pass

    C() | should.be.callable

    None | should.not_be.callable

    with pytest.raises(AssertionError):
        "foo" | should.be.callable
    with pytest.raises(AssertionError):
        123 | should.be.callable

    # raises
    def bad():
        raise ValueError("nope")

    bad | should.raise_error(ValueError)
    bad | should.raise_error(Exception)  # superclass
    bad | should.raises(ValueError)  # alias
    bad | should.raise_errors(ValueError)  # plural alias
    bad | should.do_not.raise_error(KeyError)  # different type

    # raise_error with > chains the error message as the new subject
    bad | should.raise_error(ValueError) > should.equal("nope")
    bad | should.raise_error(ValueError) > should.contain("nope")

    # multi-arg exception: rebound subject is the args concatenated by space
    def bad_multi():
        raise RuntimeError("part1", "part2")

    bad_multi | should.raise_error(RuntimeError) > should.contain("part1")
    bad_multi | should.raise_error(RuntimeError) > should.contain("part2")

    def safe():
        return 1

    with pytest.raises(AssertionError):
        safe | should.raise_error(ValueError)
    with pytest.raises(AssertionError):
        bad | should.raise_error(KeyError)
    with pytest.raises(AssertionError):
        # Subject must be callable
        None | should.raise_error(ValueError)
    with pytest.raises(AssertionError):
        # Non-callable subject must fail (not crash)
        "not callable" | should.raise_error(ValueError)

    # > chain failure surfaces the WRONG-MSG sentinel — and the actual
    # exception message ("nope") must also appear, confirming that the >
    # operator did rebind the subject to the exception text rather than
    # silently running the second assertion against the callable.
    with pytest.raises(AssertionError) as exc_info:
        bad | should.raise_error(ValueError) > should.equal("WRONG-MSG")
    msg = str(exc_info.value)
    assert "WRONG-MSG" in msg
    assert "nope" in msg


# ---------------------------------------------------------------------------
# Functional predicates: pass_test / pass_function
# ---------------------------------------------------------------------------


def test_pass_test_and_pass_function():
    """``pass_test`` / ``pass_function`` apply the user-supplied predicate
    to the subject; truthy result means the assertion holds.  Lambdas and
    named functions both qualify; arbitrary callables (e.g. classes) do not.
    """

    def has_len_three(x):
        return len(x) == 3

    "foo" | should.pass_test(has_len_three)
    "foo" | should.pass_function(lambda x: x == "foo")
    [1, 2, 3] | should.pass_test(lambda x: sum(x) == 6)

    "fo" | should.do_not.pass_test(has_len_three)

    with pytest.raises(AssertionError):
        "foobar" | should.pass_test(has_len_three)
    with pytest.raises(AssertionError):
        [1, 2, 3] | should.pass_function(lambda x: sum(x) == 0)


# ---------------------------------------------------------------------------
# Composition: all / any
# ---------------------------------------------------------------------------


def test_all_and_any_composition():
    """``all(*tests)`` and ``any(*tests)`` compose multiple sub-assertions
    against the same subject.  ``all`` requires every assertion to pass;
    ``any`` requires at least one.
    """
    "foo" | should.all(should.be.a("string"), should.have.length.of(3))
    "foo" | should.any(should.be.a("number"), should.have.length.of(3))

    with pytest.raises(AssertionError):
        "foo" | should.all(should.be.a("string"), should.have.length.of(5))
    with pytest.raises(AssertionError):
        "foo" | should.any(should.be.a("number"), should.have.length.of(5))


# ---------------------------------------------------------------------------
# DSL plumbing: | pipe, > chain, with context-manager
# ---------------------------------------------------------------------------


def test_pipe_and_chain_operators_propagate_subject():
    """The ``|`` operator pipes a subject into an assertion chain.
    The ``>`` operator chains a SECOND assertion against whatever new
    subject the previous matcher exposed (e.g. ``have.key('x')`` exposes
    the value at that key; ``have.index.at(i)`` exposes the i-th item;
    ``have.property('p')`` exposes the property value).  ``expect`` is
    interchangeable with ``should`` on either side of a ``>``.
    """
    # key chain — subject becomes the value at the key
    {"foo": "bar"} | should.have.key("foo") > should.be.equal.to("bar")

    # Deep chain
    payload = {"users": [{"name": "alice"}]}
    payload | should.have.key("users") > should.be.a("list") > should.have.length.of(1)

    # index chain — subject becomes the item at that index
    [10, 20, 30] | should.have.index.at(1) > should.be.equal.to(20)

    # property chain — subject becomes the attribute value
    class P:
        port = 8080

    P() | should.have.property("port") > should.be.equal.to(8080)

    # expect on either side of > must work the same as should
    {"foo": "bar"} | expect.to.have.key("foo") > expect.to.be.equal.to("bar")
    {"foo": "bar"} | should.have.key("foo") > expect.to.be.equal.to("bar")

    # > chain across three levels rebinds the subject TWICE (not once)
    deep = {"outer": {"inner": "value"}}
    deep | should.have.key("outer") > should.have.key("inner") > should.be.equal.to(
        "value"
    )

    # Failures must surface even mid-chain
    with pytest.raises(AssertionError) as exc_info:
        {"foo": "bar"} | should.have.key("foo") > should.be.equal.to("WRONG")
    # The failure message must mention BOTH the rebound value 'bar' and the
    # expected 'WRONG' — confirms that the > chain did rebind the subject,
    # rather than (a broken implementation) running the second assertion
    # against the original {} subject (which would mention 'foo' not 'bar').
    msg = str(exc_info.value)
    assert "WRONG" in msg
    assert "bar" in msg

    with pytest.raises(AssertionError):
        [10, 20, 30] | should.have.index.at(0) > should.be.equal.to(99)
    with pytest.raises(AssertionError):
        # Deep > chain failure surfaces
        deep | should.have.key("outer") > should.have.key("inner") > should.be.equal.to(
            "WRONG"
        )

    # Four-level > chain — exercises the runner's mid-chain rebinding across
    # multiple operators in series (each step rebinds the subject before the
    # next assertion runs). A broken runner that loses the rebinding after
    # the first hop would let the deep assertion silently pass against the
    # wrong subject — this catches that class of bug.
    nested = {"a": {"b": {"c": "deep_value"}}}
    nested | should.have.key("a") > should.have.key("b") > should.have.key(
        "c"
    ) > should.be.equal.to("deep_value")
    with pytest.raises(AssertionError):
        nested | should.have.key("a") > should.have.key("b") > should.have.key(
            "c"
        ) > should.be.equal.to("WRONG")


def test_context_manager_binds_subject_implicitly():
    """``with should(value):`` (and ``with expect(value):``) bind ``value``
    as the implicit subject of every assertion inside the block, so the
    user does not need to repeat ``value |`` for each call.  An assertion
    failure inside the block must propagate out as ``AssertionError``.
    """
    with should("hello"):
        should.be.equal.to("hello")
        should.be.a("string")
        should.have.length.of(5)
        should.startswith("he")
        should.endswith("lo")
        should.contain("ell")

    with expect("hello"):
        expect.to.be.equal.to("hello")
        expect.to.have.length.of(5)

    # Failure inside the block must escape
    with pytest.raises(AssertionError):
        with should("hello"):
            should.be.equal.to("hello")
            should.have.length.of(99)  # this fails

    # The implicit-subject block also works with `expect` style
    with expect([1, 2, 3]):
        expect.to.be.a("list")
        expect.to.have.length.of(3)
        expect.to.contain(2)


# ---------------------------------------------------------------------------
# Negation grammar (all the keyword aliases)
# ---------------------------------------------------------------------------


def test_negation_keywords_invert_assertions():
    """Negation attributes (``not_be``, ``not_have``, ``do_not``,
    ``does_not``, ``to_not``, ``not_to``, ``dont``, etc.) flip the
    assertion result without otherwise changing semantics.  Verifies that
    the keyword grammar (positive: ``be``/``have``/``to``/``that``;
    negative: ``not_*``/``*_not``/``do_not``/...) is preserved.
    """
    # Positive grammar — keyword aliases stack freely before the matcher
    "foo" | should.be.equal.to("foo")
    "foo" | should.that.equal("foo")
    "foo" | should.which.equal("foo")
    [1] | should.have.length.of(1)
    "foo" | expect.to.equal("foo")
    "foo" | expect.to.have.length.of(3)

    # Negative grammar — multiple aliases must all work
    "foo" | should.not_be.equal.to("bar")
    "foo" | should.do_not.equal("bar")
    "foo" | should.does_not.equal("bar")
    [1] | should.not_have.length.of(99)
    "foo" | expect.to_not.equal("bar")
    "foo" | expect.not_to.equal("bar")

    # Failures
    with pytest.raises(AssertionError):
        "foo" | should.not_be.equal.to("foo")
    with pytest.raises(AssertionError):
        "foo" | should.do_not.equal("foo")
    with pytest.raises(AssertionError):
        [1] | should.not_have.length.of(1)


# ---------------------------------------------------------------------------
# Extensibility: @operator decorator
# ---------------------------------------------------------------------------


def test_decorator_family_registers_matcher_and_attribute_keywords():
    """The ``@operator`` and ``@attribute`` decorator family registers new
    keywords on ``should`` / ``expect`` from a plain function.

    * ``@operator`` registers a MATCHER: the function receives
      ``(subject, expected)`` and returns a bool (or a ``(bool, reasons)``
      tuple).  All registered keyword names become chainable members.
    * ``@attribute`` registers an ATTRIBUTE-kind keyword: a chain keyword
      that performs no assertion of its own but exposes extra DSL grammar
      and can appear anywhere in a chain without changing the result.

    Both decorators dispatch through the same registration machinery
    (differing only in operator ``kind``), so a single test exercises the
    shared code path while still covering both surface forms.
    """

    # @operator — MATCHER form (function takes subject + expected)
    # Use unique names to avoid collision with the standard registry
    @operator(operators=("be_uppercased_of_xyz123", "is_uppercased_of_xyz123"))
    def be_uppercased_of(subject, expected):
        return subject == expected.upper()

    "FOO" | should.be_uppercased_of_xyz123("foo")
    "FOO" | should.is_uppercased_of_xyz123("foo")
    "FOO" | expect.to.be_uppercased_of_xyz123("foo")
    "BAR" | should.do_not.be_uppercased_of_xyz123("foo")

    with pytest.raises(AssertionError):
        "foo" | should.be_uppercased_of_xyz123("foo")
    with pytest.raises(AssertionError):
        "FOO" | should.do_not.be_uppercased_of_xyz123("foo")

    # @attribute — ATTRIBUTE form (chain keyword, side-effect only)
    state = {"hits": 0}

    @attribute(operators=("xyz_grammar_attr_abc999",))
    def my_attr(ctx):
        state["hits"] += 1

    # Attribute keyword fits anywhere in the chain without affecting result
    "foo" | should.xyz_grammar_attr_abc999.be.equal.to("foo")
    assert state["hits"] >= 1

    with pytest.raises(AssertionError):
        "foo" | should.xyz_grammar_attr_abc999.be.equal.to("bar")


def test_register_duplicate_operator_keyword_raises_value_error():
    """Registering an ``Operator`` subclass whose keyword name is already in
    use by another operator must raise ``ValueError`` — the engine refuses
    silent collisions because they would shadow existing matchers and make
    DSL behavior non-deterministic.
    """

    class FirstOpXyz(Operator):
        operators = ("collision_keyword_xyz_42",)
        kind = Operator.Type.MATCHER

        def match(self, subject, expected):
            return True, []

    class SecondOpXyz(Operator):
        operators = ("collision_keyword_xyz_42",)  # same keyword name
        kind = Operator.Type.MATCHER

        def match(self, subject, expected):
            return True, []

    register(FirstOpXyz)
    with pytest.raises(ValueError):
        register(SecondOpXyz)


def test_register_class_based_operator():
    """``register`` (also exported) installs an ``Operator`` subclass into
    the global engine.  The class declares its keyword names through the
    ``operators`` tuple and its ``kind`` (``MATCHER`` / ``ACCESSOR`` /
    ``ATTRIBUTE``).  After ``register(...)`` is called, the keywords are
    immediately chainable on ``should`` / ``expect``.
    """

    class DivisibleByOperator(Operator):
        operators = ("divisible_by_xyz789",)
        kind = Operator.Type.MATCHER

        def match(self, subject, expected):
            return (subject % expected) == 0, []

    register(DivisibleByOperator)

    10 | should.be.divisible_by_xyz789(2)
    10 | should.be.divisible_by_xyz789(5)
    10 | should.do_not.be.divisible_by_xyz789(3)

    with pytest.raises(AssertionError):
        10 | should.be.divisible_by_xyz789(3)
    with pytest.raises(AssertionError):
        10 | should.do_not.be.divisible_by_xyz789(2)


# ---------------------------------------------------------------------------
# Plugin loading via use(...)
# ---------------------------------------------------------------------------


def test_use_loads_function_and_object_plugins():
    """``use(plugin)`` installs a plugin into grappa.  A plugin is either:

    * a function that takes the global ``Engine`` and returns/registers
      whatever it likes; OR
    * an object exposing a ``register(engine)`` method.

    Any other argument must raise ``ValueError``.
    """
    state = {"fn_called": 0, "method_called": 0}

    def function_plugin(engine):
        # Engine is the global engine class with a `.register` callable
        assert hasattr(engine, "register")
        state["fn_called"] += 1

    use(function_plugin)
    assert state["fn_called"] == 1

    class ObjectPlugin:
        @staticmethod
        def register(engine):
            assert hasattr(engine, "register")
            state["method_called"] += 1

    use(ObjectPlugin)
    assert state["method_called"] == 1

    # Invalid plugin must raise ValueError
    with pytest.raises(ValueError):
        use("not a plugin")
    with pytest.raises(ValueError):
        use(123)


# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------


def test_config_settings_round_trip_and_reject_unknown_keys():
    """``config`` is a key/value store that exposes the runtime flags
    (``debug``, ``show_code``, ``use_colors``) via attribute access.

    Writing and reading must round-trip; reading or writing an unsupported
    key must raise ``ValueError``.  ``show_code`` must additionally have an
    *observable* effect: when enabled the failure message includes a code
    excerpt (a "Where" section pointing at the failing line); when
    disabled, that section must NOT appear.
    """
    # Defaults are readable
    initial_show_code = config.show_code
    initial_use_colors = config.use_colors

    # Round-trip
    config.show_code = False
    assert config.show_code is False
    config.show_code = True
    assert config.show_code is True

    config.use_colors = False
    assert config.use_colors is False

    # Observable behavior: show_code controls inclusion of the "Where"
    # source-code block in failure messages.
    try:
        config.show_code = False
        config.use_colors = False
        with pytest.raises(AssertionError) as exc_info:
            "foo" | should.be.equal.to("bar")
        msg_off = str(exc_info.value)
        assert (
            "Where" not in msg_off
        ), "show_code=False must suppress the 'Where' code block"

        config.show_code = True
        with pytest.raises(AssertionError) as exc_info:
            "foo" | should.be.equal.to("bar")
        msg_on = str(exc_info.value)
        assert "Where" in msg_on, "show_code=True must include the 'Where' code block"
    finally:
        # Restore initial state for hygiene
        config.show_code = initial_show_code
        config.use_colors = initial_use_colors

    # Unsupported keys are rejected on write
    with pytest.raises(ValueError):
        config.does_not_exist_xyz = True

    # And on read
    with pytest.raises(ValueError):
        _ = config.no_such_setting_xyz


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


def test_test_class_can_be_instantiated_directly():
    """``Test`` is the explicit class behind ``should``/``expect``.  A user
    may instantiate ``Test(subject)`` directly; attribute access on the
    instance begins the assertion chain (``Test(x).be.equal.to(y)``).
    """
    # Direct chain on the Test instance
    Test("hello").be.a("string")
    Test("foo").be.equal.to("foo")

    with pytest.raises(AssertionError):
        Test("foo").be.equal.to("bar")


# ---------------------------------------------------------------------------
# Error rendering on unknown operator
# ---------------------------------------------------------------------------


def test_unknown_operator_keyword_raises_attribute_error():
    """Looking up a non-registered keyword on ``should`` / ``expect``
    triggers an ``AttributeError`` whose message mentions the unknown
    keyword (per the public spec).
    """
    with pytest.raises(AttributeError) as exc_info:
        "foo" | should.be.totally_made_up_keyword_xyz_12345("bar")
    msg = str(exc_info.value)
    # Per spec: the error message must mention the unknown keyword.
    assert "totally_made_up_keyword_xyz_12345" in msg


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------


def test_package_exposes_working_public_api_surface():
    """Every documented public symbol must be present and importable from the
    top-level ``grappa`` package, behind a real assertion engine.

    This is the package-level integration smoke whose UNIQUE contract is the
    public-name surface check below: it guards against a *shell* package that
    re-exports the documented names without a working engine.  The behavioral
    contracts of every operator and entry point (equality, length, numeric,
    ``Test`` construction, ``config`` round-trip, ``operator`` / ``attribute`` /
    ``register`` / ``use``) are each verified by their own dedicated tests
    above, so this test does NOT re-drive them — it only asserts the public
    symbol set plus a single minimal smoke that the surface is wired to a live
    engine rather than placeholders.
    """
    # UNIQUE contract: the public API symbol set must include the documented
    # names. No other test checks the exported-name surface, so this is the
    # anti-shell-package guard.
    public_names = {
        "should",
        "expect",
        "Test",
        "use",
        "config",
        "Operator",
        "operator",
        "attribute",
        "register",
    }
    grappa_names = set(dir(grappa))
    assert public_names.issubset(grappa_names)

    # Single minimal smoke that the surface is wired to a live engine (silent
    # pass + raise on fail), not placeholders. The full behavioral coverage of
    # each operator lives in its dedicated test, so we deliberately do not
    # re-exercise equality/length/numeric/Test/config here.
    1 | grappa.should.be.equal.to(1)
    with pytest.raises(AssertionError):
        1 | grappa.should.be.equal.to(2)
