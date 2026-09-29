#!/bin/bash
# WRG grading driver. Runs offline inside the per-task image; every dependency
# is pre-baked. No `set -e` — we capture pytest's exit code for the reward.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

WORKDIR="$PWD"

# Build the candidate offline. Run the candidate's setup.sh defensively in a
# subshell so any `cd`, `set -e`, or early exit inside it is isolated from the
# grader. Then fall back to a direct `make` at the repo root if the tester
# binary was not produced — the build contract guarantees ./bin/binjgb-tester.
( bash ./setup.sh ) >/dev/null 2>&1 || true
[ -x ./bin/binjgb-tester ] || make >/dev/null 2>&1 || true

export BINJGB_TESTER="$WORKDIR/bin/binjgb-tester"

pytest --ctrf /logs/verifier/ctrf.json /tests/test_binjgb.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
