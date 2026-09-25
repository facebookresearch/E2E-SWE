#!/usr/bin/env python3
"""Convert `cargo test` console output into a CTRF report for the WRG grader.

Usage: ctrf.py <cargo-test-output-file> <ctrf-output-path>

`cargo test` is run with a single integration target (`--test koto_grading`), so the
only per-test lines are of the form:

    test <name> ... ok
    test <name> ... FAILED
    test <name> ... ignored

One such line == one `#[test] fn` == one CTRF entry. A compile failure produces zero
test lines -> zero tests -> reward 0. Names are deduped (last status wins), preserving
first-seen order so the count is stable regardless of cargo's parallel scheduling.
"""
import os
import re
import sys

# Matches a libtest result line. Anchored so prose containing "... ok" can't match.
LINE_RE = re.compile(r"^test ([^ ]+) \.\.\. (ok|FAILED|ignored)$")
STATUS = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}


def main() -> int:
    in_path, out_path = sys.argv[1], sys.argv[2]
    tests: dict[str, str] = {}
    order: list[str] = []
    with open(in_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE_RE.match(line.rstrip("\n"))
            if not m:
                continue
            name, raw = m.group(1), m.group(2)
            if name not in tests:
                order.append(name)
            tests[name] = STATUS[raw]

    result_tests = [{"name": n, "status": tests[n], "duration": 0} for n in order]
    passed = sum(1 for t in result_tests if t["status"] == "passed")
    failed = sum(1 for t in result_tests if t["status"] == "failed")
    skipped = sum(1 for t in result_tests if t["status"] == "skipped")
    out = {
        "results": {
            "tool": {"name": "cargo-test"},
            "summary": {
                "tests": len(result_tests),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pending": 0,
                "other": 0,
                "start": 0,
                "stop": 0,
            },
            "tests": result_tests,
        }
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    import json

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(
        f"cargo-test -> {passed}/{len(result_tests)} passed "
        f"({failed} failed, {skipped} skipped)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
