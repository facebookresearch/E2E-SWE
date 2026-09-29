"""Hidden grading suite for the render task.

Drives the compiled `render` CLI (built by setup.sh at /app/render): it takes a template file path as
its argument and a JSON context object on stdin, and writes the rendered template to stdout. Each test
asserts a distinct behavioral contract with exact values, so the pass fraction tracks real
completeness of the template engine (tags, filters, expressions, inheritance).

Local iteration against a ground-truth build:
    BIN_ENV=/tmp/render pytest tests/test_render.py -q
"""

import json
import os
import subprocess

BIN = os.environ.get("BIN_ENV", "/app/render")


def render(tmp_path, template, context=None, extra_files=None):
    """Write `template` (+ any extra_files) into tmp_path, run render with JSON context on stdin."""
    if extra_files:
        for name, content in extra_files.items():
            (tmp_path / name).write_text(content)
    main = tmp_path / "main.html"
    main.write_text(template)
    stdin = json.dumps(context or {})
    proc = subprocess.run(
        [BIN, str(main)], input=stdin, capture_output=True, text=True, timeout=20
    )
    return proc.stdout, proc.stderr, proc.returncode


def out(tmp_path, template, context=None, extra_files=None):
    """Render expecting success; assert exit 0 and return stdout."""
    so, se, rc = render(tmp_path, template, context, extra_files)
    assert rc == 0, f"expected success, got rc={rc}, stderr={se!r}"
    return so


# ---------------------------------------------------------------------------
# Variables, attribute/index access, expressions
# ---------------------------------------------------------------------------


def test_variable(tmp_path):
    assert out(tmp_path, "{{ name }}", {"name": "World"}) == "World"


def test_attribute_access(tmp_path):
    assert (
        out(
            tmp_path,
            "{{ user.name }}-{{ user.age }}",
            {"user": {"name": "Al", "age": 30}},
        )
        == "Al-30"
    )


def test_index_access(tmp_path):
    assert (
        out(tmp_path, "{{ items.0 }}{{ items.2 }}", {"items": ["a", "b", "c"]}) == "ac"
    )


def test_nested_access(tmp_path):
    assert (
        out(
            tmp_path,
            "{{ data.list.1.k }}",
            {"data": {"list": [{"k": "x"}, {"k": "y"}]}},
        )
        == "y"
    )


def test_arithmetic_precedence(tmp_path):
    assert out(tmp_path, "{{ 2 + 3 * 4 - 1 }}", {}) == "13"


def test_context_number_is_integer(tmp_path):
    """Integer-valued JSON numbers render as integers (not floats)."""
    assert out(tmp_path, "{{ x }} {{ x|add:1 }}", {"x": 5}) == "5 6"


def test_boolean_renders_capitalized(tmp_path):
    assert out(tmp_path, "{{ b }}", {"b": True}) == "True"


def test_missing_variable_is_empty(tmp_path):
    assert out(tmp_path, "[{{ nope }}]", {}) == "[]"


# ---------------------------------------------------------------------------
# Control flow: if/elif/else, logical operators
# ---------------------------------------------------------------------------


def test_if_else(tmp_path):
    assert (
        out(tmp_path, "{% if n > 3 %}big{% else %}small{% endif %}", {"n": 5}) == "big"
    )


def test_if_elif_else(tmp_path):
    assert (
        out(
            tmp_path,
            "{% if n > 10 %}H{% elif n > 5 %}M{% else %}L{% endif %}",
            {"n": 7},
        )
        == "M"
    )


def test_logical_and_not(tmp_path):
    assert (
        out(
            tmp_path,
            "{% if a and not b %}Y{% else %}N{% endif %}",
            {"a": True, "b": False},
        )
        == "Y"
    )


def test_ifequal(tmp_path):
    assert (
        out(
            tmp_path,
            "{% ifequal a b %}same{% else %}diff{% endifequal %}",
            {"a": 5, "b": 5},
        )
        == "same"
    )


# ---------------------------------------------------------------------------
# for loops and the forloop object
# ---------------------------------------------------------------------------


