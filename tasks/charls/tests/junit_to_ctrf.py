#!/usr/bin/env python3
"""Minimal JUnit XML -> CTRF JSON converter for the WRG grader.

The WRG grader reads `/logs/verifier/ctrf.json` and only requires:
  results.summary.{passed, failed, other (optional)}
  results.tests[].{name, status, message (optional), trace (optional)}

We map JUnit testcase elements as follows:
  <testcase>                              -> status "passed"
  <testcase><failure .../></testcase>     -> status "failed"
  <testcase><error .../></testcase>       -> status "failed"
  <testcase><skipped .../></testcase>     -> status "skipped"

Test name = "<classname>.<name>" if classname is present, else <name>.

This is the gtest-pattern bridge between `--gtest_output=xml:...` JUnit XML
and the CTRF schema the WRG grader expects. We use a stdlib-only Python
script (rather than the npm package `junit-to-ctrf`) because Python is already
in the base image, so grading needs no install step and no network access.
"""

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET


def convert(xml_path: str) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    if root.tag == "testsuites":
        suites = root.findall("testsuite")
    elif root.tag == "testsuite":
        suites = [root]
    else:
        raise ValueError(f"Unexpected root element: {root.tag}")

    tests = []
    passed = 0
    failed = 0
    skipped = 0
    other = 0
    now = time.time()

    for suite in suites:
        for tc in suite.findall("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            full_name = f"{classname}.{name}" if classname else name

            failure = tc.find("failure")
            error = tc.find("error")
            skipped_el = tc.find("skipped")

            if failure is not None:
                status = "failed"
                message = failure.get("message", "")
                trace = (failure.text or "").strip()
                failed += 1
            elif error is not None:
                status = "failed"
                message = error.get("message", "")
                trace = (error.text or "").strip()
                failed += 1
            elif skipped_el is not None:
                status = "skipped"
                message = skipped_el.get("message", "")
                trace = ""
                skipped += 1
            else:
                status = "passed"
                message = ""
                trace = ""
                passed += 1

            try:
                duration = float(tc.get("time", "0") or 0)
            except ValueError:
                duration = 0.0

            entry = {
                "name": full_name,
                "status": status,
                "duration": duration,
            }
            if message:
                entry["message"] = message
            if trace:
                entry["trace"] = trace
            tests.append(entry)

    ctrf = {
        "results": {
            "tool": {"name": "gtest", "version": ""},
            "summary": {
                "tests": passed + failed + skipped + other,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pending": 0,
                "other": other,
                "start": now,
                "stop": now,
            },
            "tests": tests,
        }
    }
    return ctrf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="JUnit XML file")
    ap.add_argument("-o", "--output", required=True, help="CTRF JSON output path")
    args = ap.parse_args()

    ctrf = convert(args.input)
    with open(args.output, "w") as f:
        json.dump(ctrf, f, indent=2)
    print(f"Wrote {args.output}: {ctrf['results']['summary']}", file=sys.stderr)


if __name__ == "__main__":
    main()
