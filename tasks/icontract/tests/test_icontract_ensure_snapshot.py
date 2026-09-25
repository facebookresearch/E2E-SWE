"""Tests for the @ensure postcondition decorator and @snapshot (OLD values)."""

import re

import icontract


_LOCATION_RE = re.compile(
    r"\AFile [^\n]+, line [0-9]+ in [^\n]+:\n(.*)\Z",
    flags=re.MULTILINE | re.DOTALL,
)


def _strip_location(text):
  match = _LOCATION_RE.match(text)
  return match.group(1) if match else text


def _violation(func, *args, **kwargs):
  try:
    func(*args, **kwargs)
  except icontract.ViolationError as err:
    return _strip_location(str(err))
  raise AssertionError("expected a ViolationError, none was raised")


def test_postcondition_passes_and_violates():
  """@ensure checks the return value; `result` binds the returned value."""
  @icontract.ensure(lambda result, x: result > x)
  def good(x):
    return x + 1

  assert good(x=5) == 6  # postcondition holds.

  @icontract.ensure(lambda result, x: result > x)
  def bad(x):
    return x - 1

  assert _violation(bad, x=5) == "result > x:\nresult was 4\nx was 5"


def test_snapshot_captures_old_state():
  """@snapshot captures pre-call state, exposed as OLD in the postcondition."""
  @icontract.snapshot(lambda lst: lst[:])
  @icontract.ensure(lambda OLD, lst: len(lst) == len(OLD.lst) + 1)
  def append_two(lst):
    lst.append(1)
    lst.append(2)

  message = _violation(append_two, lst=[1])
  # OLD.lst is the captured copy ([1]); the live lst grew by two, not one.
  assert message == (
      "len(lst) == len(OLD.lst) + 1:\n"
      "OLD was a bunch of OLD values\n"
      "OLD.lst was [1]\n"
      "len(OLD.lst) was 1\n"
      "len(lst) was 3\n"
      "lst was [1, 1, 2]\n"
      "result was None")


def test_snapshot_named_capture():
  """A `name` gives the snapshot an explicit attribute on OLD."""
  @icontract.snapshot(lambda lst: len(lst), name="length")
  @icontract.ensure(lambda OLD, lst: len(lst) == OLD.length + 1)
  def append_two(lst):
    lst.append(1)
    lst.append(2)

  message = _violation(append_two, lst=[1])
  assert message == (
      "len(lst) == OLD.length + 1:\n"
      "OLD was a bunch of OLD values\n"
      "OLD.length was 1\n"
      "len(lst) was 3\n"
      "lst was [1, 1, 2]\n"
      "result was None")


def test_snapshot_satisfied_postcondition():
  """A correct implementation with a snapshot passes silently."""
  @icontract.snapshot(lambda lst: lst[:])
  @icontract.ensure(lambda OLD, lst: len(lst) == len(OLD.lst) + 1)
  def append_one(lst):
    lst.append(42)

  data = [1, 2]
  append_one(lst=data)
  assert data == [1, 2, 42]
