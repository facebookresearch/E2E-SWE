"""Hidden pytest suite for the packcc WRG task.

Each test writes a small PEG grammar fixture, invokes the agent's
`/usr/local/bin/packcc` binary to generate `parser.c` / `parser.h`, then
compiles a driver `main.c` that includes the generated parser (via the
`#include "parser.h"` + `#include "parser.c"` pattern), runs the driver
against a stdin fixture, and asserts on stdout.

The pattern mirrors the upstream `tests/*.d/` bats-based suite, translated
to pytest+subprocess+gcc so it plugs into the WRG grading harness. See
`tests/main.c` in the upstream repo for the driver shape (adopted verbatim).
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest


PACKCC_BIN = "/usr/local/bin/packcc"

COMPILE_TIMEOUT = 30
RUN_TIMEOUT = 30

# The driver `main.c` used for the majority of tests. Mirrors the upstream
# tests/main.c: pcc_create → drain via pcc_parse loop → pcc_destroy.
# Tests that need a non-default return type / auxil / prefix override RET_TYPE
# / CREATE / PARSE / DESTROY defines before including the driver.
DEFAULT_MAIN_C = r"""
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "parser.h"

#define PRINT(X) printf("%s\n", X);
#define PRINT_L(LBL, X) printf("%s: %s\n", LBL, X);

#ifndef RET_TYPE
#define RET_TYPE int
#endif

#include "parser.c"

int main(int argc, char **argv) {
    RET_TYPE ret;
    pcc_context_t *ctx = pcc_create(NULL);
    while (pcc_parse(ctx, &ret));
    pcc_destroy(ctx);
    (void)argc; (void)argv;
    return 0;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_packcc(
    tmp_path: Path,
    peg_source: str,
    *,
    extra_args: list[str] | None = None,
    output_base: str = "parser",
) -> subprocess.CompletedProcess:
    """Invoke packcc on an inline PEG source and return the completed process."""
    peg_path = tmp_path / "input.peg"
    peg_path.write_text(peg_source)
    cmd = [PACKCC_BIN]
    if output_base:
        cmd += ["-o", output_base]
    if extra_args:
        cmd += extra_args
    cmd += [str(peg_path)]
    return subprocess.run(
        cmd, cwd=tmp_path, capture_output=True, text=True, timeout=RUN_TIMEOUT
    )


def _compile_driver(
    tmp_path: Path,
    main_c: str = DEFAULT_MAIN_C,
    *,
    parser_base: str = "parser",
    extra_cflags: list[str] | None = None,
) -> Path:
    """Compile main.c + generated parser into an executable and return its path."""
    (tmp_path / "main.c").write_text(main_c)
    binary = tmp_path / "driver"
    cmd = [
        "gcc",
        "-std=c99",
        "-Wall",
        "-Wno-unused-value",
        "-Wno-unused-function",
        "-Wno-unused-parameter",
        "-Wno-unused-variable",
        "-Wno-parentheses",
        "-Wno-format",
        f"-I{tmp_path}",
        str(tmp_path / "main.c"),
        "-o",
        str(binary),
    ]
    if extra_cflags:
        cmd += extra_cflags
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    assert r.returncode == 0, (
        f"compile failed:\nCMD: {' '.join(cmd)}\n"
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}\n"
        f"parser.c head:\n{(tmp_path / f'{parser_base}.c').read_text()[:2048]}"
    )
    return binary


