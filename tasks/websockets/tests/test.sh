#!/bin/bash

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Loopback must not be routed through an ambient forward proxy. The suite starts a local
# server and connects to it, and websockets honours *_proxy env vars; the grading
# container's proxy is already cut, so the stale vars point at nothing and the connect
# fails with a 500 instead of reaching 127.0.0.1.
unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY all_proxy ALL_PROXY
# Offline grading. The test harness (pytest + plugins) and the build backend are pre-baked in the
# per-task image (see environment/Dockerfile), and PIP_NO_INDEX=1 is set. There is NO network — do
# not add pip install / apt-get / curl / download steps. websockets has zero runtime dependencies
# and no system service, so nothing extra needs to be started here.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# Install/build the project. setup.sh was written by the agent (or by solve.sh for GT eval) and
# runs offline against the pre-installed build backend in this same environment.
bash ./setup.sh

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_websockets.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
