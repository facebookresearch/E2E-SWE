#!/usr/bin/env python3
"""Offline test driver for the bosphorus WRG task.

Enumerates CLI-behaviour checks against `/usr/local/bin/bosphorus` and emits a
CTRF-compatible JSON at the path in the environment variable CTRF_OUT (default:
/logs/verifier/ctrf.json) so the grader can compare passed against the declared total.

This driver is intentionally stdlib-only python3 (no pytest, no pypi) because
the offline eval container has no network access. Each test is a top-level
function whose name starts with `test_`; the runner sorts them, executes each,
records pass/fail plus a short message, and writes the aggregate CTRF at the
end. A single failing test only fails itself — the runner does not short-circuit.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BOSPHORUS = shutil.which("bosphorus") or "/usr/local/bin/bosphorus"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

CTRF_OUT = Path(os.environ.get("CTRF_OUT", "/logs/verifier/ctrf.json"))
PER_TEST_TIMEOUT_S = 60


# ------------------------------ helpers ------------------------------


def run_bosphorus(args, *, input_bytes=None, timeout=PER_TEST_TIMEOUT_S, cwd=None):
    """Invoke bosphorus with the given argv suffix, return CompletedProcess."""
    return subprocess.run(
        [BOSPHORUS, *args],
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        cwd=cwd,
    )


def parse_anf_output(text: str) -> dict:
    """Return {'fixed': [...], 'equiv': [...], 'unsat': bool, 'header': str}.

    Parses the bosphorus --anfwrite output, which is a sequence of three fenced
    sections (Fixed values / Equivalences / optional UNSAT block) plus a
    trailing `c UNSAT : <bool>` marker.
    """
    fixed = []
    equiv = []
    unsat = None
    header = ""
    section = None
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("c Executed arguments:"):
            header = stripped
            continue
        if stripped == "c -------------":
            continue
        if stripped == "c Fixed values":
            section = "fixed"
            continue
        if stripped == "c Equivalences":
            section = "equiv"
            continue
        if stripped.startswith("c UNSAT :"):
            unsat = stripped.endswith("true")
            section = None
            continue
        if stripped.startswith("c "):
            continue
        if not stripped:
            continue
        if section == "fixed":
            fixed.append(stripped)
        elif section == "equiv":
            equiv.append(stripped)
    return {
        "fixed": fixed,
        "equiv": equiv,
        "unsat": unsat,
        "header": header,
    }


def equiv_line_present(
    equiv: list, var_a: int, var_b: int, plus_one: bool = False
) -> bool:
    """True iff any equiv-block line encodes `x(a) XOR x(b) [+ 1] = 0`.

    Over GF(2) the two orderings `x(a) + x(b)` and `x(b) + x(a)` denote the same
    equivalence, and the printer's choice depends on which of the two variables
    is picked as the substitution 'pivot' — an implementation detail the spec
    does not pin. This helper accepts either. `plus_one=True` requires the
    ` + 1` suffix (encoding `x(a) = NOT x(b)`).
    """
    suffix = " + 1" if plus_one else ""
    forms = {
        f"x({var_a}) + x({var_b}){suffix}",
        f"x({var_b}) + x({var_a}){suffix}",
    }
    return bool(forms & set(equiv))


def equiv_line_present_triple(
    equiv: list, var_a: int, var_b: int, var_c: int, plus_one: bool = False
) -> bool:
    """True iff any equiv-block line encodes `x(a) XOR x(b) XOR x(c) [+ 1] = 0`.

    Same GF(2) rationale as ``equiv_line_present``: XOR is commutative and
    associative, so any of the six permutations of {a, b, c} is a valid
    printer output. Accepts all six.
    """
    from itertools import permutations

    suffix = " + 1" if plus_one else ""
    forms = {
        f"x({p[0]}) + x({p[1]}) + x({p[2]}){suffix}"
        for p in permutations([var_a, var_b, var_c])
    }
    return bool(forms & set(equiv))


def equiv_vars_connected(equiv: list, members) -> bool:
    """True iff every variable in `members` is proven mutually equivalent.

    Treats each equivalence-block line as edges among the `x(N)` variables it
    names and runs union-find over `members`. This checks the spec-level
    contract -- that the listed variables all collapse into a single
    equivalence class -- without pinning which variable each line uses as its
    representative, so a star (every member paired with the class minimum) and a
    chain encoding are both accepted (over GF(2) they denote the same class).
    """
    import re

    parent: dict = {}

    def find(v):
        parent.setdefault(v, v)
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for line in equiv:
        vs = [int(m) for m in re.findall(r"x\((\d+)\)", line)]
        for other in vs[1:]:
            parent[find(other)] = find(vs[0])
    return len({find(v) for v in members}) == 1


def parse_dimacs_cnf(text: str) -> dict:
    """Return {'header': (nvars, nclauses), 'clauses': [[int, ...], ...]}."""
    header = None
    clauses = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            # p cnf N M
            if len(parts) >= 4 and parts[0] == "p" and parts[1] == "cnf":
                header = (int(parts[2]), int(parts[3]))
            continue
        toks = line.split()
        if not toks:
            continue
        # A clause ends with " 0". Ignore trailing 0.
        if toks[-1] != "0":
            # bosphorus can emit an XOR-clause header "x " prefix; drop it
            if toks[0] == "x":
                toks = toks[1:]
            if toks and toks[-1] != "0":
                # not a well-formed clause; skip
                continue
        # drop the trailing 0
        clauses.append([int(t) for t in toks[:-1]])
    return {"header": header, "clauses": clauses}


# ------------------------------ tests ------------------------------

# Category A: CLI infrastructure ----------------------------------------


def test_help_and_version_cli_smoke():
    """--help prints all 5 option-group headers; --version exits 0 with output."""
    import re

    r = run_bosphorus(["--help"])
    assert r.returncode == 0, f"--help exit {r.returncode}: {r.stderr[:200]}"
    out = r.stdout.decode()
    # The spec names the five groups but leaves the header punctuation to the
    # implementation, so a trailing ':' is optional; the header must still be a
    # line of its own introducing the group's listing.
    for header in (
        "Main options",
        "CNF conversion",
        "XL",
        "ElimLin options",
        "SAT options",
    ):
        assert re.search(
            rf"^[ \t]*{re.escape(header)}:?[ \t]*$", out, re.M
        ), f"missing section header {header!r} in --help output"
    rv = run_bosphorus(["--version"])
    assert rv.returncode == 0, f"--version exit {rv.returncode}"
    assert len(rv.stdout.strip()) > 0, "--version produced no stdout"


def test_no_input_file_errors():
    """With neither --anfread nor --cnfread, bosphorus exits non-zero."""
    r = run_bosphorus([])
    assert r.returncode != 0, "no-input should have failed but exited 0"


def test_both_inputs_error():
    """Providing both --anfread and --cnfread is a user error."""
    anf = FIXTURES_DIR / "simple.anf"
    cnf = FIXTURES_DIR / "mini.cnf"
    r = run_bosphorus(["--anfread", str(anf), "--cnfread", str(cnf)])
    assert r.returncode != 0, "providing both inputs should error"


def test_unknown_option_errors():
    """A bogus flag is a user error."""
    anf = FIXTURES_DIR / "simple.anf"
    r = run_bosphorus(["--anfread", str(anf), "--wibblewobble"])
    assert r.returncode != 0, "unknown --wibblewobble should error"


# Category B: Range checks ----------------------------------------------


def test_cutnum_too_low_errors():
    """--cutnum < 3 must be rejected (documented 3..10)."""
    anf = FIXTURES_DIR / "simple.anf"
    r = run_bosphorus(
        ["--anfread", str(anf), "--cutnum", "2", "--anfwrite", "/dev/null"]
    )
    assert r.returncode != 0, "--cutnum 2 should error"


def test_xldeg_too_high_errors():
    """--xldeg > 3 must be rejected (documented 0..3)."""
    anf = FIXTURES_DIR / "simple.anf"
    r = run_bosphorus(
        ["--anfread", str(anf), "--xldeg", "5", "--anfwrite", "/dev/null"]
    )
    assert r.returncode != 0, "--xldeg 5 should error"


def test_karn_too_high_errors():
    """--karn > 20 must be rejected."""
    anf = FIXTURES_DIR / "simple.anf"
    r = run_bosphorus(
        ["--anfread", str(anf), "--karn", "25", "--anfwrite", "/dev/null"]
    )
    assert r.returncode != 0, "--karn 25 should error"


# Category C: ANF parsing -----------------------------------------------


def test_parse_paren_syntax_equals_bare():
    """`x(1) + x(2)` produces the same equivalence as `x1 + x2`."""
    r1 = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "simple.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    r2 = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "paren.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r1.returncode == 0 and r2.returncode == 0
    p1 = parse_anf_output(r1.stdout.decode())
    p2 = parse_anf_output(r2.stdout.decode())
    # Two files with identical polynomials (just differing in surface notation)
    # must produce identical Fixed and Equivalences blocks.
    assert p1["fixed"] == p2["fixed"]
    assert p1["equiv"] == p2["equiv"]
    # And the recovered equivalence is between vars 1 and 2 (either ordering).
    assert equiv_line_present(
        p1["equiv"], 1, 2
    ), f"expected an equivalence between x(1) and x(2), got {p1['equiv']}"
    # The output header echoes the CLI argv[1:] (excluding argv[0]).
    assert p1["header"].startswith("c Executed arguments:")
    assert "--anfread" in p1["header"] and "simple.anf" in p1["header"]


def test_parse_malformed_paren_errors():
    """A file with `(x1))` is malformed and must be rejected."""
    r = run_bosphorus(
        ["--anfread", str(FIXTURES_DIR / "paren_bad.anf"), "--anfwrite", "/dev/null"]
    )
    assert r.returncode != 0, "malformed parens should fail"


def test_comment_lines_ignored():
    """Lines starting with `c ` are comments and don't produce polynomials."""
    with tempfile.NamedTemporaryFile("w", suffix=".anf", delete=False) as f:
        f.write("c a comment\n")
        f.write("c another comment\n")
        f.write("x1 + x2\n")
        f.write("c a trailing comment\n")
        path = f.name
    try:
        r = run_bosphorus(
            [
                "--anfread",
                path,
                "--anfwrite",
                "/dev/stdout",
                "--el",
                "0",
                "--xl",
                "0",
                "--sat",
                "0",
            ]
        )
        assert r.returncode == 0
        out = parse_anf_output(r.stdout.decode())
        assert equiv_line_present(
            out["equiv"], 1, 2
        ), f"comments should not perturb equivalence x(1)~x(2), got {out['equiv']}"
    finally:
        os.unlink(path)


