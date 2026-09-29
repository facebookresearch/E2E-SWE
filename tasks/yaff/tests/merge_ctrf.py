#!/usr/bin/env python3
"""Merge per-component CTRF partials into one CTRF JSON for the WRG grader.

Each held-out component binary (test_base, test_flat, ...) is run with the bundled
doctest 'ctrf' reporter, writing its own partial CTRF to <partials_dir>/<stem>.ctrf.json.
This script concatenates every partial's results.tests[] and sums results.summary counts
into a single /logs/verifier/ctrf.json.

Partial-credit contract: a component whose binary failed to COMPILE produces no partial
here, so its cases are simply ABSENT from the merge. The grader's denominator is
task.toml [verifier] test_case_count (fixed at 34), NOT the number of merged entries, so
an absent component's cases just don't count as passed and the pass percentage drops
correctly — no synthesized 'failed' entries are needed. A component that compiled but had
a case fail contributes that case as status 'failed'.

Usage: merge_ctrf.py <partials_dir> <output_path>
Always writes a valid CTRF file (empty results if no partials exist) so the grader never
sees a missing/malformed file when every component failed to build.
"""

import glob
import json
import os
import sys


def main() -> int:
    partials_dir = sys.argv[1]
    output_path = sys.argv[2]

    merged_tests = []
    passed = failed = skipped = other = 0

    for path in sorted(glob.glob(os.path.join(partials_dir, "*.ctrf.json"))):
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            # A corrupt/empty partial (e.g. a binary that crashed before writing) is
            # skipped; its cases are absent, which lowers the pass % correctly.
            sys.stderr.write(f"[merge_ctrf] skipping unreadable partial {path}: {e}\n")
            continue
        results = data.get("results", {})
        summary = results.get("summary", {})
        tests = results.get("tests", [])
        merged_tests.extend(tests)
        passed += int(summary.get("passed", 0))
        failed += int(summary.get("failed", 0))
        skipped += int(summary.get("skipped", 0))
        other += int(summary.get("other", 0))

    merged = {
        "results": {
            "summary": {
                "tests": len(merged_tests),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pending": 0,
                "other": other,
            },
            "tests": merged_tests,
        }
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as fh:
        json.dump(merged, fh, indent=2)

    sys.stderr.write(
        f"[merge_ctrf] merged {len(merged_tests)} cases "
        f"(passed={passed} failed={failed} other={other}) -> {output_path}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
