"""Hidden grading suite for the minify task.

Drives the compiled `minify` CLI (built by setup.sh at /app/minify) entirely through subprocess:
program/args + stdin in, stdout/stderr/exit-code out. Each test models a realistic minification
scenario and asserts EXACT expected output (the minifier is deterministic and its output has no
trailing newline), so the pass fraction tracks real implementation completeness.

Scope: JSON, CSS and XML minification via `--type=`. All expected values were probed against the
ground-truth binary. Set BIN_ENV to iterate locally:
    BIN_ENV=/tmp/minify-gt pytest tests/test_minify.py -q
"""

import os
import subprocess

BIN = os.environ.get("BIN_ENV", "/app/minify")


def run(argv, stdin=""):
    """Run the binary with argv (list); return (stdout, stderr, returncode)."""
    proc = subprocess.run(
        [BIN, *argv], input=stdin, capture_output=True, text=True, timeout=20
    )
    return proc.stdout, proc.stderr, proc.returncode


def mini(filetype, src, *flags):
    """Minify `src` as `filetype`; assert success and return stdout (no trailing newline added)."""
    so, se, rc = run(["--type=" + filetype, *flags], stdin=src)
    assert rc == 0, f"expected success, got rc={rc}, stderr={se!r}"
    return so


# ======================================================================================
# JSON
# ======================================================================================

def test_json_removes_insignificant_whitespace():
    """Insignificant whitespace between JSON tokens is removed, structure preserved."""
    assert mini("json", '{ "a": [1, 2] }') == '{"a":[1,2]}'
    assert mini("json", '[{ "a": [{"x": null}, true] }]') == '[{"a":[{"x":null},true]}]'
    assert mini("json", "[\n  1,\n  2\n]") == "[1,2]"


def test_json_normalizes_numbers():
    """Numbers are canonicalized to their shortest equivalent form."""
    assert mini("json", "1.0") == "1"
    assert mini("json", "1.3e1") == "13"
    assert mini("json", "1E+03") == "1e3"
    assert mini("json", "0.1") == "0.1"
    assert mini("json", "-0.1") == "-0.1"


def test_json_keep_numbers_flag():
    """--json-keep-numbers preserves the original numeric literals verbatim."""
    assert mini("json", "1.0", "--json-keep-numbers") == "1.0"
    assert mini("json", "1E+03", "--json-keep-numbers") == "1E+03"


def test_json_precision_flag():
    """--json-precision limits significant digits of numbers."""
    assert mini("json", "3.141592653589793", "--json-precision=4") == "3.142"


def test_json_preserves_string_content():
    """String contents (including escape sequences) are preserved exactly."""
    assert mini("json", '"a\\nb"') == '"a\\nb"'
    assert mini("json", '{ "key with spaces": "v" }') == '{"key with spaces":"v"}'


def test_json_empty_input():
    """Empty input yields empty output with success."""
    assert mini("json", "") == ""


def test_json_invalid_input_errors():
    """Syntactically invalid JSON exits nonzero with a diagnostic on stderr."""
    so, se, rc = run(["--type=json"], stdin="{bad")
    assert rc != 0
    assert se.strip() != ""


# ======================================================================================
# CSS — selectors and structure
# ======================================================================================

def test_css_collapses_selector_whitespace():
    """Whitespace in selector lists and around combinators is removed."""
    assert mini("css", "a , b , c { x : y }") == "a,b,c{x:y}"
    assert mini("css", "a > b{x:y}") == "a>b{x:y}"
    assert mini("css", "a + b{x:y}") == "a+b{x:y}"
    assert mini("css", "a ~ b{x:y}") == "a~b{x:y}"


def test_css_removes_trailing_semicolons_and_empty_rules():
    """The final semicolon in a block is dropped and empty rules are removed entirely."""
    assert mini("css", "a{x:y;}") == "a{x:y}"
    assert mini("css", "a{}") == ""
    assert mini("css", "a{x:y}\n\n\nb{z:w}") == "a{x:y}b{z:w}"


def test_css_drops_comments_but_keeps_bang_comments():
    """Ordinary comments are removed; /*! ... */ bang comments are kept (and trimmed)."""
    assert mini("css", "/*c*/a{x:y}") == "a{x:y}"
    assert mini("css", "/*! keep */a{x:y}") == "/*!keep*/a{x:y}"
    assert mini("css", "/*x*/") == ""


