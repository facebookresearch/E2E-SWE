"""
Tests for pyyaml — YAML parser and emitter for Python.
"""

import datetime
import math

import pytest

import yaml


class TestScalarTypes:

    def test_all_scalar_types_parse_correctly(self):
        doc = """\
string: hello world
quoted: "hello world"
single_quoted: 'hello world'
integer: 42
negative_int: -17
hex_int: 0xFF
octal_yaml: 077
large_int: 1000000
float_val: 3.14159
negative_float: -2.5
scientific: 1.0e+3
infinity: .inf
neg_infinity: -.inf
nan_val: .nan
bool_true: true
bool_false: false
bool_yes: yes
bool_no: no
null_val: null
null_tilde: ~
empty_val:
date_val: 2024-01-15
"""
        data = yaml.safe_load(doc)

        assert data["string"] == "hello world"
        assert data["quoted"] == "hello world"
        assert data["single_quoted"] == "hello world"

        assert data["integer"] == 42
        assert isinstance(data["integer"], int)
        assert data["negative_int"] == -17
        assert data["hex_int"] == 255
        assert data["octal_yaml"] == 63
        assert data["large_int"] == 1000000

        assert abs(data["float_val"] - 3.14159) < 0.0001
        assert data["negative_float"] == -2.5
        assert abs(data["scientific"] - 1000.0) < 0.1
        assert data["infinity"] == float("inf")
        assert data["neg_infinity"] == float("-inf")
        assert math.isnan(data["nan_val"])

        assert data["bool_true"] is True
        assert data["bool_false"] is False
        assert data["bool_yes"] is True
        assert data["bool_no"] is False

        assert data["null_val"] is None
        assert data["null_tilde"] is None
        assert data["empty_val"] is None

        assert data["date_val"] == datetime.date(2024, 1, 15)


class TestCollections:

    def test_nested_mappings_and_sequences(self):
        doc = """\
database:
  host: localhost
  port: 5432
  credentials:
    username: admin
    password: secret
  replicas:
    - host: replica1
      port: 5433
    - host: replica2
      port: 5434
  tags:
    - primary
    - production
users:
  - name: Alice
    age: 30
    active: true
  - name: Bob
    age: 25
    active: false
"""
        data = yaml.safe_load(doc)

        assert data["database"]["host"] == "localhost"
        assert data["database"]["port"] == 5432
        assert data["database"]["credentials"]["username"] == "admin"
        assert len(data["database"]["replicas"]) == 2
        assert data["database"]["replicas"][0]["host"] == "replica1"
        assert data["database"]["replicas"][1]["port"] == 5434
        assert data["database"]["tags"] == ["primary", "production"]

        assert len(data["users"]) == 2
        assert data["users"][0]["name"] == "Alice"
        assert data["users"][0]["age"] == 30
        assert data["users"][1]["active"] is False

    def test_flow_and_edge_cases(self):
        assert yaml.safe_load("{key1: value1, key2: 42}") == {"key1": "value1", "key2": 42}
        assert yaml.safe_load("[1, 2, 3, four, 5.0]") == [1, 2, 3, "four", 5.0]
        assert yaml.safe_load("{outer: {inner: [a, b]}}") == {"outer": {"inner": ["a", "b"]}}
        assert yaml.safe_load("v: {a: [1, {b: 2}]}") == {"v": {"a": [1, {"b": 2}]}}
        assert yaml.safe_load("v: {}") == {"v": {}}
        assert yaml.safe_load("v: []") == {"v": []}
        assert yaml.safe_load("key: 1\nkey: 2\nkey: 3") == {"key": 3}


