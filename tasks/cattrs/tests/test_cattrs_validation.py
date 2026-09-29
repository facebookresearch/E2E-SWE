"""Detailed validation: error collection, path-annotated reporting, and the fast path."""

from attrs import define

from cattrs import Converter, transform_error
from cattrs.errors import ClassValidationError


def test_detailed_validation_reporting_and_fast_path():
    """transform_error paths/messages, forbid_extra reporting, and the detailed_validation=False path.

    One workflow over the validation surface: a multi-error nested payload (asserting exact
    transform_error strings and ClassValidationError.cl), mapping-key repr paths, the
    forbid_extra_keys message, and the fast path raising the first native exception.
    """
    c = Converter()

    @define
    class Inner:
        x: int

    @define
    class Outer:
        a: int
        b: list[int]
        c: Inner

    try:
        c.structure({"b": [1, "z", 3], "c": {"x": "nope"}}, Outer)
    except ClassValidationError as e:
        assert e.cl is Outer
        assert set(transform_error(e)) == {
            "required field missing @ $.a",
            "invalid value for type, expected int @ $.b[1]",
            "invalid value for type, expected int @ $.c.x",
        }
    else:
        raise AssertionError("expected ClassValidationError")

    # Mapping value errors render the offending key with repr (quotes for string keys).
    try:
        c.structure({"good": 1, "bad": "x"}, dict[str, int])
    except Exception as e:
        assert transform_error(e) == ["invalid value for type, expected int @ $['bad']"]
    else:
        raise AssertionError("expected a validation error")

    fe = Converter(forbid_extra_keys=True)

    @define
    class P:
        a: int

    try:
        fe.structure({"d": 1}, P)
    except ClassValidationError as e:
        assert set(transform_error(e)) == {
            "required field missing @ $.a",
            "extra fields found (d) @ $",
        }
    else:
        raise AssertionError("expected ClassValidationError")

    # detailed_validation=False -> the first native exception propagates directly.
    fast = Converter(detailed_validation=False)
    try:
        fast.structure({}, P)
    except ClassValidationError:
        raise AssertionError("should not wrap when detailed_validation is off")
    except KeyError as e:
        assert e.args[0] == "a"