def _run_driver(binary: Path, stdin_input: str = "") -> tuple[int, str, str]:
    r = subprocess.run(
        [str(binary)],
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    return r.returncode, r.stdout, r.stderr


def run_peg(
    tmp_path: Path,
    peg_source: str,
    stdin_input: str,
    *,
    main_c: str = DEFAULT_MAIN_C,
    packcc_args: list[str] | None = None,
) -> str:
    """End-to-end helper: generate, compile, run, return stdout string.

    Asserts on successful packcc generation and successful driver exit (rc=0).
    Returns the captured stdout so tests can perform exact-string assertions.
    """
    r = _run_packcc(tmp_path, peg_source, extra_args=packcc_args)
    assert (
        r.returncode == 0
    ), f"packcc failed rc={r.returncode}:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    binary = _compile_driver(tmp_path, main_c=main_c)
    rc, out, err = _run_driver(binary, stdin_input=stdin_input)
    assert rc == 0, f"driver exited rc={rc}:\nSTDOUT:\n{out}\nSTDERR:\n{err}"
    return out


# ===========================================================================
# A. PEG basics — literals, alternation, character classes, quantifiers
# ===========================================================================


class TestBasicPeg:
    def test_literal_sequence_and_alternation(self, tmp_path):
        """A sequence of literals must all match; `/` picks the first sequence.

        Sequence `'foo' 'bar'` matches only when both literals match in order.
        Alternation tries each branch left to right and commits to the first
        that succeeds; subsequent branches are not evaluated.
        """
        peg = textwrap.dedent(
            r"""
            FILE <- (LINE '\n')*
            LINE <- FOOBAR / FOO / BAR / OTHER
            FOOBAR <- 'foo' 'bar' { PRINT("FOOBAR"); }
            FOO    <- 'foo'       { PRINT("FOO"); }
            BAR    <- 'bar'       { PRINT("BAR"); }
            OTHER  <- [^\n]+      { PRINT("OTHER"); }
            """
        )
        out = run_peg(tmp_path, peg, "foobar\nfoo\nbar\nbaz\n")
        assert out == "FOOBAR\nFOO\nBAR\nOTHER\n"


class TestCharacterClasses:
    def test_class_negation_and_ranges(self, tmp_path):
        """`[abc]`, `[^abc]`, `[a-z0-9]` — inclusive ranges and negation."""
        peg = textwrap.dedent(
            r"""
            FILE <- (TOKEN _)*
            TOKEN <- LETTER / DIGIT / OTHER
            LETTER <- [a-zA-Z]+ { printf("LETTER:%s\n", $0); }
            DIGIT  <- [0-9]+    { printf("DIGIT:%s\n",  $0); }
            OTHER  <- [^ \n]+   { printf("OTHER:%s\n",  $0); }
            _      <- [ \n]+
            """
        )
        out = run_peg(tmp_path, peg, "abc 123 !? Hello 42 zZ\n")
        assert out == (
            "LETTER:abc\n"
            "DIGIT:123\n"
            "OTHER:!?\n"
            "LETTER:Hello\n"
            "DIGIT:42\n"
            "LETTER:zZ\n"
        )

    def test_class_escape_sequences_hex_and_backslash(self, tmp_path):
        r"""C-escape sequences (`\t`, `\\`, `\]`) and hex (`\x41`) in classes."""
        peg = textwrap.dedent(
            r"""
            FILE <- (TOKEN)* !.
            TOKEN <- HEX / SLASH / TAB / OTHER
            HEX    <- [\x41-\x43]+     { printf("HEX:%s\n", $0); }
            SLASH  <- [\\\]]+          { printf("SLASH:%s\n", $0); }
            TAB    <- [\t]+            { printf("TAB\n"); }
            OTHER  <- .                { printf("OTHER:%s\n", $0); }
            """
        )
        # Input: "ABC\\]\tX"  — ABC=hex range, \\ and ] hit SLASH, tab hits TAB, X falls to OTHER.
        out = run_peg(tmp_path, peg, "ABC\\]\tX")
        assert out == "HEX:ABC\nSLASH:\\]\nTAB\nOTHER:X\n"


class TestQuantifiers:
    def test_optional_star_and_plus(self, tmp_path):
        """`?` = 0-or-1, `*` = 0-or-more, `+` = 1-or-more."""
        peg = textwrap.dedent(
            r"""
            FILE <- (LINE '\n')*
            LINE <- OPTIONAL / STAR / PLUS
            OPTIONAL <- '?' 'A'?  { PRINT($0); }
            STAR     <- '*' 'B'*  { PRINT($0); }
            PLUS     <- '+' 'C'+  { PRINT($0); }
            """
        )
        out = run_peg(tmp_path, peg, "?\n?A\n*\n*BBB\n+C\n+CCCC\n")
        assert out == "?\n?A\n*\n*BBB\n+C\n+CCCC\n"


# ===========================================================================
# B. Predicates and positions
# ===========================================================================


class TestPredicates:
    def test_positive_and_negative_predicates(self, tmp_path):
        """`&elem` succeeds without consuming; `!elem` succeeds iff elem fails.

        Uses the upstream `(BEGINS_UPPER / FOLLOWED_BY_SPACE / .)*` shape so
        `.` guarantees forward progress even when neither predicate branch
        matches at the current position.
        """
        peg = textwrap.dedent(
            r"""
            FILE <- (BEGINS_UPPER / FOLLOWED_BY_SPACE / .)*
            BEGINS_UPPER      <- &[A-Z] [a-zA-Z]+ { printf("BEG_UP:%s\n", $0); }
            FOLLOWED_BY_SPACE <- [a-zA-Z]+ &' '   { printf("FOL_SP:%s\n", $0); }
            """
        )
        # "Hello there world\nFoo bar\n":
        #   "Hello"     -> BEG_UP (uppercase-led)
        #   "there"     -> FOL_SP (followed by space; not upper-led so BEG_UP fails)
        #   "world"     -> matched char-by-char via the trailing `.` (no space after)
        #   "Foo"       -> BEG_UP (uppercase-led; BEG_UP wins over FOL_SP by order)
        #   "bar"       -> char-by-char via `.` (no space after)
        out = run_peg(tmp_path, peg, "Hello there world\nFoo bar\n")
        assert out == "BEG_UP:Hello\nFOL_SP:there\nBEG_UP:Foo\n"

    def test_end_of_input_idiom(self, tmp_path):
        """The `!.` idiom matches only after the last character was consumed."""
        peg = textwrap.dedent(
            r"""
            FILE <- WORD ' '* !. { PRINT("EOF_REACHED"); }
                  / [^\n]+       { PRINT("NO_EOF"); }
            WORD <- [a-z]+ { printf("WORD:%s\n", $0); }
            """
        )
        # Trailing spaces then EOF -> matches the `!.` branch.
        out = run_peg(tmp_path, peg, "abc   ")
        assert out == "WORD:abc\nEOF_REACHED\n"

    def test_caret_matches_start_of_input(self, tmp_path):
        """`^` matches the beginning of the input (position 0)."""
        peg = textwrap.dedent(
            r"""
            FILE <- (NUM_AT_START / NUM_MID / .)*
            NUM_AT_START <- ^  ( [0] / [1-9][0-9]* ) { printf("AT_START:%s\n", $0); }
            NUM_MID      <- !^ ( [0] / [1-9][0-9]* ) { printf("MID:%s\n",     $0); }
            """
        )
        out = run_peg(tmp_path, peg, "12 34 5\n")
        assert out == "AT_START:12\nMID:34\nMID:5\n"


# ===========================================================================
# C. Captures and back-references
# ===========================================================================


class TestCaptures:
    def test_dollar_backref_reuses_captured_string(self, tmp_path):
        """A captured group can be referenced later as `$1` to match the same text."""
        peg = textwrap.dedent(
            r"""
            FILE <- (LINE '\n')*
            LINE <- QUOTED / OTHER
            QUOTED <- < ["'] > ( !$1 . )* $1 { printf("QUOTED:%s\n", $0); }
            OTHER  <- [^\n]+ { printf("OTHER:%s\n", $0); }
            """
        )
        # First line uses double quotes, second single quotes; the back-reference
        # forces the closing delimiter to match the opening one.
        out = run_peg(tmp_path, peg, '"hello world"\n\'goodbye\'\n"mixed\'delim"\n')
        assert out == (
            'QUOTED:"hello world"\n' "QUOTED:'goodbye'\n" 'QUOTED:"mixed\'delim"\n'
        )

    def test_capture_positions_and_multi_index(self, tmp_path):
        """`$1s`, `$1e`, `$2` are 0-based positions and additional captures."""
        peg = textwrap.dedent(
            r"""
            FILE <- (LINE '\n')*
            LINE <- < 'aa' > ' ' < 'bb' >
                    { printf("%d,%d:%s %d,%d:%s\n",
                             (int)$1s, (int)$1e, $1, (int)$2s, (int)$2e, $2); }
                  / [^\n]+ { printf("OTHER:%s\n", $0); }
            """
        )
        out = run_peg(tmp_path, peg, "aa bb\nother\n")
        # $1s=0, $1e=2, $2s=3, $2e=5 (position values reset per rule attempt,
        # 0-based counting from where the rule attempt began).
        assert out == "0,2:aa 3,5:bb\nOTHER:other\n"

    def test_dollar_zero_holds_full_match(self, tmp_path):
        """`$0` is the text between the rule's start and the current position."""
        peg = textwrap.dedent(
            r"""
            FILE <- (WORD (' ' / '\n'))*
            WORD <- [a-z]+ { printf("[%s]\n", $0); }
            """
        )
        out = run_peg(tmp_path, peg, "alpha beta gamma\n")
        assert out == "[alpha]\n[beta]\n[gamma]\n"

    def test_nested_captures_are_addressable_by_outer_to_inner_index(self, tmp_path):
        """Nested `< < < > > >` groups — captures are numbered by the opening
        bracket position, LTR: outer opens first (so it is `$1`), then middle
        (`$2`), then innermost (`$3`). Each `$N` must contain the exact matched
        substring for that group, addressable independently.
        """
        peg = textwrap.dedent(
            r"""
            FILE <- ( LINE '\n' )*
            LINE <- < 'a' < 'b' < 'c' > 'd' > 'e' >
                    { printf("outer=%s mid=%s inner=%s\n", $1, $2, $3); }
                  / [^\n]+ { printf("other:%s\n", $0); }
            """
        )
        out = run_peg(tmp_path, peg, "abcde\nzzz\n")
        assert out == "outer=abcde mid=bcd inner=c\nother:zzz\n"


# ===========================================================================
# D. Rule variables, actions, error actions
# ===========================================================================


class TestActions:
    def test_rule_variable_arithmetic_expression(self, tmp_path):
        """`name:rule` binds the rule's `$$` output into a local variable."""
        peg = textwrap.dedent(
            r"""
            FILE <- (LINE '\n')*
            LINE <- e:sum { printf("=%d\n", e); }
            sum  <- l:num '+' r:num { $$ = l + r; }
                  / l:num '-' r:num { $$ = l - r; }
                  / e:num           { $$ = e; }
            num  <- < [0-9]+ >      { $$ = atoi($1); }
            """
        )
        out = run_peg(tmp_path, peg, "3+4\n10-6\n7\n")
        assert out == "=7\n=4\n=7\n"

    def test_error_action_fires_on_element_failure(self, tmp_path):
        """`elem ~{ ... }` — the block runs when `elem` fails to match."""
        peg = textwrap.dedent(
            r"""
            FILE <- (RULE '\n')*
            RULE <- '1' [A-Z] ':'
                    E1 ~{ printf("E1 failed: %s\n", $0); }
                    E2 ~{ printf("E2 failed: %s\n", $0); }
                    E3 ~{ printf("E3 failed: %s\n", $0); }
                    { PRINT($0); }
                  / [^\n]+
            E1 <- '1'
            E2 <- '2'
            E3 <- '3'
            """
        )
        out = run_peg(tmp_path, peg, "1A:123\n1B:023\n1C:1?3\n1D:124\n")
        # Error actions fire during backtracking (as each E1/E2/E3 fails at its
        # position); successful actions are queued as thunks and flushed after
        # the whole top-level parse completes. So the three error diagnostics
        # print first, in position order, and the success action for line 1
        # ("1A:123") prints last.
        assert out == (
            "E1 failed: 1B:\n" "E2 failed: 1C:1\n" "E3 failed: 1D:12\n" "1A:123\n"
        )

    def test_error_action_reads_multi_positional_captures(self, tmp_path):
        """Error action `~{ }` accesses `$1`, `$2`, `$3`, `$0` referring to the
        earlier `< … >` groups that matched before the failing element. Each
        capture must be initialised and readable inside the error-action block.
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            }
            FILE <- ( ROW '\n' )*
            ROW  <- < [A-Z] > ':' < [0-9] > ':' < [a-z] >
                    SUFFIX ~{ printf("bad row=%s letter=%s digit=%s tail=%s\n", $1, $3, $2, $0); }
                    { printf("ok:%s\n", $0); }
                  / [^\n]+ { printf("other:%s\n", $0); }
            SUFFIX <- '.'
            """
        )
        # ROW matches "<upper>:<digit>:<lower>." — SUFFIX is the trailing '.'.
        # Rows lacking the trailing '.' fail at SUFFIX, so the error action
        # fires with $1=upper, $2=digit, $3=lower, $0=partial match ("<u>:<d>:<l>").
        # Successful rows queue a thunk that prints "ok:<match>" at end-of-parse.
        out = run_peg(tmp_path, peg, "A:1:a.\nB:2:b\nX:9:c\nZ:3:z.\n")
        # Error actions fire IMMEDIATELY (during backtrack). The failing "other"
        # branch's printf is a success-action thunk. Both success thunks (ok:A:1:a.
        # for row 1, ok:Z:3:z. for row 4, other:B:2:b, other:X:9:c) flush at end.
        assert out == (
            "bad row=B letter=b digit=2 tail=B:2:b\n"
            "bad row=X letter=c digit=9 tail=X:9:c\n"
            "ok:A:1:a.\n"
            "other:B:2:b\n"
            "other:X:9:c\n"
            "ok:Z:3:z.\n"
        )