# Category D: Trivial simplification ------------------------------------


def test_fixed_var_zero():
    """`x1` alone sets x1 = 0 (Fixed values block contains `x(1)`)."""
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "fixed_zero.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r.returncode == 0
    out = parse_anf_output(r.stdout.decode())
    assert "x(1)" in out["fixed"], f"expected x(1) in fixed, got {out['fixed']}"
    assert "x(1) + 1" not in out["fixed"]


def test_fixed_var_one():
    """`x1 + 1` sets x1 = 1 (Fixed values block contains `x(1) + 1`)."""
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "fixed_one.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r.returncode == 0
    out = parse_anf_output(r.stdout.decode())
    assert "x(1) + 1" in out["fixed"], f"expected x(1) + 1 in fixed, got {out['fixed']}"


# Category E: ElimLin ---------------------------------------------------


def test_elimlin_el_fixture():
    """el.anf reduces (with --el 1) to fixed x(2)=1 and a 3-term equivalence over x1/x3."""
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "el.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "1",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r.returncode == 0
    out = parse_anf_output(r.stdout.decode())
    assert (
        "x(2) + 1" in out["fixed"]
    ), f"el.anf expected fixed x(2)+1, got {out['fixed']}"
    # The recovered fact is `x1 XOR x3 XOR 1 = 0` -- either variable ordering
    # is a valid printer output (GF(2) XOR is commutative).
    assert equiv_line_present(
        out["equiv"], 1, 3, plus_one=True
    ), f"el.anf expected equiv 'x(1) + x(3) + 1' (either ordering), got {out['equiv']}"


