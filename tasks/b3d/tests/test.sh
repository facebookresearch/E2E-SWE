#!/bin/bash
# WRG grading driver for b3d. Runs offline inside the per-task image; every
# dependency (pytest, pytest-json-ctrf, pytest-timeout, gcc, make) is baked.
# No `set -e` — we capture pytest's exit code for the reward.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

WORKDIR="$PWD"

# Build+install the candidate offline. Run the candidate's setup.sh
# defensively in a subshell so any `cd`, `set -e`, or early exit inside it
# does not leak into the grader. The install contract (documented in
# instruction.md) guarantees headers at /usr/local/include/b3d*.h and a
# linkable libb3d at /usr/local/lib/libb3d.{a,so}.
( bash ./setup.sh ) >/dev/null 2>&1 || true

pytest --ctrf /logs/verifier/ctrf.json /tests/test_b3d.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
