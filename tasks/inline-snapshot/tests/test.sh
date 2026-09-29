#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — no apt-get / curl /
# download / venv setup. The image's system Python is 3.12 (installed in the Dockerfile because
# inline-snapshot requires CPython >= 3.11), so `pip`/`pytest`/`python` all resolve to it.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline against the pre-installed dependencies in this environment.
# setup.sh (written by solve.sh for GT, or by the agent) runs `pip install -e . --no-build-isolation`.
bash ./setup.sh

# The suite drives inline-snapshot end-to-end via subprocess pytest runs. `-p no:inline_snapshot`
# disables the installed plugin in THIS (outer) pytest run so it does not interfere with grading;
# the inner subprocess runs load the plugin normally.
pytest --ctrf /logs/verifier/ctrf.json /tests/test_inline_snapshot.py -v --timeout=60 -rA -p no:inline_snapshot

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
