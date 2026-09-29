"""Convert the Harness JSONL results into a CTRF report.

Reads one JSON object per line ({name, status, message}) and writes a CTRF report whose summary the
WRG grader reads. If the results file is missing/short (e.g. the agent's validator failed to compile
or the harness crashed), every canonical case is recorded as failed so the denominator is preserved
(reward 0) rather than producing a grader error.

Usage: make_ctrf.py <results.jsonl> <expected_count> <out_ctrf.json>
"""
import json
import sys


def main():
    results_path, expected_count, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    entries = []
    seen = 0
    try:
        with open(results_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:      # never let one malformed line zero the whole run
                    continue
                entries.append({"name": r.get("name", "case-%d" % seen), "status": r.get("status", "failed"),
                                "duration": 0.0, "message": r.get("message", "")})
                seen += 1
    except FileNotFoundError:
        pass

    # Pad with failures up to the expected count if the harness produced fewer (build/crash).
    for i in range(seen, expected_count):
        entries.append({"name": "missing-%d" % i, "status": "failed", "duration": 0.0,
                        "message": "no result (harness did not run this case)"})

    passed = sum(1 for e in entries if e["status"] == "passed")
    failed = len(entries) - passed
    report = {"results": {"tool": {"name": "pytest"},
                          "summary": {"tests": len(entries), "passed": passed, "failed": failed,
                                      "skipped": 0, "pending": 0, "other": 0, "start": 0, "stop": 0},
                          "tests": entries}}
    with open(out_path, "w") as f:
        json.dump(report, f)
    print("%d/%d passed" % (passed, len(entries)))


if __name__ == "__main__":
    main()
