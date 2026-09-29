"""Higher-level strategies: include_subclasses and use_class_methods."""

from attrs import define

from cattrs import Converter
from cattrs.strategies import (
    configure_tagged_union,
    include_subclasses,
    use_class_methods,
)


def test_include_subclasses_unique_field_and_tagged():
    """include_subclasses resolves a base-typed slot to a subclass, by unique field and via a tag."""
    c = Converter()

    @define
    class Animal:
        name: str

    @define
    class Dog(Animal):
        breed: str

    @define
    class Cat(Animal):
        indoor: bool

    # Without a union strategy, a subclass is selected by its unique field.
    include_subclasses(Animal, c)
    assert c.structure({"name": "Rex", "breed": "lab"}, Animal) == Dog("Rex", "lab")
    assert c.structure({"name": "Tom", "indoor": True}, Animal) == Cat("Tom", True)

    # With a tagged-union strategy, the subclass round-trips through a tag.
    c2 = Converter()

    @define
    class Base:
        a: int

    @define
    class Left(Base):
        left: int

    @define
    class Right(Base):
        right: int

    include_subclasses(Base, c2, union_strategy=configure_tagged_union)
    payload = c2.unstructure(Left(1, 2), Base)
    assert c2.structure(payload, Base) == Left(1, 2)


def test_use_class_methods():
    """use_class_methods routes conversion through a class's own named methods."""
    c = Converter()

    @define
    class Temperature:
        celsius: float

        @classmethod
        def _structure(cls, data, _):
            return cls((data["f"] - 32) * 5 / 9)

        def _unstructure(self):
            return {"f": self.celsius * 9 / 5 + 32}

    use_class_methods(c, "_structure", "_unstructure")
    assert c.unstructure(Temperature(100.0)) == {"f": 212.0}
    assert c.structure({"f": 32.0}, Temperature) == Temperature(0.0)
