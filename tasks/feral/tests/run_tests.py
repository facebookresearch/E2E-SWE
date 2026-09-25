#!/usr/bin/env python3
"""Stdlib-only test runner for the Feral WRG task.

Walks `/tests/test_*.py`, imports each module, finds every `def test_*`
callable that takes zero args, runs it, and emits CTRF JSON + reward.txt
compatible with the WRG grader. No pytest, no pip.
"""

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path

# Number of declared test cases (must match [verifier].test_case_count in
# task.toml). The task is "solved" only when every one of them actually ran
# and passed.
CANONICAL_TOTAL = 41


def reward_from_summary(summary: dict) -> int:
    """Binary reward gate: 1 iff the task is fully solved, else 0."""
    return int(
        summary.get("passed", 0) == CANONICAL_TOTAL
        and summary.get("failed", 0) == 0
        and summary.get("other", 0) == 0
        and summary.get("skipped", 0) == 0
    )


def main() -> int:
    tests_dir = Path(__file__).parent
    sys.path.insert(0, str(tests_dir))

    tests_out = []
    passed = 0
    failed = 0
    other = 0
    start = time.time()

    for tf in sorted(tests_dir.glob("test_*.py")):
        modname = tf.stem
        spec = importlib.util.spec_from_file_location(modname, tf)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            tests_out.append(
                {
                    "name": f"{modname}::<import>",
                    "status": "failed",
                    "message": f"import error: {type(e).__name__}: {e}",
                    "trace": traceback.format_exc(),
                    "duration": 0.0,
                }
            )
            failed += 1
            continue

        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            t0 = time.time()
            try:
                fn()
                tests_out.append(
                    {
                        "name": f"{modname}::{name}",
                        "status": "passed",
                        "duration": time.time() - t0,
                    }
                )
                passed += 1
            except Exception as e:
                tests_out.append(
                    {
                        "name": f"{modname}::{name}",
                        "status": "failed",
                        "message": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc(),
                        "duration": time.time() - t0,
                    }
                )
                failed += 1

    stop = time.time()
    total = passed + failed + other
    ctrf = {
        "results": {
            "tool": {"name": "python-runner", "version": ""},
            "summary": {
                "tests": total,
                "passed": passed,
                "failed": failed,
                "skipped": 0,
                "pending": 0,
                "other": other,
                "start": start,
                "stop": stop,
            },
            "tests": tests_out,
        }
    }

    out_dir = Path("/logs/verifier")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ctrf.json").write_text(json.dumps(ctrf, indent=2))
    reward = reward_from_summary(ctrf["results"]["summary"])
    (out_dir / "reward.txt").write_text(f"{reward}\n")

    print(f"{passed}/{total} passed (reward {reward})", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
