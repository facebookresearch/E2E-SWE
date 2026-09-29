"""User-facing behaviour of the universal ``@wrapt.decorator``.

``wrapt.decorator`` builds decorators whose wrapper receives
``(wrapped, instance, args, kwargs)`` and that work uniformly across plain
functions, instance/class/static methods and classes, preserving the wrapped
object's introspectable signature. Tests are consolidated per distinct
behavioural contract: core wrapping, introspection, binding across callable
kinds, ``enabled``, ``adapter`` forms, class-as-wrapper, custom proxy class, and
``bind_state_to_wrapper``."""

import inspect

import wrapt


@wrapt.decorator
def passthrough(wrapped, instance, args, kwargs):
    """A wrapper that simply forwards the call unchanged."""
    return wrapped(*args, **kwargs)


def _instance_tracking_wrapper(wrapped, instance, args, kwargs):
    """Wrapper that records the kind of instance it was bound with."""
    label = None if instance is None else type(instance).__name__
    return (label, wrapped(*args, **kwargs))


instance_tracker = wrapt.decorator(_instance_tracking_wrapper)


def test_wrapper_can_observe_and_transform_call():
    """The wrapper sees the real args/kwargs, may alter them, and may transform
    the return value."""

    @wrapt.decorator
    def doubling(wrapped, instance, args, kwargs):
        new_args = (args[0] + 1,) + args[1:]
        return wrapped(*new_args, **kwargs) * 2

    @doubling
    def compute(x, y=0):
        return x + y

    assert compute(3, y=10) == 28


def test_decorator_preserves_introspection():
    """A decorated function keeps the original name, docstring and signature, and
    exposes the original via ``__wrapped__``."""

    @passthrough
    def documented(a, b=2):
        """documented docstring."""
        return a + b

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "documented docstring."
    assert str(inspect.signature(documented)) == "(a, b=2)"
    assert documented.__wrapped__.__name__ == "documented"
    assert documented(1) == 3


def test_decorator_binding_delivers_correct_instance_across_kinds():
    """Binding delivers the right ``instance`` for every callable kind: the
    object for an instance method (including when called via the class with
    explicit self), the class for a class method, ``None`` for a static method,
    and ``None`` when the decorator wraps a class (which still constructs real
    instances)."""

    class Service:
        @instance_tracker
        def imethod(self, value):
            return value * 2

        @instance_tracker
        @classmethod
        def cmethod(cls, value):
            return value * 3

        @instance_tracker
        @staticmethod
        def smethod(value):
            return value * 4

    service = Service()
    # Instance method: bound call and explicit-self-via-class call agree.
    assert service.imethod(5) == ("Service", 10)
    assert Service.imethod(service, 5) == ("Service", 10)
    # Class method: instance is the class (its type is ``type``).
    assert Service.cmethod(5) == ("type", 15)
    # Static method: no instance.
    assert Service.smethod(5) == (None, 20)

    @passthrough
    class Point:
        def __init__(self, x):
            self.x = x

    p = Point(7)
    assert p.x == 7
    assert isinstance(p, Point.__wrapped__)


def test_decorator_enabled_boolean_and_callable():
    """``enabled`` controls whether the wrapper runs: a ``False`` boolean is
    resolved at decoration time (bare original returned, no ``__wrapped__``); a
    callable is consulted on every call, including for bound methods."""

    @wrapt.decorator(enabled=False)
    def disabled(wrapped, instance, args, kwargs):
        return "wrapped"

    @disabled
    def original():
        return "original"

    assert original() == "original"
    assert not hasattr(original, "__wrapped__")

    switch = {"on": True}
    gate = wrapt.decorator(
        lambda wrapped, instance, args, kwargs: "intercepted",
        enabled=lambda: switch["on"],
    )

    @gate
    def free():
        return "real"

    class Service:
        @gate
        def run(self):
            return "real"

    service = Service()
    assert free() == "intercepted" and service.run() == "intercepted"
    switch["on"] = False
    assert free() == "real" and service.run() == "real"


def test_decorator_adapter_forms_override_signature():
    """The ``adapter`` argument overrides the exposed signature without changing
    execution, accepting a prototype callable, an ``inspect.getfullargspec``
    argument specification (including its annotations) and an ``adapter_factory``
    built lazily from the wrapped function."""

    def prototype(a, b, c=3):
        pass

    @wrapt.decorator(adapter=prototype)
    def via_prototype(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    @via_prototype
    def impl1(*args, **kwargs):
        return sum(args)

    assert str(inspect.signature(impl1)) == "(a, b, c=3)"
    assert impl1(1, 2) == 3

    def annotated(a: int, b) -> bool:
        pass

    @wrapt.decorator(adapter=inspect.getfullargspec(annotated))
    def via_argspec(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    @via_argspec
    def impl2(*args, **kwargs):
        return args

    sig2 = inspect.signature(impl2)
    assert sig2.parameters["a"].annotation is int
    assert sig2.return_annotation is bool

    @wrapt.decorator(adapter=wrapt.adapter_factory(lambda wrapped: prototype))
    def via_factory(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    @via_factory
    def impl3(*args, **kwargs):
        return args

    assert str(inspect.signature(impl3)) == "(a, b, c=3)"


def test_decorator_construction_options_class_wrapper_and_custom_proxy():
    """Two construction options: a class decorated with ``@wrapt.decorator``
    becomes a decorator factory (instances act as the wrapper, supporting ``@D``
    and ``@D(...)``); and the ``proxy`` keyword builds the wrapper from a custom
    ``FunctionWrapper`` subclass."""

    @wrapt.decorator
    class Prefixer:
        def __init__(self, prefix="X"):
            self.prefix = prefix

        def __call__(self, wrapped, instance, args, kwargs):
            return f"{self.prefix}:{wrapped(*args, **kwargs)}"

    @Prefixer(prefix="P")
    def greet():
        return "hi"

    @Prefixer
    def greet_default():
        return "yo"

    assert greet() == "P:hi"
    assert greet_default() == "X:yo"

    class CustomFunctionWrapper(wrapt.FunctionWrapper):
        pass

    forward = wrapt.decorator(
        lambda wrapped, instance, args, kwargs: wrapped(*args, **kwargs),
        proxy=CustomFunctionWrapper,
    )

    @forward
    def compute(x):
        return x + 1

    assert isinstance(compute, CustomFunctionWrapper)
    assert compute(41) == 42


def test_bind_state_to_wrapper_attaches_owner_instance():
    """``bind_state_to_wrapper`` attaches the owner instance onto the wrapper
    produced by a factory method — working over both ``function_wrapper`` and
    ``decorator`` factories, under a configurable attribute name."""

    class Owner:
        def __init__(self, label):
            self.label = label

        @wrapt.bind_state_to_wrapper(name="state")
        @wrapt.function_wrapper
        def track(self, wrapped, instance, args, kwargs):
            return wrapped(*args, **kwargs)

        @wrapt.bind_state_to_wrapper()
        @wrapt.decorator
        def track_via_decorator(self, wrapped, instance, args, kwargs):
            return wrapped(*args, **kwargs)

    owner = Owner("owner-A")

    @owner.track
    def action():
        return 42

    @owner.track_via_decorator
    def action2():
        return 9

    assert action() == 42 and action.state is owner
    assert action2() == 9 and action2.state is owner
