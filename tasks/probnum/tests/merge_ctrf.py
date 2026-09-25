"""Merge per-file CTRF reports into a single report for the WRG grader.

Each test file is run in its own process (see test.sh) so that a memory blow-up,
crash, or hang in one file cannot zero the whole suite. This script unions the
per-file CTRF JSONs and, using the full collected-test list as the canonical set,
records any test whose file produced no result (crashed / timed out / OOM-killed)
as ``failed`` — so the denominator always reflects every test in the suite.

Usage: merge_ctrf.py <parts_dir> <collected_list_file> <output_json>
"""
import glob
import json
import os
import sys


def _key(node_id):
    """Match on the unique test-method name (the segment after the last '::')."""
    return node_id.split("::")[-1]


def main():
    parts_dir, collected_file, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    # Collect results from every per-file CTRF that was produced.
    test_by_key = {}
    for part in sorted(glob.glob(os.path.join(parts_dir, "*.json"))):
        try:
            data = json.load(open(part))
        except Exception:
            continue  # truncated/corrupt part (process was hard-killed) -> skip
        for test in data.get("results", {}).get("tests", []):
            test_by_key[_key(test["name"])] = test

    # The canonical denominator: every test collected before any file ran.
    collected = []
    try:
        for line in open(collected_file):
            line = line.strip()
            if "::" in line:
                collected.append(line)
    except FileNotFoundError:
        pass
    if not collected:  # fall back to whatever results exist
        collected = [t["name"] for t in test_by_key.values()]

    merged, passed, failed, seen = [], 0, 0, set()
    for node in collected:
        key = _key(node)
        if key in seen:
            continue
        seen.add(key)
        if key in test_by_key:
            test = test_by_key[key]
        else:
            test = {
                "name": node,
                "status": "failed",
                "duration": 0.0,
                "message": "no result produced (file crashed, timed out, or OOM-killed)",
            }
        merged.append(test)
        if test.get("status") == "passed":
            passed += 1
        else:
            failed += 1

    summary = {
        "tests": len(merged),
        "passed": passed,
        "failed": failed,
        "skipped": 0,
        "pending": 0,
        "other": 0,
        "start": 0,
        "stop": 0,
    }
    report = {"results": {"tool": {"name": "pytest"}, "summary": summary, "tests": merged}}
    with open(out_path, "w") as fh:
        json.dump(report, fh)
    print(f"merged: {passed} passed, {failed} failed, {len(merged)} total")


if __name__ == "__main__":
    main()
