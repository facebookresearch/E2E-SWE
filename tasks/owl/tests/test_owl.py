"""End-to-end tests for the owl parser generator (WRG C task).

Every test targets one distinct behavioral contract. Interpreter-mode tests
shell out to the agent's ./owl and assert on the parse-tree text loosely
(label presence, not exact whitespace). Compile-mode tests emit a parser
header via `owl -c`, compile a small C driver against it with gcc, run the
driver, and assert on typed output.
"""

import os
import re

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_ws(s):
    """Collapse all whitespace runs to single spaces (for label-presence checks)."""
    return " ".join(s.split())


def has_label(stdout, label):
    """True if `label` appears in the whitespace-collapsed stdout."""
    return label in strip_ws(stdout)


# ---------------------------------------------------------------------------
# Cluster 1 — CLI + basic operation (4 tests)
# ---------------------------------------------------------------------------


def test_version_prints_owl_v4_to_stderr(run_owl):
    for flag in ("-V", "--version"):
        r = run_owl(flag)
        assert r.returncode == 0, f"{flag}: exit {r.returncode}, stderr={r.stderr!r}"
        # version goes to stderr, not stdout
        assert "owl.v4" in r.stderr, f"{flag}: stderr={r.stderr!r}"


def test_usage_errors_exit_nonzero(run_owl):
    # Missing grammar entirely.
    r = run_owl(stdin="")
    assert r.returncode != 0
    # Unknown option.
    r = run_owl("--this-flag-does-not-exist", stdin="")
    assert r.returncode != 0


def test_grammar_via_g_flag(run_owl):
    """-g / --grammar accepts inline grammar; parsing succeeds on matching input."""
    # Use a distinctive rule name that can't false-alarm on a random token.
    r = run_owl("-g", "myroot = 'x'", stdin="x\n")
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    # The rule name must appear as a whole-word label in the tree region.
    assert re.search(r"\bmyroot\b", r.stdout), r.stdout


def test_input_file_flag(run_owl, tmp_path, write_grammar):
    """-i / --input reads the input from a file instead of stdin."""
    gpath = write_grammar("#using owl.v4\na = identifier+\n")
    ipath = tmp_path / "in.txt"
    ipath.write_text("hello world\n")
    r = run_owl(gpath, "-i", str(ipath), stdin="")
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    assert has_label(r.stdout, "hello") and has_label(r.stdout, "world")


# ---------------------------------------------------------------------------
# Cluster 2 — Interpreter mode grammar features (15 tests)
# ---------------------------------------------------------------------------


