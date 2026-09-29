#!/bin/bash
# Offline, fully C++-native grading for the rko_lio core.
#
# The held-out Catch2 tests (this directory) are compiled against the agent's
# implementation under /app/rko_lio/core and run once. A custom Catch2 reporter
# (ctrf_reporter.cpp, compiled into the binary) writes results directly in CTRF —
# the language-agnostic format the WRG grader reads from /logs/verifier/ctrf.json.
# There is no pytest layer.
#
# The toolchain (cmake, g++ C++20) and every dependency (Eigen3, Sophus, TBB,
# tsl-robin-map, Catch2) are pre-baked in the per-task image; there is NO network.
#
# No `set -e`: a build/run failure must still emit a clean reward-0 CTRF. A missing
# ctrf.json would be treated by the grader as a grading error rather than a failed
# run, so every exit path below leaves a valid CTRF behind.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

CTRF=/logs/verifier/ctrf.json
BUILD_DIR=/tmp/rko_lio_test_build
BINARY="$BUILD_DIR/rko_lio_core_tests"
TEST_CASE_COUNT=38

mkdir -p /logs/verifier

# Emit an all-failed CTRF so a build/crash scores a clean 0 (the grader needs
# .results.summary.{passed,failed,other} plus a .results.tests array; any failed>0
# or passed<test_case_count => reward 0).
write_fail_ctrf() {
  cat > "$CTRF" <<EOF
{
  "reportFormat": "CTRF",
  "specVersion": "0.0.0",
  "results": {
    "tool": { "name": "Catch2" },
    "summary": { "tests": ${TEST_CASE_COUNT}, "passed": 0, "failed": ${TEST_CASE_COUNT}, "pending": 0, "skipped": 0, "other": 0, "start": 0, "stop": 0 },
    "tests": []
  }
}
EOF
  echo 0 > /logs/verifier/reward.txt
}

# Configure + build the grading test binary (held-out Catch2 tests + agent core +
# the CTRF reporter). Independent of the agent's own build system.
NPROC="$(nproc 2>/dev/null || echo 1)"
if ! cmake -S /tests -B "$BUILD_DIR" -DAPP_DIR=/app -DCMAKE_BUILD_TYPE=Release; then
  echo "[test.sh] CMake configure failed"; write_fail_ctrf; exit 0
fi
if ! cmake --build "$BUILD_DIR" -j "$NPROC" --target rko_lio_core_tests; then
  echo "[test.sh] Build of rko_lio_core_tests failed"; write_fail_ctrf; exit 0
fi
if [ ! -x "$BINARY" ]; then
  echo "[test.sh] Test binary not produced at $BINARY"; write_fail_ctrf; exit 0
fi

# Run all cases once; the reporter writes CTRF directly. The noisy [!mayfail] ICP
# cases execute but are excluded from the CTRF by the reporter (okToFail), so they
# never affect the score.
"$BINARY" --reporter ctrf --out "$CTRF"
status=$?

# Guard against a crash that killed the process before the report was written.
if [ ! -s "$CTRF" ]; then
  echo "[test.sh] No CTRF produced (test binary crashed?)"; write_fail_ctrf; exit 0
fi

if [ "$status" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
