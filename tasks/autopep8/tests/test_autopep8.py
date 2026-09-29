"""End-to-end tests for the ``autopep8`` PEP 8 autoformatter CLI.

Every test drives the public command-line interface via ``python -m autopep8`` and
asserts the exact reformatted source (stdin -> stdout), the exact unified diff, the
exact rewritten file contents, or the exact process exit code. No internal modules
are imported, so any faithful reimplementation that reproduces the documented CLI
contract passes.

stdin invocations run in a fresh, empty working directory so that no stray
``setup.cfg`` / ``tox.ini`` / ``.flake8`` / ``pyproject.toml`` in the current
directory can change the formatting defaults; the tests therefore exercise the
documented defaults.
"""

import subprocess
import sys
import tempfile

AP8 = [sys.executable, "-m", "autopep8"]

# An empty directory used as the CWD for every stdin invocation so autopep8's
# configuration-file auto-discovery finds nothing and the documented defaults apply.
_CLEAN_CWD = tempfile.mkdtemp(prefix="ap8_clean_")


def fmt(flags, source):
    """Run ``autopep8 <flags> -`` feeding ``source`` on stdin.

    Returns ``(returncode, stdout, stderr)``.
    """
    proc = subprocess.run(
        AP8 + list(flags) + ["-"],
        input=source,
        capture_output=True,
        text=True,
        cwd=_CLEAN_CWD,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_file(args, tmp_path, source, name="m.py"):
    """Write ``source`` to ``tmp_path/name`` and run ``autopep8 <args> <name>``.

    The command runs with ``cwd=tmp_path`` and a bare filename so diff headers are
    deterministic. Returns ``(proc, file_contents_after)``.
    """
    path = tmp_path / name
    path.write_text(source)
    proc = subprocess.run(
        AP8 + list(args) + [name],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    return proc, path.read_text()


# --------------------------------------------------------------------------- #
# Default (whitespace-only) fixes, stdin -> stdout                            #
# --------------------------------------------------------------------------- #

def test_basic_whitespace():
    """Extraneous/missing whitespace around brackets, commas, operators, and
    keyword-argument equals is normalised (E201/E202/E211/E225/E231/E251), and a
    second blank line is inserted before the top-level def (E302)."""
    rc, out, err = fmt([], "spam( ham[ 1 ],{eggs:2} )\nx=1\ndef g(a,b = 3):\n    return a==b\n")
    assert rc == 0, err
    assert out == "spam(ham[1], {eggs: 2})\nx = 1\n\n\ndef g(a, b=3):\n    return a == b\n"


def test_imports_and_compound_statements():
    """Comma-joined imports are split onto separate lines (E401), and a
    colon/semicolon compound statement is broken into one statement per line
    (E701/E702)."""
    rc, out, err = fmt([], "import os, sys\nif True: x = 1; y = 2\n")
    assert rc == 0, err
    assert out == "import os\nimport sys\nif True:\n    x = 1\n    y = 2\n"


def test_blank_lines():
    """Blank lines around top-level definitions are normalised to two: inserted
    where missing (E302), trimmed where excessive (E303), and added after a
    function body before following code (E305)."""
    rc, out, err = fmt([], "import os\ndef f():\n    pass\n\n\n\ndef g():\n    pass\nz = 1\n")
    assert rc == 0, err
    assert out == "import os\n\n\ndef f():\n    pass\n\n\ndef g():\n    pass\n\n\nz = 1\n"


def test_trailing_and_eof_whitespace():
    """Trailing whitespace is stripped from code lines and blank lines
    (W291/W293) and a missing final newline is added (W292)."""
    rc, out, err = fmt([], "def f():\n    x = 1   \n    \n    return x")
    assert rc == 0, err
    assert out == "def f():\n    x = 1\n\n    return x\n"


def test_comment_spacing():
    """A block comment gains a space after its hash (E265) and an inline comment's
    doubled hash is normalised to a single hash with a space (E262)."""
    rc, out, err = fmt([], "#bad block comment\nx = 1  ## inline\n")
    assert rc == 0, err
    assert out == "# bad block comment\nx = 1  # inline\n"


def test_reindent_tabs():
    """Tab indentation is converted to four-space indentation (E101/W191)."""
    rc, out, err = fmt([], "if True:\n\tx = 1\n")
    assert rc == 0, err
    assert out == "if True:\n    x = 1\n"


def test_default_mode_conservative():
    """In default (non-aggressive) mode autopep8 makes only whitespace changes: a
    ``== None`` comparison is left alone (E711 needs --aggressive) and missing
    whitespace around an arithmetic operator is left alone (E226 is ignored by
    default)."""
    rc, out, err = fmt([], "if x == None:\n    pass\ny = a+b\n")
    assert rc == 0, err
    assert out == "if x == None:\n    pass\ny = a+b\n"


# --------------------------------------------------------------------------- #
# Aggressive (non-whitespace) fixes                                           #
# --------------------------------------------------------------------------- #

def test_aggressive_level1_semantic():
    """A single --aggressive enables level-1 semantic fixes: ``!= None`` becomes
    ``is not None`` (E711), a bare ``except:`` becomes ``except BaseException:``
    (E722), a lambda assignment becomes a def (E731), and an invalid escape
    sequence is made a raw-style escape (W605). Converting the lambda to a def also
    introduces the surrounding blank lines (E305/E302)."""
    src = (
        "import re\n"
        "if x != None:\n    pass\n"
        "try:\n    f()\nexcept:\n    pass\n"
        "g = lambda z: z * 2\n"
        "p = re.compile('\\d+')\n"
    )
    rc, out, err = fmt(["-a"], src)
    assert rc == 0, err
    assert out == (
        "import re\n"
        "if x is not None:\n    pass\n"
        "try:\n    f()\nexcept BaseException:\n    pass\n\n\n"
        "def g(z): return z * 2\n\n\n"
        "p = re.compile('\\\\d+')\n"
    )


def test_aggressive_level2_boolean_membership():
    """Two --aggressive flags enable level-2 fixes: ``== True``/``== False``
    comparisons collapse to the truthy/falsy form (E712), ``not x in`` becomes
    ``x not in`` (E713), and ``not x is`` becomes ``x is not`` (E714)."""
    src = (
        "if x == True:\n    pass\n"
        "if y == False:\n    pass\n"
        "if not a in b:\n    pass\n"
        "if not c is d:\n    pass\n"
    )
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "if x:\n    pass\n"
        "if not y:\n    pass\n"
        "if a not in b:\n    pass\n"
        "if c is not d:\n    pass\n"
    )


# --------------------------------------------------------------------------- #
# Long-line handling (E501)                                                    #
# --------------------------------------------------------------------------- #

def test_e501_physical_default():
    """In default mode a too-long line is shortened by breaking after the opening
    bracket of the call (physical line shortening)."""
    src = "result = some_function_name(first_argument, second_argument, third_argument, fourth_one)\n"
    rc, out, err = fmt([], src)
    assert rc == 0, err
    assert out == (
        "result = some_function_name(\n"
        "    first_argument, second_argument, third_argument, fourth_one)\n"
    )


def test_e501_aggressive_reflow():
    """With --aggressive --aggressive a too-long call is reflowed onto one
    argument per line."""
    src = "result = some_function_name(first_argument, second_argument, third_argument, fourth_one)\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "result = some_function_name(\n"
        "    first_argument,\n"
        "    second_argument,\n"
        "    third_argument,\n"
        "    fourth_one)\n"
    )


def test_max_line_length_option():
    """``--max-line-length`` changes the wrap threshold: at width 40 a line that is
    otherwise acceptable is broken with a backslash continuation."""
    src = "x = aaaaaaaaaa + bbbbbbbbbb + cccccccccc + dddddddddd\n"
    rc, out, err = fmt(["--max-line-length=40"], src)
    assert rc == 0, err
    assert out == "x = aaaaaaaaaa + bbbbbbbbbb + \\\n    cccccccccc + dddddddddd\n"


# --------------------------------------------------------------------------- #
# Indentation of continuation lines & import position                          #
# --------------------------------------------------------------------------- #

def test_continuation_indent():
    """Continuation lines of a bracketed expression are aligned to the visual
    indent of the opening bracket (E12x), when a token follows the bracket: an
    under-indented line is pushed out to that column and an over-indented one is
    pulled back to it."""
    rc, out, err = fmt([], "foo = dict(a=1,\n    b=2,\n              c=3)\n")
    assert rc == 0, err
    assert out == "foo = dict(a=1,\n           b=2,\n           c=3)\n"


def test_hanging_indent():
    """When the opening bracket ends the line, mis-indented continuation lines are
    re-indented to a 4-space hanging indent (E12x hanging-indent branch)."""
    rc, out, err = fmt([], "foo = long_function_name(\n  var_one,\n  var_two)\n")
    assert rc == 0, err
    assert out == "foo = long_function_name(\n    var_one,\n    var_two)\n"


def test_e704_aggressive_level3():
    """E704 (a one-line ``def f(): return ...``) is only split with three
    --aggressive flags; at level 2 it is left untouched."""
    rc2, out2, err2 = fmt(["-aa"], "def f(): return 1\n")
    assert rc2 == 0, err2
    assert out2 == "def f(): return 1\n"

    rc3, out3, err3 = fmt(["-aaa"], "def f(): return 1\n")
    assert rc3 == 0, err3
    assert out3 == "def f():\n    return 1\n"


def test_e501_nested_reflow():
    """A too-long nested collection is reflowed recursively under -aa: each level
    of nesting places its elements one per line, indented by 4 per level, with each
    closing bracket attached to its last element."""
    src = "data = {'outer': {'inner_key_one': 111, 'inner_key_two': 222, 'inner_key_three': 333}}\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "data = {\n"
        "    'outer': {\n"
        "        'inner_key_one': 111,\n"
        "        'inner_key_two': 222,\n"
        "        'inner_key_three': 333}}\n"
    )


def test_e402_import_to_top():
    """With aggressive fixes, a module-level import that is not at the top of the
    file is moved above the preceding statement (E402)."""
    rc, out, err = fmt(["-aa"], "x = 1\nimport os\n")
    assert rc == 0, err
    assert out == "import os\nx = 1\n"


def test_comprehensive_readme():
    """The README's end-to-end example: with two --aggressive flags a thoroughly
    misformatted module is fully normalised -- imports split, comments spaced and
    wrapped, whitespace fixed, compound statements broken up, the nested literal
    reflowed, and the multiline string contents left untouched."""
    before = (
        'import math, sys;\n'
        '\n'
        'def example1():\n'
        '    ####This is a long comment. This should be wrapped to fit within 72 characters.\n'
        "    some_tuple=(   1,2, 3,'a'  );\n"
        "    some_variable={'long':'Long code lines should be wrapped within 79 characters.',\n"
        "    'other':[math.pi, 100,200,300,9876543210,'This is a long string that goes on'],\n"
        "    'more':{'inner':'This whole logical line should be wrapped.',some_tuple:[1,\n"
        '    20,300,40000,500000000,60000000000000000]}}\n'
        '    return (some_tuple, some_variable)\n'
        "def example2(): return process_data(first_value, second_value, third_value, fourth_value);\n"
        'class Example3(   object ):\n'
        '    def __init__    ( self, bar ):\n'
        '     #Comments should have a space after the hash.\n'
        '     if bar : bar+=1;  bar=bar* bar   ; return bar\n'
        '     else:\n'
        '                    some_string = """\n'
        '                       Indentation in multiline strings should not be touched.\n'
        'Only actual code should be reindented.\n'
        '"""\n'
        '                    return (sys.path, some_string)\n'
    )
    expected = (
        'import math\n'
        'import sys\n'
        '\n'
        '\n'
        'def example1():\n'
        '    # This is a long comment. This should be wrapped to fit within 72\n'
        '    # characters.\n'
        "    some_tuple = (1, 2, 3, 'a')\n"
        '    some_variable = {\n'
        "        'long': 'Long code lines should be wrapped within 79 characters.',\n"
        "        'other': [\n"
        '            math.pi,\n'
        '            100,\n'
        '            200,\n'
        '            300,\n'
        '            9876543210,\n'
        "            'This is a long string that goes on'],\n"
        "        'more': {\n"
        "            'inner': 'This whole logical line should be wrapped.',\n"
        '            some_tuple: [\n'
        '                1,\n'
        '                20,\n'
        '                300,\n'
        '                40000,\n'
        '                500000000,\n'
        '                60000000000000000]}}\n'
        '    return (some_tuple, some_variable)\n'
        '\n'
        '\n'
        "def example2(): return process_data(\n"
        "    first_value,\n"
        "    second_value,\n"
        "    third_value,\n"
        "    fourth_value)\n"
        '\n'
        '\n'
        'class Example3(object):\n'
        '    def __init__(self, bar):\n'
        '        # Comments should have a space after the hash.\n'
        '        if bar:\n'
        '            bar += 1\n'
        '            bar = bar * bar\n'
        '            return bar\n'
        '        else:\n'
        '            some_string = """\n'
        '                       Indentation in multiline strings should not be touched.\n'
        'Only actual code should be reindented.\n'
        '"""\n'
        '            return (sys.path, some_string)\n'
    )
    rc, out, err = fmt(["-aa"], before)
    assert rc == 0, err
    assert out == expected


def test_idempotent():
    """Formatting is a fixed point: running autopep8 on already-formatted output
    produces identical text."""
    src = "import os, sys\nx=1;y=2\n"
    rc, once, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert once == "import os\nimport sys\nx = 1\ny = 2\n"
    rc2, twice, err2 = fmt(["-aa"], once)
    assert rc2 == 0, err2
    assert twice == once


def test_multiline_string_preserved():
    """Code-like content inside a triple-quoted string is never reformatted, while
    the surrounding real code is (default mode)."""
    rc, out, err = fmt([], 'x="""\nkeep = this  ;exact\n"""\ny=2\n')
    assert rc == 0, err
    assert out == 'x = """\nkeep = this  ;exact\n"""\ny = 2\n'


# --------------------------------------------------------------------------- #
# Code selection and disable regions                                          #
# --------------------------------------------------------------------------- #

def test_select_specific_code():
    """``--select`` restricts fixing to the named code only: with ``--select=E225``
    the missing operator whitespace is fixed but the comma-joined import is left
    untouched."""
    rc, out, err = fmt(["--select=E225"], "import os,sys\nx=1\n")
    assert rc == 0, err
    assert out == "import os,sys\nx = 1\n"


def test_ignore_category():
    """``--ignore`` with a category prefix skips a whole family: ``--ignore=E1``
    leaves indentation untouched while still applying other fixes (E225)."""
    rc, out, err = fmt(["--ignore=E1"], "if True:\n  x=1\n")
    assert rc == 0, err
    assert out == "if True:\n  x = 1\n"


def test_fmt_off_on():
    """A ``# fmt: off`` ... ``# fmt: on`` region is left exactly as written while
    code after the region is still formatted."""
    rc, out, err = fmt([], "# fmt: off\na=1\n# fmt: on\nb=2\n")
    assert rc == 0, err
    assert out == "# fmt: off\na=1\n# fmt: on\nb = 2\n"


# --------------------------------------------------------------------------- #
# File modes and exit codes                                                    #
# --------------------------------------------------------------------------- #

def test_diff_mode(tmp_path):
    """``--diff`` prints a unified diff with ``original/<file>`` and
    ``fixed/<file>`` headers, leaves the file unmodified, and exits 0."""
    proc, after = run_file(["--diff"], tmp_path, "x=1\n")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        "--- original/m.py\n"
        "+++ fixed/m.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x = 1\n"
    )
    assert after == "x=1\n"  # --diff never edits


