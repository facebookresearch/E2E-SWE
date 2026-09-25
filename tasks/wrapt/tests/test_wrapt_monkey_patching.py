"""User-facing behaviour of wrapt's monkey-patching helpers:
``wrap_function_wrapper``, ``patch_function_wrapper`` (incl. deferred ``?``),
``transient_function_wrapper``, ``resolve_path``, ``wrap_object``,
``apply_patch`` and ``wrap_object_attribute``."""

import importlib
import sys

import pytest

import wrapt


class AttributeHolder:
    def __init__(self, value):
        self.value = value


def test_wrap_function_wrapper_and_decorator_form_intercept_methods():
    """``wrap_function_wrapper`` replaces a method in place (delivering ``self``
    as ``instance``), and ``patch_function_wrapper`` is its decorator spelling."""

    class Calculator:
        def add(self, a, b):
            return a + b

    def offset(wrapped, instance, args, kwargs):
        assert isinstance(instance, Calculator)
        return wrapped(*args, **kwargs) + 100

    wrapt.wrap_function_wrapper(Calculator, "add", offset)
    assert Calculator().add(1, 2) == 103

    class Greeter:
        def greet(self, name):
            return f"hi {name}"

    @wrapt.patch_function_wrapper(Greeter, "greet")
    def shout(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs).upper()

    assert Greeter().greet("ann") == "HI ANN"


def test_wrap_and_patch_can_defer_until_module_imported(tmp_path, monkeypatch):
    """Both ``wrap_function_wrapper`` and ``patch_function_wrapper`` accept a
    target string with a trailing ``?`` to defer the wrapping until the named
    module is first imported."""

    monkeypatch.syspath_prepend(str(tmp_path))

    name1 = "wrapt_defer_wrap"
    (tmp_path / f"{name1}.py").write_text("def scale(x):\n    return x\n")
    importlib.invalidate_caches()
    sys.modules.pop(name1, None)
    result = wrapt.wrap_function_wrapper(
        f"{name1}?", "scale", lambda w, i, a, k: w(*a, **k) + 1
    )
    assert result is None
    assert __import__(name1).scale(10) == 11

    name2 = "wrapt_defer_patch"
    (tmp_path / f"{name2}.py").write_text("def scale(x):\n    return x\n")
    importlib.invalidate_caches()
    sys.modules.pop(name2, None)

    @wrapt.patch_function_wrapper(f"{name2}?", "scale")
    def add_five(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs) + 5

    assert __import__(name2).scale(10) == 15


def test_transient_function_wrapper_lifecycle():
    """``transient_function_wrapper`` patches the target only for the duration of
    the decorated call — for static and instance methods — and restores the
    original afterwards, even when the body raises."""

    class Maths:
        @staticmethod
        def double(x):
            return x * 2

    @wrapt.transient_function_wrapper(Maths, "double")
    def make_it_triple(wrapped, instance, args, kwargs):
        return args[0] * 3

    @make_it_triple
    def run_static():
        return Maths.double(10)

    assert run_static() == 30
    assert Maths.double(10) == 20

    class Repository:
        def fetch(self, key):
            return key

    @wrapt.transient_function_wrapper(Repository, "fetch")
    def offset(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs) + 100

    @offset
    def run_instance():
        return Repository().fetch(1)

    assert run_instance() == 101
    assert Repository().fetch(1) == 1

    @offset
    def run_and_fail():
        Repository().fetch(1)
        raise ValueError("boom")

    with pytest.raises(ValueError):
        run_and_fail()
    assert Repository().fetch(1) == 1  # restored despite exception


def test_resolve_path_wrap_object_and_apply_patch():
    """``resolve_path`` returns (parent, attribute, original) without binding;
    ``wrap_object`` builds a replacement via a factory and installs it;
    ``apply_patch`` is the underlying setattr."""

    class Outer:
        def method(self):
            return "v"

    parent, attribute, original = wrapt.resolve_path(Outer, "method")
    assert parent is Outer and attribute == "method"
    assert original is Outer.__dict__["method"]

    class Registry:
        @staticmethod
        def lookup(key):
            return key

    returned = wrapt.wrap_object(
        Registry, "lookup", wrapt.FunctionWrapper, (lambda w, i, a, k: w(*a, **k) + 1,)
    )
    assert Registry.lookup(41) == 42
    assert isinstance(returned, wrapt.FunctionWrapper)

    sentinel = object()
    wrapt.apply_patch(Registry, "marker", sentinel)
    assert Registry.marker is sentinel


def test_wrap_object_attribute_proxies_instance_attribute():
    """``wrap_object_attribute`` installs a class descriptor so each read of an
    instance attribute is passed through a factory, while writes update it."""

    wrapt.wrap_object_attribute(__name__, "AttributeHolder.value", wrapt.ObjectProxy)
    holder = AttributeHolder(1)
    assert holder.value == 1 and isinstance(holder.value, wrapt.ObjectProxy)
    holder.value = 5
    assert holder.value == 5 and isinstance(holder.value, wrapt.ObjectProxy)
