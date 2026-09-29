"""User-facing behaviour of ``wrapt.with_signature``: override the introspected
signature (and the derived ``__defaults__`` / ``__kwdefaults__`` / ``__code__``
argument attributes) of a callable without altering its real implementation or
call behaviour. Tests are consolidated per distinct behavioural contract: full
introspection derivation, the three sources, the one-source rule, and method
binding."""

import inspect

import pytest

import wrapt


def test_with_signature_derives_full_introspection_from_prototype():
    """A prototype supplies the exposed signature, and every derived
    introspection surface is consistent with it — ``inspect.signature``,
    ``__defaults__``, ``__kwdefaults__``, ``inspect.getfullargspec`` and the raw
    ``__code__`` argument attributes — while the real implementation still
    runs."""

    def prototype(a, b=5, *args, c=3, **kw):
        pass

    @wrapt.with_signature(prototype=prototype)
    def implementation(*args, **kwargs):
        return sum(a for a in args if isinstance(a, int))

    assert str(inspect.signature(implementation)) == "(a, b=5, *args, c=3, **kw)"
    assert implementation.__defaults__ == (5,)
    assert implementation.__kwdefaults__ == {"c": 3}

    spec = inspect.getfullargspec(implementation)
    assert spec.args == ["a", "b"]
    assert spec.varargs == "args"
    assert spec.varkw == "kw"
    assert spec.kwonlyargs == ["c"]

    # Raw code-object argument attributes are derived too (not just signature).
    assert implementation.__code__.co_argcount == 2
    assert implementation.__code__.co_varnames[:3] == ("a", "b", "c")

    # Real implementation still executes.
    assert implementation(1, 2) == 3


def test_with_signature_accepts_signature_object_and_factory_sources():
    """Besides a prototype, the override may be supplied as a prebuilt
    ``inspect.Signature`` or produced by a ``factory(wrapped)`` at decoration
    time."""

    sig = inspect.Signature(
        [
            inspect.Parameter("x", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("y", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=9),
        ]
    )

    @wrapt.with_signature(signature=sig)
    def from_signature(*args, **kwargs):
        return args

    @wrapt.with_signature(
        factory=lambda wrapped: inspect.signature(lambda only=0: None)
    )
    def from_factory(*args, **kwargs):
        return kwargs

    assert str(inspect.signature(from_signature)) == "(x, y=9)"
    assert from_signature.__defaults__ == (9,)
    assert str(inspect.signature(from_factory)) == "(only=0)"


def test_with_signature_requires_exactly_one_source():
    """Supplying none, or more than one, of prototype/signature/factory is a
    TypeError."""

    def proto(a):
        pass

    with pytest.raises(TypeError):
        wrapt.with_signature(lambda: None)  # none specified
    with pytest.raises(TypeError):
        wrapt.with_signature(prototype=proto, signature=inspect.Signature())


def test_with_signature_on_methods_strips_self_and_cls():
    """Applied to instance and class methods, the override is reported with
    ``self``/``cls`` correctly stripped when accessed through an instance/class,
    for both the prototype and prebuilt-``Signature`` sources."""

    def instance_prototype(self, x: int, y: str = "z") -> bool:
        pass

    sig_with_self = inspect.Signature(
        [
            inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("n", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        ]
    )

    def classmethod_prototype(cls, value, scale=2):
        pass

    class Handler:
        @wrapt.with_signature(prototype=instance_prototype)
        def handle(self, *args, **kwargs):
            return (args, kwargs)

        @wrapt.with_signature(signature=sig_with_self)
        def via_signature(self, *args, **kwargs):
            return args

        @wrapt.with_signature(prototype=classmethod_prototype)
        @classmethod
        def build(cls, *args, **kwargs):
            return args

    assert (
        str(inspect.signature(Handler.handle)) == "(self, x: int, y: str = 'z') -> bool"
    )
    assert str(inspect.signature(Handler().handle)) == "(x: int, y: str = 'z') -> bool"
    assert str(inspect.signature(Handler().via_signature)) == "(n)"
    assert str(inspect.signature(Handler.build)) == "(value, scale=2)"
    # Calls still execute the real implementation.
    assert Handler().handle(1, y="q") == ((1,), {"y": "q"})
