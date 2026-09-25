#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile) and PIP_NO_INDEX is set — there is NO network, so no apt-get / pip
# install / download steps here. No `set -e`: the reward logic relies on pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

bash ./setup.sh

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_pytermgui.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
