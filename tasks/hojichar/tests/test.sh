#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — no apt-get / curl /
# download / pip-install steps here. The Redis dedup tests talk to the in-container server on
# localhost.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline (setup.sh = `pip install -e . --no-build-isolation`).
bash ./setup.sh

# Start the baked Redis service for the RedisDeduplicator tests (localhost:6379).
redis-server --daemonize yes --save "" --appendonly no

pytest --ctrf /logs/verifier/ctrf.json /tests/test_hojichar.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
