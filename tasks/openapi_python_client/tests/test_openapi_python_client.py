"""Integration tests for ``pyclientgen``, an OpenAPI -> Python client generator.

Every test models what a real user does with the tool: it feeds a small OpenAPI
document to the ``pyclientgen generate`` command, then *imports and executes* the
generated client code to check that it behaves correctly at runtime (model
encode/decode, enums, unions, endpoint request building, response parsing,
docstrings), or feeds an invalid document and checks the generator's diagnostics.

Both the generator and the code it produces are treated as black boxes: the only
generator surface used is the ``pyclientgen`` command line, and the only generated
surface used is the public, documented layout of the generated package
(``<title>_client.models.*``, ``.api.<tag>.<operation>``, ``.client``, ``.types``,
``.errors``). Any reasonable internal organisation of the generator passes.
"""

import asyncio
import datetime
import importlib
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

# Every spec below omits ``openapi:``/``info:``/``paths:`` unless relevant; the
# helper fills them in with a fixed title so the generated package is always
# importable as ``testapi_client``.
BASE_MODULE = "testapi_client"


def _build_spec(spec: str) -> str:
    if not re.search("^openapi:", spec, re.MULTILINE):
        spec += "\nopenapi: '3.1.0'\n"
    if not re.search("^info:", spec, re.MULTILINE):
        spec += "\ninfo: {'title': 'testapi', 'description': 'my test api', 'version': '0.0.1'}\n"
    if not re.search("^paths:", spec, re.MULTILINE):
        spec += "\npaths: {}\n"
    return spec


class _Result:
    def __init__(self, proc: subprocess.CompletedProcess) -> None:
        self.exit_code = proc.returncode
        self.stdout = proc.stdout or ""
        self.stderr = proc.stderr or ""
        self.output = self.stdout + self.stderr


def _run_generator(spec: str, config: str, extra_args, add_sections: bool, suffix: str = ".yaml"):
    """Run ``pyclientgen generate`` on an inline spec. Returns (out_dir, _Result)."""
    if add_sections:
        spec = _build_spec(spec)
    # work_dir holds only the generator inputs (spec + config); a context manager
    # guarantees it is removed even if generation raises. out_root holds the
    # generated code and is returned to the caller, so it is only cleaned up here
    # on failure (the caller owns it on success).
    with tempfile.TemporaryDirectory() as work_dir:
        spec_path = Path(work_dir) / f"openapi{suffix}"
        spec_path.write_text(spec, encoding="utf-8")
        # Post-hooks (ruff) are turned off so generation is fast and its output is
        # not polluted by formatter warnings; it has no effect on generated behavior.
        cfg_text = "post_hooks: []\n"
        if config:
            cfg_text += config + "\n"
        cfg_path = Path(work_dir) / "config.yaml"
        cfg_path.write_text(cfg_text, encoding="utf-8")

        out_root = tempfile.mkdtemp()
        try:
            out_path = Path(out_root) / BASE_MODULE
            args = [
                "pyclientgen",
                "generate",
                "--path",
                str(spec_path),
                "--meta",
                "none",
                "--config",
                str(cfg_path),
                "--output-path",
                str(out_path),
                "--overwrite",
                *list(extra_args),
            ]
            proc = subprocess.run(args, capture_output=True, text=True)
            return out_root, _Result(proc)
        except Exception:
            shutil.rmtree(out_root, ignore_errors=True)
            raise


class GeneratedClient:
    """Holds a generated client and lets tests import pieces of it."""

    def __init__(self, out_root: str, result: _Result) -> None:
        self.out_root = out_root
        self.result = result
        self.base_module = BASE_MODULE
        self._old_modules: set[str] | None = None

    def __enter__(self) -> "GeneratedClient":
        sys.path.insert(0, self.out_root)
        self._old_modules = set(sys.modules.keys())
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            sys.path.remove(self.out_root)
        except ValueError:
            pass
        if self._old_modules is not None:
            for name in set(sys.modules.keys()) - self._old_modules:
                del sys.modules[name]
        shutil.rmtree(self.out_root, ignore_errors=True)

    def import_module(self, module_path: str) -> Any:
        return importlib.import_module(f"{self.base_module}{module_path}")

    def import_symbol(self, module_path: str, name: str) -> Any:
        module = self.import_module(module_path)
        try:
            return getattr(module, name)
        except AttributeError:
            existing = ", ".join(n for n in dir(module) if not n.startswith("_"))
            raise AssertionError(
                f'Could not find "{name}" in "{self.base_module}{module_path}". '
                f"Available: {existing}\nGenerator output:\n{self.result.output}"
            )


@contextmanager
def generate_client(spec: str, *, config: str = "", extra_args=(), raise_on_error: bool = True):
    out_root, result = _run_generator(spec, config, extra_args, add_sections=True)
    if raise_on_error and result.exit_code != 0:
        shutil.rmtree(out_root, ignore_errors=True)
        raise AssertionError(f"Generator failed (exit {result.exit_code}):\n{result.output}")
    with GeneratedClient(out_root, result) as gc:
        yield gc


def run_generator(spec: str, *, config: str = "", extra_args=(), add_sections: bool = False, suffix: str = ".yaml") -> _Result:
    """Run the generator and return its result, discarding any generated code."""
    out_root, result = _run_generator(spec, config, extra_args, add_sections=add_sections, suffix=suffix)
    shutil.rmtree(out_root, ignore_errors=True)
    return result


def generation_should_fail(spec: str, *, config: str = "", extra_args=(), add_sections: bool = False, suffix: str = ".yaml") -> _Result:
    result = run_generator(spec, config=config, extra_args=extra_args, add_sections=add_sections, suffix=suffix)
    assert result.exit_code != 0, f"Expected generation to fail but it succeeded:\n{result.output}"
    return result


def generate_project(spec: str, meta: str, work_dir: str) -> _Result:
    """Generate a full project (with metadata) into ``work_dir`` as the working directory.

    No ``--output-path`` is given, so the project/package directory names are
    derived from the document title.
    """
    spec_path = Path(work_dir) / "openapi.yaml"
    spec_path.write_text(spec, encoding="utf-8")
    cfg_path = Path(work_dir) / "config.yaml"
    cfg_path.write_text("post_hooks: []\n", encoding="utf-8")
    args = [
        "pyclientgen",
        "generate",
        "--path",
        str(spec_path),
        "--meta",
        meta,
        "--config",
        str(cfg_path),
        "--overwrite",
    ]
    return _Result(subprocess.run(args, capture_output=True, text=True, cwd=work_dir))


# ----- decorators that turn a spec + imports into class-scoped fixtures --------


