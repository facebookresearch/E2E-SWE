"""Tests for pytest-check, a pytest plugin that allows multiple failures per test.

pytest-check turns assertions into "soft checks": a failing check is logged but does not
stop the test, so a single test can report many failures at once. Because a failing check
makes the *containing* test fail at teardown, the failure-path behaviour is exercised through
pytest's bundled ``pytester`` fixture — an inner test file is generated, run with
``runpytest``, and its outcomes/output are asserted (mirroring how a real user runs pytest
with the plugin installed). Passing-path behaviour and direct return values are tested
in-process.

The ``pytester`` fixture is enabled with ``-p pytester`` (see tests/test.sh).
"""

import pytest

import pytest_check
from pytest_check import any_failures, check, check_func, raises


def _count_failure_blocks(result) -> int:
    """Count the plugin's ``FAILURE:`` report blocks in the failure report.

    Each recorded soft failure is rendered as one line that *starts* with ``FAILURE:`` (the
    per-failure block header). Counting only those block-header lines — rather than every raw
    ``FAILURE:`` substring anywhere in stdout — avoids miscounting pytest's own short-test-summary
    line, whose text is implementation-dependent (the plugin may surface the failure to pytest via
    an exception whose message begins with the documented ``FAILURE:`` prefix).
    """
    return sum(1 for line in result.stdout.lines if line.lstrip().startswith("FAILURE:"))


# --------------------------------------------------------------------------- #
# Passing path: check functions return True and log nothing (tested directly).
# --------------------------------------------------------------------------- #
class TestCheckFunctionsPass:
    def test_all_check_functions_return_true_on_success(self) -> None:
        """Every public check function returns True for a satisfied condition and logs
        no failure (so this test passes)."""
        same = object()
        assert pytest_check.equal(1, 1) is True
        assert pytest_check.not_equal(1, 2) is True
        assert pytest_check.is_(same, same) is True
        assert pytest_check.is_not(same, object()) is True
        assert pytest_check.is_true(1) is True
        assert pytest_check.is_false(0) is True
        assert pytest_check.is_none(None) is True
        assert pytest_check.is_not_none(0) is True
        assert pytest_check.is_nan(float("nan")) is True
        assert pytest_check.is_not_nan(1.0) is True
        assert pytest_check.is_in(2, [1, 2, 3]) is True
        assert pytest_check.is_not_in(9, [1, 2, 3]) is True
        assert pytest_check.is_instance(1, int) is True
        assert pytest_check.is_not_instance(1, str) is True
        assert pytest_check.almost_equal(1.0, 1.0 + 1e-9) is True
        assert pytest_check.not_almost_equal(1.0, 2.0) is True
        assert pytest_check.greater(2, 1) is True
        assert pytest_check.greater_equal(2, 2) is True
        assert pytest_check.less(1, 2) is True
        assert pytest_check.less_equal(2, 2) is True
        assert pytest_check.between(2, 1, 3) is True            # 1 < 2 < 3
        assert pytest_check.between(1, 1, 3, ge=True) is True   # 1 <= 1 < 3
        assert pytest_check.between(3, 1, 3, le=True) is True   # 1 < 3 <= 3
        assert pytest_check.between_equal(1, 1, 3) is True      # 1 <= 1 <= 3
        assert any_failures() is False

    def test_check_object_accessors_match_module_functions(self) -> None:
        """The same check functions are reachable as attributes of the ``check`` object."""
        assert check.equal(1, 1) is True
        assert check.greater(5, 1) is True
        assert check.is_in("a", "abc") is True
        assert check.is_instance("x", str) is True
        assert any_failures() is False


# --------------------------------------------------------------------------- #
# raises(): passing path (tested directly, the expected exception is suppressed).
# --------------------------------------------------------------------------- #
class TestRaisesPass:
    def test_context_manager_suppresses_expected_exception(self) -> None:
        with raises(ValueError):
            raise ValueError("boom")

    def test_exposes_caught_exception_value(self) -> None:
        with raises(ValueError) as excinfo:
            raise ValueError("the message")
        assert str(excinfo.value) == "the message"

    def test_accepts_multiple_exception_types(self) -> None:
        with raises((ValueError, TypeError)):
            raise TypeError
        with raises((ValueError, TypeError)):
            raise ValueError

    def test_function_form_passes_args_and_kwargs(self) -> None:
        def assert_equal(a, b=None):
            assert a == b

        raises(AssertionError, assert_equal, 1, b=2)