# ===========================================================================
# E. Programmable predicates and marker variables
# ===========================================================================


class TestProgrammablePredicates:
    def test_predicate_gates_match_on_output_variable(self, tmp_path):
        """`&{ ... }` — matching continues only when @@ is set to nonzero.

        `!{ ... }` — matching continues only when @@ is set to zero (the initial
        value differs: 1 for `&{ }`, 0 for `!{ }`).
        """
        peg = textwrap.dedent(
            r"""
            %marker @count

            FILE <- (LINE '\n')*
            LINE <- LONG_HASH / SHORT_HASH / OTHER
            LONG_HASH  <- &{ @count = 0; } ('#' &{ @count++; })+
                          &{ @@ = (@count >= 3); }
                          { printf("LONG:%d\n",  (int)@count); }
            SHORT_HASH <- &{ @count = 0; } ('#' &{ @count++; })+
                          !{ @@ = (@count >= 3); }
                          { printf("SHORT:%d\n", (int)@count); }
            OTHER      <- [^\n]+ { printf("OTHER:%s\n", $0); }
            """
        )
        out = run_peg(tmp_path, peg, "#\n##\n###\n####\nabc\n")
        assert out == "SHORT:1\nSHORT:2\nLONG:3\nLONG:4\nOTHER:abc\n"

    def test_predicate_reads_capture_to_gate_match(self, tmp_path):
        """`&{ ... }` block reads `$1` from an earlier `< ... >` and sets `@@`.
        The model must emit capture-variable declarations/initialisations inside
        the predicate C block (same treatment as inside an action or error action).
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            #include <string.h>
            }
            FILE <- ( LINE '\n' )*
            LINE <- < [A-Za-z]+ > &{ @@ = (strlen($1) > 3); } { printf("long=%s\n", $1); }
                  / < [A-Za-z]+ > { printf("short=%s\n", $2); }
                  / [^A-Za-z\n]+ { printf("nonword\n"); }
            """
        )
        # "hello" -> len 5 > 3, first branch, prints "long=hello"
        # "hi"    -> len 2, predicate false, fallthrough to second, prints "short=hi"
        # "abcd"  -> len 4 > 3, prints "long=abcd"
        # "42"    -> no letters, third branch, prints "nonword"
        out = run_peg(tmp_path, peg, "hello\nhi\nabcd\n42\n")
        assert out == "long=hello\nshort=hi\nlong=abcd\nnonword\n"