# Category F: XL --------------------------------------------------------


def test_xl_fixture_fully_solves():
    """xl.anf reduces (with --xl 1) to fixed x(1)=1, x(2)=0, x(3)=0."""
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "xl.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "1",
            "--sat",
            "0",
        ]
    )
    assert r.returncode == 0
    out = parse_anf_output(r.stdout.decode())
    assert (
        "x(1) + 1" in out["fixed"]
    ), f"xl.anf expected fixed x(1)+1, got {out['fixed']}"
    assert "x(2)" in out["fixed"], f"xl.anf expected fixed x(2), got {out['fixed']}"
    assert "x(3)" in out["fixed"], f"xl.anf expected fixed x(3), got {out['fixed']}"


def test_all_passes_off_leaves_only_direct_facts():
    """xl.anf with --el 0 --xl 0 --sat 0 does NOT fully solve.

    Trivial linear substitution alone can't crack a bilinear system, so with
    all three simplification passes off we expect the fixed/equiv blocks to
    NOT contain x(2)=0 (only XL/SAT can prove it from these polynomials).
    """
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "xl.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r.returncode == 0
    out = parse_anf_output(r.stdout.decode())
    # With no simplification passes, bosphorus can't prove x(2)=0.
    assert (
        "x(2)" not in out["fixed"]
    ), f"xl.anf with all passes off should NOT have fixed x(2), got {out['fixed']}"


# Category G: ANF -> CNF conversion -------------------------------------


