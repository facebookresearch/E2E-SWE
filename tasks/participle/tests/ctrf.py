#!/usr/bin/env python3
"""Convert `go test -json` output into a CTRF report for the WRG grader.

Usage: ctrf.py <go-test-json-file> <ctrf-output-path>

Only top-level tests (no "/" in the name, i.e. not subtests) become CTRF entries,
so one `func TestXxx` == one CTRF entry. A build failure yields zero tests -> reward 0.
"""
import json
import os
import sys


def main() -> int:
    in_path, out_path = sys.argv[1], sys.argv[2]
    tests: dict[str, dict] = {}
    order: list[str] = []
    with open(in_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = e.get("Test")
            if not name or "/" in name:  # top-level tests only
                continue
            action = e.get("Action")
            if name not in tests:
                tests[name] = {"name": name, "status": "pending", "duration": 0}
                order.append(name)
            if action in ("pass", "fail", "skip"):
                status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
                tests[name]["status"] = status
                tests[name]["duration"] = int(float(e.get("Elapsed", 0)) * 1000)
    result_tests = [tests[n] for n in order]
    passed = sum(1 for t in result_tests if t["status"] == "passed")
    failed = sum(1 for t in result_tests if t["status"] == "failed")
    skipped = sum(1 for t in result_tests if t["status"] == "skipped")
    out = {
        "results": {
            "tool": {"name": "go-test"},
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
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"go-test -> {passed}/{len(result_tests)} passed ({failed} failed, {skipped} skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
