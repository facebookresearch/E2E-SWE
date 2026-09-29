"""Tests for contracts on async (coroutine) functions."""

import asyncio
import re

import icontract


_LOCATION_RE = re.compile(
    r"\AFile [^\n]+, line [0-9]+ in [^\n]+:\n(.*)\Z",
    flags=re.MULTILINE | re.DOTALL,
)


def _strip_location(text):
  match = _LOCATION_RE.match(text)
  return match.group(1) if match else text


def _async_violation(coro_func, *args, **kwargs):
  try:
    asyncio.run(coro_func(*args, **kwargs))
  except icontract.ViolationError as err:
    return _strip_location(str(err))
  raise AssertionError("expected a ViolationError, none was raised")


def test_async_precondition():
  """@require guards an async function's arguments before it runs."""
  @icontract.require(lambda x: x > 0)
  async def func(x):
    return x

  assert asyncio.run(func(5)) == 5  # satisfied.
  assert _async_violation(func, -1) == "x > 0: x was -1"


def test_async_postcondition():
  """@ensure checks an async function's awaited result."""
  @icontract.ensure(lambda result: result > 0)
  async def func(x):
    return x

  assert asyncio.run(func(5)) == 5  # satisfied.
  assert _async_violation(func, -5) == "result > 0:\nresult was -5\nx was -5"


def test_async_condition():
  """A coroutine condition is awaited and enforced."""
  async def positive(x):
    return x > 0

  @icontract.require(positive)
  async def func(x):
    return x

  assert asyncio.run(func(5)) == 5
  # The async condition fails for a non-positive argument.
  try:
    asyncio.run(func(-1))
  except icontract.ViolationError:
    pass
  else:
    raise AssertionError("expected a ViolationError")
