#!/bin/bash
# WRG verifier driver for the tinyxml2 gtest-pattern task (Tier 2 coverage).
# Runs OFFLINE (allow_internet = false). Uses the C++ base image
# directly — it already ships gcc + cmake + build-essential + gtest v1.15.2
# (headers + .so + .a), so this driver does ZERO installs at grade time.
# The two Python converters (junit_to_ctrf.py, coverage_summarize.py) live
# in tests/ alongside this script and get uploaded into /tests/ by the
# grader (called via python3 below).
#
# Pipeline:
#   1. source ./setup.sh to build + install the agent's tinyxml2 library
#      (uninstrumented; this is the "official" pass-rate run).
#   2. Compile the gtest test runner against the agent's header + library
#      + gtest + pthread.
#   3. Run the runner, emit JUnit XML.
#   4. Translate the JUnit XML to CTRF JSON via the bundled Python converter
#      and write reward.txt + ctrf.json for the grader. ----- pass-rate done -----
#
# Coverage pass (Tier 2 — measures line coverage of the agent's library):
#   5. Wipe the agent's install + cached build dir.
#   6. Install a g++ wrapper that appends `--coverage -O0 -g` to every
#      invocation (so CMake / Make build scripts that call bare g++ pick
#      up instrumentation without per-script changes).
#   7. Re-run /app/setup.sh with CC/CXX pointed at the wrapper and
#      CXXFLAGS/LDFLAGS carrying --coverage (covers CMake-driven and
#      Make-driven setups; CMake cache wipe from step 5 lets CXX env stick).
#   8. Rebuild the test runner with --coverage so its includes also count.
#   9. Run the instrumented runner (output discarded — pass rate already
#      captured in step 4).
#  10. Run gcov over BOTH the test-runner build dir AND the agent's library
#      build dir (.gcda files land next to .o files from compile time),
#      aggregate .gcov files into one dir, summarize via coverage_summarize.py.
#      Coverage failures are non-fatal — they don't affect the official
#      pass-rate report.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# Build + install the agent's tinyxml2 library to /usr/local.
# setup.sh commonly uses `set -e` internally, which propagates via `source`
# into this shell and would abort test.sh at the first nonzero-exit command
# (in particular, at test_runner if any test fails, losing the CTRF file
# and giving the grader a grading_error instead of a real pass/fail count).
# Explicitly disable `-e` after sourcing so we always reach junit_to_ctrf.py.
bash ./setup.sh
set +e

# Compile the gtest runner against the agent's header + library.
g++ -std=c++17 /tests/test_tinyxml2.cpp \
    -ltinyxml2 -lgtest -lgtest_main -lpthread \
    -o /tmp/test_runner
COMPILE_EXIT=$?
if [ $COMPILE_EXIT -ne 0 ]; then
  # Compilation failure -> emit a CTRF result with all tests marked as failed
  # so the grader still gets a well-formed file.
  echo "{\"results\":{\"tool\":{\"name\":\"gtest\"},\"summary\":{\"tests\":0,\"passed\":0,\"failed\":0,\"other\":1},\"tests\":[{\"name\":\"<compile>\",\"status\":\"failed\",\"message\":\"test_tinyxml2.cpp failed to compile against the agent's installed tinyxml2 header/library\"}]}}" \
    > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi

# Run gtest, capture JUnit XML. We want to translate to CTRF whether or not
# tests pass, so we ignore the runner exit code here.
/tmp/test_runner --gtest_output=xml:/tmp/junit.xml
TEST_EXIT=$?

# Translate JUnit XML -> CTRF JSON for the grader.
python3 /tests/junit_to_ctrf.py /tmp/junit.xml -o /logs/verifier/ctrf.json