def with_generated_client_fixture(spec: str, *, config: str = "", extra_args=(), raise_on_error: bool = True):
    def _decorator(cls):
        def generated_client(self):
            with generate_client(
                spec, config=config, extra_args=extra_args, raise_on_error=raise_on_error
            ) as gc:
                yield gc

        cls.generated_client = pytest.fixture(scope="class")(generated_client)
        return cls

    return _decorator


def with_generated_code_import(import_path: str, alias: str | None = None):
    parts = import_path.split(".")
    name = parts[-1]
    module_path = ".".join(parts[:-1])

    def _decorator(cls):
        fixture_name = alias or name

        def _func(self, generated_client):
            return generated_client.import_symbol(module_path, name)

        _func.__name__ = fixture_name
        setattr(cls, fixture_name, pytest.fixture(scope="class")(_func))
        return cls

    return _decorator


def with_generated_code_imports(*import_paths: str):
    def _decorator(cls):
        decorated = cls
        for import_path in import_paths:
            decorated = with_generated_code_import(import_path)(decorated)
        return decorated

    return _decorator


def assert_model_decode_encode(model_class: Any, json_data: dict, expected_instance: Any) -> None:
    instance = model_class.from_dict(json_data)
    assert instance == expected_instance
    assert instance.to_dict() == json_data


def _split_top_level_union(s: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current = ""
    for ch in s:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return parts


def _normalize_type(s: str) -> str:
    """Canonicalize a string type annotation so union member *ordering* doesn't matter.

    Generated annotations are PEP 563 strings like ``"int | str | Unset"``. The order
    in which union members are written is an unspecified implementation detail, so we
    sort union members (recursively, including inside ``list[...]``) before comparing.
    """
    members = sorted(_normalize_member(p.strip()) for p in _split_top_level_union(s))
    return " | ".join(members)


def _normalize_member(p: str) -> str:
    match = re.match(r"^(\w+)\[(.*)\]$", p)
    if match:
        return f"{match.group(1)}[{_normalize_type(match.group(2))}]"
    return p


def assert_type_hint(model_class: Any, name: str, expected: str) -> None:
    actual = model_class.__annotations__[name]
    assert isinstance(actual, str), f"expected a string annotation for {name}, got {actual!r}"
    # Forward-reference quoting is an implementation choice (``x: 'str'`` vs ``x: str``);
    # strip quotes so we compare the type structure, not how it was spelled.
    actual_clean = actual.replace("'", "").replace('"', "")
    assert _normalize_type(actual_clean) == _normalize_type(expected), f"{name}: {actual!r} != {expected!r}"


# ===========================================================================
# Models: properties
# ===========================================================================


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      type: object
      properties:
        req1: {type: string}
        req2: {type: string}
        opt: {type: string}
      required: ["req1", "req2"]
    DerivedModel:
      allOf:
        - $ref: "#/components/schemas/MyModel"
        - type: object
          properties:
            req3: {type: string}
          required: ["req3"]
"""
)
@with_generated_code_imports(".models.MyModel", ".models.DerivedModel")
class TestRequiredAndOptionalProperties:
    def test_roundtrip(self, MyModel, DerivedModel):
        assert_model_decode_encode(MyModel, {"req1": "a", "req2": "b"}, MyModel(req1="a", req2="b"))
        assert_model_decode_encode(
            MyModel, {"req1": "a", "req2": "b", "opt": "c"}, MyModel(req1="a", req2="b", opt="c")
        )
        # allOf merges the base model's properties into the derived one.
        assert_model_decode_encode(
            DerivedModel,
            {"req1": "a", "req2": "b", "req3": "c", "opt": "d"},
            DerivedModel(req1="a", req2="b", req3="c", opt="d"),
        )

    def test_required_missing_raises_keyerror(self, MyModel, DerivedModel):
        with pytest.raises(KeyError):
            MyModel.from_dict({"req1": "a"})
        with pytest.raises(KeyError):
            DerivedModel.from_dict({"req1": "a", "req2": "b"})


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      type: object
      properties:
        booleanProp: {type: boolean}
        stringProp: {type: string}
        numberProp: {type: number}
        intProp: {type: integer}
        anyObjectProp: {"$ref": "#/components/schemas/AnyObject"}
        nullProp: {type: "null"}
        anyProp: {}
    AnyObject:
      type: object
"""
)
@with_generated_code_imports(".models.MyModel", ".models.AnyObject")
class TestBasicScalarAndAnyProperties:
    def test_decode_encode(self, MyModel, AnyObject):
        json_data = {
            "booleanProp": True,
            "stringProp": "a",
            "numberProp": 1.5,
            "intProp": 2,
            "anyObjectProp": {"d": 3},
            "nullProp": None,
            "anyProp": "e",
        }
        expected_any_object = AnyObject()
        expected_any_object.additional_properties = {"d": 3}
        assert_model_decode_encode(
            MyModel,
            json_data,
            MyModel(
                boolean_prop=True,
                string_prop="a",
                number_prop=1.5,
                int_prop=2,
                any_object_prop=expected_any_object,
                null_prop=None,
                any_prop="e",
            ),
        )

    def test_decode_error_not_object(self, MyModel):
        for bad in ("a", True, 2, None):
            with pytest.raises(Exception):
                MyModel.from_dict(bad)


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      type: object
      properties:
        dateProp: {type: string, format: date}
        dateTimeProp: {type: string, format: date-time}
        uuidProp: {type: string, format: uuid}
        unknownFormatProp: {type: string, format: weird}
"""
)
@with_generated_code_imports(".models.MyModel")
class TestSpecialStringFormats:
    def test_decode_encode(self, MyModel):
        date_value = datetime.date(2021, 2, 3)
        date_time_value = datetime.datetime(2021, 2, 3, 4, 5, 6, tzinfo=datetime.UTC)
        uuid_value = uuid.UUID("07EF8B4D-AA09-4FFA-898D-C710796AFF41")
        assert_model_decode_encode(MyModel, {"dateProp": date_value.isoformat()}, MyModel(date_prop=date_value))
        assert_model_decode_encode(
            MyModel, {"dateTimeProp": date_time_value.isoformat()}, MyModel(date_time_prop=date_time_value)
        )
        assert_model_decode_encode(MyModel, {"uuidProp": str(uuid_value)}, MyModel(uuid_prop=uuid_value))
        # An unrecognized format falls back to a plain string.
        assert_model_decode_encode(
            MyModel, {"unknownFormatProp": "whatever"}, MyModel(unknown_format_prop="whatever")
        )

    def test_type_hints(self, MyModel):
        assert_type_hint(MyModel, "date_prop", "datetime.date | Unset")
        assert_type_hint(MyModel, "date_time_prop", "datetime.datetime | Unset")
        assert_type_hint(MyModel, "uuid_prop", "UUID | Unset")
        assert_type_hint(MyModel, "unknown_format_prop", "str | Unset")


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      type: object
      properties:
        refProp: {"$ref": "#/components/schemas/Alias1"}
    Alias1:
      $ref: "#/components/schemas/Alias2"
    Alias2:
      type: object
      properties:
        booleanProp: {type: boolean}
"""
)
@with_generated_code_imports(".models.MyModel")
class TestReferenceChains:
    def test_decode_encode(self, MyModel):
        # A property whose schema is a chain of $ref-only aliases resolves to the
        # final concrete object, which is parsed into a real nested instance
        # (whatever the generator names it) rather than left as a raw dict.
        instance = MyModel.from_dict({"refProp": {"booleanProp": False}})
        assert instance.ref_prop.boolean_prop is False
        assert instance.to_dict() == {"refProp": {"booleanProp": False}}


