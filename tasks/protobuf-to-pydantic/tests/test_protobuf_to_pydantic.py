"""Behaviour tests for protobuf-to-pydantic across its three generation flows (pydantic v2).

Each test feeds a compiled protobuf message into a flow and asserts the resulting pydantic model accepts
valid input and rejects specific rule violations with ``ValidationError`` -- semantic behaviour, never the
exact text of generated source.

Flows under test:
* runtime  -- ``msg_to_pydantic_model`` (helper ``runtime_model``)
* code-gen -- ``pydantic_model_to_py_code`` then ``exec`` (helper ``codegen_model``)
* plugin   -- the protoc plugin's ``*_p2p`` modules (imported below)
"""
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid1, uuid4

import pytest
from google.protobuf.any_pb2 import Any as AnyMessage  # type: ignore
from pydantic import ValidationError

import demo_p2p_pb2 as p2p  # compiled message module (P2P rules)
import demo_pgv_pb2 as pgv  # compiled message module (PGV rules)

from conftest import CustomCommentTemplate, codegen_model, plugin_models, runtime_model


def _check(model_class, normal_dict, error_map_dict):
    """Assert ``normal_dict`` validates and each single-field override in ``error_map_dict`` is rejected."""
    model_class(**normal_dict)
    for key, value in error_map_dict.items():
        bad = deepcopy(normal_dict)
        bad[key] = value
        with pytest.raises(ValidationError):
            model_class(**bad)


def _string_normal():
    return {
        "const_test": "aaa", "len_test": "aaa", "s_range_len_test": "aa", "pattern_test": "testaa",
        "prefix_test": "prefix_testaa", "suffix_test": "aa_suffix", "contains_test": "aaa_contains_test",
        "not_contains_test": "aaa", "in_test": "a", "not_in_test": "d", "email_test": "example@example.com",
        "hostname_test": "example.com", "ip_test": "127.0.0.1", "ipv4_test": "127.0.0.1", "ipv6_test": "::1",
        "uri_test": "http://127.0.0.1", "uri_ref_test": "http://127.0.0.1/paths", "address_test": "127.0.0.1",
        "uuid_test": str(uuid4()), "pydantic_type_test": str(uuid1()), "miss_default_test": "aa",
        "required_test": "aa",
    }


# For each constrained string field, a value that violates ONLY that field's rule (every other field
# stays at its valid value from ``_string_normal``). Each value is unambiguously rejected by the
# documented rule: ``hostname`` (RFC 1034) and ``address`` (a valid RFC-1034 hostname OR an IP) both
# reject a label containing an underscore -- RFC 1034 allows only letters/digits/hyphen, and an
# underscore string is not an IP either. ``uri_ref`` is intentionally not probed: per RFC 3986 it
# accepts any relative-or-absolute reference, so no string is unambiguously an invalid uri_ref.
# Probing one field at a time -- rather than also poisoning ``not_contains_test`` on every row --
# guarantees the rejection comes from the field under test.
_STRING_VIOLATIONS = {
    "len_test": "aaaa", "s_range_len_test": "aaaa", "pattern_test": "aaaa", "prefix_test": "aaaa",
    "suffix_test": "aaaa", "contains_test": "aaaa", "not_contains_test": "not_contains", "in_test": "aaaa",
    "not_in_test": "a", "email_test": "aaaa", "hostname_test": "aa_aa", "ip_test": "aaaa",
    "ipv4_test": "aaaa", "ipv6_test": "aaaa", "uri_test": "aaaa",
    "address_test": "aa_aa", "uuid_test": "aaaa",
}


def _assert_string_rules(model_class, skip=()):
    """Each constrained string field must reject its single rule-violating value.

    ``skip`` names fields whose constraint a given flow legitimately does not enforce (e.g. the code-gen
    flow emits a plain ``str`` for ``pattern``), so only those fields are exempted -- every other field is
    still checked end-to-end.
    """
    normal = _string_normal()
    model_class(**normal)
    for column, bad_value in _STRING_VIOLATIONS.items():
        if column in skip:
            continue
        bad = deepcopy(normal)
        bad[column] = bad_value
        with pytest.raises(ValidationError):
            model_class(**bad)


