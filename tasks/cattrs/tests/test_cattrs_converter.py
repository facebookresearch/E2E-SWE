"""Converter object model: hook registration/factories, copy, and BaseConverter specifics."""

from attrs import define

from cattrs import BaseConverter, Converter, UnstructureStrategy
from cattrs.errors import StructureHandlerNotFoundError


def test_hook_precedence_factories_and_unsupported():
    """Newest/subclass hook precedence, plain/extended hook factories, and unsupported-type errors."""
    c = Converter()

    class Base:
        pass

    class Sub(Base):
        pass

    c.register_unstructure_hook(Base, lambda v: "base")
    c.register_unstructure_hook(Base, lambda v: "base2")
    c.register_unstructure_hook(Sub, lambda v: "sub")
    assert c.unstructure(Base()) == "base2"
    assert c.unstructure(Sub()) == "sub"

    class Marker:
        def __init__(self, raw):
            self.raw = raw

        def __eq__(self, other):
            return isinstance(other, Marker) and other.raw == self.raw

    # Plain structure factory: factory(type) -> hook.
    c.register_structure_hook_factory(
        lambda t: t is Marker, lambda t: lambda v, _: Marker(v)
    )
    assert c.structure("hi", Marker) == Marker("hi")

    class Wrapped:
        def __init__(self, v):
            self.v = v

    # Extended unstructure factory: factory(type, converter) -> hook.
    c.register_unstructure_hook_factory(
        lambda t: t is Wrapped, lambda t, conv: lambda v: {"w": v.v}
    )
    assert c.unstructure(Wrapped(5)) == {"w": 5}

    class Plain:
        pass

    try:
        c.structure({}, Plain)
    except StructureHandlerNotFoundError as e:
        assert e.type_ is Plain
    else:
        raise AssertionError(
            "unsupported type must raise StructureHandlerNotFoundError"
        )


def test_copy_and_baseconverter_specifics():
    """copy() preserves config + custom hooks; BaseConverter AS_TUPLE and fromdict semantics.

    Bundles the converter object-model contracts: copy() carrying configuration and
    post-construction hooks, BaseConverter AS_TUPLE (un)structuring to/from tuples, and
    structure_attrs_fromdict ignoring extras and missing-defaulted keys.
    """
    c = Converter(forbid_extra_keys=True)

    @define
    class A:
        x: int

    c.register_structure_hook(int, lambda v, _: int(v) + 100)
    clone = c.copy()
    assert clone.structure("1", int) == 101
    try:
        clone.structure({"x": 1, "extra": 2}, A)
    except Exception as e:
        assert e.__class__.__name__ == "ClassValidationError"
    else:
        raise AssertionError("forbid_extra_keys config not preserved by copy")

    tup = BaseConverter(unstruct_strat=UnstructureStrategy.AS_TUPLE)

    @define
    class Point:
        x: int
        y: int

    assert tup.unstructure(Point(1, 2)) == (1, 2)
    assert tup.structure_attrs_fromtuple((1, 2), Point) == Point(1, 2)

    plain = BaseConverter()

    @define
    class Rec:
        a: int
        b: int = 9

    assert plain.structure_attrs_fromdict({"a": 1, "zzz": 5}, Rec) == Rec(1, 9)