def test_cnf_output_wellformed_dimacs():
    """`--cnfwrite --simplify 0` on a nonlinear ANF emits well-formed DIMACS that is *also* equisatisfiable.

    ternary.anf (`x0*x1 + x2 + 1`, `x0 + x1 + 1`) is the only --cnfwrite fixture with a
    nonlinear monomial. We pass `--simplify 0` so the simplify loop (which otherwise eliminates
    x0/x2 by linear substitution and strips the nonlinear term before conversion) is off and the
    `x0*x1` monomial actually reaches the ANF->CNF encoder. Beyond DIMACS shape (a `p cnf N M`
    header over the 3 un-simplified input variables plus clauses of nonzero ints), we feed the
    produced CNF to an independent solver: ternary.anf is satisfiable ((x0,x1,x2) ∈
    {(0,1,1),(1,0,1)}), so a correct conversion yields a SAT CNF, while a well-formed CNF that
    silently drops the nonlinear x0*x1 constraint would be caught.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as f:
        cnf_path = f.name
    try:
        r = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "ternary.anf"),
                "--cnfwrite",
                cnf_path,
                "--simplify",
                "0",
            ]
        )
        assert r.returncode == 0, f"--cnfwrite exit {r.returncode}: {r.stderr[:200]}"
        parsed = parse_dimacs_cnf(Path(cnf_path).read_text())
        assert parsed["header"] is not None, "no `p cnf N M` header"
        nvars, nclauses = parsed["header"]
        # With --simplify 0 nothing is eliminated, so all 3 input variables are encoded.
        assert nvars >= 3, f"expected >=3 vars, got {nvars}"
        assert nclauses >= 1, f"expected >=1 clauses, got {nclauses}"
        assert parsed["clauses"], "no clauses parsed"
        for c in parsed["clauses"]:
            assert c, "empty clause body in DIMACS output"
            for lit in c:
                assert lit != 0, "literal 0 leaked into clause body"
        # Equisatisfiability check via an independent oracle: a semantically-broken but
        # well-formed CNF (e.g. one that dropped the x0*x1 monomial) is caught here.
        cms = subprocess.run(
            ["/usr/bin/cryptominisat5", cnf_path],
            capture_output=True,
            timeout=60,
        )
        assert cms.returncode == 10, (
            f"cryptominisat5 should judge the CNF of the satisfiable ternary.anf as "
            f"SAT (exit 10); got exit {cms.returncode}"
        )
    finally:
        os.unlink(cnf_path)


# Category H: CNF -> ANF chunking ---------------------------------------


def test_cnfread_produces_anf_output():
    """--cnfread <dimacs> recovers an ANF that preserves the CNF's satisfiability.

    mini.cnf is `(x1 OR x2) AND (NOT x1 OR x3)`, which is satisfiable, so the ANF
    recovered from it must (a) not be marked UNSAT and (b) be judged SATISFIABLE when
    solved. Asserting the solve verdict — not just the `c UNSAT : false` marker —
    verifies the CNF's clauses actually survived the CNF->ANF translation: an
    implementation that drops them (yielding an empty/vacuous ANF) is caught.
    """
    r = run_bosphorus(
        [
            "--cnfread",
            str(FIXTURES_DIR / "mini.cnf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r.returncode == 0, f"--cnfread exit {r.returncode}: {r.stderr[:200]}"
    out = parse_anf_output(r.stdout.decode())
    assert (
        out["unsat"] is False
    ), f"mini.cnf is SAT; expected UNSAT=false, got {out['unsat']}"
    r_solve = run_bosphorus(
        [
            "--cnfread",
            str(FIXTURES_DIR / "mini.cnf"),
            "--solve",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert (
        r_solve.returncode == 0
    ), f"--cnfread --solve exit {r_solve.returncode}: {r_solve.stderr[:200]}"
    assert "s ANF-SATISFIABLE" in r_solve.stdout.decode(), (
        f"mini.cnf is SAT; the ANF recovered from it must solve SATISFIABLE, "
        f"got tail:\n{r_solve.stdout.decode()[-400:]}"
    )


# Category I: SAT solving -----------------------------------------------


def test_solve_satisfiable_prints_answer():
    """`--solve` on a satisfiable ANF prints ANF-SATISFIABLE + a v line."""
    r = run_bosphorus(["--anfread", str(FIXTURES_DIR / "sat_solvable.anf"), "--solve"])
    assert r.returncode == 0, f"--solve exit {r.returncode}: {r.stderr[:200]}"
    out = r.stdout.decode()
    assert "s ANF-SATISFIABLE" in out, f"no SATISFIABLE line: {out[-300:]}"
    # x0=1 is forced by `x0 + 1 = 0`; must appear as `1+x(0)`.
    assert (
        "1+x(0)" in out
    ), f"expected 1+x(0) in v line (x0 forced to 1), got:\n{out[-400:]}"


def test_solve_unsatisfiable_reported():
    """The trivially-UNSAT `1` ANF is reported UNSAT in the anfwrite output."""
    # We must ask for --anfwrite so the `c UNSAT : true` marker is actually
    # emitted; --solve alone would only print the SAT-solver's verdict (which
    # for a preprocessed-empty-CNF is vacuously SATISFIABLE and not the
    # observable contract we care about here).
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "unsat.anf"),
            "--anfwrite",
            "/dev/stdout",
        ]
    )
    out = parse_anf_output(r.stdout.decode())
    assert (
        out["unsat"] is True
    ), f"unsat.anf should report c UNSAT : true, got unsat={out['unsat']}"


def test_solvewrite_file_format():
    """`--solvewrite <file>` writes `Solution SAT\\nv 0 -1 …` on success."""
    with tempfile.NamedTemporaryFile("w", suffix=".sol", delete=False) as f:
        sol_path = f.name
    try:
        r = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "sat_solvable.anf"),
                "--solvewrite",
                sol_path,
            ]
        )
        assert r.returncode == 0, f"--solvewrite exit {r.returncode}"
        text = Path(sol_path).read_text()
        assert "Solution SAT" in text, f"missing 'Solution SAT' line in {text!r}"
        # A `v ` line with signed integers.
        v_lines = [line for line in text.splitlines() if line.startswith("v ")]
        assert v_lines, f"no 'v ' line in {text!r}"
        tokens = v_lines[0].split()[1:]
        assert all(
            t.lstrip("-").isdigit() for t in tokens
        ), f"non-integer token in v line: {tokens!r}"
        # sat_solvable.anf forces x0 = true (`x0 + 1 = 0`). In the CNF-style
        # solution a true variable k is the unsigned literal `k`, so variable 0
        # must appear as `0` (never `-0`) -- pinning the actual solved value,
        # not merely the line shape.
        assert "0" in tokens and "-0" not in tokens, (
            f"x0 is forced true, so the v line must contain `0` (unsigned) and "
            f"not `-0`; got {tokens!r}"
        )
    finally:
        os.unlink(sol_path)


# Category J: Pipeline --------------------------------------------------


def test_full_pipeline_anf_cnf_sol():
    """--anfread + --cnfwrite + --solvewrite all produce their own files."""
    with tempfile.TemporaryDirectory() as td:
        cnf_out = f"{td}/out.cnf"
        sol_out = f"{td}/out.sol"
        r = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "sat_solvable.anf"),
                "--cnfwrite",
                cnf_out,
                "--solvewrite",
                sol_out,
            ]
        )
        assert r.returncode == 0
        assert Path(cnf_out).exists() and Path(cnf_out).stat().st_size > 0
        assert Path(sol_out).exists() and Path(sol_out).stat().st_size > 0
        cnf_text = Path(cnf_out).read_text()
        assert (
            parse_dimacs_cnf(cnf_text)["header"] is not None
        ), "cnf output missing `p cnf N M` header"
        assert "Solution SAT" in Path(sol_out).read_text()


def test_simplify_zero_disables_simplification():
    """--simplify 0 leaves the ANF fixed/equivalences blocks empty."""
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "el.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--simplify",
            "0",
        ]
    )
    assert r.returncode == 0
    out = parse_anf_output(r.stdout.decode())
    # el.anf normally yields fixed x(2)+1. With simplify off, nothing learned.
    assert (
        "x(2) + 1" not in out["fixed"]
    ), f"--simplify 0 should NOT learn any facts, but got fixed {out['fixed']}"


# Category K: Output structure ------------------------------------------


def test_unsat_ternary_via_all_passes():
    """`x1*x2 + x3` + `x1 + x2 + 1` + `x3` — SAT, with the concrete derived facts pinned.

    With all passes on the system is satisfiable (x3=0 forces x1*x2=0, and x1+x2=1 forces
    exactly one of x1/x2 true, so x1*x2=0 holds). Beyond the `c UNSAT : false` verdict the
    simplified output is fully determined: x3 is a fixed value (0) and x1+x2+1=0 collapses
    x1/x2 into the equal-to-negation equivalence x1 = NOT x2. Asserting those facts (not just
    the boolean marker) catches a simplifier that is subtly wrong yet still reports SAT.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".anf", delete=False) as f:
        f.write("x1*x2 + x3\n")
        f.write("x1 + x2 + 1\n")
        f.write("x3\n")
        path = f.name
    try:
        r = run_bosphorus(["--anfread", path, "--anfwrite", "/dev/stdout"])
        assert r.returncode == 0
        out = parse_anf_output(r.stdout.decode())
        assert out["unsat"] is False, f"expected SAT for this system, got UNSAT"
        # x3 is proven equal to 0 -> a fixed value written `x(3)` (no `+ 1` suffix).
        assert "x(3)" in out["fixed"], (
            f"expected x(3) fixed to 0 with all passes on, got fixed {out['fixed']}"
        )
        # x1 + x2 + 1 = 0 forces x1 = NOT x2 -> equal-to-negation equivalence
        # `x(1) + x(2) + 1` (either GF(2) ordering).
        assert equiv_line_present(out["equiv"], 1, 2, plus_one=True), (
            f"expected equal-to-negation equivalence 'x(1) + x(2) + 1' (either ordering), "
            f"got equiv {out['equiv']}"
        )
    finally:
        os.unlink(path)


