#!/bin/bash
# Offline grading. The test harness (pytest + plugins) and the setuptools/wheel build backend are
# pre-baked in the per-task image (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO
# network — do not add pip install / apt-get / curl / download steps.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# The container inherits http_proxy/https_proxy but no no_proxy, and the forward proxy is off during
# grading; exempt loopback so the in-container supervisord HTTP server the tests hit is reached
# directly instead of through a dead proxy.
export no_proxy=localhost,127.0.0.1,::1
export NO_PROXY=localhost,127.0.0.1,::1

# Install/build the project. setup.sh was written by the agent (or by solve.sh for GT eval) and
# runs offline against the pre-installed build backend in this same environment. It registers the
# supervisord/supervisorctl console scripts on PATH, which the CLI integration tests invoke.
bash ./setup.sh

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_supervisor.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
