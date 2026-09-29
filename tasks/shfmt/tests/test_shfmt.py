"""Hidden grading suite for the shfmt task.

Drives the compiled shfmt CLI (built by setup.sh at /app/shfmt) entirely through subprocess —
program/args + stdin in, stdout/stderr/exit-code out. Each test models a realistic usage scenario
and asserts a distinct behavioral contract with EXACT expected values (no shape-only checks), so the
pass fraction tracks real implementation completeness.

Set BIN_ENV to point at the binary (defaults to /app/shfmt, the grading location). Use a local GT
build for iteration: BIN_ENV=/tmp/shfmt-gt pytest tests/test_shfmt.py -q

Fairness: parse-error tests assert exit code + the `<stdin>:line:col` position prefix and empty
stdout, NOT the exact diagnostic wording (which is parser-specific). Everything else is fully
determined by the documented formatting contract in instruction.md.
"""

import os
import subprocess

BIN = os.environ.get("BIN_ENV", "/app/shfmt")


def run(argv, stdin="", env=None):
    """Run the binary with argv (list); return (stdout, stderr, returncode)."""
    proc = subprocess.run(
        [BIN, *argv], input=stdin, capture_output=True, text=True, env=env, timeout=20
    )
    return proc.stdout, proc.stderr, proc.returncode


def out(argv, stdin="", env=None):
    """Run expecting success; assert exit 0 and return stdout."""
    so, se, rc = run(argv, stdin=stdin, env=env)
    assert rc == 0, f"expected success, got rc={rc}, stderr={se!r}"
    return so


# ----------------------------------------------------------------------------------------
# Canonical formatting (default: tabs, stdin -> stdout)
# ----------------------------------------------------------------------------------------


def test_operator_and_keyword_spacing():
    """Tokens get canonical single-space separation; keywords stay on one line with `; `."""
    assert (
        out([], stdin='if [ "$x" = 1 ];then echo hi;fi\n')
        == 'if [ "$x" = 1 ]; then echo hi; fi\n'
    )


def test_simple_commands_split_to_lines():
    """`;`-separated *simple* commands become separate lines."""
    assert out([], stdin="a; b; c\n") == "a\nb\nc\n"


def test_nested_blocks_use_tabs():
    """Nested compound statements are indented one tab per level."""
    src = "if true; then\necho a\nfor x in 1 2; do\necho $x\ndone\nfi\n"
    assert out([], stdin=src) == (
        "if true; then\n\techo a\n\tfor x in 1 2; do\n\t\techo $x\n\tdone\nfi\n"
    )


def test_collapse_consecutive_blank_lines():
    """Runs of blank lines collapse to a single blank line."""
    assert out([], stdin="a\n\n\n\nb\n") == "a\n\nb\n"


def test_leading_blank_lines_removed():
    """Leading blank lines are stripped."""
    assert out([], stdin="\n\necho hi\n") == "echo hi\n"


def test_trailing_semicolon_removed():
    """A trailing `;` after a simple command is dropped."""
    assert out([], stdin="echo hi;\n") == "echo hi\n"


def test_inline_comments_aligned():
    """Inline comments in a contiguous block are aligned to a common column."""
    assert out([], stdin="x=1    # c\nyy=2   # c\n") == "x=1  # c\nyy=2 # c\n"


def test_trailing_newline_added():
    """Output always ends with exactly one newline even if input lacks it."""
    assert out([], stdin="echo hi") == "echo hi\n"


def test_empty_input_yields_single_newline():
    """Empty input formats to a single newline."""
    so, se, rc = run([], stdin="")
    assert rc == 0 and so == "\n"


def test_idempotent_formatting():
    """Re-formatting already-formatted output is a no-op."""
    once = out([], stdin="if  true;then echo  hi;fi\n")
    assert once == "if true; then echo hi; fi\n"
    assert out([], stdin=once) == once


def test_heredoc_body_preserved():
    """Heredoc bodies are copied verbatim (internal whitespace untouched)."""
    src = "cat <<EOF\nhello   world\n  indented\nEOF\n"
    assert out([], stdin=src) == src


def test_long_line_not_wrapped():
    """shfmt never hard-wraps long lines."""
    line = "echo " + "a" * 80 + "\n"
    assert out([], stdin=line) == line


def test_pipeline_operator_stays_at_eol_by_default():
    """Multiline binary operators stay at end-of-line by default, continuations indented."""
    src = "foo |\nbar &&\nbaz\n"
    assert out([], stdin=src) == "foo |\n\tbar &&\n\tbaz\n"


