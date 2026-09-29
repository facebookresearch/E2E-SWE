"""Fold per-method PASSED/FAILED lines into a single CTRF report for the WRG grader.

test.sh writes one ``<Class>.<method> PASSED|FAILED`` line per expected test to a results file
(a runaway/crashing/hanging test, or a whole layer that failed to compile, yields FAILED). Using
the baked ``expected_tests.txt`` as the canonical set of test names, any expected test with no
recorded PASS is counted ``failed`` -- so the denominator always reflects every test in the suite,
exactly like a Python task that runs each file in isolation.

Usage: results_to_ctrf.py <results_file> <expected_list_file> <output_json>
"""

import json
import sys


def main():
    results_path, expected_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    # Parse "<Class>.<method> PASSED|FAILED" lines; a PASS anywhere wins.
    passed_set = set()
    seen = set()
    try:
        with open(results_path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) != 2:
                    continue
                name, status = parts[0], parts[1].upper()
                seen.add(name)
                if status == "PASSED":
                    passed_set.add(name)
    except FileNotFoundError:
        pass

    # Canonical denominator: every expected test name (one per line, "Class.method").
    expected = []
    try:
        with open(expected_path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    expected.append(line)
    except FileNotFoundError:
        pass
    if not expected:
        expected = sorted(seen)

    tests, passed, failed = [], 0, 0
    for name in expected:
        status = "passed" if name in passed_set else "failed"
        if status == "passed":
            passed += 1
        else:
            failed += 1
        message = (
            ""
            if status == "passed"
            else "test failed, or produced no result (compile error, crash, hang, or OOM)"
        )
        tests.append(
            {"name": name, "status": status, "duration": 0.0, "message": message}
        )

    report = {
        "results": {
            "tool": {"name": "swift test"},
            "summary": {
                "tests": len(tests),
                "passed": passed,
                "failed": failed,
                "skipped": 0,
                "pending": 0,
                "other": 0,
                "start": 0,
                "stop": 0,
            },
            "tests": tests,
        }
    }
    with open(out_path, "w") as fh:
        json.dump(report, fh)
    print(f"merged: {passed} passed, {failed} failed, {len(tests)} total")


if __name__ == "__main__":
    main()
