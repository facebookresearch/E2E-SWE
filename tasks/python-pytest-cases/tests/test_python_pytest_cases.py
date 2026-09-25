"""Hidden test suite for the ``python-pytest-cases`` WRG task.

``pytest-cases`` is a ``pytest`` plugin: almost all of its value is in *what test
items it generates and how* (the case ids, the item counts, the fixture-union
splitting, the parametrization). Those collection-level contracts are exercised
the way a real user observes them — by running an inner ``pytest`` session via the
bundled ``pytester`` fixture and asserting on the collected node ids and outcomes.
Pure helper functions (id generation, tag/mark introspection, ``assert_exception``)
are exercised in-process through the public surface.
"""
import re

import pytest

# Imports used directly by the in-process (non-pytester) tests below. The
# collection-level tests construct inner test modules as strings and import the
# rest of the public surface (parametrize_with_cases, parametrize, fixture,
# fixture_ref, fixture_union, param_fixture(s), unpack_fixture, get_all_cases,
# get_parametrize_args, get_current_cases, THIS_MODULE, ...) inside those modules.
from pytest_cases import (
    case,
    lazy_value,
    is_lazy,
    get_case_id,
    get_case_tags,
    get_case_marks,
    set_case_id,
    copy_case_info,
    matches_tag_query,
    is_case_class,
    is_case_function,
    with_case_tags,
    assert_exception,
    unfold_expected_err,
)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def ran(result, status="PASSED"):
    """Return the list of test node-ids (without the file prefix) that reached
    ``status`` in a ``pytester`` run, in collection order."""
    ids = []
    for line in result.outlines:
        parts = line.split()
        if len(parts) >= 2 and "::" in parts[0] and parts[1] == status:
            ids.append(parts[0].split("::", 1)[1])
    return ids


def params(result, status="PASSED"):
    """Return just the ``[...]`` parametrization id of each test that reached
    ``status`` (empty string if the test has no parameters)."""
    out = []
    for nid in ran(result, status):
        m = re.search(r"\[(.*)\]$", nid)
        out.append(m.group(1) if m else "")
    return out


