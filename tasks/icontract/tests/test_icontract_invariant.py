"""Tests for the @invariant class decorator."""

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


def test_invariant_enforced_after_method_call():
  """An invariant holds after construction and is re-checked after each method."""
  @icontract.invariant(lambda self: self.x > 0)
  class Counter:
    def __init__(self):
      self.x = 1

    def decrement(self):
      self.x -= 2

    def __repr__(self):
      return "an instance of {}".format(type(self).__name__)

  counter = Counter()  # invariant holds at construction.
  assert counter.x == 1
  # decrement() drives x to -1, violating the invariant when the method returns.
  assert _violation(counter.decrement) == (
      "self.x > 0:\nself was an instance of Counter\nself.x was -1")


def test_invariant_checked_after_construction():
  """The invariant is verified at the end of __init__."""
  @icontract.invariant(lambda self: self.x > 0)
  class Holder:
    def __init__(self, x):
      self.x = x

    def __repr__(self):
      return "an instance of Holder"

  assert Holder(x=5).x == 5
  assert _violation(Holder, x=-5) == (
      "self.x > 0:\nself was an instance of Holder\nself.x was -5")


def test_invariant_check_on_all_rechecks_call_and_setattr():
  """check_on=ALL (= CALL | SETATTR) re-checks on both a method call and a setattr."""
  @icontract.invariant(
      lambda self: self.x > 0,
      check_on=icontract.InvariantCheckEvent.ALL)
  class Holder:
    def __init__(self):
      self.x = 1

    def break_via_call(self):
      # Mutate without going through __setattr__ so only the CALL-event check can
      # catch this; the SETATTR event never fires for this assignment.
      self.__dict__["x"] = -1

    def __repr__(self):
      return "an instance of Holder"

  # SETATTR semantics: a violating attribute assignment is caught.
  holder = Holder()
  assert _violation(setattr, holder, "x", -1) == (
      "self.x > 0:\nself was an instance of Holder\nself.x was -1")

  # CALL semantics: a method that violates the invariant (without a tracked
  # setattr) is caught when it returns. ALL must enforce this too.
  fresh = Holder()
  assert _violation(fresh.break_via_call) == (
      "self.x > 0:\nself was an instance of Holder\nself.x was -1")


def test_multiple_invariants_all_enforced():
  """Stacking several @invariant decorators enforces each independently."""
  @icontract.invariant(lambda self: self.x > 0)
  @icontract.invariant(lambda self: self.x < 100)
  class Bounded:
    def __init__(self, x):
      self.x = x

    def __repr__(self):
      return "an instance of Bounded"

  assert Bounded(50).x == 50  # both invariants hold.
  assert _violation(Bounded, x=-1) == (
      "self.x > 0:\nself was an instance of Bounded\nself.x was -1")
  assert _violation(Bounded, x=200) == (
      "self.x < 100:\nself was an instance of Bounded\nself.x was 200")


def test_invariant_condition_calling_method():
  """An invariant may call a method on self; the call result is reported."""
  @icontract.invariant(lambda self: self.is_valid())
  class Validated:
    def __init__(self, x):
      self.x = x

    def is_valid(self):
      return self.x > 0

    def __repr__(self):
      return "an instance of Validated"

  assert Validated(5).x == 5
  assert _violation(Validated, x=-1) == (
      "self.is_valid():\nself was an instance of Validated\n"
      "self.is_valid() was False")


def test_invariant_check_on_setattr():
  """check_on=SETATTR re-checks on attribute assignment but NOT on a plain method call."""
  @icontract.invariant(
      lambda self: self.x > 0,
      check_on=icontract.InvariantCheckEvent.SETATTR)
  class Holder:
    def __init__(self):
      self.x = 1

    def break_via_call(self):
      # Mutate without going through __setattr__: under SETATTR-only no event
      # fires, so the violated invariant must NOT be caught on method return.
      self.__dict__["x"] = -1

    def __repr__(self):
      return "an instance of Holder"

  # SETATTR semantics: a violating attribute assignment is caught.
  holder = Holder()
  assert _violation(setattr, holder, "x", -1) == (
      "self.x > 0:\nself was an instance of Holder\nself.x was -1")

  # The defining negative of SETATTR-only mode: a method that violates the
  # invariant without a tracked setattr is NOT re-checked (no CALL event), so
  # break_via_call returns normally and leaves the instance in a broken state.
  fresh = Holder()
  fresh.break_via_call()
  assert fresh.x == -1