@with_generated_client_fixture(
    """
components:
  schemas:
    StringDict:
      type: object
      additionalProperties: {type: string}
"""
)
@with_generated_code_imports(".models.StringDict")
class TestAdditionalProperties:
    def test_typed_additional_properties_roundtrip(self, StringDict):
        instance = StringDict.from_dict({"a": "x", "b": "y"})
        assert instance.additional_properties == {"a": "x", "b": "y"}
        assert instance.to_dict() == {"a": "x", "b": "y"}

    def test_mapping_interface(self, StringDict):
        instance = StringDict.from_dict({"a": "x", "b": "y"})
        assert instance["a"] == "x"
        assert set(instance.additional_keys) == {"a", "b"}
        instance["c"] = "z"
        assert instance["c"] == "z"
        assert "c" in instance


# ===========================================================================
# Enums and consts
# ===========================================================================


@with_generated_client_fixture(
    """
components:
  schemas:
    MyEnum:
      type: string
      enum: ["a", "B", "a23", "123", "1bc", "a Thing WIth spaces", ""]
    MyModel:
      properties:
        enumProp: {"$ref": "#/components/schemas/MyEnum"}
        inlineEnumProp:
          type: string
          enum: ["a", "b"]
    MyModelWithRequired:
      properties:
        enumProp: {"$ref": "#/components/schemas/MyEnum"}
      required: ["enumProp"]
"""
)
@with_generated_code_imports(
    ".models.MyEnum",
    ".models.MyModel",
    ".models.MyModelInlineEnumProp",
    ".models.MyModelWithRequired",
)
class TestStringEnum:
    def test_member_names(self, MyEnum):
        # Member names are derived from values: identifier-safe values are upper-cased,
        # others get a VALUE_<n> name; whitespace/symbols become underscores.
        expected = {
            "A": "a",
            "B": "B",
            "A23": "a23",
            "VALUE_3": "123",
            "VALUE_4": "1bc",
            "A_THING_WITH_SPACES": "a Thing WIth spaces",
            "VALUE_6": "",
        }
        for member_name, value in expected.items():
            assert getattr(MyEnum, member_name) == MyEnum(value)

    def test_enum_prop_roundtrip(self, MyEnum, MyModel, MyModelInlineEnumProp):
        assert_model_decode_encode(MyModel, {"enumProp": "B"}, MyModel(enum_prop=MyEnum.B))
        # Inline enums get a synthesized name based on the owning model + property.
        assert_model_decode_encode(
            MyModel, {"inlineEnumProp": "a"}, MyModel(inline_enum_prop=MyModelInlineEnumProp.A)
        )

    def test_invalid_values(self, MyModel):
        with pytest.raises(ValueError):
            MyModel.from_dict({"enumProp": "c"})
        with pytest.raises(ValueError):
            MyModel.from_dict({"enumProp": "A"})  # member *name*, not a value
        with pytest.raises(ValueError):
            MyModel.from_dict({"enumProp": 2})


@with_generated_client_fixture(
    """
components:
  schemas:
    MyStrEnum:
      type: string
      enum: ["a", "b", "c"]
      x-enum-varnames: ["One", "More than OnE", "not_quite_four"]
    MyIntEnum:
      type: integer
      enum: [2, 3, -4]
      x-enum-varnames: ["Two", "Three", "Negative Four"]
"""
)
@with_generated_code_imports(".models.MyStrEnum", ".models.MyIntEnum")
class TestEnumVarNames:
    def test_string_varnames(self, MyStrEnum):
        for name, value in [("ONE", "a"), ("MORE_THAN_ON_E", "b"), ("NOT_QUITE_FOUR", "c")]:
            assert getattr(MyStrEnum, name) == MyStrEnum(value)

    def test_int_varnames(self, MyIntEnum):
        for name, value in [("TWO", 2), ("THREE", 3), ("NEGATIVE_FOUR", -4)]:
            assert getattr(MyIntEnum, name) == MyIntEnum(value)


@with_generated_client_fixture(
    """
components:
  schemas:
    MyEnum:
      type: integer
      enum: [2, 3, -4]
    MyModel:
      properties:
        enumProp: {"$ref": "#/components/schemas/MyEnum"}
    MyModelWithRequired:
      properties:
        enumProp: {"$ref": "#/components/schemas/MyEnum"}
      required: ["enumProp"]
"""
)
@with_generated_code_imports(".models.MyEnum", ".models.MyModel", ".models.MyModelWithRequired")
class TestIntEnum:
    def test_member_names_and_roundtrip(self, MyEnum, MyModel):
        for name, value in [("VALUE_2", 2), ("VALUE_3", 3), ("VALUE_NEGATIVE_4", -4)]:
            assert getattr(MyEnum, name) == MyEnum(value)
        assert_model_decode_encode(MyModel, {"enumProp": 2}, MyModel(enum_prop=MyEnum.VALUE_2))

    def test_invalid_values(self, MyModel):
        with pytest.raises(ValueError):
            MyModel.from_dict({"enumProp": 5})
        with pytest.raises(ValueError):
            MyModel.from_dict({"enumProp": "a"})


