"""Helpers for the binjgb test suite.

Runs the headless `binjgb-tester` binary as a subprocess, hashes and parses
its PPM output. Tests use these to assert either exact framebuffer hashes
(matching binjgb's own expected outputs from `scripts/test.json`) or
structural properties (dimensions, palette characteristics, determinism).
"""

import hashlib
import os
import subprocess
from pathlib import Path


ROM_DIR = Path(__file__).parent / "roms"
BINJGB_TESTER = os.environ.get("BINJGB_TESTER", "./bin/binjgb-tester")


def run_tester(
    rom_name,
    frames=None,
    out_ppm=None,
    seed=0,
    palette=None,
    force_dmg=False,
    sgb_border=False,
    animate=False,
    joypad=None,
    timeout=45,
    cwd=None,
):
    """Invoke binjgb-tester and return the completed subprocess.

    Only assembles the CLI; the test decides what to assert on the result.
    Callers may pass `cwd=<dir>` to run the tester in a specific working
    directory (useful for testing that no PPM leaks into the caller's cwd
    when `-o` is omitted).
    """
    cmd = [str(BINJGB_TESTER)]
    if frames is not None:
        cmd.extend(["-f", str(frames)])
    if out_ppm is not None:
        cmd.extend(["-o", str(out_ppm)])
    if palette is not None:
        cmd.extend(["-P", str(palette)])
    if force_dmg:
        cmd.append("--force-dmg")
    if sgb_border:
        cmd.append("--sgb-border")
    if animate:
        cmd.append("-a")
    if joypad is not None:
        cmd.extend(["-j", str(joypad)])
    if seed is not None:
        cmd.extend(["-s", str(seed)])
    # rom is the last positional arg
    cmd.append(str(ROM_DIR / rom_name))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def hash_file(path):
    """SHA-1 hex digest of a file (matches binjgb's scripts/tester.py)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def parse_ppm_header(path):
    """Parse a P3 PPM header and return (width, height, maxval, header_bytes).

    header_bytes is the raw prefix through the maxval line (used to assert
    exact header format).
    """
    with open(path, "rb") as f:
        data = f.read()
    # P3 header: "P3\n<width> <height>\n<maxval>\n"
    # Find the third newline that ends the header.
    idx = 0
    for _ in range(3):
        nl = data.index(b"\n", idx)
        idx = nl + 1
    header = data[:idx]
    lines = header.split(b"\n")
    magic = lines[0]
    dims = lines[1].split()
    maxval = int(lines[2])
    width, height = int(dims[0]), int(dims[1])
    assert magic == b"P3", f"expected P3 magic, got {magic!r}"
    return width, height, maxval, header


def parse_ppm_pixels(path):
    """Return the list of (R, G, B) tuples from a P3 PPM.

    Uses whitespace-split parsing (P3 is ASCII). Returns pixels in row-major
    order (top-to-bottom, left-to-right).
    """
    with open(path, "rb") as f:
        data = f.read()
    # Skip the 3-line header.
    idx = 0
    for _ in range(3):
        idx = data.index(b"\n", idx) + 1
    tokens = data[idx:].split()
    ints = [int(t) for t in tokens]
    assert len(ints) % 3 == 0, "PPM pixel token count not a multiple of 3"
    return [(ints[i], ints[i + 1], ints[i + 2]) for i in range(0, len(ints), 3)]