if [ $TEST_EXIT -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

# ============================================================
# COVERAGE PASS (Tier 2: grader-side library rebuild with --coverage).
# Non-fatal — preserves the pass-rate signal from above no matter what.
# ============================================================

# 7. Wipe what setup.sh installed + the agent's cached build directory.
#    tinyxml2's install footprint: header + (libtinyxml2.a or libtinyxml2.so*).
rm -f /usr/local/include/tinyxml2.h
rm -f /usr/local/lib/libtinyxml2.*
rm -rf /app/build /app/cmake_build

# 8. Install gcc + g++ shims that append --coverage -O0 -g to every invocation
#    AND snapshot every .gcno the compiler emits to /tmp/gcno_safe/<abs-path>.
#    The snapshot is necessary because many agent setup.sh scripts end with
#    `rm -rf build` or `rm -f *.o` that ALSO wipes the .gcno alongside the
#    .o. Without the snapshot, when test_runner runs and writes .gcda to
#    the compile-time path, the matching .gcno is already gone — gcov
#    reports "cannot open notes file" and emits an empty .gcov.
#
#    Flags go AFTER "$@" so they win over the agent's -O3 / Release defaults
#    (g++ "last optimization flag wins"). /usr/local/bin is ahead of
#    /usr/bin on PATH, so bare `g++` / `gcc` in setup.sh transparently pick
#    them up. We MUST ship BOTH wrappers: tinyxml2's CMakeLists declares
#    `project(... LANGUAGES C CXX)`, so CMake probes the C compiler with a
#    .c file. If CC points at a g++ wrapper, the C probe fails with
#    `#error "The CMAKE_C_COMPILER is set to a C++ compiler"` and
#    setup.sh's `set -e` aborts before any .gcda lands.
GCNO_SAFE=/tmp/gcno_safe
mkdir -p "$GCNO_SAFE"

# Shared snapshot helper — installed once, sourced by both shims.
cat > /usr/local/bin/_cov_snapshot_gcno <<'SNAP_EOF'
#!/bin/bash
# Find any .gcno emitted by the just-finished compile and copy it to
# /tmp/gcno_safe/<abs-path>. Scan a few plausible dirs:
#   - the dir of -o <output> (if any)
#   - CWD (raw `g++ -c foo.cpp` lands .gcno in CWD)
#   - dirs holding any input *.c/*.cpp/*.cc/*.cxx args (less common)
# This is a best-effort sweep, not exhaustive — but it covers every
# pattern we have observed (CMake, make, raw g++).
SAFE=/tmp/gcno_safe
mkdir -p "$SAFE"
snap_dir() {
  local d="$1"
  [ -d "$d" ] || return 0
  local abs
  abs=$(cd "$d" 2>/dev/null && pwd) || return 0
  for f in "$abs"/*.gcno; do
    [ -e "$f" ] || continue
    local rel="$abs/$(basename "$f")"
    local target="$SAFE$rel"
    mkdir -p "$(dirname "$target")"
    cp -uf "$f" "$target" 2>/dev/null
  done
}
# CWD
snap_dir "."
# -o <path> dir
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    snap_dir "$(dirname "$arg")"
  fi
  prev="$arg"
done
SNAP_EOF
chmod +x /usr/local/bin/_cov_snapshot_gcno

cat > /usr/local/bin/gcc <<'GCC_EOF'
#!/bin/bash
/usr/bin/gcc "$@" --coverage -O0 -g
rc=$?
/usr/local/bin/_cov_snapshot_gcno "$@"
exit $rc
GCC_EOF
chmod +x /usr/local/bin/gcc

cat > /usr/local/bin/g++ <<'GXX_EOF'
#!/bin/bash
/usr/bin/g++ "$@" --coverage -O0 -g
rc=$?
/usr/local/bin/_cov_snapshot_gcno "$@"
exit $rc
GXX_EOF
chmod +x /usr/local/bin/g++

# 9. Re-run the agent's setup.sh with CC/CXX + flags pointing at the
#    wrappers. CMake reads CXXFLAGS/LDFLAGS at configure time (the build
#    cache was wiped above so the new CC/CXX sticks); Make/autotools read
#    them as defaults too.
CC=/usr/local/bin/gcc CXX=/usr/local/bin/g++ \
CFLAGS="--coverage -O0 -g" CXXFLAGS="--coverage -O0 -g" \
LDFLAGS="--coverage" \
  bash /app/setup.sh

# 10. Rebuild the test runner with --coverage (its #includes get tracked too).
COV_DIR=/tmp/cov_build
mkdir -p "$COV_DIR"
/usr/local/bin/g++ -std=c++17 /tests/test_tinyxml2.cpp \
    -ltinyxml2 -lgtest -lgtest_main -lpthread \
    -o "$COV_DIR/test_runner"
COV_COMPILE=$?
if [ $COV_COMPILE -ne 0 ]; then
  echo "coverage rebuild failed (g++ compile of test runner); skipping summary"
  exit 0
fi

# 11. Run the instrumented binary. Output ignored — .gcda emission is the goal.
#     .gcda files land at compile-time .o paths by default. The agent's
#     setup.sh decides where those are (e.g. /app/tinyxml2.gcda for an
#     in-tree `g++ -c tinyxml2.cpp -o tinyxml2.o`, or
#     /app/build/CMakeFiles/tinyxml2.dir/tinyxml2.cpp.gcda for CMake).
#     Some agent setup.sh recipes `rm -f tinyxml2.o` at the end — this
#     deletes the .o BUT NOT the .gcno (gcno is the symbol-graph file
#     gcov needs alongside .gcda; setup.sh almost never deletes it).
#     The .gcda is written FRESH at runtime to the compile-time .o dir.
#
#     GCOV_PREFIX redirects all .gcda writes to a deterministic location
#     so we don't have to guess where the agent built. With
#     GCOV_PREFIX_STRIP=0, libgcov prepends GCOV_PREFIX to the absolute
#     .gcda path: e.g. /app/tinyxml2.gcda → /tmp/gcov_runtime/app/tinyxml2.gcda.
#     This keeps the relative structure intact so gcov can still find the
#     matching .gcno (we tell gcov where to look via -o below).
GCOV_PREFIX=/tmp/gcov_runtime
mkdir -p "$GCOV_PREFIX"
echo "[cov] running instrumented test_runner with GCOV_PREFIX=$GCOV_PREFIX"
( cd "$COV_DIR" && GCOV_PREFIX="$GCOV_PREFIX" GCOV_PREFIX_STRIP=0 \
    ./test_runner --gtest_output=xml:/tmp/junit_cov.xml ) || true

# Diagnostic snapshot of what just got emitted, where.
echo "[cov] .gcda inventory after test_runner run:"
echo "  -- under $COV_DIR --"
find "$COV_DIR" -name '*.gcda' -printf '    %p (%s bytes)\n' 2>/dev/null
find "$COV_DIR" -name '*.gcno' -printf '    %p (%s bytes)\n' 2>/dev/null
echo "  -- under $GCOV_PREFIX --"
find "$GCOV_PREFIX" -name '*.gcda' -printf '    %p (%s bytes)\n' 2>/dev/null
echo "  -- under /app --"
find /app -name '*.gcda' -printf '    %p (%s bytes)\n' 2>/dev/null
find /app -name '*.gcno' -printf '    %p (%s bytes)\n' 2>/dev/null

# 12. Relocate the redirected .gcda files BACK to the dirs their matching
#     .gcno expects them in, then run gcov on each FROM ITS COMPILE-TIME
#     DIRECTORY (cd into the .gcda's dir before invoking gcov). This is
#     required because:
#       - gcov needs .gcda + .gcno in the SAME directory (or both under -o).
#         Restoring the .gcda back from $GCOV_PREFIX/<path> -> <path>
#         puts it next to the .gcno.
#       - gcov resolves source-file paths RECORDED IN THE .GCNO relative
#         to gcov's CWD. CMake records absolute paths (e.g.
#         /app/tinyxml2.cpp), but raw `g++ -c tinyxml2.cpp` in /app
#         records `tinyxml2.cpp` (relative). If gcov runs from
#         /tmp/all_gcov, the relative form misses; if gcov runs from /app,
#         both absolute and relative resolve.
#       - Output .gcov files land in gcov's CWD, so we cd back to the
#         aggregation dir before moving them.
#
#     NEVER pass `gcov -r` / `--relative-only`: it SILENTLY drops sources
#     with absolute paths (our case: /tests/, /usr/local/include/, /app/),
#     producing zero .gcov files with no error.
COV_GCOV_DIR=/tmp/all_gcov
mkdir -p "$COV_GCOV_DIR"
: > /tmp/gcov.log

# Restore .gcno files snapshotted by the g++/gcc shim. The agent's
# setup.sh may have `rm -rf build` or similar after install, wiping the
# .gcno alongside the .o. We re-materialize them here so gcov has both
# halves of its input.
SNAPSHOT_GCNO=$(find "$GCNO_SAFE" -name '*.gcno' 2>/dev/null)
if [ -n "$SNAPSHOT_GCNO" ]; then
  for s in $SNAPSHOT_GCNO; do
    orig="${s#$GCNO_SAFE}"
    orig_dir=$(dirname "$orig")
    mkdir -p "$orig_dir"
    # cp -n: only if missing — don't clobber a .gcno that survived in place
    cp -nf "$s" "$orig" 2>/dev/null
    echo "[cov] gcno snapshot $s -> $orig" >> /tmp/gcov.log
  done
fi

# Copy each redirected .gcda back to its compile-time location so gcov
# can find it next to the matching .gcno.
RELOCATED_GCDA=$(find "$GCOV_PREFIX" -name '*.gcda' 2>/dev/null)
if [ -n "$RELOCATED_GCDA" ]; then
  for g in $RELOCATED_GCDA; do
    orig="${g#$GCOV_PREFIX}"
    orig_dir=$(dirname "$orig")
    mkdir -p "$orig_dir"
    cp -f "$g" "$orig"
    echo "[cov] restored $g -> $orig" >> /tmp/gcov.log
  done
fi

# Run gcov for each .gcda from its OWN directory. After each call, sweep
# any *.gcov files produced into $COV_GCOV_DIR (so the summarizer's
# single scan still picks them up).
run_gcov_in_dir() {
  local gcda_path="$1"
  local gcda_dir
  gcda_dir=$(dirname "$gcda_path")
  local gcda_base
  gcda_base=$(basename "$gcda_path")
  echo "[cov] cd $gcda_dir && gcov $gcda_base" >> /tmp/gcov.log
  ( cd "$gcda_dir" && gcov "$gcda_base" >> /tmp/gcov.log 2>&1 ) || true
  # Sweep into the aggregation dir; mv to avoid double-summarizing.
  find "$gcda_dir" -maxdepth 1 -name '*.gcov' -exec mv -f {} "$COV_GCOV_DIR/" \; 2>/dev/null
}

# Test runner's .gcda files (under $COV_DIR).
for g in "$COV_DIR"/*.gcda; do
  [ -e "$g" ] || continue
  run_gcov_in_dir "$g"
done

# Library .gcda files — anywhere under /app. Restored from GCOV_PREFIX
# above plus anything an agent built in-place. Covers both CMake
# out-of-source builds (e.g. /app/build/CMakeFiles/...) and raw-g++
# in-tree builds (e.g. /app/tinyxml2.gcda).
LIB_GCDA=$(find /app -name '*.gcda' 2>/dev/null)
if [ -n "$LIB_GCDA" ]; then
  for g in $LIB_GCDA; do
    run_gcov_in_dir "$g"
  done
else
  echo "warning: no library .gcda found under /app — library was not instrumented"
fi

echo "[cov] .gcov files produced in $COV_GCOV_DIR:"
ls -la "$COV_GCOV_DIR" 2>/dev/null | head -40

echo "[cov] /tmp/gcov.log contents:"
cat /tmp/gcov.log 2>/dev/null | head -200

python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_GCOV_DIR" \
    --out /logs/verifier/coverage.json \
    --source tinyxml2.cpp \
    --source tinyxml2.h \
  || echo "coverage_summarize failed (non-fatal)"

# Dump coverage.json into stdout so it lands in the grader's debug.log
# (the grader only downloads /logs/verifier/ctrf.json + reward.txt; this
# is currently the only way to surface per-file coverage numbers in the
# eval outputs without changing the grader).
echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="