# --------------------------------------------------------------------------- #
# parametrize_with_cases : collection, ids, sources, AUTO                      #
# --------------------------------------------------------------------------- #
class TestCaseCollection:
    def test_basic_collection_and_ids(self, pytester):
        """Collecting cases from the current module: the ``case_`` prefix is
        stripped to form the id, ``@case(id=...)`` overrides it, functions not
        matching the prefix are ignored, and cases keep source-code order."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases, case

            def case_simple_int():
                return 42

            def case_simple_str():
                return "hi"

            @case(id="custom")
            def case_renamed():
                return 1

            def helper_not_a_case():   # no case_ prefix -> ignored
                return 0

            @parametrize_with_cases("v", cases=".")
            def test_x(v):
                assert v is not None
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=3)
        assert ran(result) == ["test_x[simple_int]", "test_x[simple_str]", "test_x[custom]"]

    def test_collection_sources(self, pytester):
        """Cases can be drawn from an explicit module, an explicit class (which
        may have any name when passed explicitly), or an explicit case function;
        results are concatenated."""
        pytester.makepyfile(
            mycases="""
            def case_from_module():
                return "m"
            """
        )
        pytester.makepyfile(
            """
            import mycases
            from pytest_cases import parametrize_with_cases

            class Bag:           # arbitrary name, allowed because passed explicitly
                def case_in_bag(self):
                    return "b"

            def case_explicit():
                return "e"

            @parametrize_with_cases("v", cases=[mycases, Bag, case_explicit])
            def test_x(v):
                assert v in ("m", "b", "e")
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=3)
        assert set(params(result)) == {"from_module", "in_bag", "explicit"}

    def test_auto_cases_module(self, pytester):
        """With ``cases=AUTO`` (the default for ``parametrize_with_cases``), the
        cases are loaded automatically from the companion module
        ``test_<name>_cases.py`` next to ``test_<name>.py``."""
        pytester.makepyfile(
            test_primary="""
            from pytest_cases import parametrize_with_cases
            @parametrize_with_cases("v")
            def test_p(v):
                assert v > 0
            """,
            test_primary_cases="""
            def case_a():
                return 5
            def case_b():
                return 6
            """,
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)
        assert set(ran(result)) == {"test_p[a]", "test_p[b]"}

    def test_filtering(self, pytester):
        """Cases are filtered by ``has_tag``, by a glob pattern on the case id,
        and by ``filter`` callables (including the composable filters in
        ``pytest_cases.filters``)."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases, case
            from pytest_cases.filters import has_tag

            @case(tags=["fast"])
            def case_quick():
                return 1

            @case(tags=["slow"])
            def case_heavy():
                return 2

            def case_quick_extra():
                return 3

            @parametrize_with_cases("v", cases=".", has_tag="fast")
            def test_tag(v):
                pass

            @parametrize_with_cases("v", cases=".", glob="quick*")
            def test_glob(v):
                pass

            @parametrize_with_cases("v", cases=".", filter=has_tag("slow"))
            def test_filter(v):
                pass
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=4)
        assert ran(result, "PASSED") == [
            "test_tag[quick]",
            "test_glob[quick]",
            "test_glob[quick_extra]",
            "test_filter[heavy]",
        ]

    def test_case_requiring_fixture(self, pytester):
        """A case function that requests a fixture is turned into a fixture
        reference behind the scenes: the fixture is injected and its value flows
        into the test, while the case id is preserved."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases, fixture

            @fixture
            def token():
                return "T"

            def case_uses_fixture(token):
                return token + "!"

            def case_plain():
                return "P"

            @parametrize_with_cases("v", cases=".")
            def test_x(v):
                assert v in ("T!", "P")
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)
        assert set(params(result)) == {"uses_fixture", "plain"}

    def test_parametrized_case_becomes_fixture(self, pytester):
        """A parametrized case (``@parametrize`` on the case function) expands to
        one item per parameter, with ids of the form ``<caseid>-<paramid>``."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases, parametrize

            @parametrize("n", [1, 2, 3])
            def case_scaled(n):
                return n * 10

            def case_plain():
                return 0

            @parametrize_with_cases("v", cases=".")
            def test_x(v):
                assert v in (0, 10, 20, 30)
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=4)
        assert set(params(result)) == {"scaled-1", "scaled-2", "scaled-3", "plain"}

    def test_multi_argname_cases(self, pytester):
        """``parametrize_with_cases`` accepts several argnames; each case returns
        a tuple that is unpacked into those names."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases

            def case_low():
                return 1, 2

            def case_high():
                return 10, 20

            @parametrize_with_cases("a,b", cases=".")
            def test_x(a, b):
                assert b == 2 * a
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)
        assert set(params(result)) == {"low", "high"}

    def test_get_current_cases(self, pytester):
        """The ``current_cases`` fixture (and ``get_current_cases``) expose, for
        the active item, a ``{argname: (id, function, params)}`` mapping where the
        case parameters are included when the case is itself parametrized."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases, parametrize, get_current_cases

            def case_alpha():
                return 1

            @parametrize("k", [7])
            def case_beta(k):
                return k

            @parametrize_with_cases("v", cases=".")
            def test_x(v, current_cases, request):
                info = current_cases["v"]
                # namedtuple fields: id, func, params -- pin the exact (id, func,
                # params) per branch, not just a shape check.
                assert get_current_cases(request) == current_cases
                if v == 7:
                    assert info.id == "beta"
                    assert info.func is case_beta
                    assert info.params == {"k": 7}
                else:
                    assert info.id == "alpha"
                    assert info.func is case_alpha
                    assert info.params == {}
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)

    def test_parametrize_with_cases_on_fixture(self, pytester):
        """``@parametrize_with_cases`` can decorate a *fixture* (not just a test
        function): the fixture is expanded once per collected case, the items use
        the plain case ids, and a test requesting the fixture runs once per case
        with that case's value flowing through the fixture."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases, fixture

            def case_one():
                return 1

            def case_two():
                return 2

            @fixture
            @parametrize_with_cases("v", cases=".")
            def myfix(v):
                return v * 10

            def test_uses(myfix):
                assert myfix in (10, 20)
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)
        assert set(params(result)) == {"one", "two"}


