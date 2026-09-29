"""Tests for contract inheritance via the DBC base / DBCMeta metaclass.

Liskov substitution: preconditions weaken down the hierarchy (a call passes if
ANY ancestor's precondition holds), while postconditions and invariants
strengthen (ALL must hold).
"""

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


def test_precondition_weakens_across_inheritance():
  """An overriding method's precondition is OR-ed with the inherited one."""
  class Base(icontract.DBC):
    @icontract.require(lambda x: x % 2 == 0)
    def func(self, x):
      pass

  class Derived(Base):
    @icontract.require(lambda x: x % 3 == 0)
    def func(self, x):
      pass

    def __repr__(self):
      return "an instance of Derived"

  derived = Derived()
  derived.func(x=4)  # satisfies the base precondition (4 % 2 == 0).
  derived.func(x=9)  # satisfies the derived precondition (9 % 3 == 0).
  # x=5 satisfies neither; the reported condition is the subclass's own.
  assert _violation(derived.func, x=5) == (
      "x % 3 == 0:\nself was an instance of Derived\nx was 5")


def test_postcondition_strengthens_across_inheritance():
  """An overriding method must honour both its own and inherited postconditions."""
  class Base(icontract.DBC):
    @icontract.ensure(lambda result: result > 0)
    def func(self):
      return 1

  class Derived(Base):
    @icontract.ensure(lambda result: result < 100)
    def func(self):
      return 1000

    def __repr__(self):
      return "an instance of Derived"

  # 1000 satisfies the base postcondition but violates the derived one.
  assert _violation(Derived().func) == (
      "result < 100:\nresult was 1000\nself was an instance of Derived")


def test_precondition_inherited_without_override():
  """A subclass that does not override the method still enforces the contract."""
  class Base(icontract.DBC):
    @icontract.require(lambda x: x < 100)
    def func(self, x):
      pass

  class Derived(Base):
    def __repr__(self):
      return "an instance of Derived"

  derived = Derived()
  derived.func(x=1)  # within the inherited precondition.
  assert _violation(derived.func, x=1000) == (
      "x < 100:\nself was an instance of Derived\nx was 1000")


def test_snapshot_inherited_with_postcondition():
  """A snapshot+postcondition defined on a DBC base applies to an override."""
  class Base(icontract.DBC):
    @icontract.snapshot(lambda lst: lst[:])
    @icontract.ensure(lambda OLD, lst: len(lst) == len(OLD.lst) + 1)
    def add(self, lst):
      raise NotImplementedError

  class Good(Base):
    def add(self, lst):
      lst.append(1)

  data = [1, 2]
  Good().add(lst=data)  # adds exactly one element: postcondition holds.
  assert data == [1, 2, 1]

  class Bad(Base):
    def add(self, lst):
      lst.append(1)
      lst.append(2)

    def __repr__(self):
      return "an instance of Bad"

  # Adds two elements, violating the inherited postcondition.
  assert _violation(Bad().add, lst=[1]) == (
      "len(lst) == len(OLD.lst) + 1:\n"
      "OLD was a bunch of OLD values\n"
      "OLD.lst was [1]\n"
      "len(OLD.lst) was 1\n"
      "len(lst) was 3\n"
      "lst was [1, 1, 2]\n"
      "result was None\n"
      "self was an instance of Bad")


def test_dbc_supports_abstract_methods():
  """DBC composes with abc: a class with an abstract method cannot be built."""
  import abc

  class Base(icontract.DBC):
    @abc.abstractmethod
    def func(self):
      raise NotImplementedError

  try:
    Base()
  except TypeError as err:
    assert "abstract" in str(err).lower()
  else:
    raise AssertionError("expected a TypeError for the abstract class")


def test_invariant_inherited_by_subclass():
  """A subclass inherits and enforces its parent's invariant."""
  @icontract.invariant(lambda self: self.x > 0)
  class Base(icontract.DBC):
    def __init__(self):
      self.x = 1

    def __repr__(self):
      return "an instance of {}".format(type(self).__name__)

  class Derived(Base):
    def break_it(self):
      self.x = -1

  derived = Derived()
  assert _violation(derived.break_it) == (
      "self.x > 0:\nself was an instance of Derived\nself.x was -1")