def test_solve_hard_returns_valid_solution():
    """hard.anf is 3-vars 3-eqs and definitively SAT — solver must report SATISFIABLE
    and print x1 forced true in the assignment."""
    r = run_bosphorus(["--anfread", str(FIXTURES_DIR / "hard.anf"), "--solve"])
    assert r.returncode == 0, f"hard.anf solve exit {r.returncode}"
    out = r.stdout.decode()
    # hard.anf's only satisfying assignments are (x0,x1,x2) = (0,1,0) and (1,1,1), so
    # the only correct verdict is SATISFIABLE; a solver that wrongly reports UNSAT fails.
    assert (
        "s ANF-SATISFIABLE" in out
    ), f"expected an ANF-SATISFIABLE line for a satisfiable system, got tail:\n{out[-400:]}"
    # x1 is true in *every* model of hard.anf, so a correct solver must print it as
    # `1+x(1)` in the v line. This pins a real computed solution value rather than
    # relying on the binary's internal self-check.
    assert (
        "1+x(1)" in out
    ), f"expected x1 forced true (`1+x(1)`) in the solution, got tail:\n{out[-400:]}"


def test_solvewrite_unsat_reports_unsat_line():
    """`--solvewrite` on an UNSAT problem writes `Solution UNSAT` to the file."""
    with tempfile.NamedTemporaryFile("w", suffix=".sol", delete=False) as f:
        sol_path = f.name
    try:
        # Feed an obviously UNSAT ANF: `x1 + 1` (x1=1) and `x1` (x1=0) together.
        with tempfile.NamedTemporaryFile("w", suffix=".anf", delete=False) as af:
            af.write("x1 + 1\n")
            af.write("x1\n")
            anf_path = af.name
        r = run_bosphorus(["--anfread", anf_path, "--solvewrite", sol_path])
        text = Path(sol_path).read_text()
        assert (
            "Solution UNSAT" in text
        ), f"expected 'Solution UNSAT' in solve file, got {text!r}"
    finally:
        os.unlink(sol_path)
        os.unlink(anf_path)


def test_two_var_two_sol_lists_three_assignments():
    """`--allsol` on x1*x2=0 enumerates ALL THREE distinct satisfying assignments.

    Over {x1, x2}, x1*x2=0 has three satisfying points: (0,0), (0,1), (1,0).
    bosphorus must emit exactly three s-lines and a trailing count of 3.
    """
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "two_vars_two_sol.anf"),
            "--solve",
            "--allsol",
        ]
    )
    assert r.returncode == 0
    out = r.stdout.decode()
    sat_lines = [ln for ln in out.splitlines() if ln.strip() == "s ANF-SATISFIABLE"]
    assert len(sat_lines) == 3, (
        f"expected exactly 3 satisfying assignments for x1*x2=0, "
        f"got {len(sat_lines)}\n{out[-500:]}"
    )
    # The trailing summary line should read "c Number of solutions found: 3".
    assert (
        "Number of solutions found: 3" in out
    ), f"expected count-of-3 summary, got:\n{out[-300:]}"


# Category M: ElimLin depth ---------------------------------------------
#
# These fixtures start with only degree-2 polynomials (no linear seeds), so the
# trivial linear-substitution path cannot make progress. Only ElimLin's Gauss-
# Jordan on the coefficient matrix over GF(2) can produce the expected linear
# consequences. --el 0 gives us the negative-control.


def test_elimlin_multi_recovers_two_pair_equivalences():
    """Two degree-2 polys sharing a bilinear monomial -> ElimLin GJ derives 2 equivalences.

    Fixture (`elimlin_multi.anf`):
        x1*x2 + x1 + x2
        x1*x2 + x1 + x3
        x1*x2 + x2 + x4

    Pivoting on x1*x2 (a single column in the GJ matrix over GF(2)):
        row1 XOR row2 = x2 + x3       -> equivalence x(3) + x(2)
        row1 XOR row3 = x1 + x4       -> equivalence x(4) + x(1)
    """
    r_on = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "elimlin_multi.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "1",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r_on.returncode == 0, f"--el 1 exit {r_on.returncode}"
    out_on = parse_anf_output(r_on.stdout.decode())
    # XOR is commutative, so either printer ordering of each equivalence counts.
    assert equiv_line_present(out_on["equiv"], 2, 3), (
        f"expected equivalence between x(2) and x(3) from ElimLin GJ pivot on "
        f"x1*x2, got {out_on['equiv']}"
    )
    assert equiv_line_present(out_on["equiv"], 1, 4), (
        f"expected equivalence between x(1) and x(4) from ElimLin GJ pivot on "
        f"x1*x2, got {out_on['equiv']}"
    )

    # Negative control: with ElimLin off, trivial linear substitution alone can
    # NOT derive either equivalence (no linear polynomial in the input).
    r_off = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "elimlin_multi.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r_off.returncode == 0
    out_off = parse_anf_output(r_off.stdout.decode())
    assert not equiv_line_present(out_off["equiv"], 2, 3), (
        f"linear substitution alone should NOT recover x(2)~x(3) equivalence, "
        f"got {out_off['equiv']}"
    )
    assert not equiv_line_present(out_off["equiv"], 1, 4), (
        f"linear substitution alone should NOT recover x(1)~x(4) equivalence, "
        f"got {out_off['equiv']}"
    )


