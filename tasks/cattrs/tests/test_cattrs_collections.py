"""Collection conversions and collection-level customization."""

from collections import Counter, defaultdict
from typing import NamedTuple, Sequence

from attrs import define

from cattrs import Converter


def test_collections_and_overrides():
    """Tuple/Counter/defaultdict/NamedTuple conversions plus unstruct_collection_overrides.

    Bundles the collection-shape contracts (homogeneous and heterogeneous tuples with
    tuple-preserving unstructure, Counter int-coercion, defaultdict factory wiring,
    NamedTuple round-trip) with collection-level override behavior (abstract->concrete
    propagation, and serializing a set via a chosen callable).
    """
    c = Converter()
    assert c.structure(["1", "2", "3"], tuple[int, ...]) == (1, 2, 3)
    assert c.structure(["1", 2.0], tuple[int, str]) == (1, "2.0")
    out = c.unstructure((1, "x"), tuple[int, str])
    assert out == (1, "x") and isinstance(out, tuple)

    assert c.structure({"a": "3", "b": "5"}, Counter[str]) == Counter(a=3, b=5)

    dd = c.structure({"x": "1"}, defaultdict[str, int])
    assert isinstance(dd, defaultdict) and dd["x"] == 1 and dd["missing"] == 0

    class RGB(NamedTuple):
        r: int
        g: int
        b: int

    assert c.structure(["1", "2", "3"], RGB) == RGB(1, 2, 3)
    assert c.unstructure(RGB(1, 2, 3)) == (1, 2, 3)

    # An override keyed on the abstract Sequence type applies to concrete list fields.
    seq_conv = Converter(unstruct_collection_overrides={Sequence: tuple})

    @define
    class Holder:
        xs: list[int]

    holder_out = seq_conv.unstructure(Holder([1, 2, 3]))
    assert holder_out == {"xs": (1, 2, 3)} and isinstance(holder_out["xs"], tuple)

    # A set override serializes set fields via the chosen callable (here, sorted).
    set_conv = Converter(unstruct_collection_overrides={set: sorted})

    @define
    class Tags:
        values: set[int]

    assert set_conv.unstructure(Tags({3, 1, 2})) == {"values": [1, 2, 3]}