def test_css_lowercases_elements_atrules_hex_not_class():
    """Element names, at-rule keywords and hex digits are lowercased; class names are not."""
    assert mini("css", "DIV{x:y}") == "div{x:y}"
    assert mini("css", "@MEDIA all{a{x:y}}") == "@media all{a{x:y}}"
    assert mini("css", "a{color:#ABCDEF}") == "a{color:#abcdef}"
    assert mini("css", ".CLA{x:y}") == ".CLA{x:y}"


def test_css_unquotes_attribute_selectors():
    """Attribute selector values are unquoted when safe and internal whitespace removed."""
    assert mini("css", 'input[type="radio"]{x:y}') == "input[type=radio]{x:y}"
    assert mini("css", ".cla[id ^= L] { x:y; }") == ".cla[id^=L]{x:y}"


def test_css_collapses_declaration_whitespace():
    """Whitespace around colons, braces and declarations is collapsed."""
    assert mini("css", "a{ color : red }") == "a{color:red}"
    assert (
        mini("css", "a{color:red;background:blue;margin:0}")
        == "a{color:red;background:blue;margin:0}"
    )


# ======================================================================================
# CSS — colors
# ======================================================================================

def test_css_shortens_hex_colors():
    """Six/eight-digit hex colors collapse to three/four digits when possible; hex lowercased."""
    assert mini("css", "a{color:#ffffff}") == "a{color:#fff}"
    assert mini("css", "a{color:#aabbcc}") == "a{color:#abc}"
    assert mini("css", "a{color:#ABC}") == "a{color:#abc}"
    assert mini("css", "a{color:#aabbccdd}") == "a{color:#abcd}"


def test_css_canonicalizes_colors_to_shortest_form():
    """Named/functional colors are rewritten to the shortest equivalent (name or hex)."""
    assert mini("css", "a{color:white}") == "a{color:#fff}"
    assert mini("css", "a{color:black}") == "a{color:#000}"
    assert mini("css", "a{color:#ff0000}") == "a{color:red}"
    assert mini("css", "a{color:rgb(255,0,0)}") == "a{color:red}"
    assert mini("css", "a{color:rgb(0,128,0)}") == "a{color:green}"
    assert mini("css", "a{color:rgb(1,2,3)}") == "a{color:#010203}"
    assert mini("css", "a{color:rgba(0,0,0,0)}") == "a{color:transparent}"


# ======================================================================================
# CSS — numbers and units
# ======================================================================================

def test_css_strips_units_from_zero_and_collapses_shorthands():
    """Zero values drop their unit and repeated box-shorthand values collapse."""
    assert mini("css", "a{margin:0px}") == "a{margin:0}"
    assert mini("css", "a{margin:0 0 0 0}") == "a{margin:0}"
    assert mini("css", "a{margin:1px 1px}") == "a{margin:1px}"
    assert mini("css", "a{margin:10px 20px 10px 20px}") == "a{margin:10px 20px}"
    assert mini("css", "a{transform:rotate(0deg)}") == "a{transform:rotate(0)}"


def test_css_normalizes_number_forms():
    """Numbers drop leading/trailing zeros and use scientific notation when shorter."""
    assert mini("css", "a{margin:0.5em}") == "a{margin:.5em}"
    assert mini("css", "a{margin:-0.5px}") == "a{margin:-.5px}"
    assert mini("css", "a{width:1.500px}") == "a{width:1.5px}"
    assert mini("css", "a{width:100000px}") == "a{width:1e5px}"
    assert mini("css", "a{width:0.0001px}") == "a{width:1e-4px}"
    assert mini("css", "a{transition:1000ms}") == "a{transition:1e3ms}"


def test_css_precision_flag():
    """--css-precision limits significant digits of numeric values."""
    assert mini("css", "a{width:1.23456px}", "--css-precision=3") == "a{width:1.23px}"


# ======================================================================================
# CSS — values and keywords
# ======================================================================================

def test_css_font_weight_keywords_to_numbers():
    """The font-weight keywords bold/normal become their numeric equivalents."""
    assert mini("css", "a{font-weight:bold}") == "a{font-weight:700}"
    assert mini("css", "a{font-weight:normal}") == "a{font-weight:400}"


def test_css_important_whitespace_removed():
    """Whitespace around !important is removed (in all spacing variants)."""
    assert mini("css", "a{color:red !important}") == "a{color:red!important}"
    assert mini("css", "a{color:red ! important}") == "a{color:red!important}"
    assert mini("css", "a{color:red!important;}") == "a{color:red!important}"


def test_css_unquotes_url_values():
    """url() values are unquoted and internal whitespace removed when safe."""
    assert mini("css", "a{background:url('x.png')}") == "a{background:url(x.png)}"
    assert (
        mini("css", "a{background:url( data:image/png;base64,AAA )}")
        == "a{background:url(data:image/png;base64,AAA)}"
    )