def test_for_loop_one_line():
    """A one-line for-loop collapses extra spacing in its word list to single spaces."""
    assert (
        out([], stdin="for i in a   b   c;do echo $i;done\n")
        == "for i in a b c; do echo $i; done\n"
    )


def test_while_loop_one_line():
    """A one-line while-loop keeps `; do`/`; done` keyword spacing on a single line."""
    assert (
        out([], stdin="while true;do echo x;done\n") == "while true; do echo x; done\n"
    )


def test_case_default_not_indented():
    """Without -ci, case patterns sit at the same column as `case`; `;;` gets a leading space."""
    src = "case $x in\na) echo a;;\nb) echo b;;\nesac\n"
    assert out([], stdin=src) == "case $x in\na) echo a ;;\nb) echo b ;;\nesac\n"


def test_subshell_inner_spaces_removed():
    assert out([], stdin="( echo a )\n") == "(echo a)\n"


def test_brace_group_preserved():
    assert out([], stdin="{ echo b; }\n") == "{ echo b; }\n"


def test_arithmetic_command_spacing():
    assert out([], stdin="((x=1+2))\n") == "((x = 1 + 2))\n"


def test_redirect_no_space_by_default():
    assert out([], stdin="echo hi >file\n") == "echo hi >file\n"


def test_here_string_preserved():
    assert out([], stdin='cat <<<"hello"\n') == 'cat <<<"hello"\n'


def test_background_ampersand_preserved():
    assert out([], stdin="sleep 1 &\nwait\n") == "sleep 1 &\nwait\n"


def test_param_expansion_preserved():
    assert out([], stdin="echo ${x:-default}\n") == "echo ${x:-default}\n"


def test_single_quotes_preserved():
    assert out([], stdin="echo 'a  b'\n") == "echo 'a  b'\n"


def test_escaped_newline_continuation_indented():
    assert out([], stdin="echo a \\\n  b\n") == "echo a \\\n\tb\n"


def test_comment_only_line_preserved():
    assert out([], stdin="# just a comment\n") == "# just a comment\n"


# ----------------------------------------------------------------------------------------
# Indentation (-i)
# ----------------------------------------------------------------------------------------


def test_indent_two_spaces():
    assert (
        out(["-i", "2"], stdin="if true; then\necho a\nfi\n")
        == "if true; then\n  echo a\nfi\n"
    )


def test_indent_zero_means_tabs():
    assert (
        out(["-i", "0"], stdin="if true; then\necho a\nfi\n")
        == "if true; then\n\techo a\nfi\n"
    )


# ----------------------------------------------------------------------------------------
# Printer flags
# ----------------------------------------------------------------------------------------


def test_binary_next_line_flag():
    """-bn moves binary operators to the start of the continuation line with `\\`."""
    src = "foo |\nbar &&\nbaz\n"
    assert out(["-bn"], stdin=src) == "foo \\\n\t| bar \\\n\t&& baz\n"


def test_case_indent_flag():
    """-ci indents case patterns one level under `case`."""
    src = "case $x in\n a) echo a ;;\nesac\n"
    assert out(["-ci"], stdin=src) == "case $x in\n\ta) echo a ;;\nesac\n"


def test_space_redirects_flag():
    """-sr puts a space after redirect operators."""
    src = "a >f\nb >>g\nc 2>e\nd <in\n"
    assert out(["-sr"], stdin=src) == "a > f\nb >> g\nc 2> e\nd < in\n"


def test_func_next_line_flag():
    """-fn places the function's opening brace on its own line."""
    src = "fn() {\necho hi\n}\n"
    assert out(["-fn"], stdin=src) == "fn()\n{\n\techo hi\n}\n"


def test_keep_padding_flag():
    """-kp keeps the original column padding instead of re-aligning."""
    src = "x=1    # c\nyy=2   # c\n"
    assert out(["-kp"], stdin=src) == src


def test_combined_indent_and_case_indent():
    """Flags compose: -i 2 -ci gives 2-space-indented case patterns."""
    src = "case $x in\na) echo a;;\nesac\n"
    assert out(["-i", "2", "-ci"], stdin=src) == "case $x in\n  a) echo a ;;\nesac\n"


# ----------------------------------------------------------------------------------------
# Minify (-mn)
# ----------------------------------------------------------------------------------------


def test_minify_strips_indentation_and_comments():
    src = "if true; then\n  echo hello world\nfi\n# comment\n"
    assert out(["-mn"], stdin=src) == "if true;then\necho hello world\nfi\n"