class TestBlockScalars:

    def test_block_scalar_styles_and_chomping(self):
        doc = """\
literal: |
  Line one.
  Line two.
  Line three.
folded: >
  This is a long
  paragraph that should
  be folded into one line.
literal_strip: |-
  No trailing newline
folded_strip: >-
  No trailing
  newline here
literal_keep: |+
  Keep trailing.
  Second line.

folded_keep: >+
  Folded
  keep.

"""
        data = yaml.safe_load(doc)

        assert data["literal"] == "Line one.\nLine two.\nLine three.\n"
        assert data["folded"] == "This is a long paragraph that should be folded into one line.\n"
        assert data["literal_strip"] == "No trailing newline"
        assert not data["folded_strip"].endswith("\n")
        assert data["literal_keep"] == "Keep trailing.\nSecond line.\n\n"
        assert data["folded_keep"] == "Folded keep.\n\n"

        doc2 = "text: |\n  line1\n\n  line3\n"
        assert yaml.safe_load(doc2)["text"] == "line1\n\nline3\n"


class TestEscapeSequences:

    def test_escape_sequences_in_double_quoted_strings(self):
        cases = {
            'tab: "col1\\tcol2"': ("tab", "col1\tcol2"),
            'newline: "line1\\nline2"': ("newline", "line1\nline2"),
            'hex: "\\x41\\x42\\x43"': ("hex", "ABC"),
            'unicode4: "\\u0048\\u0065\\u006C\\u006C\\u006F"': ("unicode4", "Hello"),
            'backslash: "a\\\\b"': ("backslash", "a\\b"),
            'null_char: "a\\0b"': ("null_char", "a\x00b"),
            'quote: "say \\"hi\\""': ("quote", 'say "hi"'),
        }
        for yaml_str, (key, expected) in cases.items():
            data = yaml.safe_load(yaml_str)
            assert data[key] == expected, f"Failed for {key}: got {data[key]!r}, expected {expected!r}"


class TestAnchorsAndMergeKeys:

    def test_anchors_aliases_and_merge_keys(self):
        doc = """\
defaults: &defaults
  adapter: postgres
  host: localhost
  port: 5432

extra: &extra
  pool: 5
  timeout: 30

development:
  <<: *defaults
  database: dev_db

production:
  <<: [*defaults, *extra]
  host: prod-server
  database: prod_db
"""
        data = yaml.safe_load(doc)

        assert data["development"]["adapter"] == "postgres"
        assert data["development"]["host"] == "localhost"
        assert data["development"]["database"] == "dev_db"

        assert data["production"]["host"] == "prod-server"
        assert data["production"]["adapter"] == "postgres"
        assert data["production"]["pool"] == 5
        assert data["production"]["port"] == 5432

        doc2 = "base: &base [1, 2, 3]\nref1: *base\nref2: *base\n"
        data2 = yaml.safe_load(doc2)
        assert data2["ref1"] is data2["base"]
        assert data2["ref2"] is data2["base"]


class TestMultipleDocuments:

    def test_safe_load_all_multiple_documents(self):
        doc = """\
---
name: Document One
value: 1
---
name: Document Two
value: 2
---
name: Document Three
value: 3
"""
        documents = list(yaml.safe_load_all(doc))
        assert len(documents) == 3
        assert documents[0]["name"] == "Document One"
        assert documents[1]["value"] == 2
        assert documents[2]["name"] == "Document Three"


class TestTimestamps:

    def test_yaml_timestamp_types(self):
        doc = """\
date_only: 2024-01-15
datetime_space: 2024-01-15 10:30:00
datetime_iso: 2024-01-15T10:30:00Z
"""
        data = yaml.safe_load(doc)

        assert data["date_only"] == datetime.date(2024, 1, 15)
        assert isinstance(data["date_only"], datetime.date)

        assert isinstance(data["datetime_space"], datetime.datetime)
        assert data["datetime_space"].year == 2024
        assert data["datetime_space"].hour == 10
        assert data["datetime_space"].minute == 30

        assert isinstance(data["datetime_iso"], datetime.datetime)
        assert data["datetime_iso"].tzinfo is not None
        # A trailing 'Z' resolves to a zero-offset (UTC) timezone, not merely "some tzinfo".
        assert data["datetime_iso"].utcoffset() == datetime.timedelta(0)


