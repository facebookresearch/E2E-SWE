#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — do not add
# apt-get / curl / download steps. Tests that hit the in-container redis/memcached reach them
# directly over the loopback interface.
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

# Start the baked system services the tests need (ext:redis + ext:memcached backends).
redis-server --daemonize yes
memcached -d -u root

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_beaker.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
