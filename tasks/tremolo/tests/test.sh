#!/bin/bash
# Offline grading. The test harness (pytest, pytest-json-ctrf, pytest-timeout) and the test-only
# HTTP/WebSocket clients (httpx, websockets) are all pre-baked in the per-task image
# (environment/Dockerfile), and PIP_NO_INDEX=1 is set. There is NO network — no apt-get / curl /
# pip-install steps here. tremolo needs no system service.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# The tests drive a loopback server with proxy-aware clients (httpx, websockets). Grading is
# offline, so any proxy env var inherited by this container points at nothing — drop it here too
# (the suite also does this in-process) so 127.0.0.1 traffic is never diverted.
unset http_proxy https_proxy all_proxy ws_proxy wss_proxy
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY WS_PROXY WSS_PROXY
export no_proxy="*" NO_PROXY="*"

# Install/build the project offline. setup.sh was written by the agent (or by solve.sh for GT
# eval) and runs `pip install -e . --no-build-isolation` against the baked build backend.
bash ./setup.sh

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_tremolo.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