def test_for_list(tmp_path):
    assert (
        out(tmp_path, "{% for i in items %}{{ i }} {% endfor %}", {"items": [1, 2, 3]})
        == "1 2 3 "
    )


def test_for_empty_clause(tmp_path):
    assert (
        out(tmp_path, "{% for i in xs %}{{ i }}{% empty %}none{% endfor %}", {"xs": []})
        == "none"
    )


def test_forloop_counter_and_last(tmp_path):
    tmpl = "{% for x in xs %}{{ forloop.Counter }}:{{ x }}{% if not forloop.Last %},{% endif %}{% endfor %}"
    assert out(tmp_path, tmpl, {"xs": ["a", "b", "c"]}) == "1:a,2:b,3:c"


def test_forloop_all_fields(tmp_path):
    tmpl = "{% for x in xs %}{{ forloop.Counter0 }}/{{ forloop.Revcounter }}/{{ forloop.First }}/{{ forloop.Last }} {% endfor %}"
    assert out(tmp_path, tmpl, {"xs": ["a", "b"]}) == "0/2/True/False 1/1/False/True "


def test_for_with_filter_condition(tmp_path):
    tmpl = "{% for i in xs %}{% if i|divisibleby:2 %}{{ i }} {% endif %}{% endfor %}"
    assert out(tmp_path, tmpl, {"xs": [1, 2, 3, 4, 5, 6]}) == "2 4 6 "


# ---------------------------------------------------------------------------
# Other tags: with, set, cycle, firstof, spaceless, filter, comment, templatetag
# ---------------------------------------------------------------------------


def test_with_tag(tmp_path):
    assert (
        out(tmp_path, "{% with t=a|add:b %}{{ t }}{% endwith %}", {"a": 3, "b": 4})
        == "7"
    )


def test_set_tag(tmp_path):
    assert out(tmp_path, '{% set g="hi" %}{{ g }}!', {}) == "hi!"


def test_cycle_tag(tmp_path):
    tmpl = '{% for i in xs %}{% cycle "odd" "even" %} {% endfor %}'
    assert out(tmp_path, tmpl, {"xs": [1, 2, 3]}) == "odd even odd "


def test_firstof_tag(tmp_path):
    assert out(tmp_path, "{% firstof a b c %}", {"a": "", "b": "B", "c": "C"}) == "B"


def test_spaceless_tag(tmp_path):
    tmpl = "{% spaceless %}<a>  <b> x</b></a>{% endspaceless %}"
    assert out(tmp_path, tmpl, {}) == "<a><b> x</b></a>"


def test_filter_tag(tmp_path):
    assert out(tmp_path, "{% filter upper %}hi there{% endfilter %}", {}) == "HI THERE"


def test_comment_tag(tmp_path):
    assert out(tmp_path, "a{% comment %}X{% endcomment %}b", {}) == "ab"


def test_templatetag(tmp_path):
    assert (
        out(tmp_path, "{% templatetag openblock %}{% templatetag closeblock %}", {})
        == "{%%}"
    )


# ---------------------------------------------------------------------------
# String filters
# ---------------------------------------------------------------------------


def test_upper_lower(tmp_path):
    assert out(tmp_path, "{{ s|upper }}|{{ s|lower }}", {"s": "Hello"}) == "HELLO|hello"


def test_title(tmp_path):
    assert out(tmp_path, "{{ s|title }}", {"s": "hello world"}) == "Hello World"


def test_capfirst(tmp_path):
    assert out(tmp_path, "{{ s|capfirst }}", {"s": "hello"}) == "Hello"


def test_truncatechars(tmp_path):
    assert (
        out(tmp_path, "{{ s|truncatechars:8 }}", {"s": "Hello World Foo"}) == "Hello..."
    )


def test_truncatewords(tmp_path):
    assert (
        out(tmp_path, "{{ s|truncatewords:2 }}", {"s": "one two three four"})
        == "one two ..."
    )


def test_wordcount(tmp_path):
    assert out(tmp_path, "{{ s|wordcount }}", {"s": "a b c d e"}) == "5"


def test_center(tmp_path):
    assert out(tmp_path, "[{{ s|center:9 }}]", {"s": "hi"}) == "[    hi   ]"


