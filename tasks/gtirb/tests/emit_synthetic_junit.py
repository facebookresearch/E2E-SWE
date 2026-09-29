#!/usr/bin/env python3
"""Emit a synthetic JUnit XML declaring every `TEST(Suite, Name)` in a
gtest source file as failed.

Used by the per-subsystem verifier driver (tests/test.sh) when a
subsystem's per-test signal is destroyed by one of two failure modes:

  * compile error   — g++ never produced the binary, so no gtest ran.
  * runtime crash   — binary compiled + started, but crashed hard
                      (SIGSEGV, abort, unhandled exception through
                      main) before gtest could finalize JUnit output.

Both modes leave the aggregate CTRF short by however many TEST()s
live in that subsystem's file. This script enumerates the TEST()
decls with a regex, then emits one <testcase>...<failure/></testcase>
per gtest declaration so the aggregate JUnit -> CTRF pipeline counts
those tests as *failed* rather than silently missing.

Args:
  subsystem   short label used in <testsuite name="...">
  cpp_file    the .cpp file whose TEST() decls to enumerate
  output      JUnit XML file to write

Optional:
  --kind {compile,runtime_crash}
                    default `compile` (back-compat). Controls the
                    <failure message="..."> text and the log-file
                    filename convention referenced from it.
  --log <path>      path to the g++ stderr log (compile mode) or the
                    binary's captured stdout+stderr (runtime mode);
                    included in <failure> text for debugging.
  --compile-log <path>
                    deprecated alias for --log, retained for the
                    prior compile-only call sites.
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET


# Match `TEST(Suite, Name)` at any indentation. Anchored to a TEST( token
# that begins a statement — the regex accepts leading whitespace but not
# preceding non-whitespace so we don't match comments like `// TEST(...)`
# on the same line as real code.
_TEST_RE = re.compile(r"(?m)^\s*TEST\s*\(\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\)")


def find_tests(cpp_path: str):
    with open(cpp_path) as f:
        content = f.read()
    return _TEST_RE.findall(content)


def _failure_message(kind: str, subsystem: str) -> str:
    if kind == "runtime_crash":
        return (
            f"runtime crash in subsystem={subsystem}: "
            f"binary aborted before writing JUnit output "
            f"(see /logs/verifier/run_{subsystem}.log)"
        )
    # default: compile
    return (
        f"compile error in subsystem={subsystem} "
        f"(see /logs/verifier/compile_{subsystem}.log)"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("subsystem")
    ap.add_argument("cpp_file")
    ap.add_argument("output")
    ap.add_argument(
        "--kind",
        choices=("compile", "runtime_crash"),
        default="compile",
        help="failure kind; controls the message text",
    )
    ap.add_argument(
        "--log",
        default=None,
        help="path to the log file to include in <failure> text",
    )
    ap.add_argument(
        "--compile-log",
        dest="compile_log",
        default=None,
        help="deprecated alias for --log",
    )
    args = ap.parse_args()

    log_path = args.log or args.compile_log

    tests = find_tests(args.cpp_file)
    if not tests:
        # Zero TEST() declarations parsed — surface a single failure entry
        # so the problem still shows up in the CTRF output.
        tests = [("Gtirb" + args.subsystem.capitalize() + "Subsystem", args.kind)]

    log_snippet = ""
    if log_path:
        try:
            with open(log_path) as f:
                log_snippet = f.read()[-2000:]
        except FileNotFoundError:
            log_snippet = "(log file not found)"

    message = _failure_message(args.kind, args.subsystem)

    testsuites = ET.Element("testsuites")
    testsuite = ET.SubElement(
        testsuites,
        "testsuite",
        name=args.subsystem,
        tests=str(len(tests)),
        failures=str(len(tests)),
    )
    for suite_name, test_name in tests:
        tc = ET.SubElement(
            testsuite,
            "testcase",
            classname=suite_name,
            name=test_name,
            time="0",
        )
        failure = ET.SubElement(tc, "failure", message=message)
        failure.text = log_snippet

    ET.ElementTree(testsuites).write(
        args.output, encoding="utf-8", xml_declaration=True
    )
    print(
        f"Synthesized {len(tests)} {args.kind}-failed tests for "
        f"subsystem={args.subsystem} -> {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