# ======================================================================================
# CSS — at-rules
# ======================================================================================

def test_css_media_query_whitespace():
    """Whitespace inside media query feature tests is collapsed."""
    assert (
        mini("css", "@media only screen and (max-width : 800px){a{x:y}}")
        == "@media only screen and (max-width:800px){a{x:y}}"
    )


def test_css_supports_import_charset():
    """@supports/@import/@charset are minified (space and quote/semicolon handling)."""
    assert mini("css", "@supports (display: grid){a{x:y}}") == "@supports(display:grid){a{x:y}}"
    assert mini("css", "@import url('file');") == "@import 'file'"
    assert mini("css", '@charset "utf-8";') == '@charset "utf-8"'


def test_css_preserves_calc_var_and_custom_properties():
    """calc()/var() expressions and @keyframes are preserved; custom-prop whitespace trimmed."""
    assert mini("css", "a{width:calc(100% - 10px)}") == "a{width:calc(100% - 10px)}"
    assert mini("css", "a{width:var(--x)}") == "a{width:var(--x)}"
    assert mini("css", "a{--my-var: 10px}") == "a{--my-var:10px}"
    assert (
        mini("css", "@keyframes x{from{opacity:0}to{opacity:1}}")
        == "@keyframes x{from{opacity:0}to{opacity:1}}"
    )


def test_css_lenient_on_malformed_input():
    """Malformed CSS does not error; the minifier recovers and returns exit code 0."""
    so, se, rc = run(["--type=css"], stdin="a{")
    assert rc == 0


def test_css_empty_input():
    """Empty CSS input yields empty output."""
    assert mini("css", "") == ""


# ======================================================================================
# XML
# ======================================================================================

def test_xml_collapses_whitespace():
    """Insignificant whitespace between and inside elements is collapsed."""
    assert mini("xml", "<root>  <a> x </a>  </root>") == "<root><a>x</a></root>"


def test_xml_self_closes_empty_elements():
    """An element with no content is rewritten to self-closing form."""
    assert mini("xml", "<a></a>") == "<a/>"


def test_xml_normalizes_attribute_whitespace():
    """Whitespace around attribute assignments is removed; quotes preserved."""
    assert mini("xml", "<a  b = 'c' />") == "<a b='c'/>"


def test_xml_removes_comments():
    """XML comments are removed."""
    assert mini("xml", "<a><!--c--></a>") == "<a></a>"


def test_xml_unwraps_cdata():
    """CDATA sections whose content needs no escaping are unwrapped to text."""
    assert mini("xml", "<a><![CDATA[ x ]]></a>") == "<a> x </a>"


def test_xml_keep_whitespace_flag():
    """--xml-keep-whitespace preserves whitespace but still collapses runs to one."""
    assert mini("xml", "<a>  x  y  </a>", "--xml-keep-whitespace") == "<a> x y </a>"


def test_xml_preserves_declaration():
    """The XML declaration is preserved."""
    assert mini("xml", "<?xml version='1.0'?><a/>") == "<?xml version='1.0'?><a/>"


# ======================================================================================
# CLI mechanics
# ======================================================================================

def test_requires_type_for_stdin():
    """Reading from stdin without --type is an error (filetype cannot be inferred)."""
    so, se, rc = run([], stdin='{"a":1}')
    assert rc != 0
    assert se.strip() != ""


def test_output_to_file(tmp_path):
    """-o writes minified output to the named file."""
    dst = tmp_path / "out.json"
    so, se, rc = run(["--type=json", "-o", str(dst)], stdin='{ "a": 1 }')
    assert rc == 0
    assert dst.read_text() == '{"a":1}'


# ======================================================================================
# Additional CSS corners
# ======================================================================================

def test_css_collapses_three_and_four_value_shorthands():
    """Box shorthands collapse: symmetric 3-value to 2 and mirrored 4-value to 2."""
    assert mini("css", "a{padding:5px 10px 5px}") == "a{padding:5px 10px}"
    assert mini("css", "a{margin:1px 2px 1px}") == "a{margin:1px 2px}"
    assert mini("css", "a{padding:5px 10px 5px 10px}") == "a{padding:5px 10px}"


def test_css_universal_selector_and_integer_floats():
    """The universal selector is preserved; integral floats and negative zero simplify."""
    assert mini("css", "*{margin:0}") == "*{margin:0}"
    assert mini("css", "a{width:5.0px}") == "a{width:5px}"
    assert mini("css", "a{margin:-0px}") == "a{margin:0}"
    assert mini("css", "a{margin:0% 0%}") == "a{margin:0%}"