class TestBooleanResolver:

    def test_boolean_resolver_variants(self):
        doc = """\
true_val: true
false_val: false
yes_val: yes
no_val: no
on_val: on
off_val: off
True_val: True
False_val: False
Yes_val: Yes
No_val: No
On_val: On
Off_val: Off
TRUE_val: TRUE
FALSE_val: FALSE
y_lower: y
n_lower: n
Y_upper: Y
N_upper: N
"""
        data = yaml.safe_load(doc)

        for key in ["true_val", "yes_val", "on_val", "True_val", "Yes_val", "On_val", "TRUE_val"]:
            assert data[key] is True, f"{key} should be True, got {data[key]!r}"

        for key in ["false_val", "no_val", "off_val", "False_val", "No_val", "Off_val", "FALSE_val"]:
            assert data[key] is False, f"{key} should be False, got {data[key]!r}"

        for key in ["y_lower", "n_lower", "Y_upper", "N_upper"]:
            assert isinstance(data[key], str), f"{key} should be str, got {type(data[key]).__name__}"


class TestDumpExactOutput:

    def test_dump_exact_structure(self):
        assert yaml.safe_dump({"name": "Alice", "age": 30, "active": True}, sort_keys=True) == "active: true\nage: 30\nname: Alice\n"
        data = {"server": {"host": "localhost", "port": 8080}, "features": ["auth", "logging"]}
        assert yaml.safe_dump(data, sort_keys=True) == "features:\n- auth\n- logging\nserver:\n  host: localhost\n  port: 8080\n"
        assert yaml.safe_dump([{"a": 1}, {"b": 2}]) == "- a: 1\n- b: 2\n"
        assert yaml.safe_dump({"empty_dict": {}, "empty_list": [], "null_val": None}, sort_keys=True) == "empty_dict: {}\nempty_list: []\nnull_val: null\n"
        assert yaml.safe_dump([1, "hello", True, None, 3.14]) == "- 1\n- hello\n- true\n- null\n- 3.14\n"
        assert yaml.safe_dump({"v": float("inf")}) == "v: .inf\n"
        assert yaml.safe_dump({"v": float("-inf")}) == "v: -.inf\n"
        assert yaml.safe_dump({"v": float("nan")}) == "v: .nan\n"

    def test_dump_exact_special_string_quoting(self):
        assert yaml.safe_dump({"v": "true"}) == "v: 'true'\n"
        assert yaml.safe_dump({"v": "42"}) == "v: '42'\n"
        assert yaml.safe_dump({"v": "null"}) == "v: 'null'\n"
        assert yaml.safe_dump({"v": ""}) == "v: ''\n"
        assert yaml.safe_dump({"v": "yes"}) == "v: 'yes'\n"
        assert yaml.safe_dump({"v": "# comment"}) == "v: '# comment'\n"
        assert yaml.safe_dump({"v": "*bold*"}) == "v: '*bold*'\n"
        assert yaml.safe_dump({"v": "&anchor"}) == "v: '&anchor'\n"
        assert yaml.safe_dump({"v": "hello: world"}) == "v: 'hello: world'\n"
        assert yaml.safe_dump({"v": "[1, 2]"}) == "v: '[1, 2]'\n"
        assert yaml.safe_dump({"v": "{a: 1}"}) == "v: '{a: 1}'\n"

    def test_dump_exact_formatting(self):
        data = {"a": {"b": {"c": {"d": "deep"}}}}
        assert yaml.safe_dump(data, indent=2) == "a:\n  b:\n    c:\n      d: deep\n"
        assert yaml.safe_dump(data, indent=4) == "a:\n    b:\n        c:\n            d: deep\n"
        assert yaml.safe_dump({"key": "value"}, explicit_start=True, explicit_end=True) == "---\nkey: value\n...\n"
        data2 = {"jp": "こんにちは"}
        assert yaml.safe_dump(data2, allow_unicode=True) == "jp: こんにちは\n"
        ascii_out = yaml.safe_dump(data2, allow_unicode=False)
        assert "\\u" in ascii_out


