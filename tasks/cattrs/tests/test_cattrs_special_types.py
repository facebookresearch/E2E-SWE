"""Special typing constructs: NewType, Final, Literal, Enum, TypedDict.

Each test bundles the basic case with the subtle contract for one construct so it fails as
a unit when the construct is mishandled.
"""

import enum
from typing import Final, Literal, NewType, Optional

from attrs import define
from typing_extensions import NotRequired, TypedDict

from cattrs import Converter


def test_newtype_delegation_and_transitive_hooks():
    """NewTypes delegate to their base hook, and a hook on an inner NewType is honored transitively."""
    c = Converter()
    UserId = NewType("UserId", int)
    assert c.structure("42", UserId) == 42

    Inner = NewType("Inner", int)
    Mid = NewType("Mid", Inner)
    Outer = NewType("Outer", Mid)
    c.register_structure_hook(Inner, lambda v, _: int(v) + 1)
    # The outer NewType must resolve transitively through to the innermost registered hook.
    assert c.structure("5", Outer) == 6
    assert c.structure("9", Inner) == 10

    # A hook registered on a middle NewType is used by the outer one.
    c2 = Converter()
    A = NewType("A", int)
    B = NewType("B", A)
    C = NewType("C", B)
    c2.register_structure_hook(B, lambda v, _: int(v) * 10)
    assert c2.structure("5", C) == 50

    # Optional[NewType] keeps None and otherwise applies the base conversion.
    @define
    class Bag:
        n: Optional[UserId]

    assert c.structure({"n": None}, Bag) == Bag(None)
    assert c.structure({"n": "4"}, Bag) == Bag(4)


def test_final_enum_and_literal_fields():
    """Final[T] and bare Final, enum-by-value, and Literal membership all convert in one class."""
    c = Converter()

    class Color(enum.Enum):
        RED = 1
        GREEN = 2

    @define
    class Cell:
        name: Final[str]
        color: Color
        mode: Literal["r", "w"]
        flag: Final = True

    cell = c.structure({"name": 1, "color": 2, "mode": "w", "flag": False}, Cell)
    assert cell == Cell("1", Color.GREEN, "w", False)
    # Bare Final round-trips via the default value's runtime type; enum -> value.
    assert c.unstructure(Cell("x", Color.RED, "r", True)) == {
        "name": "x",
        "color": 1,
        "mode": "r",
        "flag": True,
    }
    # Out-of-set Literal value is rejected.
    try:
        c.structure({"name": "n", "color": 1, "mode": "x", "flag": True}, Cell)
    except Exception:
        pass
    else:
        raise AssertionError("invalid Literal value must raise")


def test_typeddict_round_trip_and_non_mapping_error():
    """TypedDicts convert known keys per-type, allow absent NotRequired keys, reject non-mappings."""
    c = Converter()

    class Movie(TypedDict):
        title: str
        year: int
        rating: NotRequired[float]

    assert c.structure({"title": "X", "year": "1999", "rating": "8.5"}, Movie) == {
        "title": "X",
        "year": 1999,
        "rating": 8.5,
    }
    assert c.structure({"title": "Y", "year": "2001"}, Movie) == {
        "title": "Y",
        "year": 2001,
    }
    try:
        c.structure(5, Movie)
    except Exception:
        pass
    else:
        raise AssertionError("non-mapping input to a TypedDict must raise")