def test_css_hex_to_color_name_when_shorter():
    """A hex color is rewritten to its color name when that is shorter."""
    assert mini("css", "a{color:#808080}") == "a{color:gray}"


def test_css_grouping_with_pseudo_and_media_no_space():
    """Pseudo-class selector groups collapse; @media(...) with no space is preserved."""
    assert mini("css", "a:hover , b:focus { x:y }") == "a:hover,b:focus{x:y}"
    assert mini("css", "@media(min-width:1px){a{x:y}}") == "@media(min-width:1px){a{x:y}}"


# ======================================================================================
# Additional JSON corners
# ======================================================================================

def test_json_preserves_literals_and_nesting():
    """Boolean/null literals, nested structures and duplicate keys are preserved."""
    assert mini("json", "[true, false, null]") == "[true,false,null]"
    assert mini("json", '{"a":{"b":{"c":[1]}}}') == '{"a":{"b":{"c":[1]}}}'
    assert mini("json", '{"a":1,"a":2}') == '{"a":1,"a":2}'


def test_json_preserves_unicode_escapes():
    """Unicode escape sequences in strings are preserved verbatim."""
    assert mini("json", '"\\u00e9"') == '"\\u00e9"'


# ======================================================================================
# Additional XML corners
# ======================================================================================

def test_xml_collapses_nested_and_internal_text_whitespace():
    """Whitespace between nested elements and runs inside text are collapsed."""
    assert mini("xml", "<a> <b> <c>x</c> </b> </a>") == "<a><b><c>x</c></b></a>"
    assert mini("xml", "<a>x    y</a>") == "<a>x y</a>"


def test_xml_normalizes_multiple_attributes():
    """Multiple attributes keep single-space separation with quotes preserved."""
    assert mini("xml", "<a  x='1'   y='2'/>") == "<a x='1' y='2'/>"


def test_xml_preserves_entities():
    """Character entity references in text are preserved."""
    assert mini("xml", "<a>x &amp; y</a>") == "<a>x &amp; y</a>"


def test_xml_self_closes_mixed_and_collapses_siblings():
    """Empty elements self-close (both forms) and whitespace between siblings is removed."""
    assert mini("xml", "<a><b/><c></c></a>") == "<a><b/><c/></a>"
    assert mini("xml", "<a> <b>t</b> <b>u</b> </a>") == "<a><b>t</b><b>u</b></a>"


# ======================================================================================
# Hardening — deeper CSS / JSON corners
# ======================================================================================

def test_css_does_not_collapse_asymmetric_shorthands():
    """Box shorthands only collapse when mirrorable; asymmetric values are kept verbatim."""
    assert mini("css", "a{margin:1px 2px 3px 4px}") == "a{margin:1px 2px 3px 4px}"
    assert mini("css", "a{margin:1px 2px 3px}") == "a{margin:1px 2px 3px}"
    assert mini("css", "a{padding:0 0}") == "a{padding:0}"


def test_css_opaque_and_hsl_colors():
    """Fully-opaque colors drop alpha and shorten; hsl() converts to the shortest form."""
    assert mini("css", "a{color:#ffffffff}") == "a{color:#fff}"
    assert mini("css", "a{color:rgb(255,255,255)}") == "a{color:#fff}"
    assert mini("css", "a{color:rgba(255,255,255,1)}") == "a{color:#fff}"
    assert mini("css", "a{color:hsl(120,100%,50%)}") == "a{color:#0f0}"


def test_css_media_list_and_negation_preserved():
    """Comma media lists and not/only qualifiers keep their structure."""
    assert mini("css", "@media screen,print{a{x:y}}") == "@media screen,print{a{x:y}}"
    assert (
        mini("css", "@media not all and (monochrome){a{x:y}}")
        == "@media not all and (monochrome){a{x:y}}"
    )


def test_css_nested_calc_preserved():
    """Nested calc() expressions preserve their internal spacing."""
    assert (
        mini("css", "a{width:calc(100% - calc(10px + 5px))}")
        == "a{width:calc(100% - calc(10px + 5px))}"
    )


def test_css_shorthand_collapse_with_important():
    """A mirrorable shorthand still collapses when !important follows."""
    assert mini("css", "a{margin:0 0 0 0 !important}") == "a{margin:0!important}"


def test_css_collapses_multiple_value_spaces():
    """Runs of whitespace inside a value collapse to a single space."""
    assert mini("css", "a{margin:1px    2px}") == "a{margin:1px 2px}"