def test_in_place(tmp_path):
    """``--in-place`` rewrites the file with the fixed source, prints nothing, and
    (without --exit-code) exits 0."""
    proc, after = run_file(["--in-place"], tmp_path, "x=1\n")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert after == "x = 1\n"


def test_exit_code_flag(tmp_path):
    """``--exit-code`` makes the process return 2 when changes were made and 0 when
    the file is already correctly formatted."""
    proc_changed, after = run_file(["--in-place", "--exit-code"], tmp_path, "x=1\n")
    assert proc_changed.returncode == 2
    assert after == "x = 1\n"

    proc_clean, _ = run_file(["--diff", "--exit-code"], tmp_path, "x = 1\n", name="clean.py")
    assert proc_clean.returncode == 0
    assert proc_clean.stdout == ""


def test_stdin_exit_code_flag():
    """With ``--exit-code``, reading from stdin returns 2 when the source was changed
    (still writing the fixed source to stdout) and 0 when it was already formatted --
    the stdin ``--exit-code`` branch, distinct from the file / ``--in-place`` path."""
    rc_changed, out_changed, err = fmt(["--exit-code"], "x=1\n")
    assert rc_changed == 2, err
    assert out_changed == "x = 1\n"

    rc_clean, out_clean, err2 = fmt(["--exit-code"], "x = 1\n")
    assert rc_clean == 0, err2
    assert out_clean == "x = 1\n"


