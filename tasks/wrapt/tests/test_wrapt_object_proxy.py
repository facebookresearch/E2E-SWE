"""User-facing behaviour of ``wrapt.ObjectProxy`` and ``CallableObjectProxy``.

``ObjectProxy`` is a transparent proxy: it forwards attribute access, the full
operator set, comparisons, the container protocol and type identity to the
wrapped object, while keeping proxy-private state under ``_self_*`` names. Tests
are consolidated per distinct behavioural contract."""

import copy
import pickle

import pytest

import wrapt


class PicklableProxy(wrapt.ObjectProxy):
    """Module-level proxy subclass that opts into pickling (pickle requires a
    top-level class)."""

    def __reduce_ex__(self, protocol):
        return (PicklableProxy, (self.__wrapped__,))


# ---------------------------------------------------------------------------
# Attribute transparency and proxy-private state
# ---------------------------------------------------------------------------


def test_attribute_access_and_metadata_delegate():
    """Reading, writing and deleting attributes goes through to the wrapped
    object; metadata attributes mirror it; and ``__wrapped__`` may not be
    deleted."""

    class Target:
        """target doc."""

        def __init__(self):
            self.value = 1

        def method(self):
            return "called"

    target = Target()
    proxy = wrapt.ObjectProxy(target)

    assert proxy.value == 1
    assert proxy.method() == "called"
    assert proxy.__wrapped__ is target

    proxy.value = 2
    assert target.value == 2
    proxy.added = "new"
    assert target.added == "new"
    del proxy.added
    assert not hasattr(target, "added")

    assert proxy.__class__ is Target
    assert proxy.__module__ == Target.__module__
    assert proxy.__doc__ == "target doc."
    assert proxy.__dict__ == target.__dict__

    with pytest.raises(TypeError):
        del proxy.__wrapped__


def test_self_prefixed_state_stays_on_the_proxy():
    """Attributes named ``_self_*`` (and those set via ``__self_setattr__``) are
    stored on the proxy itself, never forwarded to the wrapped object, and
    ``__self_dict__`` exposes the proxy's own instance dict."""

    class Holder:
        pass

    target = Holder()
    target.k = "v"
    proxy = wrapt.ObjectProxy(target)

    proxy._self_marker = 123
    assert proxy._self_marker == 123
    assert "_self_marker" not in target.__dict__

    proxy.__self_setattr__("tag", "owned")
    assert proxy.tag == "owned"
    assert "tag" in proxy.__self_dict__
    assert "tag" not in target.__dict__
    assert proxy.__dict__ == target.__dict__ == {"k": "v"}


# ---------------------------------------------------------------------------
# Type transparency (proxy as value and proxy as class)
# ---------------------------------------------------------------------------


def test_type_transparency_and_class_checks():
    """``isinstance(proxy, T)`` / ``__class__`` report the wrapped type while
    ``type(proxy)`` stays the proxy class; a subclass keeps its own type-level
    ``__doc__``/``__module__``; and a proxy wrapping a class delegates
    ``isinstance``/``issubclass`` checks to the wrapped class."""

    proxy = wrapt.ObjectProxy([1, 2, 3])
    assert isinstance(proxy, list)
    assert proxy.__class__ is list
    assert type(proxy) is wrapt.ObjectProxy

    class LabeledProxy(wrapt.ObjectProxy):
        """a labeled proxy"""

    assert LabeledProxy.__doc__ == "a labeled proxy"
    assert LabeledProxy.__module__ == __name__
    assert LabeledProxy([1]).__doc__ == list.__doc__  # instance delegates

    class Base:
        pass

    class Derived(Base):
        pass

    class_proxy = wrapt.ObjectProxy(Base)
    assert isinstance(Derived(), class_proxy)
    assert issubclass(Derived, class_proxy)
    assert not issubclass(int, class_proxy)


# ---------------------------------------------------------------------------
# Operators and conversions
# ---------------------------------------------------------------------------


def test_scalar_protocols_delegate():
    """Comparisons, hashing, truthiness, string forms and numeric conversions
    all defer to the wrapped value."""

    proxy = wrapt.ObjectProxy(5)
    assert proxy == 5 and proxy != 6
    assert proxy < 6 and proxy <= 5 and proxy > 4 and proxy >= 5
    assert hash(proxy) == hash(5)
    assert {5: "x"}[proxy] == "x"

    assert bool(wrapt.ObjectProxy([])) is False
    assert bool(wrapt.ObjectProxy([0])) is True
    assert str(wrapt.ObjectProxy("hi")) == "hi"
    assert bytes(wrapt.ObjectProxy(bytearray(b"ab"))) == b"ab"
    assert format(wrapt.ObjectProxy(3.14159), ".2f") == "3.14"
    assert repr(wrapt.ObjectProxy(123)).startswith("<ObjectProxy at ")

    assert int(wrapt.ObjectProxy(3.9)) == 3
    assert float(wrapt.ObjectProxy(2)) == 2.0
    assert complex(wrapt.ObjectProxy(1)) == complex(1)
    assert [0, 1, 2][wrapt.ObjectProxy(1)] == 1  # __index__
    assert abs(wrapt.ObjectProxy(-4)) == 4
    assert -wrapt.ObjectProxy(4) == -4 and +wrapt.ObjectProxy(-4) == -4
    assert ~wrapt.ObjectProxy(0) == -1
    assert round(wrapt.ObjectProxy(3.14159), 2) == 3.14


