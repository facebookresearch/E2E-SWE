#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — do not add
# apt-get / curl / download steps.
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

# If tests/ need a system service that was installed in the image, start it here, e.g.:
#   redis-server --daemonize yes

# -o asyncio_mode=auto: run async test coroutines without needing per-test markers, and override
# any asyncio_mode=strict the agent's reproduced pyproject.toml may set.
pytest --ctrf /logs/verifier/ctrf.json /tests/test_tortoise.py -v --timeout=60 -rA -o asyncio_mode=auto -p no:cacheprovider

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