def test_interpret_named_choice_labels(run_interpret):
    """Named-choice matches label the parse tree as `rule:choice`."""
    r = run_interpret(
        "#using owl.v4\n" "item =\n" "  identifier : ident\n" "  integer : num\n",
        "42\n",
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    assert has_label(r.stdout, "item:num"), r.stdout


def test_interpret_operator_precedence(run_interpret):
    """A two-group operator grammar emits exactly the labels its parse implies.

    Precedence *grouping* (that `*` binds tighter than `+`) is authoritatively
    verified in compile mode by `test_generated_operator_precedence_via_typed_tree`
    through the typed `.left`/`.right` tree; the interpreter's spatial tree layout
    is a non-pinned visual detail. Here we assert the spec-pinned label
    multiplicity instead of mere substring presence: each operator match yields
    exactly one operator label and each operand yields one `expr:lit`.
    """
    r = run_interpret(
        "#using owl.v4\n"
        "expr =\n"
        "   number : lit\n"
        " .operators infix left\n"
        "   '*' : mul\n"
        " .operators infix left\n"
        "   '+' : add\n",
        "1 + 2 * 3\n",
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    out = strip_ws(r.stdout)
    # Exactly one `+` match, one `*` match, and three number operands. A mere
    # `"expr:add" in out` check passes even on a mis-shaped parse; exact counts
    # catch a dropped/duplicated operator or operand label.
    assert out.count("expr:add") == 1, out
    assert out.count("expr:mul") == 1, out
    assert out.count("expr:lit") == 3, out


def test_interpret_prefix_operator(run_interpret):
    """A `.operators prefix` group renders as a single labeled prefix operator."""
    r = run_interpret(
        "#using owl.v4\n"
        "expr =\n"
        "   identifier : var\n"
        " .operators prefix\n"
        "   '-' : neg\n",
        "-a\n",
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    out = strip_ws(r.stdout)
    assert "expr:neg" in out and "expr:var" in out, out


def test_interpret_infix_flat(run_interpret):
    """`.operators infix flat` collapses `1+2+3+4` into a single flat operator."""
    r = run_interpret(
        "#using owl.v4\n"
        "expr =\n"
        "   number : lit\n"
        " .operators infix flat\n"
        "   '+' : sum\n",
        "1 + 2 + 3 + 4\n",
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    out = strip_ws(r.stdout)
    # A flat group produces ONE `expr:sum` label spanning all operands.
    assert out.count("expr:sum") == 1, f"expected 1 expr:sum, got {out!r}"
    # And there should be one `expr:lit` per operand.
    assert out.count("expr:lit") == 4, out


def test_interpret_guard_bracket_recursion(run_interpret):
    """Guard brackets `[ '{' … '}' ]` permit self-recursion of the rule."""
    r = run_interpret(
        "#using owl.v4\n"
        "value =\n"
        "  [ '{' 'k' value '}' ] : obj\n"
        "  number : num\n",
        "{k {k {k 5}}}\n",
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    out = strip_ws(r.stdout)
    # Three nested objects + innermost number.
    assert out.count("value:obj") == 3, out
    assert out.count("value:num") == 1, out


def test_interpret_repetition_range_bounds(run_interpret):
    """`a{3,5}` accepts exactly 3-5 copies and rejects boundaries."""
    grammar = "#using owl.v4\nlines = ('.' 'x'{3,5} '.')+\n"
    # accepting cases
    for count in (3, 4, 5):
        body = "x " * count
        r = run_interpret(grammar, f". {body}.\n")
        assert r.returncode == 0, f"count={count}: stderr={r.stderr!r}"
    # rejecting under
    r = run_interpret(grammar, ". x x .\n")
    assert r.returncode != 0
    # rejecting over
    r = run_interpret(grammar, ". x x x x x x .\n")
    assert r.returncode != 0


def test_interpret_delimiter_repetition(run_interpret):
    """`identifier{','}` matches a comma-delimited list; per `a{b}` =
    `(a (b a)*)?`, the `,` delimiter is required between elements."""
    grammar = "#using owl.v4\nlist = identifier{','}\n"
    r = run_interpret(grammar, "alpha,beta,gamma,delta\n")
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    # The `list` rule label must cover the match.
    assert re.search(r"\blist\b", r.stdout), r.stdout
    # Real delimiter signal (not satisfiable by the input-echo row): a comma-less
    # sequence must be rejected, proving the `,` delimiter is actually consumed
    # rather than the elements being matched as a bare `identifier+` list.
    r_nocomma = run_interpret(grammar, "alpha beta\n")
    assert (
        r_nocomma.returncode != 0
    ), f"comma-less input must be rejected (',' delimiter required); got exit {r_nocomma.returncode}"
    # A single element (no delimiter needed) still parses.
    r_single = run_interpret(grammar, "gamma\n")
    assert r_single.returncode == 0, f"single element stderr={r_single.stderr!r}"


def test_interpret_builtin_tokens(run_interpret):
    """Each of the four built-in tokens produces its own named-choice label
    when routed through a per-token choice rule."""
    grammar = (
        "#using owl.v4\n"
        "top = item+\n"
        "item =\n"
        "   identifier : ident\n"
        "   integer : num\n"
        "   number : flt\n"
        "   string : str\n"
    )
    # "3.14" is a number (not integer), "0xff" is an integer (0x prefix), and
    # the integer-preferred tiebreak means "42" also lands in the num choice.
    r = run_interpret(grammar, 'foo 42 3.14 "hi"\n')
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    out = strip_ws(r.stdout)
    # Each named-choice label must actually appear — not just the input echo.
    for lbl in ("item:ident", "item:num", "item:flt", "item:str"):
        assert lbl in out, f"missing {lbl} in: {out!r}"


def test_interpret_custom_whitespace_disables_newline(run_interpret):
    """`.whitespace ' '` overrides defaults; newline becomes a non-whitespace token."""
    grammar = "#using owl.v4\n.whitespace ' '\nline = identifier+\n"
    # Without a trailing newline it parses fine (input is one line).
    r_ok = run_interpret(grammar, "a b c")
    assert r_ok.returncode == 0, f"stderr={r_ok.stderr!r}"
    # With an embedded newline the tokenizer trips (\n is no longer whitespace).
    r_bad = run_interpret(grammar, "a b\nc\n")
    assert r_bad.returncode != 0


def test_interpret_line_comment_token(run_interpret):
    """`.line-comment-token '//'` skips text from `//` to end-of-line as whitespace."""
    grammar_with = "#using owl.v4\n.line-comment-token '//'\nprog = identifier+\n"
    grammar_no = "#using owl.v4\nprog = identifier+\n"
    r_with = run_interpret(grammar_with, "a // comment\nb\n")
    assert r_with.returncode == 0, f"with .line-comment-token: stderr={r_with.stderr!r}"
    r_no = run_interpret(grammar_no, "a // comment\nb\n")
    assert (
        r_no.returncode != 0
    ), f"without .line-comment-token, // must not be treated as whitespace"


def test_interpret_exclude_choice_at_reference(run_interpret):
    r"""`rule\:choice` at a reference site excludes that choice from matching there.

    Grammar's `item` has choices {ident, num}; `container = item\:num` narrows
    to only the `ident` choice. An input matching `num` (an integer) must fail
    to parse; an input matching `ident` (an identifier) must succeed.
    """
    grammar = (
        "#using owl.v4\n"
        "container = item\\:num\n"
        "item =\n"
        "   identifier : ident\n"
        "   integer : num\n"
    )
    r_ok = run_interpret(grammar, "foo\n")
    assert r_ok.returncode == 0, (
        f"identifier should parse (num excluded, ident allowed); "
        f"stderr={r_ok.stderr!r}"
    )
    # The chosen 'ident' label must appear in the tree.
    assert has_label(r_ok.stdout, "item:ident"), r_ok.stdout
    r_bad = run_interpret(grammar, "42\n")
    assert r_bad.returncode != 0, (
        f"integer should be rejected because container excludes the 'num' "
        f"choice via item\\:num, got returncode={r_bad.returncode}"
    )


def test_interpret_postfix_operator(run_interpret):
    """A `.operators postfix` group renders a single labelled postfix operator."""
    r = run_interpret(
        "#using owl.v4\n"
        "expr =\n"
        "   identifier : var\n"
        " .operators postfix\n"
        "   '++' : inc\n",
        "x ++\n",
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    out = strip_ws(r.stdout)
    assert "expr:inc" in out and "expr:var" in out, out


def test_interpret_infix_nonassoc_rejects_chain(run_interpret):
    """`.operators infix nonassoc` accepts `a == b` but rejects `a == b == c`."""
    grammar = (
        "#using owl.v4\n"
        "expr =\n"
        "   identifier : var\n"
        " .operators infix nonassoc\n"
        "   '==' : eq\n"
    )
    r_ok = run_interpret(grammar, "a == b\n")
    assert r_ok.returncode == 0, f"single-op stderr={r_ok.stderr!r}"
    assert "expr:eq" in strip_ws(r_ok.stdout), r_ok.stdout
    r_bad = run_interpret(grammar, "a == b == c\n")
    assert (
        r_bad.returncode != 0
    ), f"chaining `==` in a nonassoc group must fail; got {r_bad.returncode}"


def test_interpret_exact_repetition(run_interpret):
    """`a{n}` matches exactly `n` copies — accepts n, rejects n-1 and n+1.

    Distinct from `a{n,m}` (range) and `a{n+}` (n-or-more): exact `{n}`
    forbids both under- and over-counts.
    """
    grammar = "#using owl.v4\ntop = 'x'{3}\n"
    r_ok = run_interpret(grammar, "x x x\n")
    assert r_ok.returncode == 0, f"3 xs should parse; stderr={r_ok.stderr!r}"
    r_short = run_interpret(grammar, "x x\n")
    assert (
        r_short.returncode != 0
    ), f"2 xs should fail (need exactly 3); got exit {r_short.returncode}"
    r_long = run_interpret(grammar, "x x x x\n")
    assert (
        r_long.returncode != 0
    ), f"4 xs should fail (need exactly 3); got exit {r_long.returncode}"


# ---------------------------------------------------------------------------
# Cluster 3 — Error diagnostics (5 tests)
# ---------------------------------------------------------------------------


def test_ambiguous_grammar_exits_3(run_interpret):
    """A grammar with two valid parses for the same input exits with code 3."""
    r = run_interpret("#using owl.v4\na = 'a' b b 'c'\nb = 'x'+\n", "a x x x c\n")
    assert (
        r.returncode == 3
    ), f"expected exit 3 for ambiguity, got {r.returncode}; stderr={r.stderr!r}"
    assert "ambiguous" in r.stderr.lower(), r.stderr


def test_incompatible_version_exits_nonzero(run_interpret):
    """`#using owl.v99` (unknown/future version) is rejected."""
    r = run_interpret("#using owl.v99\na = 'x'\n", "x\n")
    assert r.returncode != 0


def test_reserved_c_keyword_rejected(run_interpret):
    """A rule/token named after a C reserved keyword (e.g. `struct`) is rejected."""
    r = run_interpret("#using owl.v4\nmyrule = struct\nstruct = identifier\n", "a\n")
    assert r.returncode != 0


def test_invalid_input_token_exits_nonzero(run_interpret):
    """Input that can't be tokenized causes a non-zero exit."""
    r = run_interpret("#using owl.v4\na = identifier+\n", "foo @@@ bar\n")
    assert r.returncode != 0


def test_more_input_needed_exits_nonzero(run_interpret):
    """Input that ends mid-parse causes a non-zero exit."""
    r = run_interpret("#using owl.v4\na = 'x' 'y'\n", "x\n")
    assert r.returncode != 0


# ---------------------------------------------------------------------------
# Cluster 4 — Compilation mode / generated header (17 tests)
# ---------------------------------------------------------------------------

# A calc-like grammar reused across several compile-mode tests.
CALC_GRAMMAR = (
    "#using owl.v4\n"
    "expr =\n"
    "   number : lit\n"
    " .operators infix left\n"
    "   '*' : mul\n"
    " .operators infix left\n"
    "   '+' : add\n"
)


def test_generated_header_declares_root_getter(compile_grammar):
    """`owl -c` emits a header naming the root-getter after the root rule."""
    hpath = compile_grammar("#using owl.v4\nprog = identifier+\n")
    src = open(hpath).read()
    assert "owl_tree_get_parsed_prog" in src, src[:400]
    # The header should be self-contained: no #include of other project files.
    for line in src.splitlines():
        if line.startswith("#include"):
            assert re.match(r"#include\s*<[^>]+>", line), (
                f"generated header should only #include <standard headers>, "
                f"got: {line!r}"
            )


def test_generated_identifier_and_string(compile_grammar, build_and_run):
    """parsed_identifier and parsed_string expose content + length with quotes stripped."""
    hpath = compile_grammar("#using owl.v4\ntop = identifier string\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_top top = owl_tree_get_parsed_top(t);
    struct parsed_identifier id = parsed_identifier_get(top.identifier);
    struct parsed_string s = parsed_string_get(top.string);
    printf("id_len=%zu id=%.*s\n", id.length, (int)id.length, id.identifier);
    printf("s_len=%zu s=%.*s\n", s.length, (int)s.length, s.string);
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=['hello "world"'])
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert "id_len=5" in lines[0] and "id=hello" in lines[0], r.stdout
    assert "s_len=5" in lines[1] and "s=world" in lines[1], r.stdout


def test_generated_integer_and_number(compile_grammar, build_and_run):
    """parsed_integer parses decimal + 0x-hex; parsed_number parses floating point."""
    hpath = compile_grammar("#using owl.v4\ntop = integer integer number\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_top top = owl_tree_get_parsed_top(t);
    /* Two integer refs (first + second) — walk owl_next off .integer for the second. */
    struct parsed_integer i1 = parsed_integer_get(top.integer);
    struct owl_ref r2 = owl_next(top.integer);
    struct parsed_integer i2 = parsed_integer_get(r2);
    struct parsed_number n = parsed_number_get(top.number);
    printf("i1=%llu i2=%llu n=%.3f\n",
           (unsigned long long)i1.integer,
           (unsigned long long)i2.integer,
           n.number);
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=["42 0xff 3.14"])
    assert r.returncode == 0, r.stderr
    assert (
        "i1=42" in r.stdout and "i2=255" in r.stdout and "n=3.140" in r.stdout
    ), r.stdout


def test_generated_named_choice_type_enum(compile_grammar, build_and_run):
    """Named choices produce a `type` field valued by a per-choice enumerator."""
    hpath = compile_grammar(
        "#using owl.v4\n" "item =\n" "  identifier : ident\n" "  integer : num\n"
    )
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_item it = owl_tree_get_parsed_item(t);
    /* Both enumerators must be distinct positive values (0 is reserved). */
    if (PARSED_IDENT == 0 || PARSED_NUM == 0 || PARSED_IDENT == PARSED_NUM) {
        puts("BAD_ENUM"); return 3;
    }
    printf("type=%s\n", it.type == PARSED_IDENT ? "IDENT"
                      : it.type == PARSED_NUM  ? "NUM" : "OTHER");
    return 0;
}
"""
    r1 = build_and_run(driver, hpath, argv=["foo"])
    assert r1.returncode == 0, r1.stderr
    assert r1.stdout.strip() == "type=IDENT", r1.stdout
    r2 = build_and_run(driver, hpath, argv=["42"], driver_name="drv_enum2")
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip() == "type=NUM", r2.stdout


def test_generated_list_iteration_owl_next(compile_grammar, build_and_run):
    """A `rule (',' rule)*` list is walkable with `owl_next` until `.empty`."""
    hpath = compile_grammar(
        "#using owl.v4\nlist = item (',' item)*\nitem = identifier\n"
    )
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_list lst = owl_tree_get_parsed_list(t);
    int n = 0;
    for (struct owl_ref r = lst.item; !r.empty; r = owl_next(r)) {
        struct parsed_item it = parsed_item_get(r);
        struct parsed_identifier id = parsed_identifier_get(it.identifier);
        printf("[%d] %.*s\n", n, (int)id.length, id.identifier);
        n++;
    }
    printf("count=%d\n", n);
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=["foo,bar,baz,qux"])
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert "[0] foo" in lines[0], r.stdout
    assert "[1] bar" in lines[1], r.stdout
    assert "[2] baz" in lines[2], r.stdout
    assert "[3] qux" in lines[3], r.stdout
    assert lines[-1] == "count=4", r.stdout


def test_generated_bracketed_rule_nesting(compile_grammar, build_and_run):
    """Guard brackets produce a recursive parse structure the caller can traverse."""
    hpath = compile_grammar(
        "#using owl.v4\n"
        "value =\n"
        "  [ '{' 'k' value '}' ] : obj\n"
        "  integer : num\n"
    )
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
static int depth(struct owl_ref r) {
    struct parsed_value v = parsed_value_get(r);
    if (v.type == PARSED_NUM) {
        struct parsed_integer i = parsed_integer_get(v.integer);
        return (int)i.integer;
    }
    return 1 + depth(v.value);
}
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct owl_ref root = owl_tree_root_ref(t);
    printf("depth+inner=%d\n", depth(root));
    return 0;
}
"""
    # inner integer is 7, nesting is 3 → depth returns 3 + 7 = 10.
    r = build_and_run(driver, hpath, argv=["{k {k {k 7}}}"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "depth+inner=10", r.stdout


def test_generated_get_error_returns_range(compile_grammar, build_and_run):
    """Invalid input produces an error tree; `owl_tree_get_error` reports it + a range."""
    hpath = compile_grammar("#using owl.v4\na = identifier+\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    struct source_range r = {0, 0};
    enum owl_error err = owl_tree_get_error(t, &r);
    printf("err=%d start=%zu end=%zu\n", (int)err, r.start, r.end);
    return err == ERROR_NONE ? 1 : 0;
}
"""
    # `@@@` is unrecognizable — should give ERROR_INVALID_TOKEN with a range
    # that starts at the `@` position (offset 4 in "foo @@@ bar").
    r = build_and_run(driver, hpath, argv=["foo @@@ bar"])
    assert r.returncode == 0, f"expected an error tree, got: {r.stdout!r}, {r.stderr!r}"
    m = re.search(r"err=(\d+) start=(\d+) end=(\d+)", r.stdout)
    assert m, r.stdout
    err, start, end = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # Error must not be ERROR_NONE (which is 0).
    assert err != 0, f"expected non-zero owl_error, got 0"
    # Range must be non-empty and located at or after the '@' position (offset 4).
    # Upper bound: `@@@` is 3 chars; the reported range should target the
    # invalid-token span, not a whole-file wildcard. Cap length <= 3 and start
    # < 7 (must be inside the `foo @@@ bar` span, not at end).
    assert (
        end > start >= 4
    ), f"range start={start} end={end} — not at/after '@' position"
    assert (
        end - start <= 3
    ), f"range span {end - start} bytes too wide for a 3-char '@@@'"
    assert start < 7, f"range start={start} beyond the '@@@' region"


def test_generated_operator_precedence_via_typed_tree(compile_grammar, build_and_run):
    """A generated parser correctly encodes operator precedence in the typed tree."""
    hpath = compile_grammar(CALC_GRAMMAR)
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
static double eval(struct owl_ref r) {
    struct parsed_expr e = parsed_expr_get(r);
    switch (e.type) {
    case PARSED_LIT: return parsed_number_get(e.number).number;
    case PARSED_ADD: return eval(e.left) + eval(e.right);
    case PARSED_MUL: return eval(e.left) * eval(e.right);
    default: return 0;
    }
}
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    printf("%.6g\n", eval(owl_tree_root_ref(t)));
    return 0;
}
"""
    # 1 + 2 * 3 = 7 iff * binds tighter than +. If wrong, would be (1+2)*3 = 9.
    r = build_and_run(driver, hpath, argv=["1 + 2 * 3"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "7", r.stdout
    # 2 * 3 + 4 = 10, not 2 * (3+4) = 14.
    r2 = build_and_run(driver, hpath, argv=["2 * 3 + 4"], driver_name="drv_prec2")
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip() == "10", r2.stdout


def test_generated_infix_right_associative(compile_grammar, build_and_run):
    """`.operators infix right` builds a right-associative typed tree: `2^3^2`
    groups as `2^(3^2)` (= 512), not `(2^3)^2` (= 64).

    Node-counting in interpreter mode cannot distinguish the two groupings
    (both yield two operator matches); evaluating the typed `.left`/`.right`
    tree does, so associativity is checked here through the public API.
    """
    hpath = compile_grammar(
        "#using owl.v4\n"
        "expr =\n"
        "   integer : lit\n"
        " .operators infix right\n"
        "   '^' : pow\n"
    )
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
static long eval(struct owl_ref r) {
    struct parsed_expr e = parsed_expr_get(r);
    switch (e.type) {
    case PARSED_LIT: return (long)parsed_integer_get(e.integer).integer;
    case PARSED_POW: {
        long base = eval(e.left), exp = eval(e.right), acc = 1;
        for (long i = 0; i < exp; i++) acc *= base;
        return acc;
    }
    default: return -1;
    }
}
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    printf("%ld\n", eval(owl_tree_root_ref(t)));
    return 0;
}
"""
    # Right-assoc: 2^(3^2) = 2^9 = 512. A left-assoc tree would give (2^3)^2 = 64.
    r = build_and_run(driver, hpath, argv=["2 ^ 3 ^ 2"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "512", r.stdout


def test_generated_prefix_rename(compile_grammar, build_and_run):
    """`-p asdf` renames owl_/parsed_/OWL_ to asdf_/asdf_/ASDF_ in the emitted
    header AND the renamed header must actually compile against a driver that
    uses the renamed names — no owl_* leaks that break the build."""
    hpath = compile_grammar(
        "#using owl.v4\ntop = identifier+\n",
        extra_args=("-p", "asdf"),
        header_name="asdf.h",
    )
    driver = r"""
#define ASDF_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct asdf_tree *t = asdf_tree_create_from_string(argv[1]);
    if (asdf_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct asdf_top top = asdf_tree_get_asdf_top(t);
    int n = 0;
    for (struct asdf_ref r = top.identifier; !r.empty; r = asdf_next(r)) {
        struct asdf_identifier id = asdf_identifier_get(r);
        printf("[%d] %.*s\n", n, (int)id.length, id.identifier);
        n++;
    }
    printf("count=%d\n", n);
    asdf_tree_destroy(t);
    return 0;
}
"""
    # If any `owl_*` / `parsed_*` name leaks (or the rename mis-handles
    # substrings), gcc will fail on unknown identifiers. This is a stronger
    # check than a text-grep because it catches partial-rename bugs like
    # `asdf_tree_options` still referring to a nested `owl_token_func_t`.
    r = build_and_run(driver, hpath, argv=["alpha beta gamma"])
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "[0] alpha", r.stdout
    assert lines[1] == "[1] beta", r.stdout
    assert lines[2] == "[2] gamma", r.stdout
    assert lines[-1] == "count=3", r.stdout


def test_generated_at_rename_distinguishes_fields(compile_grammar, build_and_run):
    """`expr@array`/`expr@index`/`expr@value` produce three distinct renamed refs."""
    hpath = compile_grammar(
        "#using owl.v4\n"
        "setidx = expr@array '[' expr@index ']' '=' expr@value\n"
        "expr =\n"
        "  identifier : var\n"
    )
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
static void print_var(struct owl_ref r, const char *label) {
    struct parsed_expr e = parsed_expr_get(r);
    struct parsed_identifier id = parsed_identifier_get(e.identifier);
    printf("%s=%.*s\n", label, (int)id.length, id.identifier);
}
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_setidx s = owl_tree_get_parsed_setidx(t);
    print_var(s.array, "array");
    print_var(s.index, "index");
    print_var(s.value, "value");
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=["foo[bar]=baz"])
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    # Each @rename must land in the correspondingly-named struct field, and the
    # three renames must resolve to three DIFFERENT input positions (foo/bar/baz).
    assert lines[0] == "array=foo", r.stdout
    assert lines[1] == "index=bar", r.stdout
    assert lines[2] == "value=baz", r.stdout


def test_generated_token_callback(compile_grammar, build_and_run):
    """`.token digit` wires a user-defined-token callback via owl_tree_options.tokenize.

    Exercises the OWL_TOKEN_<NAME> enum, the owl_token_func_t callback signature,
    owl_tree_options.tokenize/.tokenize_info fields, and the parsed_<NAME>.data
    union (with .integer being what the callback stashes).
    """
    hpath = compile_grammar("#using owl.v4\n" ".token digit '3' '7'\n" "top = digit+\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
static struct owl_token tok(const char *s, void *info) {
    (void)info;
    if (s[0] >= '0' && s[0] <= '9') {
        struct owl_token t = {0};
        t.type = OWL_TOKEN_DIGIT;
        t.length = 1;
        t.data.integer = (uint64_t)(s[0] - '0');
        return t;
    }
    return owl_token_no_match;
}
int main(int argc, char **argv) {
    struct owl_tree_options opts = {0};
    opts.string = argv[1];
    opts.tokenize = tok;
    struct owl_tree *t = owl_tree_create_with_options(opts);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_top top = owl_tree_get_parsed_top(t);
    int n = 0, sum = 0;
    for (struct owl_ref r = top.digit; !r.empty; r = owl_next(r)) {
        struct parsed_digit d = parsed_digit_get(r);
        sum += (int)d.data.integer;
        n++;
    }
    printf("n=%d sum=%d\n", n, sum);
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=["12345"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "n=5 sum=15", r.stdout
    # Second input: 9 digits summing to 36 (with whitespace ignored by default).
    r2 = build_and_run(driver, hpath, argv=["9   9 9  9"], driver_name="drv_tok2")
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip() == "n=4 sum=36", r2.stdout


def test_generated_create_from_file(compile_grammar, build_and_run):
    """`owl_tree_create_from_file(FILE *)` reads the input via a stdio FILE
    pointer (distinct API from create_from_string)."""
    hpath = compile_grammar("#using owl.v4\ntop = identifier+\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    FILE *fp = tmpfile();
    if (!fp) { puts("TMPFILE_FAILED"); return 3; }
    fwrite(argv[1], 1, strlen(argv[1]), fp);
    rewind(fp);
    struct owl_tree *t = owl_tree_create_from_file(fp);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); fclose(fp); return 2; }
    struct parsed_top top = owl_tree_get_parsed_top(t);
    int n = 0;
    for (struct owl_ref r = top.identifier; !r.empty; r = owl_next(r)) n++;
    printf("count=%d\n", n);
    owl_tree_destroy(t);
    fclose(fp);
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=["foo bar baz qux"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "count=4", r.stdout


def test_generated_owl_tree_print(compile_grammar, build_and_run):
    """`owl_tree_print(tree)` writes a visual parse-tree representation to
    stdout — the same rule/choice labels the interpreter emits must appear."""
    hpath = compile_grammar(
        "#using owl.v4\n" "item =\n" "   identifier : ident\n" "   integer : num\n"
    )
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    owl_tree_print(t);
    fflush(stdout);
    owl_tree_destroy(t);
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=["hello"])
    assert r.returncode == 0, r.stderr
    # `owl_tree_print` must render something — at minimum the item:ident label
    # (or an unambiguous derivative that names both the rule and the choice).
    out = r.stdout
    assert (
        "item" in out and "ident" in out
    ), f"owl_tree_print output missing rule/choice labels: {out!r}"


def test_generated_owl_refs_equal(compile_grammar, build_and_run):
    """`owl_refs_equal(a, b)` returns true for two refs to the same match and
    false for refs to distinct siblings."""
    hpath = compile_grammar(
        "#using owl.v4\nlist = item (',' item)*\nitem = identifier\n"
    )
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_list lst = owl_tree_get_parsed_list(t);
    struct owl_ref r1 = lst.item;
    struct owl_ref r2 = owl_next(r1);
    /* r1 == r1 -> true; r1 == r2 -> false */
    printf("self=%d sibling=%d\n",
           owl_refs_equal(r1, r1) ? 1 : 0,
           owl_refs_equal(r1, r2) ? 1 : 0);
    owl_tree_destroy(t);
    return 0;
}
"""
    r = build_and_run(driver, hpath, argv=["alpha,beta"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "self=1 sibling=0", r.stdout


def test_generated_error_invalid_options(compile_grammar, build_and_run):
    """`owl_tree_create_with_options({0})` (neither string nor file set) is
    an invalid-options failure: the returned tree is an error tree whose
    `owl_tree_get_error` returns `ERROR_INVALID_OPTIONS`."""
    hpath = compile_grammar("#using owl.v4\ntop = identifier+\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(void) {
    struct owl_tree_options opts = {0};   /* neither .string nor .file */
    struct owl_tree *t = owl_tree_create_with_options(opts);
    enum owl_error err = owl_tree_get_error(t, NULL);
    printf("err=%d invalid_options=%d\n", (int)err, (int)ERROR_INVALID_OPTIONS);
    return err == ERROR_INVALID_OPTIONS ? 0 : 1;
}
"""
    r = build_and_run(driver, hpath, argv=[])
    assert r.returncode == 0, (
        f"expected ERROR_INVALID_OPTIONS from empty options struct; "
        f"got exit={r.returncode}, stdout={r.stdout!r}, stderr={r.stderr!r}"
    )


def test_generated_string_escape_sequences(compile_grammar, build_and_run):
    """parsed_string decodes standard escape sequences (\\n, \\t, quotes stripped)
    and .length is the *decoded* byte count, not the source-token length."""
    hpath = compile_grammar("#using owl.v4\ntop = string\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    if (owl_tree_get_error(t, NULL) != ERROR_NONE) { puts("PARSE_ERROR"); return 2; }
    struct parsed_top top = owl_tree_get_parsed_top(t);
    struct parsed_string s = parsed_string_get(top.string);
    printf("len=%zu\n", s.length);
    /* Print byte codes so exact decoded content can be checked without
       worrying about how newline/tab render in printf output. */
    for (size_t i = 0; i < s.length; i++) {
        printf("b%zu=%d\n", i, (int)(unsigned char)s.string[i]);
    }
    return 0;
}
"""
    # Source input is a quoted string containing 5 escape-decoded bytes:
    #   a  \n  b  \t  c  → 'a' 0x0a 'b' 0x09 'c'
    # Quotes are stripped; escapes decode; .length == 5.
    r = build_and_run(driver, hpath, argv=[r'"a\nb\tc"'])
    assert r.returncode == 0, f"driver failed: {r.stderr!r}"
    lines = r.stdout.splitlines()
    assert lines[0] == "len=5", f"expected len=5, got: {lines[0]!r}"
    # Byte-by-byte decoded content.
    expected_bytes = [ord("a"), 0x0A, ord("b"), 0x09, ord("c")]
    for i, want in enumerate(expected_bytes):
        assert f"b{i}={want}" in lines[1 + i], (
            f"byte {i}: expected {want}, got line {lines[1 + i]!r} "
            f"(all decoded bytes: {lines[1:]})"
        )


def test_generated_get_error_more_input_needed(compile_grammar, build_and_run):
    """Truncated input (parse cannot complete because the tokens ran out
    mid-rule) produces ERROR_MORE_INPUT_NEEDED — a distinct enumerator
    from ERROR_INVALID_TOKEN / ERROR_UNEXPECTED_TOKEN."""
    hpath = compile_grammar("#using owl.v4\ntop = 'begin' identifier 'end'\n")
    driver = r"""
#define OWL_PARSER_IMPLEMENTATION
#include "parser.h"
#include <stdio.h>
int main(int argc, char **argv) {
    struct owl_tree *t = owl_tree_create_from_string(argv[1]);
    enum owl_error err = owl_tree_get_error(t, NULL);
    printf("err=%d more_input_needed=%d\n",
           (int)err, (int)ERROR_MORE_INPUT_NEEDED);
    return err == ERROR_MORE_INPUT_NEEDED ? 0 : 1;
}
"""
    # Input "begin foo" is missing the required trailing 'end' keyword,
    # so the parse ends mid-rule → ERROR_MORE_INPUT_NEEDED.
    r = build_and_run(driver, hpath, argv=["begin foo"])
    assert r.returncode == 0, (
        f"expected ERROR_MORE_INPUT_NEEDED on truncated input; "
        f"got exit={r.returncode}, stdout={r.stdout!r}, stderr={r.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Cluster 5 — Determinism (2 tests)
# ---------------------------------------------------------------------------


def test_interpret_reproducibility(owl_bin, write_grammar, tmp_path):
    """Interpreter mode: identical (grammar, input, flags) MUST produce
    identical stdout AND identical stderr on every run. Failure modes to
    catch: hash-order-dependent traversal, timestamp / PID in output,
    random names."""
    import subprocess as _sp

    grammar = (
        "#using owl.v4\n"
        "program = stmt*\n"
        "stmt =\n"
        "    'print' expr : print\n"
        "    identifier '=' expr : assign\n"
        "expr =\n"
        "    identifier : variable\n"
        "    number : literal\n"
        "  .operators infix left\n"
        "    '+' : plus\n"
        "    '-' : minus\n"
    )
    gpath = write_grammar(grammar)
    stdin = "x = 1 + 2\nprint x\n"

    r1 = _sp.run(
        [owl_bin, gpath], input=stdin, capture_output=True, text=True, timeout=15
    )
    r2 = _sp.run(
        [owl_bin, gpath], input=stdin, capture_output=True, text=True, timeout=15
    )
    assert r1.returncode == 0, f"run1 stderr={r1.stderr!r}"
    assert r2.returncode == 0, f"run2 stderr={r2.stderr!r}"
    assert r1.stdout == r2.stdout, (
        f"interpreter stdout differs between two identical runs\n"
        f"--- run1 ---\n{r1.stdout!r}\n--- run2 ---\n{r2.stdout!r}"
    )
    assert r1.stderr == r2.stderr, (
        f"interpreter stderr differs between two identical runs\n"
        f"--- run1 ---\n{r1.stderr!r}\n--- run2 ---\n{r2.stderr!r}"
    )


def test_compile_reproducibility(owl_bin, write_grammar, tmp_path):
    """Compilation mode: `owl -c grammar.owl -o parser.h` invoked twice on the
    same grammar MUST produce byte-for-byte identical headers. Failure modes
    to catch: hash-order-dependent enum order, timestamps or build-metadata
    baked in, random name generation, unstable state-machine numbering."""
    import filecmp
    import subprocess as _sp

    grammar = (
        "#using owl.v4\n"
        "program = stmt*\n"
        "stmt =\n"
        "    'print' expr : print\n"
        "    identifier '=' expr : assign\n"
        "expr =\n"
        "    identifier : variable\n"
        "    number : literal\n"
        "  .operators infix left\n"
        "    '+' : plus\n"
        "    '-' : minus\n"
    )
    gpath = write_grammar(grammar)
    h1 = str(tmp_path / "parser1.h")
    h2 = str(tmp_path / "parser2.h")

    r1 = _sp.run(
        [owl_bin, "-c", gpath, "-o", h1], capture_output=True, text=True, timeout=30
    )
    assert r1.returncode == 0, f"first -c exited {r1.returncode}; stderr={r1.stderr}"
    r2 = _sp.run(
        [owl_bin, "-c", gpath, "-o", h2], capture_output=True, text=True, timeout=30
    )
    assert r2.returncode == 0, f"second -c exited {r2.returncode}; stderr={r2.stderr}"

    assert os.path.exists(h1) and os.path.exists(h2), "both headers should exist"
    assert filecmp.cmp(h1, h2, shallow=False), (
        "generated header differs between two identical `owl -c` invocations "
        f"(sizes {os.path.getsize(h1)} vs {os.path.getsize(h2)}). "
        "Compilation mode must be deterministic."
    )