def test_ljust_rjust(tmp_path):
    assert (
        out(tmp_path, "[{{ s|ljust:5 }}][{{ s|rjust:5 }}]", {"s": "ab"})
        == "[ab   ][   ab]"
    )


def test_cut(tmp_path):
    assert out(tmp_path, '{{ s|cut:" " }}', {"s": "a b c"}) == "abc"


def test_slice(tmp_path):
    assert out(tmp_path, '{{ s|slice:":3" }}', {"s": "abcdef"}) == "abc"


def test_make_list(tmp_path):
    assert out(tmp_path, '{{ s|make_list|join:"-" }}', {"s": "hello"}) == "h-e-l-l-o"


def test_phone2numeric(tmp_path):
    assert out(tmp_path, "{{ s|phone2numeric }}", {"s": "CALL-HOME"}) == "2255-4663"


# ---------------------------------------------------------------------------
# Number filters
# ---------------------------------------------------------------------------


def test_floatformat_default(tmp_path):
    """floatformat with no argument rounds to one decimal place."""
    assert out(tmp_path, "{{ n|floatformat }}", {"n": 3.14159}) == "3.1"


def test_floatformat_arg(tmp_path):
    assert out(tmp_path, "{{ n|floatformat:2 }}", {"n": 3.14159}) == "3.14"


def test_divisibleby(tmp_path):
    assert (
        out(tmp_path, "{% if n|divisibleby:3 %}Y{% else %}N{% endif %}", {"n": 9})
        == "Y"
    )


def test_pluralize_plural(tmp_path):
    assert out(tmp_path, "{{ n }} cat{{ n|pluralize }}", {"n": 3}) == "3 cats"


def test_pluralize_singular(tmp_path):
    assert out(tmp_path, "{{ n }} cat{{ n|pluralize }}", {"n": 1}) == "1 cat"


def test_stringformat_requires_percent(tmp_path):
    """pongo2 stringformat passes the argument straight to fmt, so it must include the `%`."""
    assert out(tmp_path, '{{ n|stringformat:"%05d" }}', {"n": 42}) == "00042"


def test_get_digit(tmp_path):
    assert out(tmp_path, "{{ n|get_digit:2 }}", {"n": 12345}) == "4"


# ---------------------------------------------------------------------------
# List filters + defaults
# ---------------------------------------------------------------------------


def test_join(tmp_path):
    assert out(tmp_path, '{{ xs|join:", " }}', {"xs": ["a", "b", "c"]}) == "a, b, c"


def test_length(tmp_path):
    assert out(tmp_path, "{{ xs|length }}", {"xs": [1, 2, 3, 4]}) == "4"


def test_length_is(tmp_path):
    assert (
        out(
            tmp_path,
            "{% if xs|length_is:3 %}Y{% else %}N{% endif %}",
            {"xs": [1, 2, 3]},
        )
        == "Y"
    )


def test_first_last(tmp_path):
    assert out(tmp_path, "{{ xs|first }}{{ xs|last }}", {"xs": ["p", "q", "r"]}) == "pr"


def test_split(tmp_path):
    assert out(tmp_path, '{{ s|split:","|join:"|" }}', {"s": "a,b,c,d"}) == "a|b|c|d"


def test_default(tmp_path):
    assert out(tmp_path, '{{ missing|default:"N/A" }}', {}) == "N/A"


def test_default_if_none(tmp_path):
    assert out(tmp_path, '{{ x|default_if_none:"none!" }}', {"x": None}) == "none!"


def test_add_strings(tmp_path):
    assert out(tmp_path, "{{ a|add:b }}", {"a": "foo", "b": "bar"}) == "foobar"


def test_yesno(tmp_path):
    tmpl = '{{ b|yesno:"yes,no,maybe" }}|{{ x|yesno:"yes,no,maybe" }}'
    assert out(tmp_path, tmpl, {"b": True, "x": None}) == "yes|maybe"


# ---------------------------------------------------------------------------
# Escaping / HTML
# ---------------------------------------------------------------------------


