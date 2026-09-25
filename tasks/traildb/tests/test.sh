#!/bin/bash
# WRG verifier driver for the traildb task (offline).
# 1. Sources the agent's ./setup.sh to build+install libtraildb.so + headers.
# 2. Runs pytest, which fans out per-test subprocesses that each compile a
#    tiny C driver against the installed library and assert on its output.
# No `set -e` -- we need the reward logic below to capture pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

# Build + install the agent's traildb library. setup.sh usually has its own
# `set -e`; that propagates via `source`, so an install/build failure here
# aborts BEFORE we can emit a well-formed CTRF. Disable -e after sourcing so
# we always reach the pytest run and CTRF emission below.
bash ./setup.sh
SETUP_EXIT=$?
set +e

if [ $SETUP_EXIT -ne 0 ]; then
  echo "{\"results\":{\"tool\":{\"name\":\"pytest\"},\"summary\":{\"tests\":1,\"passed\":0,\"failed\":1,\"skipped\":0,\"pending\":0,\"other\":0,\"start\":0,\"stop\":0},\"tests\":[{\"name\":\"<setup>\",\"status\":\"failed\",\"message\":\"setup.sh failed with exit code ${SETUP_EXIT}\"}]}}" \
    > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi

# Refresh linker cache one more time -- some agent solve.sh variants may
# skip ldconfig, and the pytest subprocesses need libtraildb.so on the
# runtime search path.
ldconfig 2>/dev/null

pytest --ctrf /logs/verifier/ctrf.json /tests/test_traildb.py -v --timeout=60 -rA
TEST_EXIT=$?

if [ $TEST_EXIT -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