# ----------------------------------------------------------------------------------------------------
# Flow (a): runtime conversion, P2P rules (parse_msg_desc_method defaults to P2P message options)
# ----------------------------------------------------------------------------------------------------
class TestRuntimeP2P:
    def test_number_rules(self):
        """Numeric rules: const/range/in/not_in/multiple_of/required across int and float encodings."""
        for msg in (p2p.Int32Test, p2p.FloatTest):
            # these messages carry a `default_template = "p2p@timestamp|10"` field needing a template hook
            model = runtime_model(msg, template=CustomCommentTemplate)
            model(in_test=2, miss_default_test=1.0, required_test=1.0, range_e_test=5, range_test=5,
                  not_in_test=9, multiple_of_test=6.0)
            with pytest.raises(ValidationError):
                model(in_test=4, miss_default_test=1.0, required_test=1.0)         # in: not allowed
            with pytest.raises(ValidationError):
                model(not_in_test=2, miss_default_test=1.0, required_test=1.0)     # not_in: forbidden value
            with pytest.raises(ValidationError):
                model(miss_default_test=1.0, required_test=1.0, range_test=99)     # range: lt violated
            with pytest.raises(ValidationError):
                model(miss_default_test=1.0, required_test=1.0, multiple_of_test=7.0)  # multiple_of
            with pytest.raises(ValidationError):
                model()  # required + miss_default both absent

    def test_string_rules(self):
        """String rules: const/len/pattern/prefix/suffix/contains/in/well-known formats (email/ip/uuid/...)."""
        _assert_string_rules(runtime_model(p2p.StringTest))

    def test_bytes_rules(self):
        """Bytes rules: length range, prefix/suffix/contains, membership."""
        model = runtime_model(p2p.BytesTest)
        normal = {
            "const_test": b"demo", "range_len_test": b"aa", "prefix_test": b"prefix_testaa",
            "suffix_test": b"aa_suffix", "contains_test": b"aaa_contains_test", "in_test": b"a",
            "not_in_test": b"d", "miss_default_test": b"d", "required_test": b"d",
        }
        model(**normal)
        for column in ["range_len_test", "prefix_test", "suffix_test", "contains_test", "in_test", "not_in_test"]:
            bad = deepcopy(normal)
            bad[column] = b"aaaaa"
            bad["not_in_test"] = b"a"
            with pytest.raises(ValidationError):
                model(**bad)

    def test_bool_rules(self):
        """Bool const rule: each field is pinned to a specific truth value."""
        model = runtime_model(p2p.BoolTest)
        model(bool_1_test=True, bool_2_test=False, miss_default_test=True, required_test=True)
        with pytest.raises(ValidationError):
            model(bool_1_test=False, bool_2_test=False, miss_default_test=True, required_test=True)

    def test_enum_rules(self):
        """Enum rules: const, in, not_in over an IntEnum-typed field."""
        _check(
            runtime_model(p2p.EnumTest),
            {"const_test": 2, "in_test": 0, "not_in_test": 1, "miss_default_test": 1, "required_test": 1},
            {"const_test": 4, "in_test": 4, "not_in_test": 2},
        )

    def test_map_rules(self):
        """Map rules: pair count bounds plus per-key and per-value constraints."""
        _check(
            runtime_model(p2p.MapTest),
            {
                "pair_test": {"a": 1}, "no_parse_test": {"a": 1}, "keys_test": {"a": 1}, "values_test": {"a": 5},
                "keys_values_test": {"a": datetime.now() + timedelta(days=1)}, "miss_default_test": {"a": 1},
                "required_test": {"a": 1},
            },
            {
                "pair_test": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6},
                "keys_test": {"aaaaaa": 1}, "values_test": {"a": 1},
                "keys_values_test": {"a": datetime.now() - timedelta(days=1)},
            },
        )

    def test_repeated_rules(self):
        """Repeated rules: item-count bounds and per-item constraints across scalar/well-known item types."""
        _check(
            runtime_model(p2p.RepeatedTest),
            {
                "range_test": ["a"], "unique_test": ["a", "b", "c"], "items_string_test": ["abc", "def"],
                "items_double_test": [1.2, 3.4], "items_int32_test": [2, 3], "items_timestamp_test": [1600000001],
                "items_duration_test": [timedelta(seconds=10)], "items_bytes_test": [b"a", b"b"],
                "miss_default_test": ["a", "b"], "required_test": ["a", "b"],
            },
            {
                "range_test": ["a", "b", "c", "d", "e", "f"], "items_string_test": ["abc", "def", "abcdef"],
                "items_double_test": [1.2, 3.4, "5.6"], "items_int32_test": [2, 3, 6],
                "items_timestamp_test": [datetime.fromtimestamp(1600000100)],
                "items_duration_test": [timedelta(seconds=25)],
                "items_bytes_test": [b"a", b"b", b"c", b"d", b"e", b"f"],
            },
        )

    def test_any_rules(self):
        """google.protobuf.Any rules: required plus type_url membership (in / not_in)."""
        _check(
            runtime_model(p2p.AnyTest),
            {
                "required_test": AnyMessage(), "not_in_test": AnyMessage(),
                "in_test": AnyMessage(type_url="type.googleapis.com/google.protobuf.Timestamp"),
                "miss_default_test": AnyMessage(type_url="type.googleapis.com/google.protobuf.Timestamp"),
            },
            {
                "in_test": AnyMessage(),
                "not_in_test": AnyMessage(type_url="type.googleapis.com/google.protobuf.Timestamp"),
            },
        )

    def test_duration_rules(self):
        """Duration rules: const, range (lt/gt and le/ge), membership."""
        _check(
            runtime_model(p2p.DurationTest),
            {
                "required_test": timedelta(seconds=3600).total_seconds(),
                "const_test": timedelta(seconds=1, microseconds=500000), "range_test": timedelta(seconds=6),
                "range_e_test": timedelta(seconds=10, microseconds=500000),
                "in_test": timedelta(seconds=1, microseconds=500000),
                "not_in_test": timedelta(seconds=2, microseconds=500000),
                "miss_default_test": timedelta(seconds=2, microseconds=500000),
            },
            {
                "const_test": timedelta(seconds=2, microseconds=500000), "range_test": timedelta(seconds=4),
                "range_e_test": timedelta(seconds=10, microseconds=500001),
                "in_test": timedelta(microseconds=500000), "not_in_test": timedelta(seconds=1, microseconds=500000),
            },
        )

    def test_timestamp_rules(self):
        """Timestamp rules: const, range, lt_now/gt_now, within window."""
        _check(
            runtime_model(p2p.TimestampTest),
            {
                "required_test": datetime.now(), "const_test": datetime.fromtimestamp(1600000000),
                "range_test": datetime.fromtimestamp(1600000009), "range_e_test": datetime.fromtimestamp(1600000010),
                "lt_now_test": datetime.now() - timedelta(days=1), "gt_now_test": datetime.now() + timedelta(days=1),
                "within_test": datetime.now(), "within_and_gt_now_test": datetime.now() + timedelta(seconds=3590),
                "miss_default_test": datetime.now(),
            },
            {
                "const_test": datetime.fromtimestamp(1600000001), "range_test": datetime.fromtimestamp(1600000010),
                "range_e_test": datetime.fromtimestamp(1600000011), "lt_now_test": datetime.now() + timedelta(days=1),
                "gt_now_test": datetime.now() - timedelta(days=1), "within_test": datetime.now() + timedelta(days=1),
                "within_and_gt_now_test": datetime.now() + timedelta(seconds=3660),
            },
        )

    def test_oneof_required(self):
        """oneof marked required: exactly one member must be set."""
        model = runtime_model(p2p.OneOfTest)
        model(x="1")
        model(y=2)
        with pytest.raises(ValidationError):
            model(x="1", y=2)   # mutually exclusive
        with pytest.raises(ValidationError):
            model()             # oneof required

    def test_oneof_not_required(self):
        """oneof without the required option: an empty init is valid."""
        runtime_model(p2p.OneOfNotTest)()

    def test_oneof_optional(self):
        """oneof_extend optional members may be explicitly None; a non-extended member may not."""
        model = runtime_model(p2p.OneOfOptionalTest)
        model(x=None)
        model(y=None)
        with pytest.raises(ValidationError):
            model(z=None)
        model(x=None, name=None, age=None)

    def test_message_required_and_skip(self):
        """message.required forces a sub-message; message.skip drops its rule checking."""
        model = runtime_model(p2p.OptionalMessage)
        with pytest.raises(ValidationError):
            model()                       # my_message1 + my_message3 required
        with pytest.raises(ValidationError):
            model(my_message1=None)
        with pytest.raises(ValidationError):
            model(my_message3={"const_test": 1, "range_e_test": 2, "range_test": 2})
        model(my_message1=None, my_message3={"const_test": 1, "range_e_test": 2, "range_test": 2})

    def test_nested_message(self):
        """Nested messages, maps-of-messages and self/forward references all validate recursively."""
        model = runtime_model(p2p.NestedMessage)
        model.model_rebuild()
        model(
            string_in_map_test={"a": _string_normal()},
            map_in_map_test={"a": {
                "pair_test": {"a": 1}, "no_parse_test": {"a": 1}, "keys_test": {"a": 1}, "values_test": {"a": 5},
                "keys_values_test": {"a": datetime.now() + timedelta(days=1)}, "miss_default_test": {"a": 1},
                "required_test": {"a": 1},
            }},
            user_pay={"bank_number": "abcabcabcabcabc", "exp": datetime.now() + timedelta(days=1), "uuid": str(uuid4())},
            not_enable_user_pay={"bank_number": "abc", "exp": datetime.now() - timedelta(days=1), "uuid": "abc"},
            empty=None,
            after_refer={"uid": "10086", "age": 18},
        )
        with pytest.raises(ValidationError):
            model(user_pay={"bank_number": "short", "exp": datetime.now() + timedelta(days=1), "uuid": str(uuid4())})

    def test_default_and_default_factory(self):
        """default / default_factory rules make a field optional and supply the configured default value."""
        from uuid import UUID

        inst = runtime_model(p2p.StringTest)(miss_default_test="x", required_test="y", const_test="aaa")
        assert inst.default_test == "default"                 # static default value
        assert isinstance(inst.default_factory_test, UUID)    # default_factory = uuid4

    def test_disabled_rule_field_is_unconstrained(self):
        """enable=false drops the field from the model entirely (absent from model_fields).

        The disabled field carries neither a definition nor rules, so it is gone from ``model_fields``;
        supplying it as an extra key is therefore merely ignored at construction (the model accepts it
        without raising) rather than enforced. Both halves are checked: the string flow's ``enable_test``
        and the numeric flows' ``not_enable_test`` must be dropped.
        """
        # The disabled field is dropped from the generated model, not kept as an unconstrained field.
        assert "enable_test" not in runtime_model(p2p.StringTest).model_fields
        for msg in (p2p.Int32Test, p2p.FloatTest):
            assert "not_enable_test" not in runtime_model(msg, template=CustomCommentTemplate).model_fields

        # Because the field is absent, passing it as an extra key is simply ignored (no ValidationError).
        model = runtime_model(p2p.StringTest)
        normal = _string_normal()
        normal["enable_test"] = "this value is ignored because the disabled field is not on the model"
        model(**normal)


