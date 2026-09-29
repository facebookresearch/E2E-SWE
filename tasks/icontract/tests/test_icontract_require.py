"""Tests for the @require precondition decorator."""

import re

import icontract


_LOCATION_RE = re.compile(
    r"\AFile [^\n]+, line [0-9]+ in [^\n]+:\n(.*)\Z",
    flags=re.MULTILINE | re.DOTALL,
)


def _strip_location(text):
  """Removes the leading 'File ..., line N in ...:' location from a message."""
  match = _LOCATION_RE.match(text)
  return match.group(1) if match else text


def _violation(func, *args, **kwargs):
  """Calls func expecting a ViolationError; returns the location-stripped text."""
  try:
    func(*args, **kwargs)
  except icontract.ViolationError as err:
    return _strip_location(str(err))
  raise AssertionError("expected a ViolationError, none was raised")


def test_precondition_passes_and_violates():
  """A satisfied precondition is a no-op; a violated one raises ViolationError."""
  @icontract.require(lambda x: x < 5)
  def func(x):
    return x

  assert func(x=3) == 3  # satisfied: returns normally.
  # The message shows the condition source followed by the (single) argument
  # value, inline. ViolationError is catchable as AssertionError (it subclasses
  # it), which we verify behaviorally rather than via an issubclass shape check.
  try:
    func(x=100)
  except AssertionError as err:
    assert _strip_location(str(err)) == "x < 5: x was 100"
  else:
    raise AssertionError("expected the violation to be catchable as AssertionError")


def test_precondition_reports_all_function_arguments():
  """A multi-argument call lists every bound argument, one per line."""
  @icontract.require(lambda x: x > 3)
  def func(x, y=5):
    return None

  assert _violation(func, x=1) == "x > 3:\nx was 1\ny was 5"


def test_precondition_description_prefixes_message():
  """A description is prepended to the rendered condition."""
  @icontract.require(lambda x: x > 3, "x must not be small")
  def func(x, y=5):
    return None

  assert _violation(func, x=1) == (
      "x must not be small: x > 3:\nx was 1\ny was 5")


def test_precondition_custom_error():
  """An `error` factory replaces ViolationError with the returned exception."""
  @icontract.require(
      lambda x: x > 0,
      error=lambda x: ValueError("x non-positive: {}".format(x)))
  def func(x):
    return x

  try:
    func(x=-1)
  except ValueError as err:
    assert str(err) == "x non-positive: -1"
  else:
    raise AssertionError("expected a ValueError")


def test_precondition_disabled():
  """enabled=False removes the check entirely."""
  @icontract.require(lambda x: x > 100, enabled=False)
  def func(x):
    return x

  assert func(x=1) == 1  # condition would fail, but the check is disabled.


def test_precondition_reports_referenced_globals():
  """Names referenced from the enclosing scope are reported alongside arguments."""
  threshold = 100

  @icontract.require(lambda x: x > threshold)
  def func(x):
    return None

  assert _violation(func, x=1) == "x > threshold:\nthreshold was 100\nx was 1"