class TestMarkers:
    def test_marker_integer_arithmetic(self, tmp_path):
        """Marker variables are ptrdiff_t; support `++`, `+=`, comparison."""
        peg = textwrap.dedent(
            r"""
            %marker @l @r

            FILE <- (BALANCED / OTHER '\n')*
            BALANCED <- &{ @l = 0; } ('<' &{ @l++; })+
                        [^<>\n]+
                        &{ @r = 0; } ('>' &{ @r++; })*
                        &{ @@ = (@l == @r); }
                        '\n'
                        { printf("BALANCED l=%d r=%d\n", (int)@l, (int)@r); }
            OTHER    <- [^\n]* { printf("OTHER:%s\n", $0); }
            """
        )
        out = run_peg(tmp_path, peg, "<abc>\n<<def>>\n<ghi>>\n<<jkl>\n")
        assert out == (
            "BALANCED l=1 r=1\n" "BALANCED l=2 r=2\n" "OTHER:<ghi>>\n" "OTHER:<<jkl>\n"
        )

    def test_marker_string_set_and_get(self, tmp_path):
        """`@name.set_string(s)` stores s; `@name` in a rule position matches
        the stored string. Together they force a later delimiter to equal an
        earlier one, so `'foo'` and `"bar"` parse but `'foo"` (mismatched
        delimiter within a line) does not.
        """
        peg = textwrap.dedent(
            r"""
            %marker @quote

            FILE     <- (LINE '\n')*
            LINE     <- QUOTED / OTHER
            QUOTED   <- start body end            { printf("OK:%s\n", $0); }
            start    <- < ['"] > &{ @quote.set_string($1); }
            body     <- ( !@quote !'\n' . )*
            end      <- @quote
            OTHER    <- [^\n]*                    { printf("OTHER:%s\n", $0); }
            """
        )
        # Well-formed on first two lines; delimiter mismatch on last two lines
        # forces QUOTED to fail and the LINE alternative falls through to OTHER.
        out = run_peg(tmp_path, peg, "'foo'\n\"bar\"\n'baz\"\n\"qux'\n")
        assert out == ("OK:'foo'\n" 'OK:"bar"\n' "OTHER:'baz\"\n" "OTHER:\"qux'\n")

    def test_marker_save_restore_returns_string_slot_to_previous_value(self, tmp_path):
        """`@name.save()` pushes (int, string) slots; `@name.restore()` pops.
        After a `set_string(...)` between save and restore, the string is back
        to its pre-save value.
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            }
            %marker @tag

            FILE <- ( LINE '\n' )*
            LINE <- &{ @tag.set_string("baseline"); }
                    &{ @tag.save(); }
                    ( 'A' &{ @tag.set_string("mutated-A"); }
                    / 'B' &{ @tag.set_string("mutated-B"); }
                    )*
                    &{ @tag.restore(); }
                    { printf("after=%s\n", @tag.get_string()); }
            """
        )
        # After each LINE, restore rewinds string back to "baseline". The A/B
        # mutations are discarded by the restore.
        out = run_peg(tmp_path, peg, "AAA\nB\nBABA\n")
        assert out == "after=baseline\nafter=baseline\nafter=baseline\n"

    def test_marker_append_string_accumulates_across_quantified_matches(self, tmp_path):
        """`@name.append_string(s)` concatenates s onto the string slot.
        Verifies accumulation across a `+` quantifier: each match appends.
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            }
            %marker @acc

            FILE <- ( LINE '\n' )*
            LINE <- &{ @acc.set_string(""); }
                    ( < [A-Z] > &{ @acc.append_string($1); } )+
                    { printf("acc=%s\n", @acc.get_string()); }
            """
        )
        out = run_peg(tmp_path, peg, "ABC\nX\nMNOPQ\n")
        assert out == "acc=ABC\nacc=X\nacc=MNOPQ\n"


# ===========================================================================
# F. Directives — code emission split
# ===========================================================================