def test_arithmetic_operators_delegate_including_inplace():
    """Binary arithmetic/bitwise operators delegate in both directions, and
    in-place operators mutate a mutable wrapped object in place (same proxy) or
    rebind a fresh proxy for an immutable one."""

    p = wrapt.ObjectProxy(6)
    assert p + 2 == 8 and 2 + p == 8
    assert p - 2 == 4 and 10 - p == 4
    assert p * 2 == 12 and 2 * p == 12
    assert p / 2 == 3.0 and 12 / p == 2.0
    assert p // 4 == 1 and 13 // p == 2
    assert p % 4 == 2 and divmod(p, 4) == (1, 2)
    assert p**2 == 36 and pow(p, 2, 5) == 1
    assert p << 1 == 12 and p >> 1 == 3
    assert (p & 3) == 2 and (p ^ 3) == 5 and (p | 1) == 7

    lst = [1]
    proxy_list = wrapt.ObjectProxy(lst)
    proxy_list += [2, 3]
    assert isinstance(proxy_list, wrapt.ObjectProxy)
    assert proxy_list.__wrapped__ is lst and lst == [1, 2, 3]

    proxy_int = wrapt.ObjectProxy(5)
    original = proxy_int
    proxy_int += 10
    assert isinstance(proxy_int, wrapt.ObjectProxy) and int(proxy_int) == 15
    assert original.__wrapped__ == 5


def test_container_protocol_delegates():
    """len, indexing, slicing, membership, iteration and item mutation act on
    the wrapped container."""

    data = {"a": 1, "b": 2}
    proxy = wrapt.ObjectProxy(data)
    assert len(proxy) == 2 and proxy["a"] == 1 and "b" in proxy
    proxy["c"] = 3
    assert data["c"] == 3
    del proxy["a"]
    assert "a" not in data
    assert sorted(iter(proxy)) == ["b", "c"]

    seq = wrapt.ObjectProxy([10, 20, 30, 40])
    assert seq[1:3] == [20, 30]
    assert list(reversed(seq)) == [40, 30, 20, 10]


def test_context_manager_protocol_delegates():
    """``with proxy:`` drives the wrapped object's __enter__/__exit__."""

    class Ctx:
        def __init__(self):
            self.events = []

        def __enter__(self):
            self.events.append("enter")
            return "resource"

        def __exit__(self, *exc):
            self.events.append("exit")
            return False

    ctx = Ctx()
    with wrapt.ObjectProxy(ctx) as value:
        assert value == "resource"
    assert ctx.events == ["enter", "exit"]


def test_copy_and_pickle_contract():
    """The base ``ObjectProxy`` refuses copy/deepcopy/pickle; a subclass that
    implements the hooks round-trips."""

    proxy = wrapt.ObjectProxy([1, 2, 3])
    with pytest.raises(NotImplementedError):
        copy.copy(proxy)
    with pytest.raises(NotImplementedError):
        copy.deepcopy(proxy)
    with pytest.raises(NotImplementedError):
        pickle.dumps(proxy)

    restored = pickle.loads(pickle.dumps(PicklableProxy("payload")))
    assert isinstance(restored, PicklableProxy)
    assert restored.__wrapped__ == "payload"


def test_object_proxy_supports_weak_references():
    """A proxy can itself be the target of a ``weakref.ref``."""

    import weakref

    class Target:
        pass

    proxy = wrapt.ObjectProxy(Target())
    ref = weakref.ref(proxy)
    assert ref() is proxy


def test_callable_object_proxy_forwards_calls():
    """``CallableObjectProxy`` adds call forwarding on top of the transparent
    proxy, passing positional and keyword arguments through unchanged."""

    def add(a, b, c=0):
        return a + b + c

    proxy = wrapt.CallableObjectProxy(add)
    assert proxy(1, 2) == 3
    assert proxy(1, 2, c=3) == 6
    assert proxy.__wrapped__ is add
    assert proxy.__name__ == "add"
