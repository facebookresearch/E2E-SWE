"""Fold per-method test results into a single CTRF report for the WRG grader.

test.sh runs each hidden test method in its own process (per-test runtime isolation) and
appends a line "<method> passed" or "<method> failed" to a results file. Using the baked
``expected_tests.txt`` as the canonical set of test names, any expected test that is not
recorded as passed (build failure, crash, timeout/hang, or missing) is scored ``failed`` --
so the denominator always reflects every test in the suite.

Usage: results_to_ctrf.py <results_file> <expected_list_file> <output_json>
"""
import json
import sys


def main():
    results_file, expected_file, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    # method -> status; a "failed" anywhere wins over "passed".
    status = {}
    try:
        with open(results_file) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) != 2:
                    continue
                name, st = parts[0], parts[1]
                st = "passed" if st == "passed" else "failed"
                if status.get(name) != "failed":
                    status[name] = st
    except FileNotFoundError:
        pass

    expected = []
    try:
        with open(expected_file) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    expected.append(line.split(".")[-1])
    except FileNotFoundError:
        pass
    if not expected:
        expected = list(status.keys())

    tests, passed, failed = [], 0, 0
    for name in expected:
        st = status.get(name, "failed")
        if st == "passed":
            passed += 1
        else:
            st = "failed"
            failed += 1
        message = "" if st == "passed" else \
            "test failed, or produced no result (compile error, crash, or timeout)"
        tests.append({"name": name, "status": st, "duration": 0.0, "message": message})

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
