"""Fixtures for the b3d WRG test suite.

CTRF is emitted by the pytest-json-ctrf plugin (`pytest --ctrf ...` in
test.sh), so this file only provides fixtures. Every test builds a small
C driver that #includes <b3d.h> (and optional <b3d-math.h>/<b3d-obj.h>/
<b3d-voxel.h>) and links against -lb3d, then runs the driver and asserts
on stdout / return code.
"""

import os
import subprocess
from dataclasses import dataclass

import pytest


@dataclass
class Run:
    stdout: str
    stderr: str
    returncode: int


@pytest.fixture
def build_and_run(tmp_path):
    """Compile a C driver against the installed libb3d and run it.

    Returns Run (stdout/stderr/returncode). The driver source is written
    into tmp_path; -lb3d resolves against /usr/local/lib/libb3d.{a,so} and
    -lm links libm for standard math (sinf/cosf/etc. used by float-mode
    b3d-math.h wrappers). Additional CFLAGS (e.g. -DB3D_FLOAT_POINT) can
    be passed via extra_cflags.
    """
    counter = {"n": 0}

    def _build_and_run(
        driver_src,
        argv=(),
        timeout=15,
        driver_name=None,
        extra_cflags=(),
    ):
        counter["n"] += 1
        name = driver_name or f"drv{counter['n']}"
        src = tmp_path / f"{name}.c"
        exe = tmp_path / name
        src.write_text(driver_src)
        cr = subprocess.run(
            [
                "gcc",
                "-std=c11",
                "-O2",
                *extra_cflags,
                str(src),
                "-lb3d",
                "-lm",
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
