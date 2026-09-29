#!/bin/bash
# Offline grading. The test harness (pytest, pytest-json-ctrf, pytest-timeout, pytest-forked) and
# every runtime dependency are pre-baked in the per-task image (see environment/Dockerfile), and
# PIP_NO_INDEX=1 is set. There is NO network — no apt-get / curl / uv / venv steps.
#
# Note: no `set -e` — the reward logic below relies on capturing pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline against the pre-baked dependencies. setup.sh was written by the
# agent (or by solve.sh for GT eval) and runs `pip install -e . --no-build-isolation`.
bash ./setup.sh

# --forked runs each test in its own subprocess so the suite is isolated from the global
# make_versioned() singleton (versioning is configured once per process in normal use; the suite
# must not depend on teardown/re-setup support).
pytest --ctrf /logs/verifier/ctrf.json /tests/test_sqlalchemy_continuum.py -v --forked --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