def test_autoescape_default_and_safe(tmp_path):
    assert (
        out(tmp_path, "{{ s }}|{{ s|safe }}", {"s": "<b>x</b>"})
        == "&lt;b&gt;x&lt;/b&gt;|<b>x</b>"
    )


def test_autoescape_off_tag(tmp_path):
    tmpl = "{% autoescape off %}{{ s }}{% endautoescape %}"
    assert out(tmp_path, tmpl, {"s": "<b>x</b>"}) == "<b>x</b>"


def test_striptags(tmp_path):
    assert out(tmp_path, "{{ s|striptags }}", {"s": "<b>hi</b> <i>x</i>"}) == "hi x"


def test_urlencode(tmp_path):
    assert out(tmp_path, "{{ s|urlencode }}", {"s": "a b/c?d"}) == "a+b%2Fc%3Fd"


def test_filter_chaining(tmp_path):
    assert (
        out(tmp_path, "{{ s|lower|capfirst }}", {"s": "HELLO WORLD"}) == "Hello world"
    )


# ---------------------------------------------------------------------------
# Template inheritance, includes, macros (multi-file)
# ---------------------------------------------------------------------------


def test_extends_block_override(tmp_path):
    child = '{% extends "base2.html" %}{% block content %}hello {{ who }}{% endblock %}'
    base = "PAGE[{% block content %}{% endblock %}]"
    assert (
        out(tmp_path, child, {"who": "X"}, extra_files={"base2.html": base})
        == "PAGE[hello X]"
    )


def test_include(tmp_path):
    main = 'MAIN {% include "partial.html" %} END'
    partial = "partial({{ v }})"
    assert (
        out(tmp_path, main, {"v": "V"}, extra_files={"partial.html": partial})
        == "MAIN partial(V) END"
    )


def test_macro(tmp_path):
    tmpl = '{% macro row(x, y) %}<{{ x }}:{{ y }}>{% endmacro %}{{ row("a", 1) }}{{ row("b", 2) }}'
    assert out(tmp_path, tmpl, {}) == "<a:1><b:2>"


# ---------------------------------------------------------------------------
# Harder edge cases: deep access, banker's rounding, padding, nested loops/blocks
# ---------------------------------------------------------------------------


def test_deep_attribute_chain(tmp_path):
    assert out(tmp_path, "{{ a.b.c.d }}", {"a": {"b": {"c": {"d": "deep"}}}}) == "deep"


def test_deep_mixed_map_list_access(tmp_path):
    assert out(tmp_path, "{{ m.0.k.1 }}", {"m": [{"k": ["x", "y", "z"]}]}) == "y"


def test_deep_access_missing_intermediate_is_empty(tmp_path):
    assert out(tmp_path, "[{{ a.b.z.q }}]", {"a": {"b": {}}}) == "[]"


def test_floatformat_round_half_to_even_2_5(tmp_path):
    """Rounding is round-half-to-even: 2.5 rounds down to 2."""
    assert out(tmp_path, "{{ n|floatformat:0 }}", {"n": 2.5}) == "2"


def test_floatformat_round_half_to_even_3_5(tmp_path):
    """3.5 rounds up to 4 (nearest even)."""
    assert out(tmp_path, "{{ n|floatformat:0 }}", {"n": 3.5}) == "4"


def test_floatformat_negative_trims_when_integral(tmp_path):
    """A negative precision drops the decimals entirely only when the value is a whole number."""
    assert out(tmp_path, '{{ n|floatformat:"-2" }}', {"n": 3.0}) == "3"


def test_floatformat_negative_keeps_when_fractional(tmp_path):
    assert out(tmp_path, '{{ n|floatformat:"-2" }}', {"n": 3.1}) == "3.10"


def test_center_even_padding_splits_evenly(tmp_path):
    """An even amount of padding is split evenly, with no extra space biased to either side."""
    assert out(tmp_path, "[{{ s|center:9 }}]", {"s": "abc"}) == "[   abc   ]"


def test_truncatechars_exact_length_no_ellipsis(tmp_path):
    assert out(tmp_path, "{{ s|truncatechars:5 }}", {"s": "hello"}) == "hello"


