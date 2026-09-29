#!/bin/bash
# Offline grading for the geom2d task. Node.js 20 (with its built-in test runner) and tsx are
# pre-baked in the per-task image, and the runtime deps (sat, poly-decomp-es) live at
# /node_modules; there is NO network — do not add apt-get / curl / npm-from-registry steps.
#
# Note: no `set -e` — the reward logic below relies on capturing the test runner's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Pre-seed a 0/N CTRF report FIRST. If the agent's build is broken and `node --test` crashes
# before the reporter can emit anything (e.g. /app/src/index.ts fails to load), this pre-seeded
# file is what the grader reads → a deterministic 0 reward, never a missing-ctrf grading error.
# TEST_COUNT must equal task.toml [verifier] test_case_count.
TEST_COUNT=52
mkdir -p /logs/verifier
python3 - "$TEST_COUNT" > /logs/verifier/ctrf.json <<'PY'
import json, sys
n = int(sys.argv[1])
print(json.dumps({"results": {"tool": {"name": "node:test"},
  "summary": {"tests": n, "passed": 0, "failed": n, "skipped": 0, "pending": 0, "other": 0, "start": 0, "stop": 0},
  "tests": [{"name": f"unstarted_{i}", "status": "failed", "duration": 0} for i in range(n)]}}))
PY

# Install/build the project. setup.sh was written by the agent (or by solve.sh for GT eval). For
# this tsx-direct engine it is a no-op (the TypeScript runs directly, deps resolve from /node_modules).
bash ./setup.sh

# node --test drives the hidden suite; tsx (loaded via --import) transpiles the TypeScript test
# file and the agent's /app/src/index.ts on the fly. The CTRF reporter overwrites the pre-seeded
# ctrf.json with the real per-test results.
node --import tsx --test \
  --test-reporter=/tests/ctrf_reporter.mjs --test-reporter-destination=stdout \
  /tests/collisions.test.ts

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