# ----------------------------------------------------------------------------------------------------
# Flow (a): runtime conversion, PGV rules (parse_msg_desc_method="PGV")
# ----------------------------------------------------------------------------------------------------
class TestRuntimePGV:
    def _pgv(self, msg):
        return runtime_model(msg, parse_msg_desc_method="PGV")

    def test_string_rules(self):
        """PGV string rules map the protoc-gen-validate names onto the same pydantic constraints."""
        normal = {
            "const_test": "aaa", "len_test": "aaa", "s_range_len_test": "aa", "pattern_test": "testaa",
            "prefix_test": "prefix_testaa", "suffix_test": "aa_suffix", "contains_test": "aaa_contains_test",
            "not_contains_test": "aaa", "in_test": "a", "not_in_test": "d", "email_test": "example@example.com",
            "hostname_test": "example.com", "ip_test": "127.0.0.1", "ipv4_test": "127.0.0.1", "ipv6_test": "::1",
            "uri_test": "http://127.0.0.1", "uri_ref_test": "http://127.0.0.1/paths", "address_test": "127.0.0.1",
            "uuid_test": str(uuid4()),
        }
        model = self._pgv(pgv.StringTest)
        model(**normal)
        for column, bad_value in _STRING_VIOLATIONS.items():
            bad = deepcopy(normal)
            bad[column] = bad_value
            with pytest.raises(ValidationError):
                model(**bad)

    def test_number_in_not_in_rules(self):
        """PGV numeric in/not_in membership over int and float."""
        for msg in (pgv.Int32Test, pgv.FloatTest):
            model = self._pgv(msg)
            for i in (1, 2, 3):
                model(in_test=i)
            for i in (0, 4):
                with pytest.raises(ValidationError):
                    model(in_test=i)
            for i in (1, 2, 3):
                with pytest.raises(ValidationError):
                    model(not_in_test=i)

    def test_repeated_rules(self):
        """PGV repeated rules: item-count bounds and per-item constraints."""
        _check(
            self._pgv(pgv.RepeatedTest),
            {
                "range_test": ["a"], "unique_test": ["a", "b", "c"], "items_string_test": ["abc", "def"],
                "items_double_test": [1.2, 3.4], "items_int32_test": [2, 3], "items_timestamp_test": [1600000001],
                "items_duration_test": [timedelta(seconds=15)], "items_bytes_test": [b"a", b"b"],
                "ignore_test": ["a", "b"],
            },
            {
                "range_test": ["a", "b", "c", "d", "e", "f"], "items_string_test": ["abc", "def", "abcdef"],
                "items_double_test": [1.2, 3.4, "5.6"], "items_int32_test": [2, 3, 6],
                "items_timestamp_test": [datetime.fromtimestamp(1600000100)],
                "items_duration_test": [timedelta(seconds=25)],
                "items_bytes_test": [b"a", b"b", b"c", b"d", b"e", b"f"],
            },
        )

    def test_map_rules(self):
        """PGV map rules: pair-count bounds and per-key/value constraints."""
        _check(
            self._pgv(pgv.MapTest),
            {
                "pair_test": {"a": 1}, "no_parse_test": {"a": 1}, "keys_test": {"a": 1}, "values_test": {"a": 5},
                "keys_values_test": {"a": datetime.now() + timedelta(days=1)}, "ignore_test": {"a": 1},
            },
            {
                "pair_test": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}, "keys_test": {"aaaaaa": 1},
                "values_test": {"a": 1}, "keys_values_test": {"a": datetime.now() - timedelta(days=1)},
            },
        )

    def test_duration_rules(self):
        """PGV duration rules: const, range, membership."""
        _check(
            self._pgv(pgv.DurationTest),
            {
                "required_test": timedelta(seconds=3600).total_seconds(),
                "const_test": timedelta(seconds=1, microseconds=500000), "range_test": timedelta(seconds=6),
                "range_e_test": timedelta(seconds=10, microseconds=500000),
                "in_test": timedelta(seconds=1, microseconds=500000),
                "not_in_test": timedelta(seconds=2, microseconds=500000),
            },
            {
                "const_test": timedelta(seconds=2, microseconds=500000), "range_test": timedelta(seconds=4),
                "range_e_test": timedelta(seconds=10, microseconds=500001),
                "in_test": timedelta(microseconds=500000), "not_in_test": timedelta(seconds=1, microseconds=500000),
            },
        )

    def test_timestamp_rules(self):
        """PGV timestamp rules: const, range, lt_now/gt_now, within."""
        _check(
            self._pgv(pgv.TimestampTest),
            {
                "required_test": datetime.now(), "const_test": datetime.fromtimestamp(1600000000),
                "range_test": datetime.fromtimestamp(1600000009), "range_e_test": datetime.fromtimestamp(1600000010),
                "lt_now_test": datetime.now() - timedelta(days=1), "gt_now_test": datetime.now() + timedelta(days=1),
                "within_test": datetime.now(), "within_and_gt_now_test": datetime.now() + timedelta(seconds=3590),
            },
            {
                "const_test": datetime.fromtimestamp(1600000001), "range_test": datetime.fromtimestamp(1600000010),
                "range_e_test": datetime.fromtimestamp(1600000011), "lt_now_test": datetime.now() + timedelta(days=1),
                "gt_now_test": datetime.now() - timedelta(days=1), "within_test": datetime.now() + timedelta(days=1),
                "within_and_gt_now_test": datetime.now() + timedelta(seconds=3660),
            },
        )

    def test_enum_rules(self):
        """PGV enum rules: const, in, not_in."""
        _check(
            self._pgv(pgv.EnumTest),
            {"const_test": 2, "in_test": 0, "not_in_test": 1},
            {"const_test": 4, "in_test": 4, "not_in_test": 2},
        )

    def test_oneof_required(self):
        """PGV required oneof: exactly one member must be set."""
        model = self._pgv(pgv.OneOfTest)
        model(x="1")
        model(y=2)
        with pytest.raises(ValidationError):
            model(x="1", y=2)
        with pytest.raises(ValidationError):
            model()