class TestDumping:

    def test_safe_dump_all_and_options(self):
        docs = [{"doc": 1}, {"doc": 2}, {"doc": 3}]
        output = yaml.safe_dump_all(docs)
        reloaded = list(yaml.safe_load_all(output))
        assert len(reloaded) == 3
        assert reloaded[0]["doc"] == 1
        assert reloaded[2]["doc"] == 3

        data = {"b": 2, "a": 1, "c": [1, 2, 3]}
        sorted_output = yaml.safe_dump(data, sort_keys=True)
        assert sorted_output.strip().split("\n")[0].startswith("a:")
        unsorted_output = yaml.safe_dump(data, sort_keys=False)
        assert unsorted_output.strip().split("\n")[0].startswith("b:")

        flow_output = yaml.safe_dump(data, default_flow_style=True)
        assert flow_output == "{a: 1, b: 2, c: [1, 2, 3]}\n"

        narrow = yaml.safe_dump({"desc": "word " * 30}, width=40)
        assert len([l for l in narrow.split("\n") if l.strip()]) > 1


class TestRoundTrip:

    def test_round_trip_fidelity(self):
        original = {
            "server": {"host": "0.0.0.0", "port": 8080, "debug": False},
            "features": ["auth", "logging", "caching"],
            "metadata": None,
        }
        assert yaml.safe_load(yaml.safe_dump(original)) == original

        tricky = {"bool": "true", "int": "42", "null": "null", "tilde": "~", "yes": "yes", "date": "2024-01-15"}
        reloaded = yaml.safe_load(yaml.safe_dump(tricky))
        for key, val in tricky.items():
            assert reloaded[key] == val and isinstance(reloaded[key], str), f"{key} failed round-trip"

        data = {"inf": float("inf"), "neg_inf": float("-inf"), "nan": float("nan")}
        reloaded = yaml.safe_load(yaml.safe_dump(data))
        assert reloaded["inf"] == float("inf")
        assert reloaded["neg_inf"] == float("-inf")
        assert math.isnan(reloaded["nan"])


class TestBinaryAndSet:

    def test_binary_round_trip(self):
        data = {"payload": b"Hello World! This is binary data."}
        dumped = yaml.safe_dump(data)
        assert "!!binary" in dumped
        reloaded = yaml.safe_load(dumped)
        assert reloaded["payload"] == b"Hello World! This is binary data."

        doc = "data: !!binary |\n  SGVsbG8gV29ybGQ=\n"
        assert yaml.safe_load(doc)["data"] == b"Hello World"

    def test_set_round_trip(self):
        data = {"tags": {1, 2, 3}}
        dumped = yaml.safe_dump(data)
        assert "!!set" in dumped
        reloaded = yaml.safe_load(dumped)
        assert reloaded["tags"] == {1, 2, 3}
        assert isinstance(reloaded["tags"], set)

        doc = "!!set\n? apple\n? banana\n? cherry\n"
        result = yaml.safe_load(doc)
        assert result == {"apple", "banana", "cherry"}
        assert isinstance(result, set)


class TestOmapAndPairs:

    def test_omap_and_pairs_parsing(self):
        doc = "!!omap\n- first: 1\n- second: 2\n- third: 3\n"
        assert yaml.safe_load(doc) == [("first", 1), ("second", 2), ("third", 3)]

        doc2 = "!!pairs\n- a: 1\n- b: 2\n- a: 3\n"
        assert yaml.safe_load(doc2) == [("a", 1), ("b", 2), ("a", 3)]


