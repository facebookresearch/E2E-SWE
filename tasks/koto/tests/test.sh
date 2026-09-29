#!/bin/bash
# Grading harness. The Rust toolchain + python3 are pre-baked in the per-task image
# (environment/Dockerfile). Network availability is controlled by the eval harness:
# GT eval's container has network; the agent's does not. Do not force offline here.
#
# Note: no `set -e` — the reward logic below relies on capturing the runner exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/target}"

# Build the project. setup.sh was written by the agent (or by solve.sh for GT eval)
# and builds the `koto` package. After it runs, dependency crates are in the cache,
# so the grader test target reuses them.
bash ./setup.sh

# Place the hidden suite into the `koto` package's integration-test dir and run ONLY
# it. The agent may lay the crate out ANY way (a flat package at /app, or a workspace
# with crates/koto/), so locate the koto package's manifest dynamically and drop the
# test in <that dir>/tests/ — hardcoding crates/koto/tests fails on a flat layout with
# "no test target named koto_grading". The suite imports the crate via its public API;
# a compile failure yields zero `test ...` lines -> zero CTRF entries -> reward 0.
KOTO_MANIFEST=$(grep -rlE '^[[:space:]]*name[[:space:]]*=[[:space:]]*"koto"' /app --include=Cargo.toml 2>/dev/null | head -1)
KOTO_DIR=$(dirname "${KOTO_MANIFEST:-/app/Cargo.toml}")
mkdir -p "$KOTO_DIR/tests"
cp /tests/koto_grading.rs "$KOTO_DIR/tests/koto_grading.rs"
echo "[test.sh] koto package dir: $KOTO_DIR"
cd /app
cargo test -p koto --test koto_grading --offline --no-fail-fast -- --test-threads=4 \
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