class TestDirectives:
    def test_source_header_common_split(self, tmp_path):
        """`%header` -> only .h; `%source` -> only .c; `%common` -> both."""
        peg = textwrap.dedent(
            r"""
            %header  { /* :HEADER: */ }
            %source  { /* :SOURCE: */ }
            %common  { /* :COMMON: */ }

            FILE <- .*
            """
        )
        r = _run_packcc(tmp_path, peg)
        assert r.returncode == 0, r.stderr
        header = (tmp_path / "parser.h").read_text()
        source = (tmp_path / "parser.c").read_text()
        assert ":HEADER:" in header
        assert ":HEADER:" not in source
        assert ":SOURCE:" in source
        assert ":SOURCE:" not in header
        assert ":COMMON:" in header
        assert ":COMMON:" in source

    def test_earlysource_precedes_generated_code(self, tmp_path):
        """`%earlysource` / `%earlyheader` — placed BEFORE any generated typedefs."""
        peg = textwrap.dedent(
            r"""
            %earlyheader { /* :EARLYHEADER: */ }
            %earlysource { /* :EARLYSOURCE: */ }

            FILE <- .*
            """
        )
        r = _run_packcc(tmp_path, peg)
        assert r.returncode == 0, r.stderr
        header = (tmp_path / "parser.h").read_text()
        source = (tmp_path / "parser.c").read_text()
        # In parser.h, :EARLYHEADER: must appear before pcc_context_t typedef.
        h_early = header.index(":EARLYHEADER:")
        h_pcc = header.index("pcc_context_t")
        assert (
            h_early < h_pcc
        ), f"earlyheader at {h_early} should precede pcc_context_t at {h_pcc}"
        # In parser.c, :EARLYSOURCE: must appear before pcc_context_t as well.
        s_early = source.index(":EARLYSOURCE:")
        s_pcc = source.index("pcc_context_t")
        assert (
            s_early < s_pcc
        ), f"earlysource at {s_early} should precede pcc_context_t at {s_pcc}"

    def test_prefix_directive_renames_api(self, tmp_path):
        """`%prefix "foo"` — API functions renamed to `foo_create/parse/destroy`."""
        peg = textwrap.dedent(
            r"""
            %prefix "calc"

            FILE <- WORD (' ' / '\n')* !.
            WORD <- [a-z]+ { PRINT($0); }
            """
        )
        # Custom driver: use calc_context_t / calc_create / calc_parse / calc_destroy.
        main_c = r"""
        #include <stddef.h>
        #include <stdio.h>

        #include "parser.h"
        #define PRINT(X) printf("%s\n", X);
        #include "parser.c"

        int main(void) {
            int ret;
            calc_context_t *ctx = calc_create(NULL);
            while (calc_parse(ctx, &ret));
            calc_destroy(ctx);
            return 0;
        }
        """
        out = run_peg(tmp_path, peg, "hello\n", main_c=main_c)
        assert out == "hello\n"

    def test_prefix_directive_with_user_rule_named_start(self, tmp_path):
        """`%prefix "mygram"` + user rule named `start`. The generated public
        API must be `mygram_create` / `mygram_parse` / `mygram_destroy` (with
        `start` as the top-level PEG rule), and the internal generated symbols
        must not clash with the user's `start` rule identifier — the driver
        must still link and run correctly.
        """
        peg = textwrap.dedent(
            r"""
            %prefix "mygram"
            %source {
            #include <stdio.h>
            }
            start <- ( LINE '\n' )*
            LINE  <- 'ok' { printf("matched:ok\n"); }
                   / [^\n]+ { printf("other\n"); }
            """
        )
        main_c = r"""
        #include <stddef.h>
        #include <stdio.h>

        #include "parser.h"
        #include "parser.c"

        int main(void) {
            int ret;
            mygram_context_t *ctx = mygram_create(NULL);
            while (mygram_parse(ctx, &ret));
            mygram_destroy(ctx);
            return 0;
        }
        """
        out = run_peg(tmp_path, peg, "ok\nnope\nok\n", main_c=main_c)
        assert out == "matched:ok\nother\nmatched:ok\n"

    def test_user_rule_named_context_does_not_collide_with_typedef(self, tmp_path):
        """A user rule literally named `context` must not collide with the
        generated `pcc_context_t` typedef. The parser must still compile,
        expose `pcc_parse`, and dispatch to the user's `context` rule.
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            }
            FILE    <- ( context '\n' )*
            context <- 'HELLO' { printf("greet\n"); }
                     / [^\n]+  { printf("other\n"); }
            """
        )
        # Use the default `pcc` prefix (no `%prefix` directive) so the collision
        # would be with `pcc_context_t` if the model name-mangles poorly.
        out = run_peg(tmp_path, peg, "HELLO\nhi\nHELLO\n")
        assert out == "greet\nother\ngreet\n"


# ===========================================================================
# G. Type customisation
# ===========================================================================


class TestTypes:
    def test_value_directive_changes_return_type(self, tmp_path):
        """`%value "double"` — `$$` and `pcc_parse(ctx, &ret)` become double."""
        peg = textwrap.dedent(
            r"""
            %value "double"

            %source {
            #include <stdlib.h>
            }

            FILE <- ( LINE '\n' )*
            LINE <- e:num { $$ = e * 2.0; printf("%.2f\n", $$); }
            num  <- < [0-9]+ '.' [0-9]+ > { $$ = strtod($1, NULL); }
            """
        )
        # Driver must declare ret as double; DEFAULT_MAIN_C's `RET_TYPE`
        # override slot lets us switch the type without rewriting the driver.
        main_c = DEFAULT_MAIN_C.replace(
            "#define RET_TYPE int", "#define RET_TYPE double"
        )
        out = run_peg(tmp_path, peg, "1.50\n3.25\n", main_c=main_c)
        assert out == "3.00\n6.50\n"

    def test_auxil_directive_carries_context_data(self, tmp_path):
        """`%auxil "T"` — the `auxil` argument to pcc_create becomes T."""
        peg = textwrap.dedent(
            r"""
            %auxil "int *"

            FILE <- ( WORD (' ' / '\n') )* !.
            WORD <- [a-z]+ { (*auxil)++; }
            """
        )
        main_c = r"""
        #include <stddef.h>
        #include <stdio.h>

        #include "parser.h"
        #include "parser.c"

        int main(void) {
            int counter = 0;
            int ret;
            pcc_context_t *ctx = pcc_create(&counter);
            while (pcc_parse(ctx, &ret));
            pcc_destroy(ctx);
            printf("count=%d\n", counter);
            return 0;
        }
        """
        out = run_peg(tmp_path, peg, "one two three four\n", main_c=main_c)
        assert out == "count=4\n"


# ===========================================================================
# H. Imports — bundled reusable grammar fragments
# ===========================================================================


