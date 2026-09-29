#!/bin/bash
# Offline grading driver for the zopfli task. setup.sh (the agent's, or GT's from solve.sh) builds
# /app/deflopt and /app/libdeflopt.so with gcc — no network. The pytest suite drives both (subprocess
# + ctypes) and validates output with the Python stdlib zlib/gzip decoder.
# Run setup.sh in a child process (not `source`) so its `set -e` cannot leak into this script and
# abort it before the reward is written; base the reward on both the build and the pytest exit codes.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

bash ./setup.sh
build_rc=$?

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_zopfli.py -v --timeout=120 -rA
test_rc=$?

if [ $build_rc -eq 0 ] && [ $test_rc -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