class TestDatetimeDump:

    def test_datetime_dump_formats(self):
        dt_naive = datetime.datetime(2024, 1, 15, 10, 30, 0)
        assert yaml.safe_dump({"v": dt_naive}) == "v: 2024-01-15 10:30:00\n"

        dt_utc = datetime.datetime(2024, 1, 15, 10, 30, 0, tzinfo=datetime.timezone.utc)
        assert yaml.safe_dump({"v": dt_utc}) == "v: 2024-01-15 10:30:00+00:00\n"

        dt_offset = datetime.datetime(
            2024, 1, 15, 10, 30, 0,
            tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)),
        )
        assert yaml.safe_dump({"v": dt_offset}) == "v: 2024-01-15 10:30:00+05:30\n"


class TestResolverQuirks:

    def test_float_exponent_requires_explicit_sign(self):
        assert yaml.safe_load("v: 1.0e3") == {"v": "1.0e3"}
        assert isinstance(yaml.safe_load("v: 1.0e3")["v"], str)
        assert yaml.safe_load("v: 1.0e+3") == {"v": 1000.0}
        assert isinstance(yaml.safe_load("v: 1.0e+3")["v"], float)
        assert yaml.safe_load("v: .5e+3") == {"v": 500.0}

    def test_numeric_edge_cases(self):
        assert yaml.safe_load("v: 0b101") == {"v": 5}
        assert yaml.safe_load("v: 0b1111_0000") == {"v": 240}
        assert yaml.safe_load("v: -0b10") == {"v": -2}

        assert yaml.safe_load("v: 0o77") == {"v": "0o77"}
        assert isinstance(yaml.safe_load("v: 0o77")["v"], str)
        assert yaml.safe_load("v: 077") == {"v": 63}

        assert yaml.safe_load("v: 008") == {"v": "008"}
        assert yaml.safe_load("v: 091") == {"v": "091"}

    def test_sexagesimal_edge_cases(self):
        assert yaml.safe_load("v: 1:30:00") == {"v": 5400}
        assert yaml.safe_load("v: -1:30") == {"v": -90}
        assert yaml.safe_load("v: 0:30") == {"v": "0:30"}
        assert yaml.safe_load("v: 1:30:00.5") == {"v": 5400.5}
        assert yaml.safe_load("v: 1:30.25") == {"v": 90.25}


class TestEmitterQuirks:

    def test_quoting_decisions(self):
        assert yaml.safe_dump({"v": "1.0e3"}) == "v: 1.0e3\n"
        assert yaml.safe_dump({"v": "1.0e+3"}) == "v: '1.0e+3'\n"
        assert yaml.safe_dump({"v": "y"}) == "v: y\n"
        assert yaml.safe_dump({"v": "Y"}) == "v: Y\n"
        assert yaml.safe_dump({"v": "n"}) == "v: n\n"
        assert yaml.safe_dump({"v": "N"}) == "v: N\n"
        assert yaml.safe_dump({"v": "yes"}) == "v: 'yes'\n"
        assert yaml.safe_dump({"v": "on"}) == "v: 'on'\n"
        assert yaml.safe_dump({"v": "abc:def"}) == "v: abc:def\n"
        assert yaml.safe_dump({"v": "abc: def"}) == "v: 'abc: def'\n"

    def test_newline_string_single_quoted_not_double(self):
        # A multiline string is emitted single-quoted (not double-quoted): each embedded break
        # becomes a blank line and the continuation is re-indented by the block indent.
        dumped = yaml.safe_dump({"v": "newline\nhere"})
        assert dumped == "v: 'newline\n\n  here'\n"
        assert yaml.safe_load(dumped) == {"v": "newline\nhere"}

    def test_tab_and_control_chars_force_double_quoted(self):
        # Strings with non-foldable control chars are emitted double-quoted, carrying the escape
        # sequence for each such character, and round-trip exactly.
        cases = {
            "tab\there": 'v: "tab\\there"\n',
            "null\x00": 'v: "null\\0"\n',
            "cr\rhere": 'v: "cr\\rhere"\n',
        }
        for s, expected in cases.items():
            dumped = yaml.safe_dump({"v": s})
            assert dumped == expected, f"Failed for {s!r}: got {dumped!r}, expected {expected!r}"
            assert yaml.safe_load(dumped) == {"v": s}

    def test_top_level_scalar_end_marker(self):
        assert yaml.safe_dump(42) == "42\n...\n"
        assert yaml.safe_dump("hello") == "hello\n...\n"
        assert yaml.safe_dump(None) == "null\n...\n"
        assert yaml.safe_dump(True) == "true\n...\n"
        assert yaml.safe_dump([1, 2]) == "- 1\n- 2\n"
        assert yaml.safe_dump({"a": 1}) == "a: 1\n"

    def test_default_unicode_is_escaped(self):
        # By default (allow_unicode falsy) a non-ASCII char is escaped inside a double-quoted
        # scalar and round-trips exactly; the exact hex-escape spelling/casing (\xE9 vs \xe9) is
        # an arbitrary emitter detail not asserted here.
        dumped = yaml.safe_dump({"v": "café"})
        assert dumped.startswith('v: "') and dumped.endswith('"\n')
        assert "é" not in dumped
        assert yaml.safe_load(dumped) == {"v": "café"}
        # With allow_unicode=True the char is emitted literally and stays plain.
        assert yaml.safe_dump({"v": "café"}, allow_unicode=True) == "v: café\n"


