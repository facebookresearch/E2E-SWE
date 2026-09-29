#!/bin/bash
# Offline grading for the goawk (Go) task. The pytest harness is pre-baked in the per-task image
# (environment/Dockerfile) and goawk builds from the Go stdlib alone — there is NO network, so do
# not add apt-get / curl / go-module-download steps.
#
# Note: no `set -e` — the reward logic below relies on capturing pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Build the project. setup.sh (written by the agent, or by solve.sh for GT eval) runs offline and
# must produce the CLI binary at /app/goawk.
bash ./setup.sh

pytest --ctrf /logs/verifier/ctrf.json /tests/test_goawk.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