@with_generated_client_fixture(
    """
components:
  schemas:
    MyEnum:
      type: string
      enum: ["a", "b"]
    MyEnumIncludingNull:
      type: ["string", "null"]
      enum: ["a", "b", null]
    MyNullOnlyEnum:
      enum: [null]
    MyModel:
      properties:
        nullableEnumProp:
          oneOf:
            - {"$ref": "#/components/schemas/MyEnum"}
            - type: "null"
        enumIncludingNullProp: {"$ref": "#/components/schemas/MyEnumIncludingNull"}
        nullOnlyEnumProp: {"$ref": "#/components/schemas/MyNullOnlyEnum"}
"""
)
@with_generated_code_imports(".models.MyEnum", ".models.MyModel")
class TestNullableEnums:
    def test_roundtrip(self, MyModel, MyEnum):
        assert_model_decode_encode(MyModel, {"nullableEnumProp": "b"}, MyModel(nullable_enum_prop=MyEnum.B))
        assert_model_decode_encode(MyModel, {"nullableEnumProp": None}, MyModel(nullable_enum_prop=None))
        assert_model_decode_encode(MyModel, {"nullOnlyEnumProp": None}, MyModel(null_only_enum_prop=None))

    def test_type_hints(self, MyModel):
        assert_type_hint(MyModel, "nullable_enum_prop", "MyEnum | None | Unset")


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      properties:
        mustBeErnest: {const: Ernest}
        mustBeThirty: {const: 30}
"""
)
@with_generated_code_imports(".models.MyModel")
class TestConst:
    def test_valid(self, MyModel):
        instance = MyModel.from_dict({"mustBeErnest": "Ernest", "mustBeThirty": 30})
        assert instance.must_be_ernest == "Ernest"
        assert instance.must_be_thirty == 30
        assert instance.to_dict() == {"mustBeErnest": "Ernest", "mustBeThirty": 30}

    def test_invalid(self, MyModel):
        with pytest.raises(ValueError):
            MyModel.from_dict({"mustBeErnest": "Jack"})
        with pytest.raises(ValueError):
            MyModel.from_dict({"mustBeThirty": 29})


@with_generated_client_fixture(
    """
components:
  schemas:
    MyStrEnum:
      type: string
      enum: ["a", "A", "b"]
    MyIntEnum:
      type: integer
      enum: [2, 3, -4]
    MyModel:
      properties:
        strProp: {"$ref": "#/components/schemas/MyStrEnum"}
        intProp: {"$ref": "#/components/schemas/MyIntEnum"}
    MyModelWithRequired:
      properties:
        strProp: {"$ref": "#/components/schemas/MyStrEnum"}
      required: ["strProp"]
""",
    config="literal_enums: true",
)
@with_generated_code_imports(
    ".models.MyModel", ".models.MyModelWithRequired", ".models.MyStrEnum", ".models.MyIntEnum"
)
class TestLiteralEnums:
    def test_literal_aliases(self, MyStrEnum, MyIntEnum):
        from typing import Literal

        assert MyStrEnum == Literal["a", "A", "b"]
        assert MyIntEnum == Literal[2, 3, -4]

    def test_roundtrip(self, MyModel):
        assert_model_decode_encode(MyModel, {"strProp": "A"}, MyModel(str_prop="A"))
        assert_model_decode_encode(MyModel, {"intProp": -4}, MyModel(int_prop=-4))

    def test_type_hints(self, MyModel, MyModelWithRequired):
        assert_type_hint(MyModel, "str_prop", "MyStrEnum | Unset")
        assert_type_hint(MyModelWithRequired, "str_prop", "MyStrEnum")

    def test_invalid_values(self, MyModel):
        with pytest.raises(TypeError):
            MyModel.from_dict({"strProp": "c"})
        with pytest.raises(TypeError):
            MyModel.from_dict({"intProp": 9})


# ===========================================================================
# Arrays
# ===========================================================================


@with_generated_client_fixture(
    """
components:
  schemas:
    SimpleObject:
      type: object
      properties:
        name: {type: string}
    ModelWithArrayOfAny:
      properties:
        arrayProp: {type: array, items: {}}
    ModelWithArrayOfInts:
      properties:
        arrayProp: {type: array, items: {type: integer}}
    ModelWithArrayOfObjects:
      properties:
        arrayProp:
          type: array
          items: {"$ref": "#/components/schemas/SimpleObject"}
"""
)
@with_generated_code_imports(
    ".models.ModelWithArrayOfAny",
    ".models.ModelWithArrayOfInts",
    ".models.ModelWithArrayOfObjects",
    ".models.SimpleObject",
)
class TestArrays:
    def test_roundtrip(self, ModelWithArrayOfAny, ModelWithArrayOfInts, ModelWithArrayOfObjects, SimpleObject):
        assert_model_decode_encode(ModelWithArrayOfAny, {"arrayProp": ["a", 1]}, ModelWithArrayOfAny(array_prop=["a", 1]))
        assert_model_decode_encode(ModelWithArrayOfInts, {"arrayProp": [1, 2]}, ModelWithArrayOfInts(array_prop=[1, 2]))
        assert_model_decode_encode(
            ModelWithArrayOfObjects,
            {"arrayProp": [{"name": "a"}, {"name": "b"}]},
            ModelWithArrayOfObjects(array_prop=[SimpleObject(name="a"), SimpleObject(name="b")]),
        )


@with_generated_client_fixture(
    """
components:
  schemas:
    SimpleObject:
      type: object
      properties:
        name: {type: string}
    ModelWithPrefixItems:
      type: object
      properties:
        arrayProp:
          type: array
          prefixItems:
            - $ref: "#/components/schemas/SimpleObject"
            - type: string
"""
)
@with_generated_code_imports(".models.ModelWithPrefixItems", ".models.SimpleObject")
class TestPrefixItems:
    def test_roundtrip(self, ModelWithPrefixItems, SimpleObject):
        assert_model_decode_encode(
            ModelWithPrefixItems,
            {"arrayProp": [{"name": "a"}, "b"]},
            ModelWithPrefixItems(array_prop=[SimpleObject(name="a"), "b"]),
        )

    def test_type_hints(self, ModelWithPrefixItems):
        assert_type_hint(ModelWithPrefixItems, "array_prop", "list[SimpleObject | str] | Unset")


# ===========================================================================
# Defaults
# ===========================================================================


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      type: object
      properties:
        booleanProp: {type: boolean, default: true}
        stringProp: {type: string, default: "a"}
        numberProp: {type: number, default: 1.5}
        intProp: {type: integer, default: 2}
        dateProp: {type: string, format: date, default: "2024-01-02"}
        dateTimeProp: {type: string, format: date-time, default: "2024-01-02T03:04:05Z"}
        uuidProp: {type: string, format: uuid, default: "07EF8B4D-AA09-4FFA-898D-C710796AFF41"}
        intWithStringValue: {type: integer, default: "4"}
        numberWithStringValue: {type: number, default: "5.5"}
        booleanWithStringTrue: {type: boolean, default: "True"}
        booleanWithStringFalse: {type: boolean, default: "false"}
        unionWithValidDefault:
          anyOf: [{type: boolean}, {type: integer}]
          default: 3
"""
)
@with_generated_code_imports(".models.MyModel")
class TestDefaults:
    def test_defaults_in_initializer(self, MyModel):
        assert MyModel() == MyModel(
            boolean_prop=True,
            string_prop="a",
            number_prop=1.5,
            int_prop=2,
            date_prop=datetime.date(2024, 1, 2),
            date_time_prop=datetime.datetime(2024, 1, 2, 3, 4, 5, tzinfo=datetime.UTC),
            uuid_prop=uuid.UUID("07EF8B4D-AA09-4FFA-898D-C710796AFF41"),
            int_with_string_value=4,
            number_with_string_value=5.5,
            boolean_with_string_true=True,
            boolean_with_string_false=False,
            union_with_valid_default=3,
        )


