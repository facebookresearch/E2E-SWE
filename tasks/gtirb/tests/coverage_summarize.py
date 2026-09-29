#!/usr/bin/env python3
"""Summarize gcov line-coverage output into a single JSON file.

Reads every .gcov file under the input directory, filters to the set of
"library headers" passed on the command line (matched by basename), parses
the standard gcov execution-count format, and writes a JSON summary to
the path given by --out.

Each .gcov line is one of:
    "        -:    N:..."     non-executable (comments, blanks, decls)
    "    #####:    N:..."     executable, never run
    "      <count>:    N:..." executable, ran <count> times

Aggregate per file: (covered executable lines) / (total executable lines).
The script is stdlib-only and meant to be invoked by tests/test.sh after
gtest runs. Copied verbatim from the sibling sqlite_modern_cpp task.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_gcov_file(path: Path) -> tuple[int, int]:
    """Return (executable_lines, covered_lines) for one .gcov file."""
    executable = 0
    covered = 0
    with path.open() as f:
        for raw in f:
            # gcov line format: "<count>:<lineno>:<source>"
            # count is "-" (non-executable), "#####" (uncovered), or an integer
            parts = raw.split(":", 2)
            if len(parts) < 3:
                continue
            count = parts[0].strip()
            if count == "-":
                continue
            executable += 1
            if count == "#####" or count == "=====":
                continue
            # Anything else (an integer, possibly with thousands separators
            # or a trailing '*' for runtime-determined counts) means executed.
            covered += 1
    return executable, covered


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--gcov-dir",
        required=True,
        help="directory to scan for .gcov files (recursive)",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="path to write the JSON summary",
    )
    ap.add_argument(
        "--header",
        action="append",
        required=True,
        help=(
            "library header basename to include in coverage (e.g. "
            "IR.hpp). Pass once per header."
        ),
    )
    args = ap.parse_args()

    gcov_dir = Path(args.gcov_dir)
    if not gcov_dir.is_dir():
        print(f"gcov dir not found: {gcov_dir}", file=sys.stderr)
        return 1

    headers = {h: None for h in args.header}
    per_file: dict[str, dict] = {}

    # gcov names files like "IR.hpp.gcov" (basename of the source).
    # System headers we don't care about (gtest, stdc++, boost, protobuf)
    # also produce .gcov; we filter by basename match against the --header
    # set.
    for gcov_path in gcov_dir.rglob("*.gcov"):
        # Strip the trailing ".gcov" to get the source basename gcov used.
        src_basename = gcov_path.name[: -len(".gcov")]
        # gcov may include path components for headers found via -I; take basename
        src_basename = os.path.basename(src_basename)
        if src_basename not in headers:
            continue
        execu, covd = parse_gcov_file(gcov_path)
        # If gcov ran multiple times over different translation units, prefer
        # the run with the most executable lines (most complete view).
        prev = per_file.get(src_basename)
        if prev is None or execu > prev["executable_lines"]:
            per_file[src_basename] = {
                "executable_lines": execu,
                "covered_lines": covd,
                "line_coverage_pct": round(100.0 * covd / execu, 2) if execu else 0.0,
                "gcov_path": str(gcov_path),
            }

    total_exec = sum(f["executable_lines"] for f in per_file.values())
    total_cov = sum(f["covered_lines"] for f in per_file.values())
    summary = {
        "tool": "gcov",
        "headers_requested": list(headers),
        "headers_found": sorted(per_file.keys()),
        "headers_missing": sorted(h for h in headers if h not in per_file),
        "aggregate": {
            "executable_lines": total_exec,
            "covered_lines": total_cov,
            "line_coverage_pct": (
                round(100.0 * total_cov / total_exec, 2) if total_exec else 0.0
            ),
        },
        "per_file": per_file,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"coverage_summarize: {len(per_file)}/{len(headers)} headers, "
        f"{total_cov}/{total_exec} lines "
        f"({summary['aggregate']['line_coverage_pct']}%) -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
