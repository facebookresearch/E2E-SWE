"""End-to-end modeling workflows.

Each test loads a realistic payload into a typed object graph and serializes it back,
asserting every contract the round-trip touches (nested classes, primitive coercion
including bool, container-type preservation, generics) so it fails as a unit.
"""

from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

from attrs import define

from cattrs import Converter

T = TypeVar("T")


def test_nested_graph_with_bool_and_set():
    """Structure a nested graph with bool and set fields; round-trip preserving bool and set types."""
    c = Converter()

    @define
    class Point:
        x: int
        y: int

    @define
    class Region:
        points: list[Point]
        active: bool
        ports: set[int]

    payload = {
        "points": [{"x": "1", "y": "2"}, {"x": "3", "y": "4"}],
        "active": 1,
        "ports": ["80", "443"],
    }
    region = c.structure(payload, Region)
    assert region == Region([Point(1, 2), Point(3, 4)], True, {80, 443})
    assert region.active is True  # bool, not int 1
    out = c.unstructure(region)
    assert out == {
        "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
        "active": True,
        "ports": {80, 443},  # set field unstructures back to a set
    }
    assert isinstance(out["ports"], set)


def test_dataclass_optional_and_generics():
    """Dataclasses (optional + dict-of-class) and generic attrs classes convert through one machinery.

    Bundles dataclass support, Optional handling, and dict-of-class recursion with generic
    type-parameter binding (simple and nested), all round-tripped.
    """
    c = Converter()

    @dataclass
    class Contact:
        email: str
        phone: Optional[str]

    @dataclass
    class Org:
        name: str
        people: dict[str, Contact]

    o = c.structure(
        {"name": "Acme", "people": {"a": {"email": "a@b.c", "phone": None}}}, Org
    )
    assert o == Org("Acme", {"a": Contact("a@b.c", None)})
    assert c.unstructure(o) == {
        "name": "Acme",
        "people": {"a": {"email": "a@b.c", "phone": None}},
    }

    @define
    class Box(Generic[T]):
        item: T

    @define
    class Shelf:
        ints: Box[int]
        strs: Box[str]

    assert c.structure({"item": "5"}, Box[int]) == Box(5)
    s = c.structure({"ints": {"item": "1"}, "strs": {"item": 2}}, Shelf)
    assert s == Shelf(Box(1), Box("2"))
    assert c.unstructure(s) == {"ints": {"item": 1}, "strs": {"item": "2"}}