def test_minify_implies_simplify():
    assert out(["-mn"], stdin='[[ "$x" == y ]]\n') == "[[ $x == y ]]\n"


# ----------------------------------------------------------------------------------------
# Simplify (-s)
# ----------------------------------------------------------------------------------------


def test_simplify_arithmetic_dollars_and_parens():
    assert out(["-s"], stdin="echo $((  $a + $b ))\n") == "echo $((a + b))\n"
    assert out(["-s"], stdin="echo $(( (a) ))\n") == "echo $((a))\n"


def test_simplify_redundant_test_quotes():
    assert out(["-s"], stdin='[[ "$x" == y ]]\n') == "[[ $x == y ]]\n"


def test_simplify_negation_merge():
    assert out(["-s"], stdin="[[ ! -n $x ]]\n") == "[[ -z $x ]]\n"
    assert out(["-s"], stdin="[[ ! -z $x ]]\n") == "[[ -n $x ]]\n"


def test_simplify_single_quotes_for_literals():
    assert out(["-s"], stdin='echo "\\$foo"\n') == "echo '$foo'\n"


def test_simplify_keeps_glob_rhs_quotes():
    """Quotes on a == RHS that would change globbing are NOT removed."""
    assert out(["-s"], stdin='[[ $x == "a*" ]]\n') == '[[ $x == "a*" ]]\n'


def test_simplify_not_applied_without_flag():
    assert out([], stdin='[[ "$x" == y ]]\n') == '[[ "$x" == y ]]\n'


# ----------------------------------------------------------------------------------------
# Language dialects (-ln)
# ----------------------------------------------------------------------------------------


def _posix_reject(src):
    so, se, rc = run(["-ln", "posix"], stdin=src)
    assert rc == 1 and so == "" and se.startswith("<standard input>:")


def test_posix_rejects_arrays():
    _posix_reject("a=(1 2)\n")


def test_posix_rejects_process_substitution():
    _posix_reject("cat <(echo hi)\n")


def test_posix_rejects_slicing():
    _posix_reject("echo ${x:0:2}\n")


def test_posix_rejects_function_keyword():
    _posix_reject("function f { echo hi; }\n")


def test_posix_accepts_plain_script():
    assert out(["-ln", "posix"], stdin="echo hi\n") == "echo hi\n"


def test_bash_dialect_accepts_arrays():
    assert out(["-ln", "bash"], stdin="a=(1   2   3)\n") == "a=(1 2 3)\n"


def test_mksh_dialect_accepts_coprocess():
    """mksh accepts a coprocess (`cmd |&`); bash and posix reject a bare `|&`."""
    assert out(["-ln", "mksh"], stdin="foo |&\n") == "foo |&\n"


def test_default_dialect_accepts_bashisms():
    """Default (auto) dialect formats bash-only syntax without error."""
    assert out([], stdin="a=(1   2)\n") == "a=(1 2)\n"


# ----------------------------------------------------------------------------------------
# Parse errors (assert exit code + position prefix + empty stdout; NOT exact wording)
# ----------------------------------------------------------------------------------------


def test_incomplete_compound_is_error():
    so, se, rc = run([], stdin="if true; then\n")
    assert rc == 1 and so == "" and se.startswith("<standard input>:")


def test_unbalanced_paren_is_error():
    so, se, rc = run([], stdin="echo (\n")
    assert rc == 1 and so == "" and se.startswith("<standard input>:")


def test_error_does_not_emit_partial_output():
    so, se, rc = run([], stdin="echo ok\nfor\n")
    assert rc == 1 and so == "" and se.startswith("<standard input>:")


# ----------------------------------------------------------------------------------------
# File arguments & CLI utilities
# ----------------------------------------------------------------------------------------


def test_file_argument_formats_to_stdout(tmp_path):
    p = tmp_path / "s.sh"
    p.write_text("echo  hi\n")
    assert out([str(p)]) == "echo hi\n"
    # without -w the file on disk is left unchanged
    assert p.read_text() == "echo  hi\n"


def test_list_flag_reports_unformatted_file(tmp_path):
    p = tmp_path / "bad.sh"
    p.write_text("echo  hi\n")
    so, se, rc = run(["-l", str(p)])
    assert rc == 1 and so == f"{p}\n"


def test_list_flag_silent_on_formatted_file(tmp_path):
    p = tmp_path / "good.sh"
    p.write_text("echo hi\n")
    so, se, rc = run(["-l", str(p)])
    assert rc == 0 and so == ""


def test_dash_argument_reads_stdin():
    assert out(["-"], stdin="echo  hi\n") == "echo hi\n"
