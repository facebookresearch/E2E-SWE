#!/bin/bash
# WRG grading driver for owl. Runs offline inside the per-task image; every
# dependency (pytest, pytest-json-ctrf, pytest-timeout, gcc, make) is baked.
# No `set -e` — we capture pytest's exit code for the reward.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

WORKDIR="$PWD"

# Build the candidate offline. Run the candidate's setup.sh defensively in a
# subshell so any `cd`, `set -e`, or early exit inside it does not leak into
# the grader (e.g. a setup.sh that does `cd "$(dirname "$0")"` misbehaves
# under sourcing). Fall back to a bare `make` at the repo root if ./owl was
# not produced — the build contract guarantees a top-level Makefile that
# yields ./owl. No env needs to persist for a plain C build.
( bash ./setup.sh ) >/dev/null 2>&1 || true
[ -x ./owl ] || make >/dev/null 2>&1

export OWL_BIN="$WORKDIR/owl"

pytest --ctrf /logs/verifier/ctrf.json /tests/test_owl.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
