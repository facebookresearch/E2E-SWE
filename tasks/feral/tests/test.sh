#!/bin/bash
# WRG verifier driver for the Feral interpreter task. Runs OFFLINE
# (allow_internet = false). No pytest / pip / apt at grade time -- the
# runner is stdlib python3 only (baked into cpp_base as python3.10).
#
# Pipeline:
#   1. `source ./setup.sh` runs the agent-authored (or GT-authored) install
#      that produces /usr/local/bin/feral + /usr/local/lib/feral/{std,prelude}.
#   2. Sanity print of the resulting feral install (never aborts the run).
#   3. Invoke `python3 /tests/run_tests.py` -- the stdlib runner walks
#      test_*.py, calls each `def test_*()`, and writes /logs/verifier/
#      {ctrf.json, reward.txt} directly.
#
# No `set -e` -- every stage must run so a CTRF is always produced. If
# setup.sh fails, run_tests.py still runs and every test fails legitimately.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

# --- Step 1: install the agent's / GT's feral build (offline). ---
bash ./setup.sh 2>/logs/verifier/setup.log

# --- Step 2: sanity print of the install (useful in debug.log; never aborts). ---
{
    echo "=== which feral ==="
    which feral || echo "feral not on PATH"
    echo "=== feral --version ==="
    /usr/local/bin/feral --version 2>&1 || echo "feral --version failed"
    echo "=== /usr/local/lib/feral tree ==="
    ls -R /usr/local/lib/feral 2>/dev/null || echo "no /usr/local/lib/feral"
} >/logs/verifier/feral_sanity.log 2>&1

# --- Step 3: run the stdlib test runner; it writes ctrf.json + reward.txt directly. ---
python3 /tests/run_tests.py >/logs/verifier/pytest.log 2>&1
RUNNER_EXIT=$?

# --- Step 4: safety net -- if the runner never wrote a CTRF, stub one. ---
if [ ! -s /logs/verifier/ctrf.json ]; then
    printf '{"results":{"tool":{"name":"python-runner"},"summary":{"tests":0,"passed":0,"failed":0,"other":1},"tests":[{"name":"<runner:crash>","status":"failed","message":"run_tests.py failed to emit CTRF"}]}}\n' \
        > /logs/verifier/ctrf.json
    echo "0" > /logs/verifier/reward.txt
fi
