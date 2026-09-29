# pytest-check

`pytest-check` is a `pytest` plugin that allows **multiple failures per test**. With a normal
`assert`, the first failed assertion stops the test. `pytest-check` provides "soft" checks that
record a failure and let the test keep running, so a single test can surface several problems at
once; when the test finishes, if any check failed, the test is reported as a failure that lists
every recorded failure.

## Example use case

pytest-check provides "soft" assertions: a failing check is recorded but does not stop the test, so one test can surface several problems at once.

```python
from pytest_check import check

def test_order():
    order = {"total": 90, "items": 2}
    check.equal(order["total"], 100)     # fails, but the test keeps going
    check.greater(order["items"], 5)     # also fails
    check.is_in("coupon", order)         # also fails
# the test ends failed, reporting all three checks plus a final "Failed Checks: 3"
```

## Dependencies

The environment is **offline** — every dependency is already installed, so do not attempt to
install anything. The available dependencies are:

- Python 3.9+.
- `pytest` (this project is a pytest plugin and depends on it).
- `typing-extensions` (used for typing support on Python < 3.11).

There are no system services to start. The importable package is `pytest_check`. The project is
built and installed offline by a `setup.sh` (an editable `pip install`) that runs in this
environment; you only need to provide a valid installable package (a `pyproject.toml` / `setup.py`
that builds offline). Once installed it auto-registers as a pytest plugin — its reporting behavior
and its `check` fixture are active automatically, with no conftest edits required.

## Public API

These are the import paths the test-suite uses; organize internals however you like as long as
they resolve:

- `from pytest_check import check, raises, any_failures, check_func, fail`
- `from pytest_check import equal, not_equal, is_, is_not, is_true, is_false, is_none, is_not_none, is_in, is_not_in, is_instance, is_not_instance, is_nan, is_not_nan, almost_equal, not_almost_equal, greater, greater_equal, less, less_equal, between, between_equal, assert_equal`
- The check functions are also reachable as `pytest_check.<name>` and as attributes of the
  `check` object (e.g. `check.equal(...)`). `any_failures` is likewise reachable as
  `check.any_failures()` (returning whether any check has failed in the current test).
- The `check` fixture: a test may request `check` as a fixture (`def test_x(check): ...`); it
  provides the same context manager and helper functions as the imported `check` object.

## Soft checks

The check functions perform a comparison and, on failure, **record** the failure and return a
boolean — `True` when the condition holds, `False` when it does not — instead of raising, so the
test continues. Each takes the value(s) under test plus an optional `msg` (extra context) and an
optional `xfail` reason (see *Xfail*). Capabilities:

- Equality / identity / truthiness: `equal`, `not_equal`, `is_`, `is_not`, `is_true`,
  `is_false`, `is_none`, `is_not_none`.
- Membership / type: `is_in`, `is_not_in`, `is_instance`, `is_not_instance`.
- Numeric: `is_nan`, `is_not_nan`; `almost_equal` / `not_almost_equal` for approximate equality
  (following `pytest.approx`, accepting `rel` and `abs` tolerances); ordering with `greater`,
  `greater_equal`, `less`, `less_equal`.
- Range: `between(value, lower, upper)` checks that `value` falls between the bounds — exclusive
  by default, with `ge=True` and/or `le=True` making the lower/upper bound inclusive;
  `between_equal(value, lower, upper)` is the both-inclusive form.
- `fail(msg)` records a failure unconditionally.
- `assert_equal(a, b, msg="")` is a plain **hard** assertion (it raises immediately on
  inequality) — the non-soft escape hatch.

## Context manager

`check` is also a context manager. A `with check:` block runs its body and, if an
`AssertionError` is raised inside it, records that as a soft failure and continues past the block
rather than stopping the test — letting ordinary `assert` statements be used as soft checks.
`with check(msg):` attaches extra context to whatever failure occurs in the block.

## Custom checks

