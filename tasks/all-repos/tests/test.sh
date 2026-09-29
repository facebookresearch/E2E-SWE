#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — no apt-get / curl /
# download / uv / virtualenv steps. setup.sh installs the project into the system Python offline.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# git is pre-baked; the autofix / clone tests drive real git subprocesses, so a committer identity
# and a deterministic default branch must be configured for grading. protocol.file.allow=always lets
# the tests clone/push between local file:// repos.
git config --global user.email "all-repos-grader@example.com"
git config --global user.name "all-repos grader"
git config --global init.defaultBranch main
git config --global protocol.file.allow always

# Install/build the project offline. setup.sh was written by the agent (or by solve.sh for GT eval)
# and installs into this same (pre-populated) system Python via `pip install -e . --no-build-isolation`.
bash ./setup.sh

pytest --ctrf /logs/verifier/ctrf.json /tests/test_all_repos.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
