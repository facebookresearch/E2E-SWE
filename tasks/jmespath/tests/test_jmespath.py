"""Hidden grading suite for the jmespath (Go) CLI task.

Each test drives the compiled `jp` binary over subprocess and asserts exact JMESPath evaluation
results. Value tests use compact output (`-c`) and compare the parsed JSON so an implementation is
free in whitespace but pinned on semantics; a few dedicated tests assert the exact output byte
formatting (pretty/compact/unquoted). Error tests assert the exit status and that a diagnostic is
emitted, never the exact wording (which varies across implementations).
"""

import json
import os
import subprocess

BIN = os.environ.get("BIN_ENV", "/app/jp")
TIMEOUT = 20


def run(expr, stdin="", *flags):
    """Run `jp [flags] <expr>` with `stdin`; return (stdout, stderr, returncode)."""
    proc = subprocess.run(
        [BIN, *flags, expr],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    return proc.stdout, proc.stderr, proc.returncode


def val(expr, stdin, *flags):
    """Evaluate `expr` against `stdin`, expect success, return the parsed compact JSON result."""
    out, err, rc = run(expr, stdin, "-c", *flags)
    assert rc == 0, f"expr={expr!r} rc={rc} stderr={err!r}"
    return json.loads(out)


# --------------------------------------------------------------------------- access & structure


def test_field_access_and_subexpressions():
    """Dotted sub-expressions and quoted identifiers (with spaces / dots) select nested values."""
    assert val("a.b.c", '{"a":{"b":{"c":42}}}') == 42
    assert val('"foo bar".baz', '{"foo bar":{"baz":1}}') == 1
    assert val('a."b.c"', '{"a":{"b.c":7}}') == 7
    assert val('"café"', '{"café":9}') == 9


def test_missing_field_returns_null():
    """A field that does not exist evaluates to null with a success exit code (not an error)."""
    out, err, rc = run("x", '{"a":1}', "-c")
    assert rc == 0 and out == "null\n", (out, err, rc)
    assert val("foo.bar.baz", '{"foo":{"bar":{}}}') is None


def test_index_positive_negative_and_out_of_range():
    """Array indexing supports positive and negative offsets; out-of-range yields null."""
    assert val("a[2]", '{"a":[10,20,30]}') == 30
    assert val("a[-1]", '{"a":[10,20,30]}') == 30
    assert val("a[10]", '{"a":[10,20,30]}') is None


def test_array_slices():
    """Slices honor start:stop:step, including omitted bounds, stepping, and negative step."""
    assert val("[1:3]", "[0,1,2,3,4]") == [1, 2]
    assert val("[:2]", "[0,1,2,3,4]") == [0, 1]
    assert val("[2:]", "[0,1,2,3,4]") == [2, 3, 4]
    assert val("[-2:]", "[0,1,2,3,4]") == [3, 4]
    assert val("[::2]", "[0,1,2,3,4]") == [0, 2, 4]
    assert val("[::-1]", "[0,1,2,3,4]") == [4, 3, 2, 1, 0]


def test_slice_on_non_array_is_null():
    """Slicing is defined only for arrays; slicing a string yields null."""
    assert val("s[0:2]", '{"s":"hello"}') is None


# --------------------------------------------------------------------------- projections


def test_list_wildcard_projection():
    """`a[*].b` projects `b` over each element, dropping elements where `b` is absent."""
    assert val("a[*].b", '{"a":[{"b":1},{"b":2},{"c":9}]}') == [1, 2]


def test_object_wildcard_projection():
    """A bare `*` projects over an object's values; `*.b` then applies a field (order unspecified)."""
    assert sorted(val("*", '{"a":1,"b":2}')) == [1, 2]
    assert sorted(val("*.b", '{"x":{"b":1},"y":{"b":2}}')) == [1, 2]


def test_flatten_operator():
    """The flatten operator `[]` merges nested arrays one level before continuing the projection."""
    assert val("a[].b", '{"a":[[{"b":1}],[{"b":2},{"b":3}]]}') == [1, 2, 3]


def test_projection_index_and_pipe_stops_projection():
    """Indexing applies inside a projection, while a pipe stops it and indexes the whole result."""
    assert val("a[*].b[0]", '{"a":[{"b":[1,2]},{"b":[3,4]}]}') == [1, 3]
    assert val("a[*].b | [1]", '{"a":[{"b":1},{"b":2},{"b":3}]}') == 2


def test_wildcard_then_multiselect_hash():
    """A projection can feed a multiselect hash built per element."""
    given = '{"people":[{"first":"a","last":"x"},{"first":"b","last":"y"}]}'
    assert val("people[*].{f: first, l: last}", given) == [
        {"f": "a", "l": "x"},
        {"f": "b", "l": "y"},
    ]


# --------------------------------------------------------------------------- filters


def test_filter_comparisons():
    """Filter expressions support ordering, equality, inequality, and boolean and/or operators."""
    assert val("a[?b>`1`].c", '{"a":[{"b":1,"c":"x"},{"b":2,"c":"y"}]}') == ["y"]
    assert val("a[?n=='foo'].v", '{"a":[{"n":"foo","v":1},{"n":"bar","v":2}]}') == [1]
    assert val("a[?b!=`1`].b", '{"a":[{"b":1},{"b":2},{"b":3}]}') == [2, 3]
    given = '{"a":[{"b":2,"c":4},{"b":3,"c":9},{"b":1,"c":1}]}'
    assert val("a[?b>=`2` && c<`5`]", given) == [{"b": 2, "c": 4}]


def test_filter_truthiness_and_null_literal():
    """Filters treat null/false/empty as falsy; a `null` JSON literal compares equal to null."""
    assert val("a[?b].b", '{"a":[{"b":1},{"b":null},{"b":2}]}') == [1, 2]
    given = '{"a":[{"b":null,"id":1},{"b":2,"id":2}]}'
    assert val("a[?b == `null`].id", given) == [1]


def test_filter_with_string_functions_and_raw_string_literal():
    """Filters may call functions and use raw-string literals (`'...'`) for string comparisons."""
    given = '{"a":[{"id":1,"tags":["x"]},{"id":2,"tags":["y"]}]}'
    assert val("a[?contains(tags, 'x')].id", given) == [1]
    people = '{"a":[{"name":"al"},{"name":"bo"},{"name":"ann"}]}'
    assert val("a[?starts_with(name,'a')].name", people) == ["al", "ann"]


# --------------------------------------------------------------------------- literals & operators


def test_literals_json_raw_and_current_node():
    """Backtick JSON literals, raw-string literals, and the current-node `@` all evaluate."""
    assert val("`[1,2]`", "{}") == [1, 2]
    assert val("`true`", "{}") is True
    assert val("'raw string'", "{}") == "raw string"
    assert val("@", "5") == 5


def test_json_literal_must_be_valid_json():
    """A backtick literal that is not valid JSON (e.g. a bare word) is an error, not an auto-string."""
    _, err, rc = run("starts_with(s, `foo`)", '{"s":"foobar"}')
    assert rc != 0 and err.strip() != ""
    # The valid-JSON string form works.
    assert val('starts_with(s, `"foo"`)', '{"s":"foobar"}') is True


def test_multiselect_list_and_hash():
    """Multiselect list `[a,b]` and hash `{k: expr}` build new structures from selected values."""
    assert val("[a,b]", '{"a":1,"b":2,"c":3}') == [1, 2]
    assert val("{x: a, y: b}", '{"a":1,"b":2}') == {"x": 1, "y": 2}


def test_or_and_not_and_grouping():
    """`||` returns the first truthy operand, `&&` the last when truthy, `!` negates, `()` groups."""
    assert val("a || b", '{"b":5}') == 5
    assert val("a || b", '{"a":null,"b":5}') == 5
    assert val("a && b", '{"a":1,"b":5}') == 5
    assert val("!a", '{"a":false}') is True
    assert val("(a || b).c", '{"b":{"c":7}}') == 7


# --------------------------------------------------------------------------- functions


def test_string_functions():
    """String builtins: length, starts_with/ends_with, contains, join, reverse, to_string."""
    assert val("length(s)", '{"s":"hello"}') == 5
    assert val("starts_with(s, 'foo')", '{"s":"foobar"}') is True
    assert val("ends_with(s, 'bar')", '{"s":"foobar"}') is True
    assert val("contains(s, 'oob')", '{"s":"foobar"}') is True
    assert val("join(', ', a)", '{"a":["x","y","z"]}') == "x, y, z"
    assert val("reverse(s)", '{"s":"abc"}') == "cba"
    assert val("to_string(n)", '{"n":42}') == "42"


def test_to_number_valid_and_invalid():
    """to_number parses numeric strings and returns null for unparseable input."""
    assert val("to_number(s)", '{"s":"3.5"}') == 3.5
    assert val("to_number(s)", '{"s":"nope"}') is None


def test_numeric_functions():
    """Numeric builtins: abs, ceil, floor, avg, sum, max, min over arrays and scalars."""
    assert val("abs(n)", '{"n":-7}') == 7
    assert val("ceil(n)", '{"n":1.2}') == 2
    assert val("floor(n)", '{"n":1.9}') == 1
    assert val("avg(a)", '{"a":[1,2,3,4]}') == 2.5
    assert val("sum(a)", '{"a":[1,2,3]}') == 6
    assert val("sum(`[]`)", "{}") == 0
    assert val("max(a)", '{"a":[3,1,4,1,5]}') == 5
    assert val("min(a)", '{"a":[3,1,4,1,5]}') == 1


def test_sort_and_reverse_array():
    """sort orders a homogeneous array ascending; reverse flips element order."""
    assert val("sort(a)", '{"a":[3,1,2]}') == [1, 2, 3]
    assert val("reverse(a)", '{"a":[1,2,3]}') == [3, 2, 1]


def test_sort_by_max_by_min_by_with_expression():
    """sort_by/max_by/min_by rank objects by an `&expr` key-expression."""
    given = '{"a":[{"name":"b","age":2},{"name":"a","age":1}]}'
    assert val("sort_by(a, &age)[*].name", given) == ["a", "b"]
    assert val("max_by(a, &age).name", given) == "b"
    assert val("min_by(a, &age).name", given) == "a"


def test_map_function_with_expression():
    """map applies an `&expr` to each element of an array, including nested function calls."""
    assert val("map(&n, a)", '{"a":[{"n":1},{"n":2}]}') == [1, 2]
    assert val("map(&length(@), a)", '{"a":["xx","yyy","z"]}') == [2, 3, 1]


def test_type_function():
    """type reports the JMESPath type name of any value."""
    assert val("type(x)", '{"x":[1]}') == "array"
    assert val("type(x)", '{"x":{"a":1}}') == "object"
    assert val("type(x)", '{"x":"s"}') == "string"
    assert val("type(x)", '{"x":5}') == "number"
    assert val("type(x)", '{"x":true}') == "boolean"
    assert val("type(x)", '{"x":null}') == "null"


def test_keys_and_values_are_order_independent():
    """keys/values return the object's keys/values; order is unspecified, so compare as sorted."""
    assert val("sort(keys(@))", '{"b":1,"a":2,"c":3}') == ["a", "b", "c"]
    assert val("sort(values(@))", '{"b":1,"a":2,"c":3}') == [1, 2, 3]
    assert sorted(val("keys(@)", '{"b":1,"a":2,"c":3}')) == ["a", "b", "c"]


def test_merge_not_null_to_array():
    """merge combines objects (later wins), not_null picks the first non-null, to_array wraps non-arrays."""
    assert val("merge(a, b)", '{"a":{"x":1},"b":{"y":2,"x":9}}') == {"x": 9, "y": 2}
    assert val("not_null(a, b, c)", '{"b":5,"c":6}') == 5
    assert val("to_array(x)", '{"x":5}') == [5]
    assert val("to_array(x)", '{"x":{"k":1}}') == [{"k": 1}]
    assert val("to_array(x)", '{"x":[1,2]}') == [1, 2]


def test_contains_on_array_and_string():
    """contains checks array membership and substring presence."""
    assert val("contains(a, 'b')", '{"a":["a","b","c"]}') is True
    assert val("contains(a, 'z')", '{"a":["a","b","c"]}') is False
    assert val("contains(s, 'ell')", '{"s":"hello"}') is True


# --------------------------------------------------------------------------- number formatting


def test_number_formatting_integer_vs_float():
    """Whole numbers print without a decimal point; fractional results keep their fraction."""
    out, _, rc = run("avg(a)", '{"a":[1,2]}', "-c")
    assert rc == 0 and out == "1.5\n", out
    out, _, rc = run("sum(a)", '{"a":[1,2,3]}', "-c")
    assert rc == 0 and out == "6\n", out
    out, _, rc = run("floor(`3.0`)", "{}", "-c")
    assert rc == 0 and out == "3\n", out


# --------------------------------------------------------------------------- CLI output formatting


def test_pretty_default_array_formatting():
    """Default output is pretty-printed JSON with two-space indentation and a trailing newline."""
    out, _, rc = run("a", '{"a":[1,2]}')
    assert rc == 0 and out == "[\n  1,\n  2\n]\n", repr(out)


def test_pretty_default_object_key_sorting():
    """Object output has its keys sorted lexicographically in both pretty and compact modes."""
    out, _, rc = run("@", '{"b":1,"a":2}')
    assert rc == 0 and out == '{\n  "a": 2,\n  "b": 1\n}\n', repr(out)
    out, _, rc = run("@", '{"b":1,"a":2}', "-c")
    assert rc == 0 and out == '{"a":2,"b":1}\n', repr(out)


def test_compact_scalar_and_string_output():
    """Compact scalar output is the bare JSON value plus a trailing newline."""
    out, _, rc = run("a", '{"a":5}', "-c")
    assert rc == 0 and out == "5\n", repr(out)
    out, _, rc = run("s", '{"s":"hi"}', "-c")
    assert rc == 0 and out == '"hi"\n', repr(out)
    out, _, rc = run("x", "{}", "-c")
    assert rc == 0 and out == "null\n", repr(out)


def test_unquoted_string_flag():
    """`-u` prints a string result without surrounding quotes but falls back to JSON for non-strings."""
    out, _, rc = run("s", '{"s":"hi"}', "-u")
    assert rc == 0 and out == "hi\n", repr(out)
    out, _, rc = run("n", '{"n":5}', "-u")
    assert rc == 0 and out == "5\n", repr(out)


def test_file_input_flag(tmp_path):
    """`-f <file>` reads the input JSON from a file instead of stdin."""
    p = tmp_path / "in.json"
    p.write_text('{"a":{"b":99}}')
    out, _, rc = run("a.b", "", "-c", "-f", str(p))
    assert rc == 0 and out == "99\n", repr(out)


# --------------------------------------------------------------------------- realistic workflows


def test_realistic_filter_project_sort_pipe():
    """A realistic query filters objects, projects a field, and sorts the piped result."""
    given = (
        '{"locations":[{"name":"Seattle","state":"WA"},'
        '{"name":"NY","state":"NY"},{"name":"Olympia","state":"WA"}]}'
    )
    assert val("locations[?state=='WA'].name | sort(@)", given) == [
        "Olympia",
        "Seattle",
    ]


def test_realistic_multiselect_hash_with_projection_and_length():
    """A multiselect hash can combine a projected list and an aggregate over the same input."""
    given = '{"people":[{"name":"a"},{"name":"b"}]}'
    assert val("{names: people[*].name, count: length(people)}", given) == {
        "names": ["a", "b"],
        "count": 2,
    }


def test_json_string_literal_comparison_in_filter():
    """A JSON-string literal (`\"WA\"` in backticks) is usable as a filter comparison operand."""
    given = '{"a":[{"name":"S","state":"WA"},{"name":"N","state":"NY"}]}'
    assert val('a[?state==`"WA"`].name', given) == ["S"]


# --------------------------------------------------------------------------- error handling


def test_error_on_syntax_error():
    """A malformed expression exits non-zero and writes a diagnostic to stderr."""
    _, err, rc = run("a[", "{}")
    assert rc != 0 and err.strip() != ""


def test_error_on_bad_function_calls():
    """Unknown function, wrong argument type, and wrong arity each fail with a diagnostic."""
    for expr, stdin in [
        ("no_such_fn(@)", "{}"),
        ("abs(s)", '{"s":"x"}'),
        ("abs(@, @)", "{}"),
    ]:
        _, err, rc = run(expr, stdin)
        assert rc != 0 and err.strip() != "", (expr, rc, err)


def test_error_on_invalid_input_json():
    """Unparseable input JSON exits non-zero with a diagnostic on stderr."""
    _, err, rc = run("@", "{bad json")
    assert rc != 0 and err.strip() != ""


def test_error_on_missing_argument():
    """Invoking the tool with no expression argument exits non-zero with a diagnostic."""
    proc = subprocess.run(
        [BIN], input="{}", capture_output=True, text=True, timeout=TIMEOUT
    )
    assert proc.returncode != 0 and proc.stderr.strip() != ""


# --------------------------------------------------------------- advanced projection semantics


def test_nested_list_projections_are_not_flattened():
    """A projection inside a projection nests: each outer element yields its own inner array."""
    assert val("a[*].b[*]", '{"a":[{"b":[1,2]},{"b":[3]}]}') == [[1, 2], [3]]
    given = '{"a":[{"b":[{"c":1},{"c":2}]},{"b":[{"c":3}]}]}'
    assert val("a[*].b[*].c", given) == [[1, 2], [3]]


def test_flatten_within_and_across_projections():
    """The flatten operator merges one array level, both inside a projection and when chained."""
    given = '{"a":[{"b":[{"c":1}]},{"b":[{"c":2},{"c":3}]}]}'
    assert val("a[*].b[].c", given) == [1, 2, 3]
    given2 = '{"a":[{"b":[{"c":1},{"c":2}]},{"b":[{"c":3}]}]}'
    assert val("a[].b[].c", given2) == [1, 2, 3]


def test_filter_projection_continues_into_subexpression():
    """A filter starts a projection that continues through following sub-expressions."""
    given = '{"a":[{"x":true,"y":{"z":1}},{"x":false,"y":{"z":9}}]}'
    assert val("a[?x].y.z", given) == [1]


def test_projection_on_non_array_yields_null():
    """A list wildcard applied to a non-array value produces null."""
    assert val("a[*]", '{"a":5}') is None


def test_pipe_after_filter_projection_then_index():
    """A pipe stops a filter projection so a following index selects from the whole result."""
    assert val("a[?v>`1`].v | [0]", '{"a":[{"v":1},{"v":2},{"v":3}]}') == 2


# --------------------------------------------------------------- map/projection null semantics


def test_map_preserves_nulls_unlike_projection():
    """map keeps a null result for every element, whereas a projection drops null results."""
    given = '{"a":[{"b":1},{"c":9},{"b":3}]}'
    assert val("map(&b, a)", given) == [1, None, 3]
    assert val("a[*].b", given) == [1, 3]


# --------------------------------------------------------------- comparator type semantics


def test_ordering_comparators_require_numbers():
    """Ordering comparators (<,>) yield no match for non-numeric operands, filtering them out."""
    assert val("a[?b<'m'].b", '{"a":[{"b":"x"},{"b":"a"}]}') == []
    assert val("a[?b>`1`]", '{"a":[{"b":"str"},{"b":2}]}') == [{"b": 2}]


def test_equality_is_type_sensitive():
    """Equality distinguishes a number from its string form (`2` != `\"2\"`)."""
    given = '{"a":[{"b":2,"id":1},{"b":"2","id":2}]}'
    assert val("a[?b==`2`].id", given) == [1]


def test_boolean_operator_precedence():
    """`&&` binds tighter than `||`; `||`/`&&` return an operand, not a coerced boolean."""
    assert val("a && b || c", '{"a":null,"b":2,"c":3}') == 3
    assert val("a && b || c", '{"a":1,"b":2,"c":3}') == 2
    assert val("!a && b", '{"a":false,"b":true}') is True


# --------------------------------------------------------------- function corners


def test_max_min_sort_operate_on_strings():
    """max/min/sort order strings lexicographically, not just numbers."""
    assert val("max(a)", '{"a":["b","a","c"]}') == "c"
    assert val("min(a)", '{"a":["b","a","c"]}') == "a"
    assert val("sort(a)", '{"a":["c","a","b"]}') == ["a", "b", "c"]


def test_length_counts_unicode_code_points():
    """length counts Unicode characters (code points), not bytes."""
    assert val("length(s)", '{"s":"héllo"}') == 5
    assert val("length(s)", '{"s":"a😀b"}') == 3


def test_sort_by_is_stable_for_equal_keys():
    """sort_by preserves the original relative order of elements with equal sort keys."""
    given = '{"a":[{"n":1,"k":2},{"n":2,"k":2},{"n":3,"k":1}]}'
    assert val("sort_by(a, &k)[*].n", given) == [3, 1, 2]


def test_functions_on_empty_object():
    """Functions over an empty object return empty results, not null."""
    assert val("keys(x)", '{"x":{}}') == []
    assert val("values(x)", '{"x":{}}') == []
    assert val("length(x)", '{"x":{}}') == 0
    assert val("merge(x)", '{"x":{}}') == {}


def test_functions_on_empty_array():
    """Functions over an empty array return their natural empty/identity result."""
    assert val("length(x)", '{"x":[]}') == 0
    assert val("sort(x)", '{"x":[]}') == []
    assert val("reverse(x)", '{"x":[]}') == []
    assert val("map(&a, x)", '{"x":[]}') == []
    assert val("to_array(x)", '{"x":[]}') == []
    assert val("sort_by(x, &a)", '{"x":[]}') == []
    assert val("contains(x, y)", '{"x":[],"y":1}') is False
    assert val("join(g, x)", '{"g":",","x":[]}') == ""


# --------------------------------------------------------------- slice corners


def test_negative_step_slices_and_bound_clamping():
    """Slices support negative steps with explicit bounds, and clamp out-of-range bounds."""
    assert val("[4:1:-1]", "[0,1,2,3,4,5]") == [4, 3, 2]
    assert val("[::-2]", "[0,1,2,3,4]") == [4, 2, 0]
    assert val("[1:10]", "[0,1,2]") == [1, 2]
    assert val("a[-10]", '{"a":[1,2,3]}') is None


# --------------------------------------------------------------- deep realistic workflows


def test_realistic_flatten_across_nested_filter_projections():
    """An AWS-style query filters nested instances then flattens the ids across reservations."""
    given = (
        '{"reservations":['
        '{"instances":[{"state":"running","id":"i1"},{"state":"stopped","id":"i2"}]},'
        '{"instances":[{"state":"running","id":"i3"}]}]}'
    )
    assert val("reservations[*].instances[?state=='running'].id | []", given) == [
        "i1",
        "i3",
    ]


def test_realistic_sort_by_multiselect_pipe_index():
    """sort_by feeds a per-element multiselect hash, piped and indexed to the first result."""
    given = '{"people":[{"name":"b","age":30},{"name":"a","age":25}]}'
    assert val("sort_by(people, &age)[*].{name: name, age: age} | [0]", given) == {
        "name": "a",
        "age": 25,
    }


# --------------------------------------------------------------- projection state machine


def test_filter_inside_projection():
    """A filter nested inside a projection filters each element's inner array independently."""
    given = '{"a":[{"b":[{"c":1},{"c":2}]},{"b":[{"c":3}]}]}'
    assert val("a[*].b[?c>`1`].c", given) == [[2], [3]]


def test_multiselect_list_inside_projection():
    """A multiselect list inside a projection builds a list per projected element."""
    assert val("a[*].[b,c]", '{"a":[{"b":1,"c":2},{"b":3,"c":4}]}') == [[1, 2], [3, 4]]


def test_slice_inside_projection():
    """A slice applies within a projection, producing one sliced array per element."""
    given = '{"a":[{"b":[1,2,3]},{"b":[4,5]}]}'
    assert val("a[*].b[0:2]", given) == [[1, 2], [4, 5]]


def test_top_level_and_double_flatten():
    """A top-level `[*]` projects the input array; `[]` flattens one level, `[][]` two."""
    assert val("[*]", "[1,2,3]") == [1, 2, 3]
    assert val("[]", "[[1,2],[3,[4]]]") == [1, 2, 3, [4]]
    assert val("[][]", "[[1,2],[3,[4]]]") == [1, 2, 3, 4]


def test_projection_piped_to_function():
    """A pipe hands the assembled projection to a function as a single array argument."""
    assert val("a[*].b | sort(@)", '{"a":[{"b":3},{"b":1},{"b":2}]}') == [1, 2, 3]
    assert val("a[*] | length(@)", '{"a":[1,2,3]}') == 3


def test_filter_on_piped_projection_result():
    """After a pipe stops a projection, a filter applies to the whole assembled array."""
    assert val("a[*].b | [?@>`1`]", '{"a":[{"b":1},{"b":2},{"b":3}]}') == [2, 3]


def test_index_in_projection_skips_empty_arrays():
    """Indexing inside a projection drops elements whose inner array is empty (index -> null)."""
    given = '{"a":[{"b":[1,2]},{"b":[]},{"b":[3]}]}'
    assert val("a[*].b[0]", given) == [1, 3]


def test_filter_with_current_node_inside_projection():
    """A filter using `@` inside a projection filters each element's inner array by its own values."""
    assert val("a[*].b[?@>`1`]", '{"a":[{"b":[1,2,3]}]}') == [[2, 3]]


def test_projection_continues_through_nested_fields():
    """A projection walks through several sub-expressions, dropping elements missing the path."""
    given = '{"a":[{"b":{"c":1}},{"b":{"c":2}},{"x":9}]}'
    assert val("a[*].b.c", given) == [1, 2]


def test_sort_by_and_max_by_then_pipe():
    """A pipe after sort_by/max_by selects into the single resulting value."""
    assert val("sort_by(a, &b) | [0].b", '{"a":[{"b":3},{"b":1},{"b":2}]}') == 1
    assert val("max_by(a, &b) | c", '{"a":[{"b":1,"c":"lo"},{"b":9,"c":"hi"}]}') == "hi"


def test_deep_projection_through_multiple_nested_fields():
    """A projection carries through several chained field accesses (and after a leading field)."""
    given = '{"a":[{"b":{"c":{"d":1}}},{"b":{"c":{"d":2}}}]}'
    assert val("a[*].b.c.d", given) == [1, 2]
    given2 = '{"a":{"b":[{"c":{"d":1}},{"c":{"d":2}}]}}'
    assert val("a.b[*].c.d", given2) == [1, 2]


def test_negative_index_inside_projection():
    """A negative index applies within a projection, selecting each element's last item."""
    given = '{"a":[{"b":[1,2,3]},{"b":[4,5]}]}'
    assert val("a[*].b[-1]", given) == [3, 5]


def test_truthiness_filter_inside_projection_zero_is_truthy():
    """A truthiness filter inside a projection keeps elements; note the number 0 is truthy."""
    given = '{"a":[{"b":[{"c":1,"d":10},{"c":0,"d":20}]}]}'
    assert val("a[*].b[?c].d", given) == [[10, 20]]