def test_css_leading_zero_dropped_in_context():
    """CSS drops the leading integer zero of fractions wherever they appear."""
    assert mini("css", "a{transition:all 0.5s ease}") == "a{transition:all .5s ease}"
    assert mini("css", "a{opacity:0.001}") == "a{opacity:.001}"
    assert mini("css", "a{margin:0.0%}") == "a{margin:0%}"


def test_css_removes_empty_declarations():
    """Empty declarations (stray semicolons) are removed, emptying the rule."""
    assert mini("css", "a{;;}") == ""


def test_json_keeps_leading_zero():
    """Unlike CSS, JSON keeps the leading zero of a fraction (required by JSON grammar)."""
    assert mini("json", "0.1") == "0.1"
    assert mini("json", "0.5") == "0.5"
    assert mini("json", "0.05") == "0.05"
    assert mini("json", "0.001") == "0.001"


def test_json_number_scientific_thresholds():
    """Scientific notation is used only when strictly shorter; zeros collapse."""
    assert mini("json", "1000000") == "1e6"
    assert mini("json", "10000") == "1e4"
    assert mini("json", "100") == "100"
    assert mini("json", "12345678") == "12345678"
    assert mini("json", "0e0") == "0"
    assert mini("json", "-0.0") == "0"
    assert mini("json", "-0") == "0"


# ======================================================================================
# Harder corners — round 2 tightening
# ======================================================================================

def test_css_attribute_operators_unquote_when_identifier():
    """Attribute selectors with ~= |= *= drop quotes when the value is a valid identifier."""
    assert mini("css", 'a[class~="x"]{y:z}') == "a[class~=x]{y:z}"
    assert mini("css", 'a[lang|="en"]{y:z}') == "a[lang|=en]{y:z}"
    assert mini("css", 'a[href*="x"]{y:z}') == "a[href*=x]{y:z}"
    # a value that is not a valid identifier (leading dot) keeps its quotes:
    assert mini("css", 'a[href$=".pdf"]{y:z}') == 'a[href$=".pdf"]{y:z}'


def test_css_modern_space_separated_rgb():
    """Space-separated rgb() is canonicalized to the shortest form just like the comma form."""
    assert mini("css", "a{color:rgb(255 0 0)}") == "a{color:red}"


def test_css_percentage_and_unit_number_normalization():
    """Trailing zeros drop across %/rem and a zero angle drops its unit."""
    assert mini("css", "a{width:50.0%}") == "a{width:50%}"
    assert mini("css", "a{font-size:1.0rem}") == "a{font-size:1rem}"
    assert mini("css", "a{transform:rotate(0turn)}") == "a{transform:rotate(0)}"


def test_css_var_fallback_whitespace():
    """Whitespace after the comma in a var() fallback is removed."""
    assert mini("css", "a{color:var(--x, red)}") == "a{color:var(--x,red)}"


def test_css_important_keyword_case_preserved():
    """Whitespace around !important is removed but the keyword's letter case is preserved."""
    assert mini("css", "a{color:red !IMPORTANT}") == "a{color:red!IMPORTANT}"


def test_css_comment_between_selectors_removed():
    """A comment between selector tokens is removed and the tokens are joined."""
    assert mini("css", "a/*x*/b{c:d}") == "ab{c:d}"


def test_css_media_no_space_before_parenthesis():
    """The space after @media is removed when the query begins with '('."""
    assert (
        mini("css", "@media (min-aspect-ratio:16/9){a{x:y}}")
        == "@media(min-aspect-ratio:16/9){a{x:y}}"
    )


def test_css_preserves_min_negative_and_alpha():
    """min()/negative lengths/non-opaque hsla are preserved as-is."""
    assert mini("css", "a{width:min(1px,2px)}") == "a{width:min(1px,2px)}"
    assert mini("css", "a{margin:-10px}") == "a{margin:-10px}"
    assert mini("css", "a{color:hsla(0,100%,50%,.5)}") == "a{color:hsla(0,100%,50%,.5)}"


def test_json_preserves_extreme_exponents_and_escapes():
    """Very large/small exponents and string escapes are preserved verbatim."""
    assert mini("json", "1e100") == "1e100"
    assert mini("json", "1e-100") == "1e-100"
    assert mini("json", '"a\\/b"') == '"a\\/b"'


def test_xml_cdata_with_special_chars_is_escaped():
    """A CDATA section containing '<' is unwrapped to text with the character escaped."""
    assert mini("xml", "<a><![CDATA[x < y]]></a>") == "<a>x &lt; y</a>"


def test_xml_removes_comment_between_elements():
    """A comment between sibling elements is removed."""
    assert mini("xml", "<a/><!--c--><b/>") == "<a/><b/>"
