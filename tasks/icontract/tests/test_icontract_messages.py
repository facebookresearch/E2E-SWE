"""Tests for the rich violation messages (recompute + represent).

When a condition fails, icontract re-evaluates the condition's expression tree
and renders the value of each sub-expression, so the message explains *why* the
condition is false. Values are rendered with Python `repr` (via `reprlib`) and
listed sorted by their source text.
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


def test_scalar_value_reprs():
  """Scalar operands are rendered with Python repr (quotes, byte prefixes)."""
  @icontract.require(lambda x: x != "oi")
  def with_str(x):
    return x

  @icontract.require(lambda x: x != b"oi")
  def with_bytes(x):
    return x

  @icontract.require(lambda x: x is not False)
  def with_bool(x):
    return x

  assert _violation(with_str, x="oi") == """x != "oi": x was 'oi'"""
  assert _violation(with_bytes, x=b"oi") == """x != b"oi": x was b'oi'"""
  assert _violation(with_bool, x=False) == "x is not False: x was False"


def test_compound_expression_subvalues():
  """A compound expression reports the whole expression and its operands."""
  @icontract.require(lambda x, y: sum([1, y, x]) > 10)
  def func(x, y):
    return None

  assert _violation(func, x=3, y=1) == (
      "sum([1, y, x]) > 10:\n"
      "sum([1, y, x]) was 5\n"
      "x was 3\n"
      "y was 1")


def test_attribute_access_in_condition():
  """An attribute access reports both the object and the attribute value."""
  class Point:
    def __init__(self, a):
      self.a = a

    def __repr__(self):
      return "Pt(a={})".format(self.a)

  @icontract.require(lambda p: p.a > 0)
  def func(p):
    return None

  assert _violation(func, p=Point(-3)) == (
      "p.a > 0:\np was Pt(a=-3)\np.a was -3")


def test_chained_binary_operators():
  """A long arithmetic expression is rendered verbatim with the operand value."""
  @icontract.require(lambda x: -x + x - x * x / x // x ** x % x > 3)
  def func(x):
    return None

  # icontract preserves the condition's source text verbatim (via asttokens),
  # so the operator spacing matches exactly how the lambda was written above.
  assert _violation(func, x=1) == (
      "-x + x - x * x / x // x ** x % x > 3: x was 1")


def test_comprehension_subvalues():
  """List and dict comprehensions report the built collection and its inputs."""
  @icontract.require(lambda lst: all([item > 0 for item in lst]))
  def with_listcomp(lst):
    return None

  assert _violation(with_listcomp, lst=[1, -2, 3]) == (
      "all([item > 0 for item in lst]):\n"
      "[item > 0 for item in lst] was [True, False, True]\n"
      "all([item > 0 for item in lst]) was False\n"
      "lst was [1, -2, 3]")

  @icontract.require(lambda n: len({i: i * i for i in range(n)}) > 5)
  def with_dictcomp(n):
    return None

  assert _violation(with_dictcomp, n=2) == (
      "len({i: i * i for i in range(n)}) > 5:\n"
      "len({i: i * i for i in range(n)}) was 2\n"
      "n was 2\n"
      "range(n) was range(0, 2)\n"
      "{i: i * i for i in range(n)} was {0: 0, 1: 1}")


def test_generator_expression_counterexample():
  """A failing generator expression reports the first failing element."""
  @icontract.require(lambda lst: all(item > 0 for item in lst))
  def func(lst):
    return None

  assert _violation(func, lst=[1, -2, 3]) == (
      "all(item > 0 for item in lst):\n"
      "all(item > 0 for item in lst) was False, e.g., with\n"
      "  item = -2\n"
      "lst was [1, -2, 3]")


def test_subscript_fstring_and_if_expression():
  """Subscripts, f-strings and conditional expressions are recomputed."""
  @icontract.require(lambda d: d["k"] > 0)
  def with_subscript(d):
    return None

  assert _violation(with_subscript, d={"k": -1}) == (
      "d[\"k\"] > 0:\nd was {'k': -1}\nd[\"k\"] was -1")

  @icontract.require(lambda name: len(f"hello {name}") < 5)
  def with_fstring(name):
    return None

  assert _violation(with_fstring, name="world") == (
      "len(f\"hello {name}\") < 5:\n"
      "f\"hello {name}\" was 'hello world'\n"
      "len(f\"hello {name}\") was 11\n"
      "name was 'world'")

  @icontract.require(lambda x: (x if x > 0 else -x) > 5)
  def with_ifexp(x):
    return None

  assert _violation(with_ifexp, x=1) == "(x if x > 0 else -x) > 5: x was 1"