def test_slice_open_ended(tmp_path):
    assert out(tmp_path, '{{ s|slice:"2:" }}', {"s": "abcdef"}) == "cdef"


def test_add_integers_is_numeric(tmp_path):
    assert out(tmp_path, "{{ a|add:b }}", {"a": 5, "b": 3}) == "8"


def test_get_digit_out_of_range_returns_value(tmp_path):
    assert out(tmp_path, "{{ n|get_digit:9 }}", {"n": 42}) == "42"


def test_nested_loops(tmp_path):
    tmpl = "{% for r in rows %}{% for c in r %}{{ c }}{% endfor %}|{% endfor %}"
    assert out(tmp_path, tmpl, {"rows": [[1, 2], [3, 4]]}) == "12|34|"


def test_forloop_parentloop(tmp_path):
    tmpl = "{% for r in rows %}{% for c in r %}{{ forloop.Parentloop.Counter }}.{{ forloop.Counter }} {% endfor %}{% endfor %}"
    assert out(tmp_path, tmpl, {"rows": [["a"], ["b", "c"]]}) == "1.1 2.1 2.2 "


def test_nested_blocks(tmp_path):
    child = '{% extends "nb.html" %}{% block inner %}X{% endblock %}'
    base = "OUT[{% block outer %}o{% block inner %}i{% endblock %}o{% endblock %}]"
    assert out(tmp_path, child, {}, extra_files={"nb.html": base}) == "OUT[oXo]"


def test_pluralize_custom_suffixes(tmp_path):
    assert out(tmp_path, '{{ n }} bo{{ n|pluralize:"x,xes" }}', {"n": 2}) == "2 boxes"


def test_yesno_two_argument(tmp_path):
    assert out(tmp_path, '{{ b|yesno:"on,off" }}', {"b": False}) == "off"


def test_default_treats_zero_as_falsy(tmp_path):
    assert out(tmp_path, '{{ n|default:"D" }}', {"n": 0}) == "D"


def test_join_integers(tmp_path):
    assert out(tmp_path, '{{ xs|join:"-" }}', {"xs": [1, 2, 3]}) == "1-2-3"


# ---------------------------------------------------------------------------
# Harder edge cases round 2: encoding, formatting verbs, expression operators
# ---------------------------------------------------------------------------


def test_urlencode_unicode(tmp_path):
    assert out(tmp_path, "{{ s|urlencode }}", {"s": "café"}) == "caf%C3%A9"


def test_stringformat_float_precision(tmp_path):
    assert out(tmp_path, '{{ n|stringformat:"%.2f" }}', {"n": 3.14159}) == "3.14"


def test_membership_in(tmp_path):
    assert (
        out(
            tmp_path,
            "{% if x in xs %}Y{% else %}N{% endif %}",
            {"x": 3, "xs": [1, 2, 3]},
        )
        == "Y"
    )


def test_string_comparison(tmp_path):
    assert (
        out(
            tmp_path,
            "{% if a > b %}Y{% else %}N{% endif %}",
            {"a": "apple", "b": "banana"},
        )
        == "N"
    )


def test_for_over_string(tmp_path):
    assert (
        out(tmp_path, "{% for c in s %}{{ c }}.{% endfor %}", {"s": "abc"}) == "a.b.c."
    )


def test_integer_division(tmp_path):
    assert out(tmp_path, "{{ 7 / 2 }}", {}) == "3"


def test_modulo(tmp_path):
    assert out(tmp_path, "{{ 17 % 5 }}", {}) == "2"


def test_unary_minus(tmp_path):
    assert out(tmp_path, "{{ -x }}", {"x": 5}) == "-5"


def test_slice_of_list(tmp_path):
    assert (
        out(tmp_path, '{{ xs|slice:"1:3"|join:"," }}', {"xs": [10, 20, 30, 40]})
        == "20,30"
    )


# ---------------------------------------------------------------------------
# Harder edge cases round 3: exact-output encoding battery
# ---------------------------------------------------------------------------


def test_urlencode_unreserved_kept(tmp_path):
    assert out(tmp_path, "{{ s|urlencode }}", {"s": "~-._"}) == "~-._"