class TestImports:
    def test_import_char_ascii_group(self, tmp_path):
        """`%import "char/ascii_character_group.peg"` exports ASCII_C_* rules.

        `%import` is placed AFTER the user rules so `FILE` remains the
        top-level rule (packcc uses the first rule defined in the file as
        top-level, and imported rules are prepended when `%import` comes first).
        """
        peg = textwrap.dedent(
            r"""
            FILE <- ( TOKEN )* !.
            TOKEN <- DIGITS / LETTERS / SPACE / OTHER
            DIGITS  <- < ASCII_C_digit+ > { printf("DIG:%s\n", $1); }
            LETTERS <- < ASCII_C_alpha+ > { printf("ALP:%s\n", $1); }
            SPACE   <- ASCII_C_space+
            OTHER   <- .                  { printf("OTH:%s\n", $0); }

            %import "char/ascii_character_group.peg"
            """
        )
        out = run_peg(tmp_path, peg, "abc 123 XyZ 42\n!")
        assert out == "ALP:abc\nDIG:123\nALP:XyZ\nDIG:42\nOTH:!\n"

    def test_import_util_eol(self, tmp_path):
        """`%import "util/eol.peg"` exposes EOL / EOF rules across line endings."""
        peg = textwrap.dedent(
            r"""
            FILE <- ( LINE EOL )* EOF
            LINE <- < [^\r\n]* > { printf("[%s]\n", $1); }

            %import "util/eol.peg"
            """
        )
        # Mix of \n, \r\n, \r line terminators — EOL matches every flavour.
        out = run_peg(tmp_path, peg, "alpha\nbeta\r\ngamma\rdelta\n")
        assert out == "[alpha]\n[beta]\n[gamma]\n[delta]\n"

    def test_import_ast_v3_builds_tree(self, tmp_path):
        """`%import "code/pcc_ast.v3.peg"` — auto-AST helper for arithmetic."""
        # This is the ast-calc example distilled: the pcc_ast.v3.peg import
        # supplies calc_ast_node__create_2 / _create_1 / _create_0, a
        # calc_ast_manager_t container, and calc_ast_node_t nodes.
        peg = textwrap.dedent(
            r"""
            %prefix "calc"

            %value "calc_ast_node_t *"
            %auxil "calc_ast_manager_t *"

            %earlysource {
            #define _POSIX_C_SOURCE 200809L
            }

            %header {
            #define CALC_AST_NODE_CUSTOM_DATA_DEFINED
            typedef struct text_data_tag {
                char *text;
            } calc_ast_node_custom_data_t;
            }

            %source {
            #include <stdio.h>
            #include <string.h>
            }

            statement <- _ e:expression _ EOL { $$ = e; }
                       / ( !EOL . )* EOL      { $$ = NULL; }

            expression <- e:term { $$ = e; }

            term <- l:term _ '+' _ r:factor { $$ = calc_ast_node__create_2(l, r); $$->custom.text = strdup("+"); }
                  / l:term _ '-' _ r:factor { $$ = calc_ast_node__create_2(l, r); $$->custom.text = strdup("-"); }
                  / e:factor                { $$ = e; }

            factor <- l:factor _ '*' _ r:unary { $$ = calc_ast_node__create_2(l, r); $$->custom.text = strdup("*"); }
                    / l:factor _ '/' _ r:unary { $$ = calc_ast_node__create_2(l, r); $$->custom.text = strdup("/"); }
                    / e:unary                  { $$ = e; }

            unary <- '+' _ e:unary { $$ = calc_ast_node__create_1(e); $$->custom.text = strdup("+"); }
                   / '-' _ e:unary { $$ = calc_ast_node__create_1(e); $$->custom.text = strdup("-"); }
                   / e:primary     { $$ = e; }

            primary <- < [0-9]+ >               { $$ = calc_ast_node__create_0(); $$->custom.text = strdup($1); }
                     / '(' _ e:expression _ ')' { $$ = e; }

            _   <- [ \t]*
            EOL <- '\n' / '\r\n' / '\r' / ';'

            %import "code/pcc_ast.v3.peg"

            %%

            void calc_ast_node_custom_data__initialize(calc_ast_manager_t *mgr, calc_ast_node_custom_data_t *obj) {
                (void)mgr;
                obj->text = NULL;
            }

            void calc_ast_node_custom_data__finalize(calc_ast_manager_t *mgr, calc_ast_node_custom_data_t *obj) {
                (void)mgr;
                free(obj->text);
            }
            """
        )
        # Custom driver dumps the AST post-order with node arity + text.
        # `_POSIX_C_SOURCE` must be defined BEFORE any system header include
        # so glibc exposes `strdup()` (used inside the generated parser's
        # inline actions). Defining it in the grammar's `%earlysource` is not
        # enough — main.c includes <string.h> before it processes parser.c,
        # so the define must fire here too.
        main_c = r"""
        #define _POSIX_C_SOURCE 200809L
        #include <stddef.h>
        #include <stdio.h>
        #include <stdlib.h>
        #include <string.h>

        #include "parser.h"
        #include "parser.c"

        static void dump_ast(const calc_ast_node_t *obj, int depth) {
            if (obj) {
                const size_t n = calc_ast_node__get_child_count(obj);
                const calc_ast_node_t *const *const p = calc_ast_node__get_child_const_array(obj);
                const calc_ast_node_custom_data_t *const d = &(obj->custom);
                static const char *const arity_name[] = { "nullary", "unary", "binary", "ternary" };
                printf("%*s%s: \"%s\"\n", 2 * depth, "", n <= 3 ? arity_name[n] : "(other)", d->text);
                {
                    size_t i;
                    for (i = 0; i < n; i++) {
                        dump_ast(p[i], depth + 1);
                    }
                }
            }
        }

        int main(void) {
            calc_ast_manager_t mgr;
            calc_ast_manager__initialize(&mgr);
            {
                calc_context_t *ctx = calc_create(&mgr);
                calc_ast_node_t *ast = NULL;
                while (calc_parse(ctx, &ast)) {
                    if (ast) dump_ast(ast, 0);
                    calc_ast_node__destroy(&mgr, ast);
                }
                calc_destroy(ctx);
            }
            calc_ast_manager__finalize(&mgr);
            return 0;
        }
        """
        out = run_peg(tmp_path, peg, "1+2*3\n", main_c=main_c)
        assert out == (
            'binary: "+"\n'
            '  nullary: "1"\n'
            '  binary: "*"\n'
            '    nullary: "2"\n'
            '    nullary: "3"\n'
        )

    def test_dash_I_flag_resolves_import_from_user_supplied_dir(self, tmp_path):
        """`packcc -I DIR` prepends DIR to the `%import` search path — a user
        grammar file `%import`ing "myhelper.peg" resolves via DIR before any
        system default.
        """
        # Layout:  tmp_path/customlib/mylib.peg  contains MY_TOKEN rule
        #          tmp_path/input.peg            imports "mylib.peg"
        customdir = tmp_path / "customlib"
        customdir.mkdir()
        (customdir / "mylib.peg").write_text(
            textwrap.dedent(
                r"""
                %source {
                #include <stdio.h>
                }
                MY_TOKEN <- 'FOO' { printf("matched_mylib\n"); }
                         / [^\n]+ { printf("noise\n"); }
                """
            )
        )
        peg_source = textwrap.dedent(
            r"""
            FILE <- ( MY_TOKEN '\n' )*

            %import "mylib.peg"
            """
        )
        # Use _run_packcc with -I flag so it points into customdir.
        r = _run_packcc(tmp_path, peg_source, extra_args=["-I", str(customdir)])
        assert r.returncode == 0, f"packcc -I failed: {r.stderr}"
        binary = _compile_driver(tmp_path)
        rc, out, _ = _run_driver(binary, stdin_input="FOO\nBAR\nFOO\n")
        assert rc == 0
        assert out == "matched_mylib\nnoise\nmatched_mylib\n"

    def test_import_util_tab_provides_column_tracking(self, tmp_path):
        """`%import "util/tab.peg"` exposes a `TAB` rule that treats space as
        column +1 and `\t` as jumping to the next multiple of `${PREFIX}_TAB_SIZE`,
        tracking column in the `@tab_col` marker. The user overrides
        `PCC_TAB_SIZE` (default 8) via a `%source` `#define`.
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            #define PCC_TAB_SIZE 4
            }
            FILE <- ( LINE '\n' )*
            LINE <- &{ @tab_col = 0; } TAB* { printf("col=%d\n", (int)@tab_col); }

            %import "util/tab.peg"
            """
        )
        # Inputs:
        #   ""      -> col=0
        #   " "     -> col=1
        #   "  "    -> col=2
        #   "   "   -> col=3
        #   "    "  -> col=4
        #   "\t"    -> col=4 (next multiple of 4 from 0)
        #   " \t"   -> col=4 (1 -> next mult of 4 = 4)
        #   "\t "   -> col=5 (4 + 1)
        out = run_peg(tmp_path, peg, "\n \n  \n   \n    \n\t\n \t\n\t \n")
        assert out == ("col=0\ncol=1\ncol=2\ncol=3\ncol=4\ncol=4\ncol=4\ncol=5\n")