def test_cli_validation_errors(tmp_path):
    """Invalid argument combinations are rejected with the dedicated argparse exit
    code 99: no files given, ``--diff`` with stdin, ``--diff`` together with
    ``--in-place``, and ``--recursive`` without ``--in-place``/``--diff``."""
    no_files = subprocess.run(AP8, capture_output=True, text=True, cwd=_CLEAN_CWD)
    assert no_files.returncode == 99

    stdin_diff = subprocess.run(
        AP8 + ["--diff", "-"], input="x=1\n",
        capture_output=True, text=True, cwd=_CLEAN_CWD,
    )
    assert stdin_diff.returncode == 99

    path = tmp_path / "m.py"
    path.write_text("x=1\n")
    diff_inplace = subprocess.run(
        AP8 + ["--diff", "--in-place", "m.py"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert diff_inplace.returncode == 99

    recursive_no_mode = subprocess.run(
        AP8 + ["--recursive", "."],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert recursive_no_mode.returncode == 99


def test_io_error_exit_code(tmp_path):
    """A missing input file is an I/O error, which exits 1 (distinct from the
    argparse usage error 99 and the success code 0)."""
    proc = subprocess.run(
        AP8 + ["--diff", "no_such_file_xyz.py"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert proc.returncode == 1


def test_recursive_directory(tmp_path):
    """``--recursive`` with ``--in-place`` walks into sub-directories and fixes
    every ``.py`` file found (not just the top-level ones)."""
    (tmp_path / "a.py").write_text("x=1\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("y=2\n")

    proc = subprocess.run(
        AP8 + ["--recursive", "--in-place", "."],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "a.py").read_text() == "x = 1\n"
    assert (sub / "b.py").read_text() == "y = 2\n"


def test_line_range():
    """``--line-range`` / ``--range`` restricts fixing to the inclusive, 1-indexed
    range of line numbers; violations on lines outside the range are left
    untouched."""
    rc, out, err = fmt(["--line-range", "2", "2"], "x=1\ny=2\nz=3\n")
    assert rc == 0, err
    assert out == "x=1\ny = 2\nz=3\n"

    rc2, out2, err2 = fmt(["--range", "1", "2"], "x=1\ny=2\nz=3\n")
    assert rc2 == 0, err2
    assert out2 == "x = 1\ny = 2\nz=3\n"


def test_list_fixes():
    """``--list-fixes`` prints the supported codes, one per line as
    ``CODE - description``, covering representative fixes across the categories."""
    proc = subprocess.run(AP8 + ["--list-fixes"], capture_output=True, text=True,
                          cwd=_CLEAN_CWD)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    # Representative codes are pinned to their exact ``CODE - description`` line so a wrong or
    # empty description is caught, not merely the presence of the code letters.
    for expected in (
        "E101 - Reindent all lines.",
        "E225 - Fix missing whitespace around operator.",
        "E501 - Try to make lines fit within --max-line-length characters.",
        "W291 - Remove trailing whitespace.",
    ):
        assert expected in lines, f"{expected!r} missing from --list-fixes"
    # W605 is a supported fix whose --list-fixes entry carries no description text; assert it is
    # listed in the documented ``CODE - `` form rather than pinning an (empty) description.
    assert any(ln.startswith("W605 -") for ln in lines), "W605 missing from --list-fixes"


# --------------------------------------------------------------------------- #
# Continuation-line indentation (E12x) — exact alignment of bracketed exprs    #
# --------------------------------------------------------------------------- #

def test_e12_closing_bracket_visual_align():
    """With a visual indent (a token follows the opening bracket), the continuation
    lines AND a closing bracket left alone on its own line align to the column just
    after the opening bracket (E124/E128)."""
    rc, out, err = fmt([], "result = function(arg_one,\n                  arg_two,\n)\n")
    assert rc == 0, err
    assert out == "result = function(arg_one,\n                  arg_two,\n                  )\n"


def test_e12_nested_call_visual_indent():
    """Continuation alignment is computed per bracket: an inner call's argument aligns
    under the inner bracket while the outer call's later argument aligns under the
    outer bracket (nested visual indents)."""
    rc, out, err = fmt([], "foo = outer(inner(a=1,\n    b=2),\n    c=3)\n")
    assert rc == 0, err
    assert out == "foo = outer(inner(a=1,\n                  b=2),\n            c=3)\n"


def test_e12_def_params_hanging_indent():
    """When a def's parameter list opens with a hanging indent (the bracket ends the
    line), the parameters are indented EIGHT spaces (a double hang) so they are
    visually distinct from the four-space function body."""
    rc, out, err = fmt([], "def long_name(\n  a, b,\n  c):\n    pass\n")
    assert rc == 0, err
    assert out == "def long_name(\n        a, b,\n        c):\n    pass\n"


def test_e12_list_hanging_close_to_margin():
    """A hanging-indent list re-indents its elements to a 4-space hang and pulls a
    closing bracket alone on its line back to the statement's own indentation."""
    rc, out, err = fmt([], "items = [\n  1,\n  2,\n  ]\n")
    assert rc == 0, err
    assert out == "items = [\n    1,\n    2,\n]\n"


def test_e12_comment_in_continuation():
    """A comment line inside a bracketed continuation is re-indented to the same visual
    indent as the surrounding continuation lines."""
    rc, out, err = fmt([], "x = foo(a,\n    # note\n    b)\n")
    assert rc == 0, err
    assert out == "x = foo(a,\n        # note\n        b)\n"


# --------------------------------------------------------------------------- #
# More E501 long-line shortening shapes                                        #
# --------------------------------------------------------------------------- #

def test_e501_aggressive_def_signature_reflow():
    """Under -aa a too-long def signature is reflowed one parameter per line, each
    indented EIGHT spaces (the def double-hang), with the closing `):` attached to the
    last parameter."""
    src = "def my_function(first_parameter, second_parameter, third_parameter, fourth_parameter):\n    pass\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "def my_function(\n"
        "        first_parameter,\n"
        "        second_parameter,\n"
        "        third_parameter,\n"
        "        fourth_parameter):\n"
        "    pass\n"
    )


# --------------------------------------------------------------------------- #
# More aggressive semantic fixes                                               #
# --------------------------------------------------------------------------- #

def test_e402_imports_moved_above_code():
    """Under aggressive mode module-level imports placed after other code are moved up
    above that code (E402), kept below a leading module docstring. The mutual order of the
    relocated imports is an incidental artifact, so it is not asserted."""
    rc, out, err = fmt(["-aa"], "'''doc'''\nx = 1\nimport os\nimport sys\n")
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[0] == "'''doc'''"
    assert set(lines[1:3]) == {"import os", "import sys"}
    assert lines[3] == "x = 1"
    assert len(lines) == 4


def test_e712_not_equal_true_false():
    """The `!=` forms of E712 (level 2): `x != True` becomes `not x` and `y != False`
    becomes the plain truthy `y`."""
    rc, out, err = fmt(["-aa"], "if x != True:\n    pass\nif y != False:\n    pass\n")
    assert rc == 0, err
    assert out == "if not x:\n    pass\nif y:\n    pass\n"


def test_w605_multiple_invalid_escapes():
    """Level-1 aggressive fixes every invalid escape sequence in a string, including
    multiple escapes within one literal (W605): `'\\d+\\w*'` -> `'\\\\d+\\\\w*'`."""
    rc, out, err = fmt(["-a"], "import re\na = re.compile('\\d+\\w*')\nb = '\\s'\n")
    assert rc == 0, err
    assert out == "import re\na = re.compile('\\\\d+\\\\w*')\nb = '\\\\s'\n"


def test_combination_default_mode():
    """A second end-to-end combination in DEFAULT mode: comma imports split, block
    comment spaced, whitespace-before-colon removed, tab reindented, missing operator
    whitespace added, a semicolon-joined compound split (kept at block indent), excess
    blank lines trimmed to two, and call-signature whitespace fixed -- while a one-line
    `def ...: return` is LEFT intact (E704 needs three -a)."""
    src = "import os,sys\n#bad\nif True :\n\tx=1 ;y=2\n\n\n\ndef f( a ):return a\n"
    rc, out, err = fmt([], src)
    assert rc == 0, err
    assert out == (
        "import os\n"
        "import sys\n"
        "# bad\n"
        "if True:\n"
        "    x = 1\n"
        "    y = 2\n"
        "\n"
        "\n"
        "def f(a): return a\n"
    )


# --------------------------------------------------------------------------- #
# Bundled breadth: additional whitespace/comment codes (one exact output each) #
# --------------------------------------------------------------------------- #

def test_whitespace_codes_bundled():
    """A bundle of distinct whitespace codes, each on its own line, all normalised in
    one pass: multiple spaces before `=` collapse to one (E221), doubled spaces around
    a keyword collapse to one (E271/E272), whitespace before a `[` subscript is removed
    (E211), an inline comment gets two spaces before its hash (E261), and whitespace
    before a comma is removed while the required space after it is added (E203/E231)."""
    rc, out, err = fmt([], "x       = 1\ny = a  and  b\nz = d [1]\nw = 1 # c\nprint(a ,b)\n")
    assert rc == 0, err
    assert out == "x = 1\ny = a and b\nz = d[1]\nw = 1  # c\nprint(a, b)\n"


def test_comment_semicolon_backslash_blank_bundled():
    """A bundle of distinct codes: a block comment's extra leading hashes collapse to a
    single `# ` (E266), a redundant trailing semicolon is removed (E703), a backslash
    continuation that is redundant inside brackets is dropped (E502), and trailing
    blank lines at end of file are removed (W391)."""
    rc, out, err = fmt([], "## block\nx = 1;\ny = (1 + \\\n     2)\n\n\n")
    assert rc == 0, err
    assert out == "# block\nx = 1\ny = (1 +\n     2)\n"


# --------------------------------------------------------------------------- #
# More E12x continuation shapes (visual / nested / hanging / closing bracket)  #
# --------------------------------------------------------------------------- #


def test_e12_hanging_over_indented():
    """An over-indented hanging continuation (8 spaces under a call whose `(` ends the
    line) is pulled back to the 4-space hanging indent."""
    rc, out, err = fmt([], "result = func(\n        a,\n        b)\n")
    assert rc == 0, err
    assert out == "result = func(\n    a,\n    b)\n"


def test_e12_nested_hanging_list():
    """A list nested inside a hanging-indent list re-indents its own elements to 8 spaces
    (4 per nesting level), while the outer closing bracket stays at the margin."""
    rc, out, err = fmt([], "data = [\n    [\n  1,\n  2],\n]\n")
    assert rc == 0, err
    assert out == "data = [\n    [\n        1,\n        2],\n]\n"


# --------------------------------------------------------------------------- #
# More combinations and aggressive semantic fixes                              #
# --------------------------------------------------------------------------- #

def test_combination_aggressive_nested_class():
    """Aggressive combination cascading through nested indentation: a class/method header
    whitespace fixed, parameter comma spaced, `== None` -> `is None` (E711), the colon
    compound `if ...: return 0` split and re-indented, and `x+1` spaced (E225 under
    aggressive re-enables the arithmetic space)."""
    src = "class Foo :\n  def bar(self,x):\n   if x==None:return 0\n   return x+1\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "class Foo:\n"
        "    def bar(self, x):\n"
        "        if x is None:\n"
        "            return 0\n"
        "        return x + 1\n"
    )


def test_e711_multiple_none_comparisons():
    """Both None-comparison forms are fixed in one line at level 1: `== None` -> `is None`
    and `!= None` -> `is not None` (E711)."""
    rc, out, err = fmt(["-a"], "if a == None and b != None:\n    pass\n")
    assert rc == 0, err
    assert out == "if a is None and b is not None:\n    pass\n"


def test_e721_type_comparison_to_isinstance():
    """Under aggressive mode an E721 type comparison `type(x) == type(y)` is rewritten to
    `isinstance(x, type(y))`."""
    rc, out, err = fmt(["-aa"], "if type(x) == type(y):\n    pass\n")
    assert rc == 0, err
    assert out == "if isinstance(x, type(y)):\n    pass\n"


# --------------------------------------------------------------------------- #
# Multi-fix combinations (many fixes composed over a realistic module)         #
# --------------------------------------------------------------------------- #

def test_combination_class_module_default():
    """A default-mode class module: comma-import split (E401), missing blank lines before
    the class (E302) and one blank line between methods (E301), call/param/operator
    whitespace, whitespace before the method colon (E203), and a colon-compound `for`
    loop split (E701)."""
    src = (
        "import sys,os\n"
        "CONST=1\n"
        "class Worker( object ):\n"
        "    def __init__(self,name):\n"
        "        self.name=name\n"
        "    def run(self) :\n"
        "        for i in range(10): print(i)\n"
        "    def stop(self):\n"
        "        return True\n"
    )
    rc, out, err = fmt([], src)
    assert rc == 0, err
    assert out == (
        "import sys\n"
        "import os\n"
        "CONST = 1\n"
        "\n"
        "\n"
        "class Worker(object):\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "\n"
        "    def run(self):\n"
        "        for i in range(10):\n"
        "            print(i)\n"
        "\n"
        "    def stop(self):\n"
        "        return True\n"
    )


def test_combination_nested_func_default():
    """A nested function gains the one blank line PEP 8 wants before it (E306), a trailing
    semicolon is removed (E703), and parameter/`=` whitespace is fixed -- while the
    arithmetic `a+b`/`c*2` is left alone (E226 default-ignored)."""
    src = "def outer(a,b):\n    x=a+b\n    def inner( c ):\n        return c*2 ;\n    return inner(x)\n"
    rc, out, err = fmt([], src)
    assert rc == 0, err
    assert out == (
        "def outer(a, b):\n"
        "    x = a+b\n"
        "\n"
        "    def inner(c):\n"
        "        return c*2\n"
        "    return inner(x)\n"
    )


def test_e304_blank_line_after_decorator():
    """A blank line between a decorator and the function it decorates is removed
    (E304)."""
    rc, out, err = fmt([], "@my_decorator\n\ndef handler(x):\n    return x\n")
    assert rc == 0, err
    assert out == "@my_decorator\ndef handler(x):\n    return x\n"


def test_combination_dict_method_aggressive():
    """Aggressive combination: dict literal whitespace (E231/E203), `== None` -> `is None`
    (E711), and the colon-compound `if ...: return {}` split + re-indented."""
    src = "def build():\n    d={'a':1,'b':2}\n    if d['a']==None: return {}\n    return dict(d)\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "def build():\n"
        "    d = {'a': 1, 'b': 2}\n"
        "    if d['a'] is None:\n"
        "        return {}\n"
        "    return dict(d)\n"
    )


def test_combination_data_module_aggressive():
    """Aggressive combination: list/dict-comprehension whitespace (E231/E225), and a
    colon-compound `if ...: pass` split -- the comprehension's `==` is left as a valid
    comparison."""
    src = "data=[1,2,3]\nresult={k:v for k,v in zip(data,data)}\nif result=={}:pass\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "data = [1, 2, 3]\n"
        "result = {k: v for k, v in zip(data, data)}\n"
        "if result == {}:\n"
        "    pass\n"
    )


# --------------------------------------------------------------------------- #
# Long-line shortening — harder break-point / reflow shapes                    #
# --------------------------------------------------------------------------- #

def test_e501_default_backslash_subscript():
    """In default mode a too-long subscript `+`-expression with no breakable call bracket
    falls back to a backslash continuation: `+` stays at the end of line 1, `\\` after it,
    continuation indented 4."""
    src = "matrix_element = first_matrix[row_index][col_index] + second_matrix[row_index][col_i]\n"
    rc, out, err = fmt([], src)
    assert rc == 0, err
    assert out == (
        "matrix_element = first_matrix[row_index][col_index] + \\\n"
        "    second_matrix[row_index][col_i]\n"
    )


def test_e501_aggressive_backslash_fallback():
    """The backslash fallback also applies to the aggressive reflow: with -aa a too-long
    line that has no bracket to reflow inside keeps its binary operator at the end of the
    first line, puts `\\` after it, and indents the continuation by 4."""
    src = "combined = alpha_module.first_attribute_value + beta_module.second_attribute_values\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "combined = alpha_module.first_attribute_value + \\\n"
        "    beta_module.second_attribute_values\n"
    )


def test_e501_aggressive_reflow_in_method():
    """Under -aa a too-long call inside a method body is reflowed one argument per line at
    the method-body depth (the params land at 12 spaces = body 8 + 4)."""
    src = "class S:\n    def m(self):\n        return process(alpha_value, beta_value, gamma_value, delta_value, ep_value)\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "class S:\n"
        "    def m(self):\n"
        "        return process(\n"
        "            alpha_value,\n"
        "            beta_value,\n"
        "            gamma_value,\n"
        "            delta_value,\n"
        "            ep_value)\n"
    )


def test_e501_aggressive_nested_call_reflow():
    """Under -aa a too-long call whose first argument is itself a call reflows recursively:
    the outer call opens one argument per line at 4 spaces, and the inner call expands its
    own arguments one per line at 8 spaces."""
    src = "result = outer_function(inner_function(alpha, beta, gamma), another_arg, final_argument)\n"
    rc, out, err = fmt(["-aa"], src)
    assert rc == 0, err
    assert out == (
        "result = outer_function(\n"
        "    inner_function(\n"
        "        alpha,\n"
        "        beta,\n"
        "        gamma),\n"
        "    another_arg,\n"
        "    final_argument)\n"
    )


def test_e402_future_and_multiple_imports():
    """Under aggressive mode, module-level imports placed after code are moved up above the
    code (E402) while a leading `from __future__ import ...` stays at the very top. The mutual
    order of the relocated imports is an incidental artifact, so it is not asserted."""
    rc, out, err = fmt(["-aa"], "from __future__ import annotations\nx = 1\nimport os\nimport sys\n")
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[0] == "from __future__ import annotations"
    assert set(lines[1:3]) == {"import os", "import sys"}
    assert lines[3] == "x = 1"
    assert len(lines) == 4