@with_generated_client_fixture(
    """
components:
  schemas:
    MyEnum:
      type: string
      enum: ["a", "b"]
    MyModel:
      type: object
      properties:
        enumProp:
          allOf:
            - $ref: "#/components/schemas/MyEnum"
          default: "a"
"""
)
@with_generated_code_imports(".models.MyEnum", ".models.MyModel")
class TestEnumDefault:
    def test_enum_default(self, MyEnum, MyModel):
        assert MyModel().enum_prop == MyEnum.A


# ===========================================================================
# Unions
# ===========================================================================


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      type: object
      properties:
        stringOrIntProp:
          type: ["string", "integer"]
"""
)
@with_generated_code_imports(".models.MyModel")
class TestUnionTypeList:
    def test_roundtrip(self, MyModel):
        assert_model_decode_encode(MyModel, {"stringOrIntProp": "a"}, MyModel(string_or_int_prop="a"))
        assert_model_decode_encode(MyModel, {"stringOrIntProp": 1}, MyModel(string_or_int_prop=1))

    def test_type_hints(self, MyModel):
        assert_type_hint(MyModel, "string_or_int_prop", "int | str | Unset")


@with_generated_client_fixture(
    """
components:
  schemas:
    ThingA:
      type: object
      properties:
        propA: {type: string}
      required: ["propA"]
    ThingB:
      type: object
      properties:
        propB: {type: string}
      required: ["propB"]
    ThingAOrB:
      oneOf:
        - $ref: "#/components/schemas/ThingA"
        - $ref: "#/components/schemas/ThingB"
    ModelWithUnion:
      type: object
      properties:
        thing: {"$ref": "#/components/schemas/ThingAOrB"}
        thingOrString:
          oneOf:
            - $ref: "#/components/schemas/ThingA"
            - type: string
    ModelWithRequiredUnion:
      type: object
      properties:
        thing: {"$ref": "#/components/schemas/ThingAOrB"}
      required: ["thing"]
    ModelWithNestedUnion:
      type: object
      properties:
        thingOrValue:
          oneOf:
            - "$ref": "#/components/schemas/ThingAOrB"
            - oneOf:
              - type: string
              - type: number
"""
)
@with_generated_code_imports(
    ".models.ThingA",
    ".models.ThingB",
    ".models.ModelWithUnion",
    ".models.ModelWithRequiredUnion",
    ".models.ModelWithNestedUnion",
)
class TestOneOf:
    def test_disambiguate_objects(self, ThingA, ThingB, ModelWithUnion):
        # Objects in a union are told apart by their required properties.
        assert_model_decode_encode(ModelWithUnion, {"thing": {"propA": "x"}}, ModelWithUnion(thing=ThingA(prop_a="x")))
        assert_model_decode_encode(ModelWithUnion, {"thing": {"propB": "x"}}, ModelWithUnion(thing=ThingB(prop_b="x")))

    def test_disambiguate_object_and_scalar(self, ThingA, ModelWithUnion):
        assert_model_decode_encode(
            ModelWithUnion, {"thingOrString": {"propA": "x"}}, ModelWithUnion(thing_or_string=ThingA(prop_a="x"))
        )
        assert_model_decode_encode(
            ModelWithUnion, {"thingOrString": "x"}, ModelWithUnion(thing_or_string="x")
        )

    def test_disambiguate_nested_union(self, ThingA, ModelWithNestedUnion):
        assert_model_decode_encode(
            ModelWithNestedUnion, {"thingOrValue": {"propA": "x"}}, ModelWithNestedUnion(thing_or_value=ThingA(prop_a="x"))
        )
        assert_model_decode_encode(
            ModelWithNestedUnion, {"thingOrValue": 3}, ModelWithNestedUnion(thing_or_value=3)
        )

    def test_type_hints(self, ModelWithUnion, ModelWithRequiredUnion):
        assert_type_hint(ModelWithUnion, "thing", "ThingA | ThingB | Unset")
        assert_type_hint(ModelWithRequiredUnion, "thing", "ThingA | ThingB")


# ===========================================================================
# Docstrings
# ===========================================================================


class DocstringParser:
    def __init__(self, item: Any) -> None:
        # Strip both ends so comparisons don't depend on indentation or trailing space.
        self.lines = [line.strip() for line in item.__doc__.split("\n")]

    def get_section(self, header_line: str) -> list[str]:
        if header_line not in self.lines:
            return []
        lines = self.lines[self.lines.index(header_line) + 1 :]
        if "" in lines:
            return lines[: lines.index("")]
        return lines


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      description: I like this type.
      type: object
      properties:
        reqStr: {type: string, description: This is necessary.}
        optStr: {type: string, description: This isn't necessary.}
        undescribedProp: {type: string}
      required: ["reqStr", "undescribedProp"]
"""
)
@with_generated_code_import(".models.MyModel")
class TestModelDocstrings:
    def test_description_and_attributes(self, MyModel):
        parser = DocstringParser(MyModel)
        assert parser.lines[0] == "I like this type."
        assert set(parser.get_section("Attributes:")) == {
            "req_str (str): This is necessary.",
            "opt_str (str | Unset): This isn't necessary.",
            "undescribed_prop (str):",
        }