def test_iriencode_keeps_reserved(tmp_path):
    assert out(tmp_path, "{{ s|iriencode }}", {"s": "a b?c=d&e#f/g"}) == (
        "a+b?c=d&amp;e#f/g"
    )


def test_iriencode_unicode(tmp_path):
    assert out(tmp_path, "{{ s|iriencode }}", {"s": "café ñ"}) == "caf%C3%A9+%C3%B1"


def test_escapejs_specials(tmp_path):
    assert out(tmp_path, "{{ s|escapejs }}", {"s": "a'b\"c<d>e&f"}) == (
        "a\\u0027b\\u0022c\\u003Cd\\u003Ee\\u0026f"
    )


def test_escapejs_backslash(tmp_path):
    assert out(tmp_path, "{{ s|escapejs }}", {"s": "a\\b/c"}) == "a\\u005Cb/c"


def test_escapejs_unicode_and_crlf(tmp_path):
    assert (
        out(tmp_path, "{{ s|escapejs }}", {"s": "café\r\n\t"})
        == "caf\\u00E9\\u000D\\u000A\\u0009"
    )


def test_linebreaks_multi_paragraph(tmp_path):
    """Blank line → new <p>; single newline → <br />; all auto-escaped."""
    assert out(tmp_path, "{{ s|linebreaks }}", {"s": "a\nb\n\nc\nd"}) == (
        "&lt;p&gt;a&lt;br /&gt;b&lt;/p&gt;&lt;p&gt;c&lt;br /&gt;d&lt;/p&gt;"
    )


def test_linebreaksbr_multi(tmp_path):
    assert out(tmp_path, "{{ s|linebreaksbr }}", {"s": "a\nb\nc"}) == (
        "a&lt;br /&gt;b&lt;br /&gt;c"
    )


def test_linebreaksbr_leading_trailing(tmp_path):
    """A leading and a trailing newline each become a <br /> too (every newline is converted)."""
    assert out(tmp_path, "{{ s|linebreaksbr }}", {"s": "\nx\n"}) == (
        "&lt;br /&gt;x&lt;br /&gt;"
    )


def test_striptags_with_attributes(tmp_path):
    assert out(
        tmp_path, "{{ s|striptags }}", {"s": '<a href="x">link</a> <br/> plain'}
    ) == ("link  plain")


def test_floatformat_signed_zero(tmp_path):
    """-0.5 rounds to the nearest even (0) but prints with the sign: -0."""
    assert out(tmp_path, "{{ n|floatformat:0 }}", {"n": -0.5}) == "-0"


# ---------------------------------------------------------------------------
# Harder edge cases round 4: float rendering, linebreaks variety, autoescape chains
# ---------------------------------------------------------------------------


def test_bare_float_six_decimals(tmp_path):
    """A bare float renders with six decimal places (Go %f)."""
    assert out(tmp_path, "{{ x }}", {"x": 5.5}) == "5.500000"


def test_whole_valued_float_six_decimals(tmp_path):
    """A whole-valued JSON float (written with a '.') is typed by lexical form, so 4.0 still
    renders with six decimals as '4.000000' rather than the integer '4'."""
    assert out(tmp_path, "{{ x }}", {"x": 4.0}) == "4.000000"


def test_float_arithmetic_six_decimals(tmp_path):
    assert out(tmp_path, "{{ 1.0 + 2.0 }}", {}) == "3.000000"


def test_linebreaks_leading_blank_dropped(tmp_path):
    assert (
        out(tmp_path, "{{ s|linebreaks }}", {"s": "\n\nhello"})
        == "&lt;p&gt;hello&lt;/p&gt;"
    )


def test_linebreaks_trailing_blank_empty_paragraph(tmp_path):
    assert out(tmp_path, "{{ s|linebreaks }}", {"s": "hello\n\n"}) == (
        "&lt;p&gt;hello&lt;/p&gt;&lt;p&gt;&lt;/p&gt;"
    )


def test_linebreaks_multiple_blank_lines_collapse(tmp_path):
    assert out(tmp_path, "{{ s|linebreaks }}", {"s": "a\n\n\n\nb"}) == (
        "&lt;p&gt;a&lt;/p&gt;&lt;p&gt;b&lt;/p&gt;"
    )


