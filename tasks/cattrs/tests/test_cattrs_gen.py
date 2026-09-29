"""Code-generation customization via override() and Converter flags.

Bundles related customization features into realistic "customize this class's serialization"
workflows.
"""

from typing import Annotated

from attrs import Factory, define, field

from cattrs import Converter
from cattrs.errors import ClassValidationError, ForbiddenExtraKeysError
from cattrs.gen import make_dict_structure_fn, make_dict_unstructure_fn, override


def test_overrides_rename_hooks_annotated_and_omit_if_default():
    """override() rename + per-field hooks, Annotated overrides, and converter omit_if_default.

    Bundles the per-field customization surface: a registered hook renaming a key and
    applying struct/unstruct hooks, an override embedded in Annotated[...], and
    converter-level omit_if_default (including factory defaults).
    """
    c = Converter()

    @define
    class Money:
        amount: int
        currency: str = "USD"

    ustruct = make_dict_unstructure_fn(
        Money, c, amount=override(unstruct_hook=lambda v: v / 100, rename="dollars")
    )
    struct = make_dict_structure_fn(
        Money,
        c,
        amount=override(struct_hook=lambda v, _: round(v * 100), rename="dollars"),
    )
    c.register_unstructure_hook(Money, ustruct)
    c.register_structure_hook(Money, struct)
    assert c.unstructure(Money(150, "EUR")) == {"dollars": 1.5, "currency": "EUR"}
    assert c.structure({"dollars": 1.5, "currency": "EUR"}, Money) == Money(150, "EUR")

    omit_conv = Converter(omit_if_default=True)

    @define
    class Doc:
        ident: Annotated[int, override(rename="id")]
        title: str = "untitled"
        tags: list = Factory(list)

    assert omit_conv.unstructure(Doc(7)) == {"id": 7}
    assert omit_conv.unstructure(Doc(7, "t", ["x"])) == {
        "id": 7,
        "title": "t",
        "tags": ["x"],
    }
    assert omit_conv.structure({"id": 9, "title": "t"}, Doc) == Doc(9, "t")


def test_use_alias_forbid_extra_and_init_false():
    """use_alias keys by alias, forbid_extra_keys rejects unknowns, init=False fields round-trip."""
    c = Converter(use_alias=True, forbid_extra_keys=True)

    @define
    class Account:
        balance: int = field(alias="_balance")
        version: int = field(init=False, default=0)

    ustruct = make_dict_unstructure_fn(Account, c, _cattrs_include_init_false=True)
    struct = make_dict_structure_fn(Account, c, _cattrs_include_init_false=True)
    c.register_unstructure_hook(Account, ustruct)
    c.register_structure_hook(Account, struct)

    a = Account(100)
    a.version = 3
    assert c.unstructure(a) == {"_balance": 100, "version": 3}
    restored = c.structure({"_balance": 100, "version": 3}, Account)
    assert restored.balance == 100 and restored.version == 3
    try:
        c.structure({"_balance": 100, "version": 3, "junk": 1}, Account)
    except ClassValidationError as e:
        assert any(isinstance(x, ForbiddenExtraKeysError) for x in e.exceptions)
    else:
        raise AssertionError("forbid_extra_keys must reject unknown keys")