# --------------------------------------------------------------------------- #
# enhanced @parametrize : plain values, lazy_value, fixture_ref                #
# --------------------------------------------------------------------------- #
class TestParametrize:
    def test_parametrize_basics(self, pytester):
        """The enhanced ``@parametrize`` behaves like ``pytest.mark.parametrize``
        for plain values: a comma-separated argnames string is unpacked from
        tuples, custom ``ids`` are honoured, and ``pytest.param(..., marks=)``
        marks individual values."""
        pytester.makepyfile(
            """
            import pytest
            from pytest_cases import parametrize

            @parametrize("a,b", [(1, 2), (3, 4)])
            def test_tuple(a, b):
                assert a < b

            @parametrize("x", [1, 2], ids=["one", "two"])
            def test_ids(x):
                pass

            @parametrize("y", [1, pytest.param(2, marks=pytest.mark.skip)])
            def test_marked(y):
                pass
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=5, skipped=1)
        assert "test_tuple[1-2]" in ran(result)
        assert "test_tuple[3-4]" in ran(result)
        assert {"test_ids[one]", "test_ids[two]"} <= set(ran(result))

    def test_parametrize_lazy_value(self, pytester):
        """``lazy_value`` defers calling its value-getter until the test runs
        (not at collection time) and uses the getter name as the id; ``is_lazy``
        recognises such values."""
        assert is_lazy(lazy_value(lambda: 1)) is True
        assert is_lazy(5) is False

        pytester.makepyfile(
            """
            from pytest_cases import parametrize, lazy_value

            called = []

            def make_value():
                called.append(1)
                return 99

            @parametrize("v", [lazy_value(make_value)])
            def test_lazy(v):
                # the getter is only called now, at test execution time
                assert called == [1]
                assert v == 99

            def test_not_called_at_collection():
                # collection of test_lazy must not have triggered make_value
                assert called == [] or called == [1]
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)
        assert "test_lazy[make_value]" in ran(result)

    def test_parametrize_fixture_ref(self, pytester):
        """``fixture_ref`` lets a fixture be used as one of the argvalues in
        ``@parametrize``: the test is expanded so plain values keep their ids and
        the fixture contributes an item identified by the fixture name, resolving
        to the fixture's value."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize, fixture, fixture_ref

            @fixture
            def special():
                return 100

            @parametrize("v", [1, 2, fixture_ref(special)])
            def test_x(v):
                assert v in (1, 2, 100)
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=3)
        assert set(params(result)) == {"1", "2", "special"}


# --------------------------------------------------------------------------- #
# fixtures : unions, parametrized fixtures, param_fixture(s), unpack_fixture   #
# --------------------------------------------------------------------------- #
class TestFixtures:
    def test_fixture_union(self, pytester):
        """``fixture_union`` makes a fixture whose value comes from one of the
        member fixtures; a test using it is expanded into one item per member.
        The ``idstyle`` controls the parametrization id: ``'compact'`` yields
        ``/<member>`` while ``'explicit'`` yields ``<union>/<member>``."""
        pytester.makepyfile(
            """
            from pytest_cases import fixture, fixture_union

            @fixture
            def first():
                return "1"

            @fixture
            def second():
                return "2"

            u_compact = fixture_union("u_compact", [first, second], idstyle="compact")
            u_explicit = fixture_union("u_explicit", [first, second], idstyle="explicit")

            def test_compact(u_compact):
                assert u_compact in ("1", "2")

            def test_explicit(u_explicit):
                assert u_explicit in ("1", "2")
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=4)
        ids = set(params(result))
        assert {"/first", "/second"} <= ids
        assert {"u_explicit/first", "u_explicit/second"} <= ids

    def test_parametrized_fixture(self, pytester):
        """``@fixture`` is an enhanced ``pytest.fixture`` that supports
        ``@parametrize`` directly on a fixture and a custom ``name=``; using the
        fixture expands the test once per fixture parameter."""
        pytester.makepyfile(
            """
            from pytest_cases import fixture, parametrize

            @fixture(name="base")
            @parametrize("raw", [2, 5])
            def base_fixture(raw):
                return raw * 10

            def test_x(base):
                assert base in (20, 50)
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)
        assert set(params(result)) == {"2", "5"}

    def test_param_fixture_and_fixtures(self, pytester):
        """``param_fixture`` creates a single parameter-driven fixture and
        ``param_fixtures`` creates several at once from tuples."""
        pytester.makepyfile(
            """
            from pytest_cases import param_fixture, param_fixtures

            color = param_fixture("color", ["red", "green"])

            def test_one(color):
                assert color in ("red", "green")

            width, height = param_fixtures("width,height", [(1, 2), (3, 4)])

            def test_two(width, height):
                assert height > width
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=4)
        assert set(params(result)) == {"red", "green", "1-2", "3-4"}

    def test_unpack_fixture(self, pytester):
        """``unpack_fixture`` splits a fixture that returns a tuple into several
        independent fixtures."""
        pytester.makepyfile(
            """
            from pytest_cases import fixture, unpack_fixture

            @fixture
            def point():
                return (10, 20)

            x, y = unpack_fixture("x,y", point)

            def test_x(x, y):
                assert x == 10
                assert y == 20
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)


# --------------------------------------------------------------------------- #
# case introspection helpers (pure, in-process)                               #
# --------------------------------------------------------------------------- #
class TestCaseIntrospection:
    def test_case_id_generation(self):
        """``get_case_id`` derives the id from the function name by stripping the
        prefix, honours an explicit id from ``@case`` / ``set_case_id``, returns
        ``<empty_case_id>`` when stripping leaves nothing, and keeps the full
        name when the prefix is absent."""
        def case_hello():
            return 1
        assert get_case_id(case_hello) == "hello"

        @case(id="explicit")
        def case_x():
            return 1
        assert get_case_id(case_x) == "explicit"

        def case_():
            return 1
        assert get_case_id(case_) == "<empty_case_id>"

        def data_thing():
            return 1
        assert get_case_id(data_thing) == "data_thing"          # default prefix not present
        assert get_case_id(data_thing, prefix_for_default_ids="data_") == "thing"

        def case_set():
            return 1
        set_case_id("forced", case_set)
        assert get_case_id(case_set) == "forced"

    def test_case_tags_and_marks(self):
        """Tags and marks attached via ``@case`` are retrievable with
        ``get_case_tags`` / ``get_case_marks``; ``with_case_tags`` tags every
        case in a class, ``copy_case_info`` copies metadata across functions, and
        ``matches_tag_query`` answers tag/filter queries."""
        @case(tags=["fast", "io"], marks=pytest.mark.skip)
        def case_a():
            return 1

        assert set(get_case_tags(case_a)) == {"fast", "io"}
        assert [m.name for m in get_case_marks(case_a)] == ["skip"]

        assert matches_tag_query(case_a, has_tag="fast") is True
        assert matches_tag_query(case_a, has_tag="missing") is False
        assert matches_tag_query(case_a, filter=lambda f: "io" in get_case_tags(f)) is True

        @with_case_tags("net")
        class TaggedCases:
            def case_one(self):
                return 1
            def case_two(self):
                return 2
        assert "net" in get_case_tags(TaggedCases.case_one)
        assert "net" in get_case_tags(TaggedCases.case_two)

        def case_src():
            return 1
        def case_dst():
            return 2
        set_case_id("shared", case_src)
        copy_case_info(case_src, case_dst)
        assert get_case_id(case_dst) == "shared"

    def test_is_case_helpers(self):
        """``is_case_class`` / ``is_case_function`` implement the default naming
        rules (``*Case*`` classes, ``case_`` functions) and can ignore the name
        check when asked."""
        class MyCaseHolder:
            pass
        class Plain:
            pass
        assert is_case_class(MyCaseHolder) is True
        assert is_case_class(Plain) is False
        assert is_case_class(Plain, check_name=False) is True

        def case_yes():
            return 1
        def nope():
            return 1
        assert is_case_function(case_yes) is True
        assert is_case_function(nope) is False
        assert is_case_function(nope, check_prefix=False) is True
        assert is_case_function(MyCaseHolder) is False


# --------------------------------------------------------------------------- #
# misc helpers : assert_exception / unfold_expected_err / programmatic API     #
# --------------------------------------------------------------------------- #
class TestHelpers:
    def test_exception_helpers(self):
        """``assert_exception`` is a context manager that validates a raised
        exception by type, by regex on its repr, by a validation callable, or by
        an exception *instance* (which checks both the type and ``==`` equality),
        and raises an ``AssertionError`` subclass when the check fails.
        ``unfold_expected_err`` normalises those same four accepted forms into
        the ``(error_type, pattern, instance, validator)`` 4-tuple."""
        with assert_exception(ValueError):
            raise ValueError("boom")

        with assert_exception("ValueError.*boom"):
            raise ValueError("boom")

        with assert_exception(lambda e: isinstance(e, KeyError)):
            raise KeyError("k")

        with pytest.raises(AssertionError):
            with assert_exception(KeyError):
                raise ValueError("wrong type")

        # Exception-instance spec: matching type AND equality passes.
        class MyExc(Exception):
            def __eq__(self, other):
                return type(self) is type(other) and self.args == other.args

            def __hash__(self):
                return hash(self.args)

        with assert_exception(MyExc("hello")):
            raise MyExc("hello")

        # Right type but unequal value -> the equality check fails.
        with pytest.raises(AssertionError):
            with assert_exception(MyExc("hello")):
                raise MyExc("different")

        # Equal-looking but wrong type -> the type check fails.
        with pytest.raises(AssertionError):
            with assert_exception(MyExc("hello")):
                raise Exception("hello")

        # The same four forms, normalised by unfold_expected_err into
        # (error_type, pattern, instance, validator).
        etype, patt, inst, valid = unfold_expected_err(ValueError)
        assert etype is ValueError and patt is None and inst is None and valid is None

        etype, patt, inst, valid = unfold_expected_err("some.*regex")
        assert etype is BaseException and patt is not None and patt.pattern == "some.*regex"
        assert inst is None and valid is None

        sentinel = ValueError("x")
        etype, patt, inst, valid = unfold_expected_err(sentinel)
        assert etype is ValueError and patt is None and inst is sentinel and valid is None

        def fn(e):
            return True

        etype, patt, inst, valid = unfold_expected_err(fn)
        assert etype is BaseException and patt is None and inst is None and valid is fn

    def test_get_all_cases_and_args(self, pytester):
        """``get_all_cases`` + ``get_parametrize_args`` reproduce, step by step,
        what ``parametrize_with_cases`` does: collecting (and filtering) the case
        functions, then turning them into argvalues."""
        pytester.makepyfile(
            """
            from pytest_cases import get_all_cases, get_parametrize_args, get_case_id, THIS_MODULE

            def case_one():
                return 1
            def case_two_success():
                return 2
            def case_three_success():
                return 3

            def test_programmatic():
                allc = get_all_cases(test_programmatic, cases=THIS_MODULE)
                assert [get_case_id(c) for c in allc] == ["one", "two_success", "three_success"]

                filtered = get_all_cases(test_programmatic, cases=THIS_MODULE, glob="*_success")
                assert [get_case_id(c) for c in filtered] == ["two_success", "three_success"]

                import sys
                mod = sys.modules[__name__]
                argvals = get_parametrize_args(mod, allc, prefix="case_")
                assert len(argvals) == 3
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)