def test_elimlin_5var_cascades_via_gj_substitution():
    """6-var 4-poly system: ElimLin's GJ + iterative back-substitution yields 3 equivalences.

    Fixture (`elimlin_5var.anf`):
        x0*x1 + x2
        x0*x1 + x3
        x2*x3 + x4
        x2*x3 + x5

    ElimLin's first Gauss-Jordan pass pivots on x0*x1 and learns x2+x3=0, giving
    equivalence x(3)+x(2). It then substitutes x2 for x3 in the remaining polys,
    which (using x*x=x over GF(2)) collapses x2*x3 to x2 and produces the linear
    equations x2+x4=0 and x2+x5=0 -> equivalences x(4)+x(2) and x(5)+x(2).

    Result: x2, x3, x4, x5 all collapse into a single equivalence class. The
    spec does not pin which variable each equivalence line names as its
    representative, so we assert only that the printed equivalences' transitive
    closure identifies {x2,x3,x4,x5} as one class (a star rooted at the minimum
    and a chain are both valid encodings). --el 0 recovers none of them.
    """
    r_on = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "elimlin_5var.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "1",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r_on.returncode == 0
    out_on = parse_anf_output(r_on.stdout.decode())
    # ElimLin's GJ cascade must prove x2, x3, x4, x5 all mutually equivalent
    # (one class). Which variable each line names as the class representative is
    # not pinned by the spec, so accept any set of equivalence lines whose
    # transitive closure collapses {x2,x3,x4,x5} into a single class.
    assert equiv_vars_connected(out_on["equiv"], [2, 3, 4, 5]), (
        f"ElimLin GJ+substitution should prove x2,x3,x4,x5 all mutually "
        f"equivalent (one class); got equivalences {out_on['equiv']}"
    )

    # Negative control: with ElimLin off, none of the three equivalences appear.
    r_off = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "elimlin_5var.anf"),
            "--anfwrite",
            "/dev/stdout",
            "--el",
            "0",
            "--xl",
            "0",
            "--sat",
            "0",
        ]
    )
    assert r_off.returncode == 0
    out_off = parse_anf_output(r_off.stdout.decode())
    for a, b in [(2, 3), (2, 4), (2, 5)]:
        assert not equiv_line_present(out_off["equiv"], a, b), (
            f"--el 0 should NOT recover equivalence between x({a}) and x({b}); "
            f"got {out_off['equiv']}"
        )


# Category N: CNF conversion completeness --------------------------------
#
# Exercises the two documented ANF -> CNF encoding paths (Brickenstein + monomial-
# encoding fallback) and the --cutnum cutting-point aux-var machinery. Also
# verifies equisatisfiability end-to-end by feeding the produced CNF into the
# pre-installed cryptominisat5 CLI (an independent oracle).


def _read_cnf_header(cnf_path: Path) -> tuple:
    """Return the first (nvars, nclauses) `p cnf N M` header in `cnf_path`."""
    for line in cnf_path.read_text().splitlines():
        if line.startswith("p cnf"):
            _, _, nv, nc = line.split()
            return int(nv), int(nc)
    return None


def test_cnf_cutnum_3_introduces_aux_var_and_shortens_clauses():
    """--cutnum 3 on a 5-lit XOR splits it into chunks joined by an auxiliary variable.

    Fixture: `x0 + x1 + x2 + x3 + x4 = 0`.

    We pass `--simplify 0` so the raw 5-literal XOR reaches the ANF->CNF cutter
    unmodified; the always-on linear-substitution pass would otherwise consume
    this sole linear equation before conversion (its fate as a lone equation is
    left to the implementation), leaving nothing for --cutnum to cut. Disabling
    simplification isolates the documented --cutnum cutting behavior.

    With --cutnum 5 the whole XOR fits in one chunk, so it is expanded without
    cutting and the widest clause spans all 5 literals. With --cutnum 3 it no
    longer fits and must be cut, which (a) forces at least one fresh auxiliary
    variable to bridge the chunks and (b) makes the widest emitted clause
    narrower than the uncut one. How many chunks the cut uses -- and hence the
    total clause count -- is left to the implementation, so only those two
    consequences are asserted.
    """
    with tempfile.TemporaryDirectory() as td:
        big = f"{td}/big.cnf"
        r_big = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "xor_chain.anf"),
                "--cnfwrite",
                big,
                "--simplify",
                "0",
                "--el",
                "0",
                "--xl",
                "0",
                "--sat",
                "0",
                "--cutnum",
                "5",
            ]
        )
        assert r_big.returncode == 0, f"--cutnum 5 exit {r_big.returncode}"
        nv_big, _nc_big = _read_cnf_header(Path(big))
        widest_big = max(
            (len(c) for c in parse_dimacs_cnf(Path(big).read_text())["clauses"]), default=0
        )

        small = f"{td}/small.cnf"
        r_small = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "xor_chain.anf"),
                "--cnfwrite",
                small,
                "--simplify",
                "0",
                "--el",
                "0",
                "--xl",
                "0",
                "--sat",
                "0",
                "--cutnum",
                "3",
            ]
        )
        assert r_small.returncode == 0, f"--cutnum 3 exit {r_small.returncode}"
        nv_small, _nc_small = _read_cnf_header(Path(small))
        widest_small = max(
            (len(c) for c in parse_dimacs_cnf(Path(small).read_text())["clauses"]), default=0
        )

    assert nv_small > nv_big, (
        f"--cutnum 3 should introduce at least one auxiliary variable; "
        f"cutnum=5 nvars={nv_big}, cutnum=3 nvars={nv_small}"
    )
    assert widest_small < widest_big, (
        f"--cutnum 3 should cut the XOR into narrower clauses than --cutnum 5; "
        f"widest clause: cutnum=5 {widest_big} literals, cutnum=3 {widest_small} literals"
    )


