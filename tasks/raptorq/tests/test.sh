#!/bin/bash
# Offline grading. The Rust toolchain + python3 are pre-baked in the per-task image
# (environment/Dockerfile) and there is NO network — do not add apt-get / curl / cargo-fetch steps.
#
# Note: no `set -e` — the reward logic below relies on capturing the test runner's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

export CARGO_NET_OFFLINE=true
export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/target}"

# Build the project. setup.sh was written by the agent (or by solve.sh for GT eval) and builds the
# crate offline against the baked toolchain.
bash ./setup.sh

# Place the hidden suite into the crate's integration-test dir and run ONLY it, so the agent's own
# unit/integration tests cannot inflate or perturb the graded count. The suite imports the crate
# via its public API as an external `raptorq` crate. A compile failure yields zero `test ... ` lines
# -> zero CTRF entries -> reward 0.
mkdir -p /app/tests
cp /tests/raptorq_grading.rs /app/tests/raptorq_grading.rs
cd /app
cargo test --test raptorq_grading --offline --no-fail-fast -- --test-threads=4 \
    > /tmp/cargo_test.out 2>&1
test_exit=$?

# Surface the run in the debug log, then convert console output -> CTRF for the grader.
cat /tmp/cargo_test.out
mkdir -p /logs/verifier
python3 /tests/ctrf.py /tmp/cargo_test.out /logs/verifier/ctrf.json

if [ "$test_exit" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
