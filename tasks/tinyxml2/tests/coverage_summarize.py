#!/usr/bin/env python3
"""Summarize gcov line-coverage output into a single JSON file.

Reads every .gcov file under the input directory, filters to the set of
"library source files" passed on the command line (matched by basename),
parses the standard gcov execution-count format, and writes a JSON summary
to the path given by --out.

Targets may be passed via --header (lib header basename, for Tier 1
header-only libs) or --source (lib .cpp/.h basename, for Tier 2 compiled
libs). Both are matched the same way (basename equality against the
gcov-stripped source name); the separate flag names are only documentation.

Each .gcov line is one of:
    "        -:    N:..."     non-executable (comments, blanks, decls)
    "    #####:    N:..."     executable, never run
    "      <count>:    N:..." executable, ran <count> times

Aggregate per file: (covered executable lines) / (total executable lines).
The JSON ALSO emits `uncovered_ranges` per file — a compressed list of
[start, end] line spans (consecutive uncovered lines collapse into a
single range), each tagged with the first line's source text so a
downstream audit can label the gap by what code is uncovered.

The script is stdlib-only and meant to be invoked by tests/test.sh after
gtest runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_gcov_file(
    path: Path,
) -> tuple[int, int, list[tuple[int, str]]]:
    """Return (executable_lines, covered_lines, uncovered_with_source).

    `uncovered_with_source` is a list of (lineno, source_text) tuples for
    every executable line that gcov marked `#####` or `=====` (i.e., never
    executed).
    """
    executable = 0
    covered = 0
    uncovered: list[tuple[int, str]] = []
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
            try:
                lineno = int(parts[1].strip())
            except ValueError:
                continue
            executable += 1
            source = parts[2].rstrip("\n")
            if count == "#####" or count == "=====":
                uncovered.append((lineno, source))
            else:
                # Anything else (an integer, possibly with thousands separators
                # or a trailing '*' for runtime-determined counts) means executed.
                covered += 1
    return executable, covered, uncovered


def compress_uncovered(
    uncovered: list[tuple[int, str]],
) -> list[dict]:
    """Compress consecutive uncovered line numbers into one range each.

    Each range carries:
      - start, end  (inclusive line numbers in the source file)
      - lines       (range length)
      - first_line  (first uncovered source line, stripped — labels the gap)
    """
    if not uncovered:
        return []
    uncovered = sorted(uncovered, key=lambda t: t[0])
    out: list[dict] = []
    start_lineno, start_src = uncovered[0]
    prev = start_lineno
    for lineno, _src in uncovered[1:]:
        if lineno == prev + 1:
            prev = lineno
        else:
            out.append(
                {
                    "start": start_lineno,
                    "end": prev,
                    "lines": prev - start_lineno + 1,
                    "first_line": start_src.strip(),
                }
            )
            start_lineno = lineno
            start_src = _src
            prev = lineno
    out.append(
        {
            "start": start_lineno,
            "end": prev,
            "lines": prev - start_lineno + 1,
            "first_line": start_src.strip(),
        }
    )
    return out


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
        default=[],
        help=(
            "library header basename to include in coverage (e.g. "
            "concurrentqueue.h). Pass once per header."
        ),
    )
    ap.add_argument(
        "--source",
        action="append",
        default=[],
        help=(
            "library source basename to include in coverage (e.g. "
            "tinyxml2.cpp). Pass once per source file. Equivalent to "
            "--header at the matching level; separate flag for clarity."
        ),
    )
    args = ap.parse_args()

    targets = list(args.header) + list(args.source)
    if not targets:
        print("must pass at least one --header or --source", file=sys.stderr)
        return 2

    gcov_dir = Path(args.gcov_dir)
    if not gcov_dir.is_dir():
        print(f"gcov dir not found: {gcov_dir}", file=sys.stderr)
        return 1

    target_set = {t: None for t in targets}
    per_file: dict[str, dict] = {}

    # gcov names files like "tinyxml2.cpp.gcov" (basename of the source).
    # System headers we don't care about (gtest, stdc++) also produce .gcov;
    # we filter by basename match against the target set.
    for gcov_path in gcov_dir.rglob("*.gcov"):
        # Strip the trailing ".gcov" to get the source basename gcov used.
        src_basename = gcov_path.name[: -len(".gcov")]
        # gcov may include path components for headers found via -I; take basename
        src_basename = os.path.basename(src_basename)
        if src_basename not in target_set:
            continue
        execu, covd, uncov_lines = parse_gcov_file(gcov_path)
        # If gcov ran multiple times over different translation units, prefer
        # the run with the most executable lines (most complete view).
        prev = per_file.get(src_basename)
        if prev is None or execu > prev["executable_lines"]:
            per_file[src_basename] = {
                "executable_lines": execu,
                "covered_lines": covd,
                "uncovered_lines": execu - covd,
                "line_coverage_pct": round(100.0 * covd / execu, 2) if execu else 0.0,
                "uncovered_ranges": compress_uncovered(uncov_lines),
                "gcov_path": str(gcov_path),
            }

    total_exec = sum(f["executable_lines"] for f in per_file.values())
    total_cov = sum(f["covered_lines"] for f in per_file.values())
    summary = {
        "tool": "gcov",
        "targets_requested": list(target_set),
        "targets_found": sorted(per_file.keys()),
        "targets_missing": sorted(t for t in target_set if t not in per_file),
        "aggregate": {
            "executable_lines": total_exec,
            "covered_lines": total_cov,
            "uncovered_lines": total_exec - total_cov,
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
        f"coverage_summarize: {len(per_file)}/{len(target_set)} targets, "
        f"{total_cov}/{total_exec} lines "
        f"({summary['aggregate']['line_coverage_pct']}%) -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
