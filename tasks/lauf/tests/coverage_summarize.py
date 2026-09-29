#!/usr/bin/env python3
"""Summarize gcov line-coverage output into a single JSON file.

Adapted from cascadb's coverage_summarize.py for lauf's directory layout:
lauf has two files that collide on basename (src/lauf/lib/memory.cpp vs
src/lauf/runtime/memory.cpp), so matching by basename alone would clobber
one file's numbers with the other's. This version identifies each .gcov
file by the "Source:" header line gcov itself writes, and filters by
path-suffix match against --source / --header arguments.

Reads every .gcov file under the input directory, extracts each file's real
source path from gcov's "Source:" header line, filters to the set of
library targets passed on the command line, parses the standard gcov
execution-count format, and writes a JSON summary to --out.

Targets may be passed via --header (public header, e.g. lauf/vm.h) or
--source (library .cpp, e.g. lauf/lib/memory.cpp). Both are matched by
suffix on the gcov-reported Source: path:
    --source lauf/lib/memory.cpp     matches /app/src/lauf/lib/memory.cpp
    --source lauf/runtime/memory.cpp matches /app/src/lauf/runtime/memory.cpp
Slash-free targets (just a basename) also work for backwards compat with
cascadb-style invocations.

Each .gcov line is one of:
    "        -:    N:..."     non-executable (comments, blanks, decls)
    "    #####:    N:..."     executable, never run
    "      <count>:    N:..." executable, ran <count> times

Aggregate per file: (covered executable lines) / (total executable lines).
The JSON ALSO emits `uncovered_ranges` per file — a compressed list of
[start, end] line spans (consecutive uncovered lines collapse into a
single range), each tagged with the first line's source text so a
downstream audit can label the gap.

Stdlib-only; invoked by tests/test.sh after gcov runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_source_path(gcov_path: Path) -> str | None:
    """Return the source path reported by gcov's `Source:` header line.

    gcov emits header lines of the form
        "        -:    0:Source:<path>"
    inside the first ~5 lines of every .gcov file. Returns None if the
    header is missing (malformed .gcov).
    """
    try:
        with gcov_path.open() as f:
            for _ in range(20):
                line = f.readline()
                if not line:
                    break
                if "Source:" in line:
                    return line.split("Source:", 1)[1].strip()
    except Exception:
        return None
    return None


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
            # count is "-" (non-executable), "#####" (uncovered), or an
            # integer (possibly with a trailing '*' for runtime-determined).
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
            # Line 0 is the header block (Source:/Graph:/Data:/Runs:...).
            # Skip so a header line with a non-"-" count marker doesn't
            # inflate the executable-line total.
            if lineno == 0:
                continue
            executable += 1
            source = parts[2].rstrip("\n")
            if count == "#####" or count == "=====":
                uncovered.append((lineno, source))
            else:
                covered += 1
    return executable, covered, uncovered


def compress_uncovered(
    uncovered: list[tuple[int, str]],
) -> list[dict]:
    """Compress consecutive uncovered line numbers into one range each."""
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


def path_matches(source_path: str, target: str) -> bool:
    """True iff `target` is a suffix of `source_path` at a path boundary.

    Handles slash-qualified targets (lauf/lib/memory.cpp) and bare
    basenames (memory.cpp — legacy cascadb behavior).
    """
    if source_path.startswith("./"):
        source_path = source_path[2:]
    if target.startswith("./"):
        target = target[2:]
    if source_path == target:
        return True
    if source_path.endswith("/" + target):
        return True
    return False


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
            "library header path suffix (e.g. lauf/vm.h). Repeat per header. "
            "Matched by path-boundary suffix against gcov's Source: header."
        ),
    )
    ap.add_argument(
        "--source",
        action="append",
        default=[],
        help=(
            "library source path suffix (e.g. lauf/lib/memory.cpp). Repeat "
            "per source. Slash-qualified suffixes disambiguate same-basename "
            "files (lib/memory.cpp vs runtime/memory.cpp). Slash-free "
            "basenames match by basename for legacy compatibility."
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

    # Key per_file by the raw target string so users get output in the same
    # shape they asked for (lauf/lib/memory.cpp).
    per_file: dict[str, dict] = {}

    for gcov_path in gcov_dir.rglob("*.gcov"):
        src_path = read_source_path(gcov_path)
        if src_path is None:
            continue
        matched = None
        for t in targets:
            if path_matches(src_path, t):
                matched = t
                break
        if matched is None:
            continue

        execu, covd, uncov_lines = parse_gcov_file(gcov_path)
        prev = per_file.get(matched)
        # gcov may emit multiple .gcov files for one source (each test group
        # binary picks up the header separately, and the shim rebuilds the
        # library independently). Keep the run with the MOST covered lines
        # so aggregation reflects the union of what all test groups hit.
        if prev is None or covd > prev["covered_lines"]:
            per_file[matched] = {
                "source_path": src_path,
                "executable_lines": execu,
                "covered_lines": covd,
                "uncovered_lines": execu - covd,
                "line_coverage_pct": (round(100.0 * covd / execu, 2) if execu else 0.0),
                "uncovered_ranges": compress_uncovered(uncov_lines),
                "gcov_path": str(gcov_path),
            }

    total_exec = sum(f["executable_lines"] for f in per_file.values())
    total_cov = sum(f["covered_lines"] for f in per_file.values())
    summary = {
        "tool": "gcov",
        "targets_requested": list(targets),
        "targets_found": sorted(per_file.keys()),
        "targets_missing": sorted(t for t in targets if t not in per_file),
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
        f"coverage_summarize: {len(per_file)}/{len(targets)} targets, "
        f"{total_cov}/{total_exec} lines "
        f"({summary['aggregate']['line_coverage_pct']}%) -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