def test_cnf_brickenstein_more_compact_than_monomial_encoding():
    """--karn 8 (Brickenstein) yields fewer CNF vars+clauses than --karn 0 (monomial encoding).

    Fixture: `x0*x1*x2 + x0 + 1 = 0` (small non-linear, support 3, well within
    the default --karn cutoff of 8).

    With --karn 8 the Brickenstein path enumerates the 3 satisfying assignments
    over {x0,x1,x2} and emits a compact CNF that has exactly those models — no
    auxiliary variable is needed. With --karn 0 the Brickenstein path is
    disabled and the polynomial falls back to the monomial-encoding: a fresh
    CNF variable is introduced for the monomial x0*x1*x2, linked to its
    factors by clauses, and the XOR is emitted separately. Result: strictly
    more CNF variables and clauses.
    """
    with tempfile.TemporaryDirectory() as td:
        brk = f"{td}/brk.cnf"
        r_brk = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "nonlin_small.anf"),
                "--cnfwrite",
                brk,
                "--el",
                "0",
                "--xl",
                "0",
                "--sat",
                "0",
                "--karn",
                "8",
            ]
        )
        assert r_brk.returncode == 0, f"--karn 8 exit {r_brk.returncode}"
        nv_brk, nc_brk = _read_cnf_header(Path(brk))

        mono = f"{td}/mono.cnf"
        r_mono = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "nonlin_small.anf"),
                "--cnfwrite",
                mono,
                "--el",
                "0",
                "--xl",
                "0",
                "--sat",
                "0",
                "--karn",
                "0",
            ]
        )
        assert r_mono.returncode == 0, f"--karn 0 exit {r_mono.returncode}"
        nv_mono, nc_mono = _read_cnf_header(Path(mono))

    assert nv_brk < nv_mono, (
        f"Brickenstein (--karn 8) should use fewer CNF vars than monomial-encoding "
        f"(--karn 0); brk_nvars={nv_brk}, mono_nvars={nv_mono}"
    )
    assert nc_brk < nc_mono, (
        f"Brickenstein (--karn 8) should emit fewer clauses than monomial-encoding "
        f"(--karn 0); brk_nclauses={nc_brk}, mono_nclauses={nc_mono}"
    )


def test_cnf_equisatisfiable_with_input_ANF_unsat_case():
    """An UNSAT ANF -> CNF must be judged UNSAT by an independent CNF solver.

    Fixture `unsat.anf` is the constant polynomial `1` (i.e. `1 = 0`), which
    is trivially UNSAT. The emitted CNF must therefore be judged UNSAT by
    cryptominisat5 (exit code 20). If the conversion silently dropped the
    constant-`1` UNSAT witness, the CNF would be trivially SAT (exit 10) and
    this test would catch it.
    """
    with tempfile.TemporaryDirectory() as td:
        cnf = f"{td}/out.cnf"
        r = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "unsat.anf"),
                "--cnfwrite",
                cnf,
                "--el",
                "0",
                "--xl",
                "0",
                "--sat",
                "0",
            ]
        )
        assert r.returncode == 0, f"--cnfwrite exit {r.returncode}"
        cms = subprocess.run(
            ["/usr/bin/cryptominisat5", cnf],
            capture_output=True,
            timeout=60,
        )
        assert cms.returncode == 20, (
            f"cryptominisat5 should judge the CNF of an UNSAT ANF as UNSAT (exit 20); "
            f"got exit {cms.returncode}"
        )


# Category O: Solution enumeration + variable-lineage mapping ------------


def test_solmap_writes_variable_lineage_trace():
    """`--solmap <file>` records the forced lineage facts of sat_solvable.anf.

    sat_solvable.anf (`x0 + 1`, `x1 + x2`) forces x0 = TRUE in every model and makes x1 and x2
    equivalent, so a correct variable-lineage trace -- whose purpose is to let the full ANF
    assignment be reconstructed from a CNF solution -- must record both facts: variable 0 fixed
    true, and variables 1 and 2 tied into one equivalence. The exact textual layout of a lineage
    record is left to the implementation (the spec pins the recorded *facts*, not the tokens), so
    the checks below tolerate token spelling / which variable is named the representative, while
    still rejecting a map that omits or mis-records either fact (e.g. records x0 false, or drops
    the x1~x2 link).
    """
    with tempfile.TemporaryDirectory() as td:
        cnf = f"{td}/out.cnf"
        smap = f"{td}/out.map"
        r = run_bosphorus(
            [
                "--anfread",
                str(FIXTURES_DIR / "sat_solvable.anf"),
                "--cnfwrite",
                cnf,
                "--solmap",
                smap,
                "--el",
                "0",
                "--xl",
                "0",
                "--sat",
                "0",
            ]
        )
        assert r.returncode == 0, f"--solmap exit {r.returncode}"
        assert Path(smap).exists(), f"--solmap did not create {smap}"
        text = Path(smap).read_text()
        assert text.strip(), f"--solmap produced an empty file"

        import re

        # A line pairing an ANF variable with its CNF/solution-variable index is the index
        # correspondence, not a value/equivalence record -- skip those when checking the facts.
        # This includes a record that simply leads with the CNF/index keyword, e.g.
        # `cnf x(0) 1` (ANF var 0 -> CNF var 1), which otherwise looks like a positional triple.
        def _is_index_map(low: str) -> bool:
            if "solution-var" in low or "internal-anf-var" in low:
                return True
            head = low.split()
            return bool(head) and head[0].strip(":-") in ("cnf", "cnf-var", "cnfvar", "index", "map")

        def _records_fixed_true(var: int) -> bool:
            """True iff some record pins ANF variable `var` to a true / 1 value.

            The spec leaves the record layout to the implementation, so this is
            layout-agnostic: it accepts a relation form (`x(0) = 1`, `x0 -> l_true`,
            `var 0: true`, or a bare `0 = 1`), a positional / whitespace-delimited
            triple with no relation operator (`fixed 0 1`, `FIXED 0 1`, `fixed x(0) 1`,
            bare `0 1` / `0 true`), OR the spec's own ANF encoding of a fixed-true
            value (`x(0) + 1`) -- mirroring the positional leniency
            `_records_equivalent` already grants. A fixed-*false* record (bare
            `x(0)`, `x(0) = 0`, `x(0) : l_false`, `fixed 0 0`) is intentionally NOT
            matched, so a map that mis-records the value still fails.
            """
            v = str(var)
            # Relation form with an x/var/val prefix (the original, kept verbatim).
            relation_prefixed = re.compile(
                r"(?:x\(?|var[ _-]*|val[ _-]*)" + v + r"\)?\b.*?"
                r"(?:=|:|->|\bis\b|\bequiv\b).*?(?:l_true|\btrue\b|\b1\b)"
            )
            # Relation form with a bare index and no prefix, e.g. `0 = 1`, `0 -> true`.
            relation_bare = re.compile(
                r"(?:^|[^\w(])" + v + r"\b.*?"
                r"(?:=|:|->|\bis\b|\bequiv\b).*?(?:l_true|\btrue\b|\b1\b)"
            )
            # Positional / whitespace-delimited triple with no relation operator, e.g.
            # `fixed 0 1` / `FIXED 0 1` / bare `0 1` / `0 true`: the index -- optionally
            # in the spec's own `xN` / `x(N)` notation -- is directly followed (whitespace
            # only) by a truthy value token. Requiring a *truthy* trailing token keeps a
            # fixed-false triple like `fixed 0 0` rejected.
            positional_true = re.compile(
                r"(?:^|[^\w(])(?:x\s*\(?\s*)?" + v + r"\s*\)?\s+(?:l_true|\btrue\b|\b1\b)\s*$"
            )
            # ANF encoding of fixed-true: `x(N) + 1` / `xN + 1` / `N + 1`, alone on a line.
            anf_true = re.compile(r"^\s*(?:x\(?)?" + v + r"\)?\s*\+\s*1\s*$")
            for ln in text.splitlines():
                low = ln.lower()
                if _is_index_map(low):
                    continue
                if (
                    relation_prefixed.search(low)
                    or relation_bare.search(low)
                    or positional_true.search(low)
                    or anf_true.search(low)
                ):
                    return True
            return False

        def _records_equivalent(a: int, b: int) -> bool:
            """True iff a single record ties ANF variables `a` and `b` into one equivalence.

            Layout-agnostic: any line naming both indices joined by an equivalence /
            pairing token counts. Accepts the spec's own ANF XOR form (`x(1) + x(2)` /
            `x(1) + x(2) + 1`) and colon / tilde separators in addition to `=`, `^`,
            `->`, `equiv`. A map that drops the link has no line naming both, so it
            still fails.
            """
            for ln in text.splitlines():
                low = ln.lower()
                if _is_index_map(low):
                    continue
                nums = re.findall(r"\d+", low)
                if (
                    str(a) in nums
                    and str(b) in nums
                    and any(t in low for t in ("=", "^", "->", "~", ":", "+", "equiv"))
                ):
                    return True
            return False

        assert _records_fixed_true(0), (
            f"--solmap must record variable 0 as fixed true (x0=1 is forced by `x0 + 1 = 0`); "
            f"a map that omits it or records the wrong value is not a correct lineage trace; "
            f"got {text!r}"
        )
        assert _records_equivalent(1, 2), (
            f"--solmap must record variables 1 and 2 as equivalent (forced by `x1 + x2 = 0`); "
            f"got {text!r}"
        )


