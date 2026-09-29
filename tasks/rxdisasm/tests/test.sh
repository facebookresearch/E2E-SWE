#!/bin/bash
# Offline grading for the rxdisasm (rust) task. The pytest harness + Rust toolchain are pre-baked in
# the per-task image; there is NO network — do not add apt-get / curl / dependency-fetch steps.
#
# No `set -e` — the reward logic relies on capturing pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Build the project. setup.sh (written by the agent, or by solve.sh for GT) runs offline and must
# produce the CLI binary at /app/rxdisasm. Run it in a child shell so a `set -e` inside it can't abort
# grading.
[ -f ./setup.sh ] && bash ./setup.sh

# Fallback for the cargo convention: cargo builds into target/, so an agent may compile successfully
# yet not place the binary at /app/rxdisasm. If it is still missing, build the project in /app offline
# and install the produced executable. (No-op for GT, whose setup.sh already produced /app/rxdisasm.)
if [ ! -x /app/rxdisasm ] && [ -f /app/Cargo.toml ]; then
  ( cd /app && cargo build --release --offline >/dev/null 2>&1 )
  cand=$(find /app/target/release -maxdepth 1 -type f -perm -u+x ! -name '*.d' 2>/dev/null | head -1)
  [ -n "$cand" ] && cp "$cand" /app/rxdisasm
fi

pytest --ctrf /logs/verifier/ctrf.json /tests/test_rxdisasm.py -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
