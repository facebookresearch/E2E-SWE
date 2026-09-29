"""Union handling: disambiguation, tagged unions, scalar passthrough."""

from typing import Literal, Union

from attrs import define

from cattrs import Converter
from cattrs.gen import make_dict_structure_fn, override
from cattrs.strategies import configure_tagged_union, configure_union_passthrough


def test_auto_disambiguation_unique_literal_and_fallback():
    """A union is disambiguated by literal discriminator, unique field, and an all-defaults fallback."""
    c = Converter()

    @define
    class Create:
        op: Literal["create"]
        name: str

    @define
    class Delete:
        op: Literal["delete"]
        target: int

    lit = Union[Create, Delete]
    assert c.structure({"op": "create", "name": "x"}, lit) == Create("create", "x")
    assert c.structure({"op": "delete", "target": "9"}, lit) == Delete("delete", 9)

    @define
    class Circle:
        radius: int

    @define
    class Unknown:
        note: str = "?"

    uf = Union[Circle, Unknown]
    assert c.structure({"radius": 1}, uf) == Circle(1)
    # No unique field present -> the all-defaults member is the fallback.
    assert c.structure({}, uf) == Unknown()

    # Disambiguation honors a field that has been renamed via an override: the unique
    # field of Renamed is read from its renamed key "rk".
    @define
    class Renamed:
        token: int

    @define
    class Other:
        other: int

    c.register_structure_hook(
        Renamed, make_dict_structure_fn(Renamed, c, token=override(rename="rk"))
    )
    ur = Union[Renamed, Other]
    assert c.structure({"rk": 7}, ur) == Renamed(7)
    assert c.structure({"other": 9}, ur) == Other(9)


def test_tagged_union_custom_and_custom_hook():
    """configure_tagged_union with custom tag/default, and a registered union hook taking precedence."""
    c = Converter()

    @define
    class A:
        a: int

    @define
    class B:
        b: int

    u = Union[A, B]
    configure_tagged_union(u, c, tag_name="kind", default=A)
    assert c.unstructure(A(1), u) == {"a": 1, "kind": "A"}
    assert c.structure({"kind": "B", "b": 2}, u) == B(2)
    # Missing tag -> default member A.
    assert c.structure({"a": 5}, u) == A(5)


def test_union_passthrough_scalars_and_int_as_float():
    """configure_union_passthrough passes valid scalars and accepts ints for float-containing unions."""
    c = Converter()
    u = Union[int, str, None]
    configure_union_passthrough(u, c)
    assert c.structure("hello", u) == "hello"
    assert c.structure(5, u) == 5
    assert c.structure(None, u) is None

    c2 = Converter()
    uf = Union[float, None]
    configure_union_passthrough(uf, c2)
    assert c2.structure(5, uf) == 5