# ===========================================================================
# I. Left-recursive grammar (calc example)
# ===========================================================================


class TestLeftRecursion:
    def test_left_recursive_arithmetic_parses_correctly(self, tmp_path):
        """Direct + indirect left recursion — canonical calc.peg example.

        Left-recursive `term <- term '+' factor / factor` MUST be supported so
        that `1+2+3` associates left as `(1+2)+3`.
        """
        peg = textwrap.dedent(
            r"""
            %prefix "calc"

            %source {
            #include <stdio.h>
            #include <stdlib.h>
            }

            statement <- _ e:expression _ EOL { printf("answer=%d\n", e); }
                       / ( !EOL . )* EOL      { printf("error\n"); }

            expression <- e:term { $$ = e; }

            term <- l:term _ '+' _ r:factor { $$ = l + r; }
                  / l:term _ '-' _ r:factor { $$ = l - r; }
                  / e:factor                { $$ = e; }

            factor <- l:factor _ '*' _ r:unary { $$ = l * r; }
                    / l:factor _ '/' _ r:unary { $$ = l / r; }
                    / e:unary                  { $$ = e; }

            unary <- '+' _ e:unary { $$ = +e; }
                   / '-' _ e:unary { $$ = -e; }
                   / e:primary     { $$ = e; }

            primary <- < [0-9]+ >               { $$ = atoi($1); }
                     / '(' _ e:expression _ ')' { $$ = e; }

            _   <- [ \t]*
            EOL <- '\n' / '\r\n' / '\r' / ';'
            """
        )
        main_c = r"""
        #include <stddef.h>
        #include <stdio.h>
        #include <stdlib.h>

        #include "parser.h"
        #include "parser.c"

        int main(void) {
            int ret;
            calc_context_t *ctx = calc_create(NULL);
            while (calc_parse(ctx, &ret));
            calc_destroy(ctx);
            return 0;
        }
        """
        out = run_peg(
            tmp_path,
            peg,
            "1+2*(3+4*(5+6))\n24 / -4 / 3\n1-2-3\n",
            main_c=main_c,
        )
        # 1+2*(3+4*(5+6)) = 1+2*(3+44) = 1+2*47 = 95
        # 24 / -4 / 3 = -6 / 3 = -2   (left-associative)
        # 1-2-3 = -4                  (left-associative)
        assert out == "answer=95\nanswer=-2\nanswer=-4\n"


# ===========================================================================
# J. Macros and substitutions
# ===========================================================================