def test_maxsol_caps_solution_enumeration():
    """`--solve --maxsol N` enumerates exactly N satisfying assignments (N < total).

    Fixture `two_vars_two_sol.anf` (x0*x1=0) has 3 satisfying assignments.
    With `--solve --maxsol 2` (and no `--allsol`), the enumeration cap kicks
    in and exactly 2 `s ANF-SATISFIABLE` lines are emitted. Default `--maxsol
    1` would emit only 1 line, so this specifically verifies the cap is being
    honoured when the user asks for more than one but not all.
    """
    r = run_bosphorus(
        [
            "--anfread",
            str(FIXTURES_DIR / "two_vars_two_sol.anf"),
            "--solve",
            "--maxsol",
            "2",
        ]
    )
    assert r.returncode == 0, f"--maxsol 2 exit {r.returncode}"
    out = r.stdout.decode()
    sat_lines = [ln for ln in out.splitlines() if ln.strip() == "s ANF-SATISFIABLE"]
    assert len(sat_lines) == 2, (
        f"--solve --maxsol 2 should enumerate exactly 2 SAT lines, "
        f"got {len(sat_lines)}\n{out[-500:]}"
    )


# ------------------------------ runner ------------------------------


def _discover_tests():
    g = globals()
    return sorted(
        (name for name in g if name.startswith("test_") and callable(g[name])),
    )


def main():
    ctrf_tests = []
    counters = {
        "tests": 0,
        "passed": 0,
        "failed": 0,
        "pending": 0,
        "skipped": 0,
        "other": 0,
    }

    for name in _discover_tests():
        counters["tests"] += 1
        t0 = time.monotonic()
        status = "passed"
        message = ""
        try:
            globals()[name]()
        except AssertionError as e:
            status = "failed"
            message = f"AssertionError: {e}"
        except subprocess.TimeoutExpired as e:
            status = "failed"
            message = f"Timeout after {e.timeout}s"
        except Exception as e:
            status = "failed"
            message = f"{type(e).__name__}: {e}"
        dt_ms = int((time.monotonic() - t0) * 1000)
        counters[status] = counters.get(status, 0) + 1
        ctrf_tests.append(
            {
                "name": name,
                "status": status,
                "duration": dt_ms,
                "message": message[:2000],
            }
        )
        print(f"[{status.upper():>6}] {name} ({dt_ms} ms) {message[:200]}")

    CTRF_OUT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "reportFormat": "CTRF",
        "specVersion": "0.0.0",
        "results": {
            "tool": {"name": "bosphorus_pytest_lite"},
            "summary": counters,
            "tests": ctrf_tests,
        },
    }
    CTRF_OUT.write_text(json.dumps(report))
    print(
        f"\nCTRF written to {CTRF_OUT} "
        f"({counters['passed']}/{counters['tests']} passed)"
    )
    # Exit 0 always; the grader reads passed/tests from ctrf.json for the
    # binary reward. Non-zero exit would be counted as grading_error.
    return 0


if __name__ == "__main__":
    sys.exit(main())