@with_generated_client_fixture(
    """
tags:
    - name: service1
paths:
  "/simple":
    post:
      operationId: postSimpleThing
      description: Post a simple thing.
      requestBody:
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/Thing"
      responses:
        "200":
          description: Success!
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/GoodResponse"
      tags:
        - service1
  "/simple/{id}":
    get:
      operationId: getById
      description: Get a simple thing's attribute.
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            description: Which one.
        - name: fries
          in: query
          required: false
          schema:
            type: boolean
            description: Do you want fries with that?
      responses:
        "200":
          description: Success!
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/GoodResponse"
      tags:
        - service1
components:
  schemas:
    GoodResponse: {type: object}
    Thing:
      type: object
      description: The thing.
"""
)
@with_generated_code_import(".api.service1.post_simple_thing.sync", alias="post_sync")
@with_generated_code_import(".api.service1.get_by_id.sync", alias="get_sync")
class TestEndpointDocstrings:
    def test_description(self, post_sync, get_sync):
        assert DocstringParser(post_sync).lines[0] == "Post a simple thing."
        assert DocstringParser(get_sync).lines[0] == "Get a simple thing's attribute."

    def test_args_document_body_and_params(self, post_sync, get_sync):
        # The Args section documents the request body and each parameter with its
        # type; the transport `client` argument is not listed there.
        post_args = DocstringParser(post_sync).get_section("Args:")
        assert any(line.startswith("body (Thing") for line in post_args), post_args
        assert not any(line.startswith("client") for line in post_args), post_args
        get_args = DocstringParser(get_sync).get_section("Args:")
        assert any(line.startswith("id (str") for line in get_args), get_args
        assert any(line.startswith("fries (bool") for line in get_args), get_args

    def test_returns_names_success_type(self, post_sync):
        returns = " ".join(DocstringParser(post_sync).get_section("Returns:"))
        assert "GoodResponse" in returns


# ===========================================================================
# Endpoints: request building & response parsing (generated code execution)
# ===========================================================================


def _mock_client(Client, *, status_code=200, json_body=None, content=b"{}"):
    mock_httpx = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body if json_body is not None else {}
    mock_response.content = content
    mock_response.headers = {}
    mock_httpx.request.return_value = mock_response
    client = Client(base_url="https://api.example.com")
    client.set_httpx_client(mock_httpx)
    return client, mock_httpx


@with_generated_client_fixture(
    """
paths:
  "/items/{item_id}/details/{detail_id}":
    get:
      operationId: getItemDetail
      parameters:
        - {name: item_id, in: path, required: true, schema: {type: string}}
        - {name: detail_id, in: path, required: true, schema: {type: string}}
      responses:
        "200":
          description: Success
          content:
            application/json:
              schema: {type: object}
"""
)
@with_generated_code_import(".api.default.get_item_detail.sync_detailed")
@with_generated_code_import(".client.Client")
class TestPathParameterEncoding:
    def test_path_params_encoded(self, sync_detailed, Client):
        # Normal characters pass through; reserved characters, spaces and '#'
        # are percent-encoded into the URL path.
        cases = [
            (("item123", "detail456"), "/items/item123/details/detail456"),
            (("item/with/slashes", "detail?with=query&chars"),
             "/items/item%2Fwith%2Fslashes/details/detail%3Fwith%3Dquery%26chars"),
            (("item with spaces", "detail with spaces"),
             "/items/item%20with%20spaces/details/detail%20with%20spaces"),
            (("item#1", "detail#id"), "/items/item%231/details/detail%23id"),
        ]
        for (item_id, detail_id), expected_url in cases:
            client, mock_httpx = _mock_client(Client)
            sync_detailed(item_id=item_id, detail_id=detail_id, client=client)
            assert mock_httpx.request.call_args[1]["url"] == expected_url


@with_generated_client_fixture(
    """
paths:
  "/widgets":
    post:
      operationId: createWidget
      parameters:
        - {name: limit, in: query, required: false, schema: {type: integer}}
      requestBody:
        content:
          application/json:
            schema: {"$ref": "#/components/schemas/Widget"}
      responses:
        "200":
          description: Success
          content:
            application/json:
              schema: {"$ref": "#/components/schemas/Widget"}
components:
  schemas:
    Widget:
      type: object
      properties:
        name: {type: string}
      required: ["name"]
"""
)
@with_generated_code_import(".api.default.create_widget.sync_detailed")
@with_generated_code_import(".client.Client")
@with_generated_code_import(".models.Widget")
class TestEndpointRequestBuilding:
    def test_request_kwargs(self, sync_detailed, Client, Widget):
        client, mock_httpx = _mock_client(Client, json_body={"name": "abc"})
        sync_detailed(client=client, body=Widget(name="abc"), limit=5)
        call = mock_httpx.request.call_args[1]
        assert call["method"].lower() == "post"
        assert call["url"] == "/widgets"
        assert call["params"] == {"limit": 5}
        assert call["json"] == {"name": "abc"}


@with_generated_client_fixture(
    """
paths:
  "/things/{id}":
    get:
      operationId: getThing
      parameters:
        - {name: id, in: path, required: true, schema: {type: string}}
      responses:
        "200":
          description: Success
          content:
            application/json:
              schema: {"$ref": "#/components/schemas/Thing"}
        "404":
          description: Missing
          content:
            application/json:
              schema: {"$ref": "#/components/schemas/ApiError"}
components:
  schemas:
    Thing:
      type: object
      properties:
        name: {type: string}
      required: ["name"]
    ApiError:
      type: object
      properties:
        message: {type: string}
      required: ["message"]
"""
)
@with_generated_code_import(".api.default.get_thing.sync")
@with_generated_code_import(".api.default.get_thing.sync_detailed")
@with_generated_code_import(".api.default.get_thing.asyncio", alias="async_parsed")
@with_generated_code_import(".api.default.get_thing.asyncio_detailed", alias="async_detailed")
@with_generated_code_import(".client.Client")
@with_generated_code_import(".models.Thing")
@with_generated_code_import(".models.ApiError")
class TestEndpointResponseParsing:
    def test_success_response_parsed_to_model(self, sync, sync_detailed, Client, Thing):
        from http import HTTPStatus

        client, _ = _mock_client(Client, status_code=200, json_body={"name": "abc"}, content=b'{"name": "abc"}')
        assert sync(id="x", client=client) == Thing(name="abc")

        client, _ = _mock_client(Client, status_code=200, json_body={"name": "abc"}, content=b'{"name": "abc"}')
        detailed = sync_detailed(id="x", client=client)
        assert detailed.status_code == HTTPStatus.OK
        assert detailed.parsed == Thing(name="abc")
        assert detailed.content == b'{"name": "abc"}'

    def test_documented_error_status_parsed(self, sync, Client, ApiError):
        client, _ = _mock_client(Client, status_code=404, json_body={"message": "nope"}, content=b'{"message": "nope"}')
        assert sync(id="x", client=client) == ApiError(message="nope")

    def test_undocumented_status_returns_none(self, sync, Client):
        client, _ = _mock_client(Client, status_code=500, json_body={}, content=b"{}")
        assert sync(id="x", client=client) is None

    def test_undocumented_status_raises_when_configured(self, sync, Client):
        errors = importlib.import_module(f"{BASE_MODULE}.errors")
        mock_httpx = MagicMock(spec=httpx.Client)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.content = b"{}"
        mock_response.headers = {}
        mock_httpx.request.return_value = mock_response
        client = Client(base_url="https://api.example.com", raise_on_unexpected_status=True)
        client.set_httpx_client(mock_httpx)
        with pytest.raises(errors.UnexpectedStatus):
            sync(id="x", client=client)

    def test_async_response_parsed_to_model(self, async_parsed, async_detailed, Client, Thing):
        # The async functions are a distinct deliverable: they issue the request via
        # the client's async httpx client and parse the response the same way.
        from http import HTTPStatus

        def _client():
            mock_async = MagicMock(spec=httpx.AsyncClient)
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = {"name": "abc"}
            mock_response.content = b'{"name": "abc"}'
            mock_response.headers = {}
            mock_async.request = AsyncMock(return_value=mock_response)
            client = Client(base_url="https://api.example.com")
            client.set_async_httpx_client(mock_async)
            return client

        assert asyncio.run(async_parsed(id="x", client=_client())) == Thing(name="abc")
        detailed = asyncio.run(async_detailed(id="x", client=_client()))
        assert detailed.status_code == HTTPStatus.OK
        assert detailed.parsed == Thing(name="abc")