def test_linebreaksbr_escapes_existing_html(tmp_path):
    assert out(tmp_path, "{{ s|linebreaksbr }}", {"s": "<b>x</b>\ny"}) == (
        "&lt;b&gt;x&lt;/b&gt;&lt;br /&gt;y"
    )


def test_filter_chain_upper_then_escapejs(tmp_path):
    assert out(tmp_path, "{{ s|upper|escapejs }}", {"s": "a<b"}) == "A\\u003CB"


def test_safe_persists_through_chain(tmp_path):
    """`safe` marks the value safe; a later filter's output is still not re-escaped."""
    assert out(tmp_path, "{{ s|safe|upper }}", {"s": "<b>x</b>"}) == "<B>X</B>"


def test_autoescape_ampersand_and_angles(tmp_path):
    assert out(tmp_path, "{{ s }}", {"s": "a & b < c > d"}) == "a &amp; b &lt; c &gt; d"


def test_default_then_filter(tmp_path):
    assert (
        out(tmp_path, "{{ a|default:b|upper }}", {"a": "", "b": "fallback"})
        == "FALLBACK"
    )


def test_literal_percent_outside_tags(tmp_path):
    assert out(tmp_path, "a % b {{ x }}", {"x": 5}) == "a % b 5"


def test_literal_brace_outside_tags(tmp_path):
    assert out(tmp_path, "a {{ x }} }", {"x": 5}) == "a 5 }"


# ---------------------------------------------------------------------------
# Harder edge cases round 5: linebreaks depth, floatformat rounding, float-in-context
# ---------------------------------------------------------------------------


def test_linebreaks_only_newlines(tmp_path):
    assert out(tmp_path, "{{ s|linebreaks }}", {"s": "\n\n\n"}) == "&lt;p&gt;&lt;/p&gt;"


def test_floatformat_rounds_up_at_repr_boundary(tmp_path):
    """0.45's binary repr is just above 0.45, so it rounds up to 0.5."""
    assert out(tmp_path, "{{ n|floatformat:1 }}", {"n": 0.45}) == "0.5"


def test_floatformat_integer_input(tmp_path):
    assert out(tmp_path, "{{ n|floatformat:2 }}", {"n": 5}) == "5.00"


def test_float_division_six_decimals(tmp_path):
    assert out(tmp_path, "{{ 7.0 / 2 }}", {}) == "3.500000"


def test_float_add_six_decimals(tmp_path):
    assert out(tmp_path, "{{ x|add:y }}", {"x": 1.5, "y": 2.5}) == "4.000000"


def test_title_with_apostrophe(tmp_path):
    assert out(tmp_path, "{{ s|title }}", {"s": "o'brien mcdonald 3rd"}) == (
        "O&#39;Brien Mcdonald 3rd"
    )


def test_pluralize_zero_is_plural(tmp_path):
    assert out(tmp_path, "{{ n }} item{{ n|pluralize }}", {"n": 0}) == "0 items"


def test_logical_precedence_and_over_or(tmp_path):
    """`a or b and c` parses as `a or (b and c)`."""
    tmpl = "{% if a or b and c %}Y{% else %}N{% endif %}"
    assert out(tmp_path, tmpl, {"a": False, "b": True, "c": False}) == "N"


def test_for_reversed(tmp_path):
    assert (
        out(
            tmp_path, "{% for v in xs reversed %}{{ v }}{% endfor %}", {"xs": [1, 2, 3]}
        )
        == "321"
    )


def test_cut_multichar_substring(tmp_path):
    assert out(tmp_path, '{{ s|cut:"an" }}', {"s": "banana"}) == "ba"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_missing_template_arg(tmp_path):
    proc = subprocess.run([BIN], input="{}", capture_output=True, text=True)
    assert proc.returncode == 2 and proc.stdout == "" and proc.stderr.strip() != ""


def test_template_syntax_error(tmp_path):
    so, se, rc = render(tmp_path, "{% if x %}unterminated", {"x": 1})
    assert rc == 1 and so == "" and se.strip() != ""