class TestMacros:
    def test_prefix_and_version_macros_substitute(self, tmp_path):
        """`${prefix}`, `${PREFIX}`, `${packcc.version}` in %source blocks."""
        peg = textwrap.dedent(
            r"""
            %prefix "my"

            %source {
            static const char *my_prefix_lc = "${prefix}";
            static const char *my_prefix_uc = "${PREFIX}";
            static const char *my_packcc_ver = "${packcc.version}";
            }

            FILE <- .* { printf("%s %s %s\n", my_prefix_lc, my_prefix_uc, my_packcc_ver); }
            """
        )
        main_c = r"""
        #include <stddef.h>
        #include <stdio.h>

        #include "parser.h"
        #include "parser.c"

        int main(void) {
            int ret;
            my_context_t *ctx = my_create(NULL);
            while (my_parse(ctx, &ret));
            my_destroy(ctx);
            return 0;
        }
        """
        out = run_peg(tmp_path, peg, "x", main_c=main_c)
        parts = out.strip().split()
        assert len(parts) == 3, f"expected 3 space-separated tokens, got {out!r}"
        assert parts[0] == "my", f"${{prefix}} should expand to 'my', got {parts[0]!r}"
        assert parts[1] == "MY", f"${{PREFIX}} should expand to 'MY', got {parts[1]!r}"
        # `${packcc.version}` must expand to PackCC's OWN version — the exact
        # X.Y.Z that `packcc --version` reports — not merely any version-shaped
        # string. A stale/default "0.0.0" or any wrong value satisfies a shape
        # regex yet is a real error, so cross-check the substituted value
        # against the binary's self-reported version.
        ver_proc = subprocess.run(
            [PACKCC_BIN, "--version"],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
        assert ver_proc.returncode == 0, f"packcc --version failed: {ver_proc.stderr}"
        m = re.search(r"\d+\.\d+\.\d+", ver_proc.stdout)
        assert m, f"packcc --version did not report an X.Y.Z version: {ver_proc.stdout!r}"
        assert parts[2] == m.group(0), (
            f"${{packcc.version}} should expand to packcc's own version "
            f"{m.group(0)!r} (as reported by `packcc --version`), got {parts[2]!r}"
        )


# ===========================================================================
# K. CLI flags
# ===========================================================================


class TestCli:
    def test_output_flag_renames_output_files(self, tmp_path):
        """`packcc -o BASE` writes BASE.c and BASE.h (not parser.c/parser.h)."""
        peg = "FILE <- .*\n"
        (tmp_path / "input.peg").write_text(peg)
        r = subprocess.run(
            [PACKCC_BIN, "-o", "myparser", "input.peg"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "myparser.c").exists()
        assert (tmp_path / "myparser.h").exists()
        assert not (tmp_path / "parser.c").exists()
        assert not (tmp_path / "parser.h").exists()

    def test_utf8_default_consumes_codepoint_ascii_flag_consumes_byte(self, tmp_path):
        """In default (UTF-8) mode, `.` consumes a whole UTF-8 codepoint; under
        `--ascii`, `.` consumes exactly one byte. A per-line codepoint counter
        driven by a `@marker` observes the difference on a mixed ASCII+multi-byte
        input.
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            }
            %marker @cnt

            FILE <- ( LINE '\n' )*
            LINE <- &{ @cnt = 0; } ( [^\n] &{ @cnt++; } )*
                    { printf("cnt=%d\n", (int)@cnt); }
            """
        )
        # Input: "aé\nhello\n" — 'é' is 2 UTF-8 bytes (0xC3 0xA9), 'hello' is 5 ASCII bytes.
        stdin = "aé\nhello\n"
        # Default (UTF-8): "aé" -> 2 codepoints, "hello" -> 5 codepoints.
        out_utf8 = run_peg(tmp_path, peg, stdin)
        assert (
            out_utf8 == "cnt=2\ncnt=5\n"
        ), f"UTF-8 mode should count codepoints, got {out_utf8!r}"

        # --ascii: "aé" -> 3 bytes (a + 2 bytes of é), "hello" -> 5 bytes.
        sub = tmp_path / "ascii"
        sub.mkdir()
        out_ascii = run_peg(sub, peg, stdin, packcc_args=["--ascii"])
        assert (
            out_ascii == "cnt=3\ncnt=5\n"
        ), f"--ascii mode should count bytes, got {out_ascii!r}"

    def test_lines_flag_emits_hash_line_directives(self, tmp_path):
        """`packcc --lines` — `#line N "input.peg"` directives in output."""
        peg = textwrap.dedent(
            r"""
            %source {
            /* :MARKER: */
            }

            FILE <- .*
            """
        )
        r = _run_packcc(tmp_path, peg, extra_args=["--lines"])
        assert r.returncode == 0, r.stderr
        source = (tmp_path / "parser.c").read_text()
        # The directive must exist and must reference the original .peg
        # file (packcc may use an absolute path, so match on basename).
        assert "#line" in source, "--lines flag should emit #line directives"
        assert (
            "input.peg" in source
        ), "#line directives should reference the .peg source filename"
        # Sanity: the marker block was placed within a #line-bracketed region.
        marker_idx = source.index(":MARKER:")
        preceding = source[:marker_idx]
        assert "#line" in preceding and "input.peg" in preceding, (
            'there should be a `#line N "input.peg"` directive before the '
            "user's %source block"
        )


# ===========================================================================
# L. Debug macro and error diagnostics
# ===========================================================================


class TestDebug:
    def test_debug_macro_hooks_evaluate_match_nomatch_events(self, tmp_path):
        """`PCC_DEBUG(auxil, event, rule, level, pos, buffer, length)`.

        Events: PCC_DBG_EVALUATE=0, PCC_DBG_MATCH=1, PCC_DBG_NOMATCH=2. When
        the user #defines PCC_DEBUG in `%source`, the generated parser MUST
        call it on rule entry / match / no-match.
        """
        peg = textwrap.dedent(
            r"""
            %source {
            #include <stdio.h>
            static const char *dbg_str[] = { "EVAL", "MATCH", "NOMATCH" };
            #define PCC_DEBUG(auxil, event, rule, level, pos, buffer, length) \
                fprintf(stdout, "%s %s\n", dbg_str[event], rule)
            }

            FILE <- (A / B) EOL
            A    <- 'a'
            B    <- 'b'
            EOL  <- '\n'
            """
        )
        out = run_peg(tmp_path, peg, "b\n")
        # Given input 'b\n', packcc will:
        #   EVAL FILE
        #     EVAL A -> NOMATCH A
        #     EVAL B -> MATCH  B
        #     EVAL EOL -> MATCH EOL
        #   MATCH FILE
        lines = out.rstrip("\n").split("\n")
        # The full trace is fully determined by PEG ordered-choice/sequencing on
        # input 'b\n': FILE (the first/start rule) is evaluated, its body tries A
        # (fails), then B (matches), then EOL (matches), then FILE matches.
        # Assert the exact ordered sequence so a wrong relative order or any
        # spurious/duplicate PCC_DEBUG events are caught, not just membership.
        assert lines == [
            "EVAL FILE",
            "EVAL A",
            "NOMATCH A",
            "EVAL B",
            "MATCH B",
            "EVAL EOL",
            "MATCH EOL",
            "MATCH FILE",
        ], f"unexpected PCC_DEBUG trace: {lines!r}"


class TestValidation:
    def test_invalid_grammar_exits_nonzero(self, tmp_path):
        """A grammar that references an undefined rule must fail with rc != 0 and
        emit a diagnostic to stderr per the §8 contract.
        """
        peg = textwrap.dedent(
            r"""
            FILE <- undefined_rule
            """
        )
        r = _run_packcc(tmp_path, peg)
        assert r.returncode != 0, (
            f"packcc should reject grammar with undefined rule reference; "
            f"got rc={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        )
        assert "undefined" in r.stderr.lower(), (
            f"packcc should emit a diagnostic mentioning the undefined rule; "
            f"got STDERR:\n{r.stderr}"
        )
