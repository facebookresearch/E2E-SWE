#!/bin/bash
# Offline grading. Node.js (with its built-in test runner) is pre-baked in the per-task image; there
# is nothing to install and NO network — do not add apt-get / curl / npm-registry steps.
#
# Note: no `set -e` — the reward logic below relies on capturing the test runner's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Run the agent's setup.sh (a no-op for this plain-Node module; it loads directly).
bash ./setup.sh

# node --test drives the agent's module (tests require /app/astring.js and call generate(node));
# the CTRF reporter writes /logs/verifier/ctrf.json.
node --test \
  --test-reporter=/tests/ctrf_reporter.mjs --test-reporter-destination=stdout \
  /tests/astring.test.js

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
