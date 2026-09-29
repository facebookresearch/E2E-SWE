"""User-facing behaviour of the lightweight function-wrapper helpers:
``wrapt.function_wrapper`` (a simple decorator builder for monkey patching) and
``wrapt.partial`` (a ``functools.partial`` analogue built on the proxy machinery
so the result stays introspectable)."""

import pytest

import wrapt


def test_function_wrapper_decorator_on_function_and_method():
    """``function_wrapper`` turns a ``(wrapped, instance, args, kwargs)`` wrapper
    into a decorator applicable to both plain functions and instance methods,
    passing the correct instance in each case."""

    @wrapt.function_wrapper
    def add_instance_flag(wrapped, instance, args, kwargs):
        bound = instance is not None
        return (bound, wrapped(*args, **kwargs))

    @add_instance_flag
    def free(x):
        return x + 1

    class Service:
        @add_instance_flag
        def method(self, x):
            return x + 2

    assert free(10) == (False, 11)
    assert Service().method(10) == (True, 12)


def test_function_wrapper_propagates_set_name_to_wrapped_descriptor():
    """A ``FunctionWrapper`` placed in a class body forwards ``__set_name__`` to
    the wrapped object, so a wrapped descriptor still learns the attribute name
    it was assigned to."""

    recorded = {}

    class NamedDescriptor:
        def __set_name__(self, owner, name):
            recorded["name"] = name

        def __get__(self, instance, owner):
            return "value"

    wrapped = wrapt.FunctionWrapper(NamedDescriptor(), lambda w, i, a, k: w(*a, **k))

    class Host:
        attr = wrapped

    assert recorded.get("name") == "attr"


def test_partial_applies_arguments_and_validates_callable():
    """``partial`` pre-binds arguments like ``functools.partial`` while staying a
    transparent, introspectable proxy; later keywords override pre-bound ones;
    and construction without a callable target raises TypeError."""

    def combine(a, b, c, sep="-"):
        return f"{a}{sep}{b}{sep}{c}"

    bound = wrapt.partial(combine, "x", sep="/")
    assert bound("y", "z") == "x/y/z"
    assert bound("y", "z", sep="+") == "x+y+z"  # later kwarg wins
    assert bound.__wrapped__ is combine

    with pytest.raises(TypeError):
        wrapt.partial()
    with pytest.raises(TypeError):
        wrapt.partial(123)
