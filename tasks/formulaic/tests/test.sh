#!/bin/bash
# Offline grading. The test harness (pytest + plugins) and every dependency are pre-baked in the
# per-task image (see environment/Dockerfile) and PIP_NO_INDEX=1 is set. There is NO network — no
# apt-get / curl / pip-install steps here. No system service is needed (the suite is pure
# numpy/pandas/scipy).
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline. setup.sh was written by the agent (or by solve.sh for GT eval)
# and runs against the pre-installed dependencies in this same environment.
bash ./setup.sh

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_formulaic.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