# ----------------------------------------------------------------------------------------------------
# Flow (b): code generation -> exec -> behaviour
# ----------------------------------------------------------------------------------------------------
class TestCodeGen:
    def test_string_rules_roundtrip(self):
        """Generated source for string rules reconstructs a model with identical validation behaviour.

        The code-gen flow emits a plain ``str`` for the ``pattern`` rule (the regex is not serialised), so
        ``pattern_test`` is exempted here while every other string constraint is still checked.
        """
        _assert_string_rules(codegen_model("StringTest", p2p.StringTest), skip={"pattern_test"})

    def test_number_rules_roundtrip(self):
        """Generated source for numeric rules enforces in-membership and required."""
        model = codegen_model("Int32Test", p2p.Int32Test, template=CustomCommentTemplate)
        model(in_test=2, miss_default_test=1.0, required_test=1.0)
        with pytest.raises(ValidationError):
            model(in_test=4, miss_default_test=1.0, required_test=1.0)
        with pytest.raises(ValidationError):
            model()

    def test_enum_rules_roundtrip(self):
        """Generated source emits the IntEnum and its const/in/not_in checks."""
        _check(
            codegen_model("EnumTest", p2p.EnumTest),
            {"const_test": 2, "in_test": 0, "not_in_test": 1, "miss_default_test": 1, "required_test": 1},
            {"const_test": 4, "in_test": 4, "not_in_test": 2},
        )

    def test_wellknown_types_roundtrip(self):
        """Generated source for Duration emits con-timedelta annotations enforcing const/range."""
        model = codegen_model("DurationTest", p2p.DurationTest)
        model(required_test=timedelta(seconds=3600).total_seconds(),
              const_test=timedelta(seconds=1, microseconds=500000), range_test=timedelta(seconds=6),
              range_e_test=timedelta(seconds=10, microseconds=500000),
              in_test=timedelta(seconds=1, microseconds=500000),
              not_in_test=timedelta(seconds=2, microseconds=500000),
              miss_default_test=timedelta(seconds=2, microseconds=500000))
        with pytest.raises(ValidationError):
            model(required_test=1.0, const_test=timedelta(seconds=2, microseconds=500000),
                  range_test=timedelta(seconds=6), range_e_test=timedelta(seconds=10, microseconds=500000),
                  in_test=timedelta(seconds=1, microseconds=500000),
                  not_in_test=timedelta(seconds=2, microseconds=500000),
                  miss_default_test=timedelta(seconds=2, microseconds=500000))

    def test_repeated_rules_roundtrip(self):
        """Generated source for repeated rules enforces item-count bounds."""
        model = codegen_model("RepeatedTest", p2p.RepeatedTest)
        model(range_test=["a"], unique_test=["a", "b"], items_string_test=["abc"], items_double_test=[1.2],
              items_int32_test=[2], items_timestamp_test=[1600000001], items_duration_test=[timedelta(seconds=10)],
              items_bytes_test=[b"a"], miss_default_test=["a"], required_test=["a"])
        with pytest.raises(ValidationError):
            model(range_test=["a", "b", "c", "d", "e", "f"], miss_default_test=["a"], required_test=["a"])

    def test_map_rules_roundtrip(self):
        """Generated source for map rules emits con-key/value types enforcing per-key/value constraints."""
        model = codegen_model("MapTest", p2p.MapTest)
        model(pair_test={"a": 1}, no_parse_test={"a": 1}, keys_test={"a": 1}, values_test={"a": 5},
              keys_values_test={"a": datetime.now() + timedelta(days=1)}, miss_default_test={"a": 1},
              required_test={"a": 1})
        with pytest.raises(ValidationError):
            model(pair_test={"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}, no_parse_test={"a": 1},
                  keys_test={"a": 1}, values_test={"a": 5},
                  keys_values_test={"a": datetime.now() + timedelta(days=1)}, miss_default_test={"a": 1},
                  required_test={"a": 1})

    def test_oneof_roundtrip(self):
        """Generated source preserves the required-oneof model-validator behaviour."""
        model = codegen_model("OneOfTest", p2p.OneOfTest)
        model(x="1")
        model(y=2)
        with pytest.raises(ValidationError):
            model(x="1", y=2)
        with pytest.raises(ValidationError):
            model()

    def test_pydantic_model_to_py_file(self, tmp_path):
        """pydantic_model_to_py_file writes runnable source whose executed model enforces the rules."""
        import importlib.util

        from conftest import local_dict
        from protobuf_to_pydantic import msg_to_pydantic_model, pydantic_model_to_py_file
        from conftest import CustomCommentTemplate

        model = msg_to_pydantic_model(p2p.Int32Test, local_dict=local_dict, template=CustomCommentTemplate)
        out = tmp_path / "generated_model.py"
        pydantic_model_to_py_file(str(out), model)
        assert out.is_file() and out.read_text().strip()

        spec = importlib.util.spec_from_file_location("generated_model", out)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.Int32Test(in_test=2, miss_default_test=1.0, required_test=1.0)
        with pytest.raises(ValidationError):
            module.Int32Test(in_test=4, miss_default_test=1.0, required_test=1.0)


# ----------------------------------------------------------------------------------------------------
# Generation knobs: alias, all_field_set_optional, enum name/value descriptions
# ----------------------------------------------------------------------------------------------------
class TestGenerationOptions:
    def test_alias_and_description_rules(self):
        """The alias / title / description rules map onto the corresponding pydantic FieldInfo attributes."""
        model = runtime_model(p2p.StringTest)
        assert model.model_fields["alias_test"].alias == "alias"
        assert model.model_fields["title_test"].title == "title_test"
        assert model.model_fields["desc_test"].description == "test desc"

    def test_custom_base_model_is_inherited(self):
        """pydantic_base lets the generated model inherit a user-supplied base (config + extra methods)."""
        from pydantic import BaseModel

        class MyBase(BaseModel):
            def shout(self) -> str:
                return "loud"

        model = runtime_model(p2p.StringTest, pydantic_base=MyBase)
        assert issubclass(model, MyBase)
        inst = model(required_test="b", miss_default_test="a", const_test="aaa")
        assert inst.shout() == "loud"

    def test_enum_name_value_desc(self):
        """enable_enum_name_value_desc documents each enum member as ``- <name> = <number>`` in its docstring."""
        import enum

        plain = runtime_model(p2p.EnumTest)
        documented = runtime_model(p2p.EnumTest, enable_enum_name_value_desc=True)

        def find_enum(model):
            for field in model.model_fields.values():
                ann = field.annotation
                args = getattr(ann, "__args__", ())
                for candidate in (ann, *args):
                    if isinstance(candidate, type) and issubclass(candidate, enum.IntEnum):
                        return candidate
            raise AssertionError("no IntEnum field found")

        assert "= 2" not in (find_enum(plain).__doc__ or "")
        documented_doc = find_enum(documented).__doc__ or ""
        assert "ACTIVE" in documented_doc and "= 2" in documented_doc


# ----------------------------------------------------------------------------------------------------
# Flow (c): protoc plugin generated models -> behaviour
# ----------------------------------------------------------------------------------------------------
class TestPlugin:
    def test_string_rules(self):
        """Plugin-generated StringTest model enforces every string constraint."""
        _assert_string_rules(plugin_models().StringTest)

    def test_number_rules(self):
        """Plugin-generated numeric model enforces in-membership and required."""
        model = plugin_models().Int32Test
        model(in_test=2, miss_default_test=1.0, required_test=1.0)
        with pytest.raises(ValidationError):
            model(in_test=4, miss_default_test=1.0, required_test=1.0)
        with pytest.raises(ValidationError):
            model()

    def test_enum_rules(self):
        """Plugin-generated enum model enforces const/in/not_in."""
        _check(
            plugin_models().EnumTest,
            {"const_test": 2, "in_test": 0, "not_in_test": 1, "miss_default_test": 1, "required_test": 1},
            {"const_test": 4, "in_test": 4, "not_in_test": 2},
        )

    def test_repeated_rules(self):
        """Plugin-generated repeated model enforces item-count bounds and per-item constraints."""
        _check(
            plugin_models().RepeatedTest,
            {
                "range_test": ["a"], "unique_test": ["a", "b"], "items_string_test": ["abc"],
                "items_double_test": [1.2], "items_int32_test": [2], "items_timestamp_test": [1600000001],
                "items_duration_test": [timedelta(seconds=10)], "items_bytes_test": [b"a"],
                "miss_default_test": ["a"], "required_test": ["a"],
            },
            {"range_test": ["a", "b", "c", "d", "e", "f"], "items_int32_test": [2, 3, 6]},
        )

    def test_oneof_required(self):
        """Plugin-generated required oneof: exactly one member must be set."""
        mod = plugin_models()
        mod.OneOfTest(x="1")
        mod.OneOfTest(y=2)
        with pytest.raises(ValidationError):
            mod.OneOfTest(x="1", y=2)
        with pytest.raises(ValidationError):
            mod.OneOfTest()

    def test_timestamp_rules(self):
        """Plugin-generated timestamp model enforces const and lt_now/gt_now."""
        _check(
            plugin_models().TimestampTest,
            {
                "required_test": datetime.now(), "const_test": datetime.fromtimestamp(1600000000),
                "range_test": datetime.fromtimestamp(1600000009), "range_e_test": datetime.fromtimestamp(1600000010),
                "lt_now_test": datetime.now() - timedelta(days=1), "gt_now_test": datetime.now() + timedelta(days=1),
                "within_test": datetime.now(), "within_and_gt_now_test": datetime.now() + timedelta(seconds=3590),
                "miss_default_test": datetime.now(),
            },
            {
                "const_test": datetime.fromtimestamp(1600000001), "lt_now_test": datetime.now() + timedelta(days=1),
                "gt_now_test": datetime.now() - timedelta(days=1),
            },
        )
