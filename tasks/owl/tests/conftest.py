"""Fixtures for the owl WRG test suite.

CTRF is emitted by the pytest-json-ctrf plugin (`pytest --ctrf ...` in
test.sh), so this file only provides fixtures. Every test runs against the
agent-built `./owl` binary at the repository root; compile-mode tests
additionally invoke gcc to build small C drivers against the generated
header.
"""

import os
import subprocess
from dataclasses import dataclass

import pytest

OWL_BIN = os.environ.get("OWL_BIN", "./owl")


@dataclass
class Run:
    stdout: str
    stderr: str
    returncode: int


@pytest.fixture(scope="session")
def owl_bin():
    path = os.path.abspath(OWL_BIN)
    assert os.path.exists(
        path
    ), f"owl binary not found at {path}; setup.sh must build ./owl"
    assert os.access(path, os.X_OK), f"owl binary at {path} is not executable"
    return path


@pytest.fixture
def write_grammar(tmp_path):
    """Write grammar text to a .owl file inside a per-test tmp dir; return path."""
    counter = {"n": 0}

    def _write(text, name=None):
        counter["n"] += 1
        n = name or f"g{counter['n']}.owl"
        p = tmp_path / n
        p.write_text(text)
        return str(p)

    return _write


@pytest.fixture
def run_owl(owl_bin):
    """Run the owl binary with arbitrary CLI args + optional stdin. Returns Run."""

    def _run(*args, stdin=None, timeout=15):
        r = subprocess.run(
            [owl_bin, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return Run(stdout=r.stdout, stderr=r.stderr, returncode=r.returncode)

    return _run


@pytest.fixture
def run_interpret(run_owl, write_grammar):
    """Run owl in interpreter mode against a grammar file and stdin string."""

    def _run(grammar_text, input_text, extra_args=(), timeout=15):
        gpath = write_grammar(grammar_text)
        return run_owl(gpath, *extra_args, stdin=input_text, timeout=timeout)

    return _run


@pytest.fixture
def compile_grammar(owl_bin, write_grammar, tmp_path):
    """Run `owl -c grammar.owl -o parser.h`; return path to parser.h."""

    def _compile(grammar_text, extra_args=(), header_name="parser.h"):
        gpath = write_grammar(grammar_text)
        hpath = str(tmp_path / header_name)
        r = subprocess.run(
            [owl_bin, "-c", gpath, "-o", hpath, *extra_args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0, (
            f"owl -c exited {r.returncode}\nstderr: {r.stderr}\nstdout head: "
            f"{r.stdout[:200]}"
        )
        assert os.path.exists(hpath), f"expected header at {hpath}"
        return hpath

    return _compile


@pytest.fixture
def build_and_run(tmp_path):
    """Compile a C driver source against a generated parser header and run it.

    Returns Run (stdout/stderr/returncode). The driver source is written into
    tmp_path; the header must already be at header_path. Any extra argv is
    forwarded to the driver.
    """
    counter = {"n": 0}

    def _build_and_run(driver_src, header_path, argv=(), timeout=15, driver_name=None):
        counter["n"] += 1
        name = driver_name or f"drv{counter['n']}"
        src = tmp_path / f"{name}.c"
        exe = tmp_path / name
        header_dir = os.path.dirname(os.path.abspath(header_path))
        header_base = os.path.basename(header_path)
        # If the driver references parser.h but the header is named
        # differently, symlink so #include "parser.h" resolves.
        if header_base != "parser.h":
            link = tmp_path / "parser.h"
            if not link.exists():
                os.symlink(header_path, str(link))
        src.write_text(driver_src)
        # Compile with -Werror-free flags: owl-generated headers are known-clean
        # under -Wall for the reference impl; we don't enforce -Werror because
        # agents may emit valid-but-warning C.
        cr = subprocess.run(
            [
                "gcc",
                "-std=c11",
                "-I",
                header_dir,
                "-I",
                str(tmp_path),
                str(src),
                "-o",
                str(exe),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert cr.returncode == 0, (
            f"driver failed to compile\nstderr:\n{cr.stderr}\n" f"stdout:\n{cr.stdout}"
        )
        rr = subprocess.run(
            [str(exe), *argv], capture_output=True, text=True, timeout=timeout
        )
        return Run(stdout=rr.stdout, stderr=rr.stderr, returncode=rr.returncode)

    return _build_and_run
