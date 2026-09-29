#!/usr/bin/env python3
"""Convert the JUnit XML emitted by `swift test --xunit-output` into CTRF JSON.

The WRG grader reads `/logs/verifier/ctrf.json` and computes reward from
`results.summary.passed / test_case_count`, so a Swift task must produce the same CTRF shape that
`pytest-json-ctrf` produces for Python tasks. This is the Swift equivalent of that plugin.

Usage:
    xunit_to_ctrf.py <xunit.xml> <ctrf.json>

If the XML is missing or unparseable (e.g. compilation failed so swift test never ran), an empty
CTRF report (0 tests) is written so the grader records a 0 result rather than crashing.
"""

import json
import sys
import xml.etree.ElementTree as ET


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: xunit_to_ctrf.py <xunit.xml> <ctrf.json>", file=sys.stderr)
        return 2
    xunit_path, ctrf_path = sys.argv[1], sys.argv[2]
    tests = []
    passed = failed = skipped = 0

    try:
        root = ET.parse(xunit_path).getroot()
    except (FileNotFoundError, ET.ParseError):
        root = None

    if root is not None:
        # swift test emits <testsuites><testsuite><testcase .../> ...; iterate all testcases.
        for case in root.iter("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "")
            full_name = f"{classname}.{name}" if classname else name
            try:
                duration_ms = int(float(case.get("time", "0")) * 1000)
            except ValueError:
                duration_ms = 0

            failure = case.find("failure")
            error = case.find("error")
            skip = case.find("skipped")
            if failure is not None or error is not None:
                node = failure if failure is not None else error
                status = "failed"
                failed += 1
                message = (node.get("message") or (node.text or "")).strip()
            elif skip is not None:
                status = "skipped"
                skipped += 1
                message = ""
            else:
                status = "passed"
                passed += 1
                message = ""

            entry = {"name": full_name, "status": status, "duration": duration_ms}
            if message:
                entry["message"] = message
            tests.append(entry)

    total = len(tests)
    report = {
        "results": {
            "tool": {"name": "swift-test"},
            "summary": {
                "tests": total,
                "passed": passed,
                "failed": failed,
                "pending": 0,
                "skipped": skipped,
                "other": 0,
                "start": 0,
                "stop": 0,
            },
            "tests": tests,
        }
    }

    with open(ctrf_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"[xunit_to_ctrf] tests={total} passed={passed} failed={failed} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