# --------------------------------------------------------------------------- #
# advanced fixture / parametrization machinery                                #
# --------------------------------------------------------------------------- #
class TestAdvanced:
    def test_nested_fixture_union(self, pytester):
        """A ``fixture_union`` may itself contain other unions; a test using the
        outer union is expanded across the flattened members, the compact ids
        reflecting the nesting (``/u1-/a``, ``/u1-/b``, ``/c``)."""
        pytester.makepyfile(
            """
            from pytest_cases import fixture, fixture_union

            @fixture
            def a():
                return 1

            @fixture
            def b():
                return 2

            @fixture
            def c():
                return 3

            u1 = fixture_union("u1", [a, b])
            u2 = fixture_union("u2", [u1, c])

            def test_x(u2):
                assert u2 in (1, 2, 3)
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=3)
        assert set(params(result)) == {"/u1-/a", "/u1-/b", "/c"}

    def test_fixture_unpack_into(self, pytester):
        """``@fixture(unpack_into="x,y")`` splits a fixture that returns a tuple
        into the named fixtures directly, without a separate ``unpack_fixture``
        call."""
        pytester.makepyfile(
            """
            from pytest_cases import fixture

            @fixture(unpack_into="x,y")
            def coords():
                return (10, 20)

            def test_x(x, y):
                assert x == 10
                assert y == 20
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_fixture_ref_to_parametrized_fixture(self, pytester):
        """When a ``fixture_ref`` in ``@parametrize`` points at a *parametrized*
        fixture, the reference contributes one item per fixture parameter
        (cross-product), each id combining fixture name and parameter id."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize, fixture, fixture_ref

            @fixture
            @parametrize("w", [1, 2])
            def wf(w):
                return w

            @parametrize("v", [10, fixture_ref(wf)])
            def test_x(v):
                assert v in (10, 1, 2)
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=3)
        assert set(params(result)) == {"10", "wf-1", "wf-2"}

    def test_parametrize_with_cases_ids_callable(self, pytester):
        """``parametrize_with_cases(ids=<callable>)`` builds each parametrization
        id by calling the callable with the (original) case function."""
        pytester.makepyfile(
            """
            from pytest_cases import parametrize_with_cases, get_case_id

            def case_one():
                return 1

            def case_two():
                return 2

            @parametrize_with_cases("v", cases=".", ids=lambda f: "ID_" + get_case_id(f))
            def test_x(v):
                pass
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=2)
        assert set(params(result)) == {"ID_one", "ID_two"}

    def test_generator_fixture(self, pytester):
        """``@fixture`` supports generator (``yield``) fixtures, including when
        parametrized: the pre-yield value is injected once per parameter and the
        post-yield teardown runs for each (the distinguishing trait vs a plain
        return fixture)."""
        pytester.makepyfile(
            """
            from pytest_cases import fixture, parametrize

            produced = []
            torn_down = []

            @fixture
            @parametrize("n", [1, 2])
            def gen(n):
                value = n * 10
                produced.append(value)
                yield value
                torn_down.append(value)

            def test_x(gen):
                assert gen in (10, 20)

            def test_teardown_ran():
                # Collected/run after both parametrized test_x items, so each gen
                # value was injected pre-yield and its teardown executed post-yield.
                assert set(produced) == {10, 20}
                assert set(torn_down) == {10, 20}
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=3)
        assert set(params(result)) == {"1", "2", ""}
