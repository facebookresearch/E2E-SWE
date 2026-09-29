#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the task image,
# and PIP_NO_INDEX is set. There is NO network — do not add apt-get / curl / download steps.
# Tests reach the in-container Redis over the loopback interface.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project. setup.sh was written by the agent (or by solve.sh for GT eval) and
# runs offline against the pre-installed dependencies in this same environment.
bash ./setup.sh

# Start the baked Redis server — the hidden tests run against a live RedisBroker.
redis-server --daemonize yes
# Give it a moment to accept connections before pytest starts.
for _ in $(seq 1 20); do redis-cli ping >/dev/null 2>&1 && break; sleep 0.2; done

pytest --ctrf /logs/verifier/ctrf.json /tests/test_faststream.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
