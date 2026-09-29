#!/bin/bash
# Offline grading driver. No `set -e` — the reward logic relies on capturing pytest's exit code.
# Every dependency is baked into the per-task image (pycodestyle==2.14.0 pinned runtime dep,
# setuptools/wheel build backend, pytest + plugins) and PIP_NO_INDEX=1 is set there, so nothing is
# fetched from the network here. Pinning pycodestyle==2.14.0 in the image keeps violation detection
# — and therefore every exact formatted-output assertion — deterministic.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# setup.sh (written by solve.sh for GT, or by the agent) installs the package under test offline
# against the baked deps. After it runs, `python -m autopep8` must work.
bash ./setup.sh

pytest --ctrf /logs/verifier/ctrf.json /tests/test_autopep8.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