# --------------------------------------------------------------------------- #
# assert_equal(): a hard assert (raises immediately), not a soft check.
# --------------------------------------------------------------------------- #
class TestAssertEqual:
    def test_passes_silently_when_equal(self) -> None:
        assert pytest_check.assert_equal(1, 1) is None

    def test_raises_assertionerror_when_not_equal(self) -> None:
        with pytest.raises(AssertionError):
            pytest_check.assert_equal(1, 2, "not equal")


# --------------------------------------------------------------------------- #
# check_func(): decorator turning an assert-based function into a soft check.
# --------------------------------------------------------------------------- #
class TestCheckFunc:
    def test_returns_true_when_inner_assert_passes(self) -> None:
        @check_func
        def is_even(n):
            assert n % 2 == 0

        assert is_even(4) is True
        assert any_failures() is False


# --------------------------------------------------------------------------- #
# Failure path + plugin integration, exercised via the ``pytester`` fixture.
# --------------------------------------------------------------------------- #
class TestFailuresReported:
    def test_multiple_failing_checks_collected_in_one_test(self, pytester) -> None:
        """A failing check does not stop the test; all failures are collected and the
        test fails exactly once with a 'Failed Checks: N' summary."""
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_many():
                check.equal(1, 2)
                check.equal(3, 4)
                check.is_true(False)
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1, passed=0)
        result.stdout.fnmatch_lines(["*FAILURE: check 1 == 2*"])
        result.stdout.fnmatch_lines(["*FAILURE: check 3 == 4*"])
        result.stdout.fnmatch_lines(["*Failed Checks: 3*"])
        assert _count_failure_blocks(result) == 3

    def test_each_check_function_logs_a_failure(self, pytester) -> None:
        """Each check function logs one failure for an unsatisfied condition."""
        pytester.makepyfile(
            """
            import pytest_check as c

            def test_fns():
                c.equal(1, 2)
                c.not_equal(1, 1)
                c.is_(object(), object())
                c.is_true(False)
                c.is_false(True)
                c.is_none(1)
                c.is_not_none(None)
                c.is_in(9, [1, 2])
                c.is_instance(1, str)
                c.greater(1, 2)
                c.less(2, 1)
                c.between(5, 1, 3)
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 12*"])
        # The documented per-check renderings appear verbatim (in source order).
        result.stdout.fnmatch_lines(
            [
                "*FAILURE: check 1 != 1*",
                "*FAILURE: check bool(False)*",
                "*FAILURE: check 1 > 2*",
                "*FAILURE: check 2 < 1*",
                "*FAILURE: check 1 < 5 < 3*",
            ]
        )
        assert _count_failure_blocks(result) == 12


class TestContextManager:
    def test_with_check_captures_assert_and_continues(self, pytester) -> None:
        """`with check:` captures an AssertionError, logs it, and lets the test continue."""
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_cm():
                with check:
                    assert 1 == 2
                with check:
                    assert "a" == "b"
                check.equal("reached", "reached")
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 2*"])

    def test_with_check_message_appears_in_output(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_cm_msg():
                with check("values should match"):
                    assert 1 == 2
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*FAILURE: *values should match*"])


class TestRaisesFailures:
    def test_wrong_exception_is_logged_as_failure(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import raises

            def test_wrong():
                with raises(ValueError):
                    raise TypeError("nope")
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*FAILURE: nope*"])

    def test_missing_exception_is_logged_as_failure(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import raises

            def test_missing():
                with raises(ValueError):
                    pass
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 1*"])

    def test_msg_kwarg_appears_in_failure_output(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import raises

            def test_msg():
                with raises(ValueError, msg="custom raise msg"):
                    raise TypeError
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*FAILURE: custom raise msg*"])

    def test_check_raises_accessor_logs_wrong_exception_as_soft_failure(self, pytester) -> None:
        """`check.raises` is the soft `raises`: a wrong exception inside the block is logged
        as a soft failure (not propagated), so the line after the block still runs."""
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_accessor():
                with check.raises(ValueError):
                    raise TypeError("boom")
                check.equal("ran-after", "ran-after")
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*FAILURE: boom*"])
        result.stdout.fnmatch_lines(["*Failed Checks: 1*"])


class TestFailAndCheckFunc:
    def test_fail_logs_an_explicit_failure(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_fail():
                check.fail("explicit failure")
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*FAILURE: explicit failure*"])

    def test_check_func_logs_failure_and_returns_false(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check_func

            @check_func
            def is_positive(n):
                assert n > 0, f"{n} is not positive"

            def test_cf():
                assert is_positive(5) is True
                assert is_positive(-1) is False
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*FAILURE: -1 is not positive*"])


class TestMaxFailAndReport:
    def test_check_max_fail_cli_stops_after_n_failures(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_mf():
                check.equal(1, 2)
                check.equal(3, 4)
                check.equal(5, 6)
            """
        )
        result = pytester.runpytest("--check-max-fail=2")
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*max fail of 2 reached*"])

    def test_set_max_fail_via_api(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_mf_api():
                check.set_max_fail(2)
                check.equal(1, 2)
                check.equal(3, 4)
                check.equal(5, 6)
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*max fail of 2 reached*"])

    def test_check_max_report_limits_reported_failures(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_mr():
                for i in range(5):
                    check.equal(i, i + 100)
            """
        )
        result = pytester.runpytest("--check-max-report=2")
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 5*"])
        assert _count_failure_blocks(result) == 2


class TestReportingControls:
    def test_set_max_report_via_api(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_mr():
                check.set_max_report(2)
                for i in range(5):
                    check.equal(i, i + 100)
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 5*"])
        assert _count_failure_blocks(result) == 2

    def test_call_on_fail_invokes_callback_per_failure(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            seen = []

            def test_cof():
                check.call_on_fail(lambda m: seen.append(m))
                check.equal(1, 2)
                check.equal(3, 4)
                assert len(seen) == 2
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 2*"])
        result.stdout.no_fnmatch_line("*assert len(seen)*")

    def test_exitfirst_stops_on_first_failed_check(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_sof():
                check.equal(1, 2)
                check.equal(3, 4)
                check.equal(5, 6)
            """
        )
        result = pytester.runpytest("-x")
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 1*"])


class TestXfail:
    def test_xfail_parameter_marks_test_xfailed(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_xf():
                check.equal(1, 2, xfail="known bug")
            """
        )
        result = pytester.runpytest("-rx")
        result.assert_outcomes(xfailed=1, failed=0, passed=0)
        result.stdout.fnmatch_lines(["* 1 xfailed *"])


class TestAnyFailuresState:
    def test_any_failures_becomes_true_after_a_failed_check(self, pytester) -> None:
        """any_failures() is False before any failure and True afterward; the soft failure
        still fails the test, but no extra AssertionError about any_failures appears."""
        pytester.makepyfile(
            """
            from pytest_check import check, any_failures

            def test_af():
                assert any_failures() is False
                check.equal(1, 2)
                assert any_failures() is True
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*Failed Checks: 1*"])
        result.stdout.no_fnmatch_line("*assert any_failures()*")

    def test_any_failures_gates_a_conditional_group_of_checks(self, pytester) -> None:
        """A later group of checks can be made conditional on `not check.any_failures()`:
        once an earlier check fails, the gated group is skipped, so only the earlier
        failure is recorded ('Failed Checks: 1')."""
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_groups():
                check.equal(1, 1)
                check.equal(2, 3)
                if not check.any_failures():
                    check.equal(10, 20)
                    check.equal(30, 40)
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        # Only the second check in the first block failed; the gated block was skipped.
        result.stdout.fnmatch_lines(["*FAILURE: check 2 == 3*"])
        result.stdout.fnmatch_lines(["*Failed Checks: 1*"])
        assert _count_failure_blocks(result) == 1


class TestMixingChecksAndAsserts:
    def test_plain_assert_stops_the_test_but_check_does_not(self, pytester) -> None:
        pytester.makepyfile(
            """
            from pytest_check import check

            def test_mix():
                check.equal(1, 2)
                assert 1 == 2
                check.equal(3, 4)
            """
        )
        result = pytester.runpytest()
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*assert 1 == 2*"])


class TestCheckFixture:
    def test_check_fixture_provides_a_working_check(self, check) -> None:
        """The plugin exposes a `check` fixture equivalent to the imported object."""
        assert check.equal(1, 1) is True
        assert check.is_true(True) is True
