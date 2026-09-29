"""Shared helpers for the Feral WRG task test suite.

`run_feral(src)` writes `src` to a temporary `.fer` file and invokes the
installed `/usr/local/bin/feral` interpreter on it, returning the
`subprocess.CompletedProcess`. Stdlib-only (no pytest) so the OFFLINE
grader can run without extra packages.
"""

import subprocess
import tempfile
from pathlib import Path

FERAL_BIN = "/usr/local/bin/feral"


def run_feral(src: str, *, timeout: int = 30, stdin: str | None = None):
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "prog.fer"
        script.write_text(src)
        return subprocess.run(
            [FERAL_BIN, str(script)],
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin,
        )
