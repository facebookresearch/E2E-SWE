#!/bin/bash
# Offline grading. The test harness (pytest + plugins) and every dependency are pre-baked in the
# per-task image (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — do
# not add apt-get / curl / pip-from-index steps.
#
# Note: no `set -e` — the reward logic below relies on capturing pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline. setup.sh was written by the agent (or by solve.sh for the GT
# eval) and runs `pip install -e . --no-build-isolation` against the pre-installed deps here.
bash ./setup.sh

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_yamlpath.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