@with_generated_client_fixture(
    """
paths:
  "/ping":
    get:
      operationId: ping
      responses:
        "200": {description: ok, content: {application/json: {schema: {type: object}}}}
"""
)
@with_generated_code_import(".client.Client")
@with_generated_code_import(".client.AuthenticatedClient")
class TestClient:
    def test_authenticated_client_sets_auth_header(self, AuthenticatedClient):
        client = AuthenticatedClient(base_url="https://api.example.com", token="abc123")
        httpx_client = client.get_httpx_client()
        assert httpx_client.headers["Authorization"] == "Bearer abc123"

    def test_with_headers_returns_new_client(self, Client):
        client = Client(base_url="https://api.example.com")
        updated = client.with_headers({"X-Custom": "yes"})
        assert updated.get_httpx_client().headers["X-Custom"] == "yes"


@with_generated_client_fixture(
    """
paths:
  "/things":
    get:
      operationId: listThings
      parameters:
        - {name: kind, in: query, required: false, schema: {"$ref": "#/components/schemas/Kind"}}
        - {name: ids, in: query, required: false, schema: {type: array, items: {type: integer}}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: array, items: {"$ref": "#/components/schemas/Thing"}}
components:
  schemas:
    Kind: {type: string, enum: ["a", "b"]}
    Thing:
      type: object
      properties: {name: {type: string}}
      required: ["name"]
"""
)
@with_generated_code_import(".api.default.list_things.sync")
@with_generated_code_import(".api.default.list_things.sync_detailed")
@with_generated_code_import(".client.Client")
@with_generated_code_import(".models.Thing")
@with_generated_code_import(".models.Kind")
class TestListResponseAndParams:
    def test_list_response_parsed(self, sync, Client, Thing):
        client, _ = _mock_client(Client, status_code=200, json_body=[{"name": "a"}, {"name": "b"}])
        assert sync(client=client) == [Thing(name="a"), Thing(name="b")]

    def test_query_param_serialization(self, sync_detailed, Client, Kind):
        # An enum query parameter serializes to its value; a list parameter stays a list.
        client, mock_httpx = _mock_client(Client, status_code=200, json_body=[])
        sync_detailed(client=client, kind=Kind.A, ids=[1, 2])
        assert mock_httpx.request.call_args[1]["params"] == {"kind": "a", "ids": [1, 2]}


@with_generated_client_fixture(
    """
paths:
  "/upload":
    post:
      operationId: uploadThing
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                someFile: {type: string, format: binary}
                someString: {type: string}
              required: ["someFile"]
      responses:
        "200": {description: ok, content: {application/json: {schema: {type: object}}}}
"""
)
@with_generated_code_import(".api.default.upload_thing.sync_detailed")
@with_generated_code_import(".client.Client")
@with_generated_code_import(".models.UploadThingBody")
@with_generated_code_import(".types.File")
class TestMultipartBody:
    def test_multipart_request(self, sync_detailed, Client, UploadThingBody, File):
        from io import BytesIO

        client, mock_httpx = _mock_client(Client)
        body = UploadThingBody(
            some_file=File(payload=BytesIO(b"data"), file_name="f.txt", mime_type="text/plain"),
            some_string="hello",
        )
        sync_detailed(client=client, body=body)
        call = mock_httpx.request.call_args[1]
        # Multipart bodies are sent as httpx ``files`` (a list of (name, file-tuple) pairs).
        files = dict(call["files"])
        assert files["someFile"][0] == "f.txt"
        assert files["someFile"][2] == "text/plain"
        assert files["someString"] == (None, b"hello", "text/plain")
        assert "multipart/form-data" in call["headers"]["Content-Type"]


@with_generated_client_fixture(
    """
paths:
  "/form":
    post:
      operationId: submitForm
      requestBody:
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              properties:
                name: {type: string}
                count: {type: integer}
              required: ["name"]
      responses:
        "200": {description: ok, content: {application/json: {schema: {type: object}}}}
"""
)
@with_generated_code_import(".api.default.submit_form.sync_detailed")
@with_generated_code_import(".client.Client")
@with_generated_code_import(".models.SubmitFormBody")
class TestUrlEncodedBody:
    def test_urlencoded_request(self, sync_detailed, Client, SubmitFormBody):
        client, mock_httpx = _mock_client(Client)
        sync_detailed(client=client, body=SubmitFormBody(name="abc", count=3))
        call = mock_httpx.request.call_args[1]
        # An ``application/x-www-form-urlencoded`` body is sent as httpx ``data`` (the
        # model serialized to its dict), with a matching Content-Type header.
        assert call["data"] == {"name": "abc", "count": 3}
        assert "application/x-www-form-urlencoded" in call["headers"]["Content-Type"]


# ===========================================================================
# Config options
# ===========================================================================


@with_generated_client_fixture(
    """
components:
  schemas:
    OriginalLongName:
      type: object
      properties:
        name: {type: string}
""",
    config="""class_overrides:
  OriginalLongName:
    class_name: ShortName
    module_name: short_name""",
)
@with_generated_code_import(".models.short_name.ShortName")
class TestConfigClassOverrides:
    def test_class_and_module_renamed(self, ShortName):
        # The schema's generated class name and module name are both overridden.
        assert ShortName.__name__ == "ShortName"
        assert_model_decode_encode(ShortName, {"name": "a"}, ShortName(name="a"))


