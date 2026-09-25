#!/usr/bin/env python3
"""Convert `go test -json` output (stdin) into a CTRF report (stdout).

The WRG grader reads /logs/verifier/ctrf.json and requires:
  results.summary.passed, results.summary.failed   (KeyError otherwise)
  results.summary.other                             (optional, defaults to 0)
  results.tests[] each with name + status           (status in passed/failed/skipped)
Reward is resolved only when passed >= test_case_count AND failed == 0 AND other == 0.

We count only TOP-LEVEL test functions (event "Test" with no "/"), so the CTRF entry
count matches `func Test*` declarations one-to-one (subtests are folded into their parent,
mirroring how pytest-json-ctrf counts one entry per method). A build/compile failure that
produces no per-test events is surfaced as a single synthetic failed entry so the run scores
0 instead of crashing the grader with an empty report.
"""
import json
import sys


def main() -> None:
    tests: dict[str, dict] = {}
    order: list[str] = []
    pkg_failed = False
    saw_test_event = False
    loose_output: list[str] = []

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            # Non-JSON line (e.g. a raw build error printed before the JSON stream).
            loose_output.append(raw)
            continue

        action = ev.get("Action", "")
        name = ev.get("Test", "")

        if not name:
            # Package-level event.
            if action == "fail":
                pkg_failed = True
            elif action == "output":
                loose_output.append(ev.get("Output", "").rstrip("\n"))
            continue

        # Fold subtests into their top-level parent.
        top = name.split("/")[0]
        rec = tests.get(top)
        if rec is None:
            rec = {"name": top, "status": "", "output": []}
            tests[top] = rec
            order.append(top)

        if action == "output":
            rec["output"].append(ev.get("Output", ""))
        elif action in ("pass", "fail", "skip"):
            saw_test_event = True
            # A failing subtest must mark the whole top-level test failed.
            if name != top:
                if action == "fail":
                    rec["status"] = "fail"
                elif action == "pass" and rec["status"] != "fail":
                    rec["status"] = rec["status"] or "pass"
                elif action == "skip" and rec["status"] == "":
                    rec["status"] = "skip"
            else:
                rec["status"] = action

    status_map = {"pass": "passed", "fail": "failed", "skip": "skipped", "": "failed"}
    ctrf_tests = []
    passed = failed = skipped = 0
    for top in order:
        rec = tests[top]
        status = status_map.get(rec["status"], "failed")
        if status == "passed":
            passed += 1
        elif status == "skipped":
            skipped += 1
        else:
            failed += 1
        entry = {"name": top, "status": status, "duration": 0}
        if status == "failed":
            entry["message"] = "".join(rec["output"])[-4000:]
        ctrf_tests.append(entry)

    other = 0
    if not saw_test_event and (pkg_failed or loose_output):
        # Compilation/build failure: no test events at all. Surface as one failure so the
        # run scores 0 rather than producing an empty (and falsely "passing") report.
        msg = "\n".join(loose_output)[-4000:] or "go test produced no test events (build failure?)"
        ctrf_tests.append({"name": "BUILD", "status": "failed", "duration": 0, "message": msg})
        failed += 1

    report = {
        "results": {
            "tool": {"name": "go-test"},
            "summary": {
                "tests": passed + failed + skipped,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pending": 0,
                "other": other,
                "start": 0,
                "stop": 0,
            },
            "tests": ctrf_tests,
        }
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
