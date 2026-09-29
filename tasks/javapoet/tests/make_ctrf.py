"""Convert the Java harness's per-test results into a CTRF report for the WRG grader.

Each *Harness.java emits one JSON line per case {"name","status","msg"}; test.sh runs the harnesses
before this script and concatenates the lines to <results>. The canonical case list is the set of
names in the committed oracle fixture /tests/expected.tsv (always present, read-only, kept in
lockstep with the harnesses), so the denominator stays fixed: if a harness failed to build/run (no
line for a case) that case is recorded failed rather than dropped -> a broken submission scores 0.
Stdlib only (python3 in the base image); no pytest, so the per-task image builds fully offline.

Usage: make_ctrf.py <results.jsonl> <out_ctrf.json> <expected.tsv>
"""
import json
import sys


def main():
    results_path, out_path, expected_path = sys.argv[1], sys.argv[2], sys.argv[3]

    canonical = []
    try:
        with open(expected_path) as fh:
            for line in fh:
                if "\t" in line:
                    canonical.append(line.split("\t", 1)[0])
    except FileNotFoundError:
        pass

    by_name = {}
    try:
        with open(results_path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    by_name[rec["name"]] = rec
    except FileNotFoundError:
        pass

    if not canonical:  # fixture missing -> fall back to whatever ran (should not happen)
        canonical = list(by_name.keys())

    tests, passed, failed = [], 0, 0
    for name in canonical:
        rec = by_name.get(name)
        if rec is not None and rec.get("status") == "passed":
            tests.append({"name": name, "status": "passed", "duration": 0.0, "message": ""})
            passed += 1
        else:
            msg = (rec.get("msg") if rec else None) or "no result produced (harness failed to build or run)"
            tests.append({"name": name, "status": "failed", "duration": 0.0, "message": msg})
            failed += 1

    report = {
        "results": {
            "tool": {"name": "pytest"},
            "summary": {
                "tests": len(tests), "passed": passed, "failed": failed,
                "skipped": 0, "pending": 0, "other": 0, "start": 0, "stop": 0,
            },
            "tests": tests,
        }
    }
    with open(out_path, "w") as fh:
        json.dump(report, fh)
    print(f"ctrf: {passed} passed, {failed} failed, {len(tests)} total")


if __name__ == "__main__":
    main()