@with_generated_client_fixture(
    """
components:
  schemas:
    MyModel:
      type: object
      properties:
        "1leadingdigit": {type: string}
        "2ndvalue": {type: string}
""",
    config="field_prefix: attr_",
)
@with_generated_code_import(".models.MyModel")
class TestConfigFieldPrefix:
    def test_invalid_identifiers_get_prefix(self, MyModel):
        # Property names that aren't valid Python identifiers (here, names starting
        # with a digit) get the configured prefix to form a valid attribute name,
        # while the original JSON names are preserved on the wire.
        assert_model_decode_encode(
            MyModel,
            {"1leadingdigit": "a", "2ndvalue": "b"},
            MyModel(attr_1leadingdigit="a", attr_2ndvalue="b"),
        )


# ===========================================================================
# Project metadata generation (--meta)
# ===========================================================================


_META_SPEC = (
    "openapi: '3.1.0'\n"
    "info: {title: My Cool API, version: '1.2.3'}\n"
    "paths: {}\n"
    "components: {schemas: {Thing: {type: object, properties: {name: {type: string}}}}}\n"
)


class TestMetadataGeneration:
    def test_poetry_project_layout(self, tmp_path):
        work = str(tmp_path)
        result = generate_project(_META_SPEC, "poetry", work)
        assert result.exit_code == 0, result.output
        # Project dir name is kebab-case(title) + "-client"; the package dir is its snake_case form.
        project = Path(work) / "my-cool-api-client"
        assert project.is_dir()
        assert (project / "my_cool_api_client").is_dir()
        assert (project / "README.md").is_file()
        pyproject = (project / "pyproject.toml").read_text()
        # Assert the project name value, not the TOML string-quote style (single vs
        # double quotes are semantically identical, valid TOML).
        assert re.search(r"""name\s*=\s*["']my-cool-api-client["']""", pyproject)
        assert "1.2.3" in pyproject  # version comes from the OpenAPI document

    def test_setup_and_none_variants(self, tmp_path):
        # Each variant generates into its own empty subdir; pytest cleans up tmp_path.
        work_setup = tmp_path / "setup_project"
        work_setup.mkdir()
        work = str(work_setup)
        assert generate_project(_META_SPEC, "setup", work).exit_code == 0
        assert (Path(work) / "my-cool-api-client" / "setup.py").is_file()

        work_none = tmp_path / "none_project"
        work_none.mkdir()
        work = str(work_none)
        assert generate_project(_META_SPEC, "none", work).exit_code == 0
        # With meta=none the package is emitted directly, with no project metadata.
        package = Path(work) / "my_cool_api_client"
        assert (package / "types.py").is_file()
        assert not (package / "pyproject.toml").exists()
        assert not (Path(work) / "my-cool-api-client").exists()


# ===========================================================================
# Generator diagnostics: invalid specs (fatal) and unprocessable schemas (warnings)
# ===========================================================================


class TestInvalidSpecsFatal:
    def test_unparseable_documents(self):
        # A .json file with broken JSON, a .yaml file with broken YAML, and a
        # syntactically valid YAML that is not an OpenAPI document each fail.
        assert "Invalid JSON" in generation_should_fail("Not JSON", add_sections=False, suffix=".json").output
        assert "Invalid YAML" in generation_should_fail("{", add_sections=False, suffix=".yaml").output
        assert "Failed to parse OpenAPI document" in generation_should_fail(
            "not a valid openapi document", add_sections=False
        ).output

    def test_missing_required_fields(self):
        # Missing any of openapi/info.title/info.version/paths is a fatal parse error.
        for spec in (
            "info: {title: My API, version: '1.0'}\npaths: {}\n",  # no openapi
            "openapi: '3.1.0'\ninfo: {version: '1.0'}\npaths: {}\n",  # no title
            "openapi: '3.1.0'\ninfo: {title: My API}\npaths: {}\n",  # no version
            "openapi: '3.1.0'\ninfo: {title: My API, version: '1.0'}\n",  # no paths
        ):
            assert "Failed to parse OpenAPI document" in generation_should_fail(spec, add_sections=False).output

    def test_swagger_rejected(self):
        result = generation_should_fail(
            "swagger: '2.0'\ninfo: {title: My API, version: '1.0'}\npaths: {}\n", add_sections=False
        )
        assert "Swagger" in result.output


@with_generated_client_fixture(
    """
components:
  schemas:
    GoodModel:
      type: object
      properties:
        name: {type: string}
    EnumWithMixedTypes:
      enum: ["A", 1]
    ArrayWithNoItems:
      type: array
""",
    raise_on_error=False,
)
@with_generated_code_import(".models.GoodModel")
class TestUnprocessableSchemasWarn:
    def test_generation_succeeds_with_warnings(self, generated_client):
        # Unprocessable schemas are reported as warnings (not fatal errors), and
        # each warning identifies the offending schema by name.
        assert generated_client.result.exit_code == 0
        output = generated_client.result.output
        assert "EnumWithMixedTypes" in output
        assert "ArrayWithNoItems" in output

    def test_bad_schemas_skipped_good_kept(self, generated_client, GoodModel):
        # The valid sibling schema is still generated and usable...
        assert_model_decode_encode(GoodModel, {"name": "a"}, GoodModel(name="a"))
        # ...while the unprocessable ones are not emitted as models.
        with pytest.raises(Exception):
            generated_client.import_symbol(".models.enum_with_mixed_types", "EnumWithMixedTypes")
        with pytest.raises(Exception):
            generated_client.import_symbol(".models.array_with_no_items", "ArrayWithNoItems")


class TestFailOnWarning:
    def test_fail_on_warning_flag(self):
        # With --fail-on-warning, a warning-level problem becomes a non-zero exit.
        spec = """
components:
  schemas:
    EnumWithMixedTypes:
      enum: ["A", 1]
"""
        assert generation_should_fail(_build_spec(spec), add_sections=False, extra_args=["--fail-on-warning"])


class TestCircularReference:
    def test_circular_reference_reported(self):
        # A circular $ref chain reached through a property is detected and
        # reported (rather than crashing or looping); the affected schema is
        # dropped with a warning and generation still completes.
        spec = """
components:
  schemas:
    MyModel:
      type: object
      properties:
        anyObjectProp: {"$ref": "#/components/schemas/AnyObject"}
    AnyObject:
      $ref: "#/components/schemas/OtherObject"
    OtherObject:
      $ref: "#/components/schemas/AnyObject"
"""
        result = run_generator(_build_spec(spec), add_sections=False)
        assert result.exit_code == 0
        assert "Circular" in result.output