`check_func` is a decorator that turns an ordinary assert-based function into a soft check: the
wrapped function returns `True` if its assertions pass and `False` (recording the failure) if an
`AssertionError` is raised, without propagating it.

## raises

`raises` is a soft counterpart to `pytest.raises` for asserting that code raises an expected
exception:

- As a context manager: `with raises(SomeError): ...` passes if the block raises `SomeError`
  (or a subclass). If the block raises a different exception, or none at all, a failure is
  recorded and the test continues. It accepts a tuple of exception types, an optional `msg`, and
  an optional `xfail` reason, and exposes the caught exception as `.value` on the `as` target.
- As a function: `raises(SomeError, func, *args, **kwargs)` calls `func` inside such a context
  (a `msg` / `xfail` keyword is consumed by `raises` itself rather than passed to `func`).

`raises` is also available as `check.raises`.

## Failure reporting

Recorded failures are tracked **per test** — each test starts fresh (failures never carry over
from a previous test), and the report/count reflect only that test. `any_failures()` returns whether any check has failed so
far in the current test. Plain `assert` is unaffected: it still stops the test immediately.

When a test both records one or more soft-check failures **and** is then stopped by a hard
failure (a plain `assert`, or any other uncaught exception), the plugin's soft-check report
**augments** — it does not replace — pytest's normal output for that stopping failure: the report
shows the recorded `FAILURE:` block(s) and the `Failed Checks: N` summary, **and** pytest's usual
representation of the stopping failure — for a plain `assert`, its normal assertion-failure
output — still appears.

When a test ends with one or more recorded failures, the plugin marks the test failed and
prints, for **each** recorded failure, a line of the form `FAILURE: <description>` followed by a
short pseudo-traceback pointing at where the check ran, and finally a summary line
`Failed Checks: N` giving the total number of failures recorded in that test (exactly one
`FAILURE:` line is printed per reported failure). The text after `FAILURE: ` is part of the
contract the test-suite matches on:

- Comparison / identity / truthiness checks echo the comparison: `equal(1, 2)` →
  `FAILURE: check 1 == 2`; `not_equal(3, 3)` → `check 3 != 3`; `greater(1, 2)` → `check 1 > 2`
  (analogously `<`, `>=`, `<=`); `is_true(False)` → `check bool(False)`; `between(5, 1, 3)` →
  `check 1 < 5 < 3` (rendered `lower < value < upper`).
- An optional `msg` is appended after `: ` — `equal(7, 8, "with a msg")` →
  `FAILURE: check 7 == 8: with a msg`.
- `fail("explicit failure")` → `FAILURE: explicit failure`.
- A `with check(...)` block that captures an `AssertionError` reports the assertion text (plus
  the block message if given): `FAILURE: assert 1 == 2, values should match`.
- `raises` reports its `msg` if supplied, otherwise the `str` of the unexpected exception:
  `raises(ValueError, msg="custom raise msg")` → `FAILURE: custom raise msg`.
- `check_func` reports the wrapped assertion's message: `FAILURE: -1 is not positive`.

The volume of reported failures can be bounded, from the command line and at runtime:

- `--check-max-fail=N` / `check.set_max_fail(N)` — once `N` checks have failed, stop that test
  and report `max fail of N reached`.
- `--check-max-report=N` / `check.set_max_report(N)` — print at most `N` `FAILURE:` blocks; the
  `Failed Checks:` total still counts every failure.
- `check.call_on_fail(func)` — register a callback invoked once per recorded failure; it is
  passed a single positional argument, the failure's `FAILURE: <description>` message string
  (i.e. called as `func(message)`). The callback fires immediately when each failure is recorded
  (during the test body), not deferred to teardown reporting.
- Running pytest with `-x` / `--maxfail=1` makes checks stop on the first failure, like a normal
  assert.

## Xfail

Passing `xfail="reason"` to any check function (or to `raises`) marks that check as
expected-to-fail: if such a check fails, the test is reported as `xfailed` with the given reason
rather than failed (as if pytest's `xfail` marker had been applied for that failure).