class TestErrorHandling:

    def test_invalid_yaml_and_errors(self):
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load("key: value\n  bad indent: here\n another: line")
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load('key: "unclosed string')
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load("key:\n\tvalue")
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load("[a,\tb,\tc]")
        with pytest.raises(yaml.YAMLError):
            yaml.safe_dump({"v": frozenset([1, 2, 3])})
        with pytest.raises(yaml.YAMLError):
            yaml.safe_dump({"v": complex(1, 2)})

        assert yaml.safe_load("") is None
        assert yaml.safe_load("   ") is None
        assert yaml.safe_load("# just a comment") is None

    def test_anchor_errors(self):
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load("x: &a 1\ny: &a 2\n")
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load("v: *nope\n")

        data = yaml.safe_load("a: &x\n  b: *x\n")
        assert data["a"]["b"] is data["a"]


class TestExplicitTags:

    def test_explicit_type_tags(self):
        doc = """\
explicit_str: !!str 42
explicit_int: !!int "42"
explicit_float: !!float "3.14"
explicit_bool: !!bool "true"
explicit_null: !!null ""
"""
        data = yaml.safe_load(doc)
        assert data["explicit_str"] == "42"
        assert isinstance(data["explicit_str"], str)
        assert data["explicit_int"] == 42
        assert isinstance(data["explicit_int"], int)
        assert abs(data["explicit_float"] - 3.14) < 0.01
        assert data["explicit_bool"] is True
        assert data["explicit_null"] is None

    def test_tag_edge_cases(self):
        assert yaml.safe_load("v: !!bool 'yes'") == {"v": True}
        assert yaml.safe_load("v: !!bool 'on'") == {"v": True}
        with pytest.raises((yaml.YAMLError, KeyError)):
            yaml.safe_load("v: !!bool 'Y'")
        with pytest.raises((yaml.YAMLError, KeyError)):
            yaml.safe_load("v: !!bool 'N'")

        assert yaml.safe_load("v: !!null ''") == {"v": None}
        assert yaml.safe_load("v: !!null 'foo'") == {"v": None}
        assert yaml.safe_load("v: !!null 42") == {"v": None}


class TestUnicodeAndSpecialChars:

    def test_unicode_round_trip(self):
        data = {
            "greeting": "こんにちは世界",
            "emoji": "Hello 🌍",
            "accents": "café résumé naïve",
        }
        yaml_str = yaml.safe_dump(data, allow_unicode=True)
        reloaded = yaml.safe_load(yaml_str)
        assert reloaded == data
