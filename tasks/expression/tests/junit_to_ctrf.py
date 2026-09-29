"""Convert swift test JUnit/xUnit XML reports into a single CTRF report for the WRG grader.

Each hidden test class is compiled and run in its own grader package (see test.sh), so a
compile failure, crash, hang, or timeout in one layer produces no XML for that layer. Using
the baked ``expected_tests.txt`` as the canonical set of test names, any expected test with
no result is recorded as ``failed`` -- so the denominator always reflects every test in the
suite, exactly like a Python task that runs each file in isolation.

Usage: junit_to_ctrf.py <parts_dir> <expected_list_file> <output_json>
"""
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET


def _status_of(testcase):
    """A testcase passed unless it carries a failure/error/skipped child."""
    for child in testcase:
        if child.tag in ("failure", "error", "skipped"):
            return "failed"
    return "passed"


def main():
    parts_dir, expected_file, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    # Map test-method name -> status, from whatever XML was produced.
    results = {}
    for xml_path in sorted(glob.glob(os.path.join(parts_dir, "*.xml"))):
        try:
            tree = ET.parse(xml_path)
        except Exception:
            continue  # truncated/corrupt (process was hard-killed) -> skip
        for testcase in tree.getroot().iter("testcase"):
            name = testcase.get("name")
            if not name:
                continue
            # Key on the bare method name (after any "Class." prefix); names are unique.
            key = name.split(".")[-1]
            status = _status_of(testcase)
            # If the same test appears twice, a failure wins.
            if results.get(key) != "failed":
                results[key] = status

    # Canonical denominator: every expected test name (one per line).
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
        expected = list(results.keys())

    tests, passed, failed = [], 0, 0
    for name in expected:
        status = results.get(name, "failed")
        if status == "passed":
            passed += 1
        else:
            status = "failed"
            failed += 1
        message = "" if status == "passed" else \
            "test failed, or produced no result (compile error, crash, or timeout)"
        tests.append({"name": name, "status": status, "duration": 0.0, "message": message})

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
