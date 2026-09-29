#!/bin/bash
# WRG verifier driver for the sqlite_modern_cpp gtest-pattern task. Runs OFFLINE
# (allow_internet = false) on the per-task sqlite_modern_cpp:v1 image
# (C++ base image + apt-installed libsqlite3-dev). That base image already
# ships gcc + cmake + build-essential + gtest v1.15.2 (headers + .so + .a),
# so this driver does ZERO installs at grade time. The two Python converters
# (junit_to_ctrf.py, coverage_summarize.py) live in tests/ alongside this script
# and get uploaded into /tests/ by the grader (called via python3 below).
#
# Pipeline:
#   1. bash ./setup.sh to install the agent's sqlite_modern_cpp header(s).
#   2. Compile the gtest test runner against the agent's header + libsqlite3
#      + gtest + pthread. sqlite_modern_cpp is header-only on the C++ side;
#      the underlying SQLite C library is the system libsqlite3 (-lsqlite3).
#      We compile with -O0 -g --coverage (instead of -O2) so the test binary
#      itself carries gcov instrumentation, which lets us measure line
#      coverage of every #include'd library header (primary sqlite_modern_cpp.h
#      plus the sub-headers transitively pulled in from sqlite_modern_cpp/)
#      without a separate rebuild step.
#   3. Run the runner, emit JUnit XML, then run gcov over the build dir.
#   4. Translate the JUnit XML to CTRF JSON via junit_to_ctrf.py.
#   5. Filter gcov output to the 8 shipped headers via coverage_summarize.py.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# Install the agent's sqlite_modern_cpp header(s) onto the system include path.
bash ./setup.sh

# Compile the gtest runner against the agent's header + system libsqlite3,
# instrumented for gcov. Compile and run in /tmp/cov_build/ so the .gcno
# (compile-time) and .gcda (run-time) files land in a predictable place
# for the coverage step.
COV_DIR=/tmp/cov_build
mkdir -p "$COV_DIR"
g++ -std=c++17 -O0 -g --coverage \
    /tests/test_sqlite_modern_cpp.cpp \
    -lsqlite3 -lgtest -lgtest_main -lpthread \
    -o "$COV_DIR/test_runner"
COMPILE_EXIT=$?
if [ $COMPILE_EXIT -ne 0 ]; then
  # Compilation failure -> emit a CTRF result with all tests marked as failed
  # so the grader still gets a well-formed file.
  echo "{\"results\":{\"tool\":{\"name\":\"gtest\"},\"summary\":{\"tests\":0,\"passed\":0,\"failed\":0,\"other\":1},\"tests\":[{\"name\":\"<compile>\",\"status\":\"failed\",\"message\":\"test_sqlite_modern_cpp.cpp failed to compile against the agent's installed sqlite_modern_cpp header(s) + libsqlite3\"}]}}" \
    > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi

# Run gtest, capture JUnit XML. We want to translate to CTRF whether or not
# tests pass, so we ignore the runner exit code here. Run from $COV_DIR so
# the .gcda files land alongside the .gcno files (gcov needs both side by
# side to produce a .gcov report).
( cd "$COV_DIR" && ./test_runner --gtest_output=xml:/tmp/junit.xml )
TEST_EXIT=$?

# Translate JUnit XML -> CTRF JSON for the grader.
python3 /tests/junit_to_ctrf.py /tmp/junit.xml -o /logs/verifier/ctrf.json

# Run gcov over the build directory's .gcda files. Two non-obvious points:
#  1. With a single-step `g++ --coverage src.cpp -o $COV_DIR/test_runner`,
#     g++ emits the notes file as `$COV_DIR/test_runner-test_sqlite_modern_cpp.gcno`
#     (binary-prefixed), NOT `$COV_DIR/test_sqlite_modern_cpp.gcno`. Calling
#     `gcov test_sqlite_modern_cpp.cpp` therefore fails the source-based
#     lookup. Passing the .gcda filenames directly sidesteps the lookup.
#  2. `gcov -r/--relative-only` SILENTLY drops sources with absolute paths
#     (our case: source at /tests/, headers at /usr/local/include/). It
#     produces zero .gcov files with no error. We MUST NOT pass -r.
# gcov writes .gcov files into the CURRENT WORKING DIRECTORY, so cd into
# $COV_DIR first to keep everything tidy.
( cd "$COV_DIR" && gcov *.gcda >/tmp/gcov.log 2>&1 ) || true

# Summarize gcov output into a single JSON. We restrict to the headers
# sqlite_modern_cpp ships under /app/hdr/ (primary header + the
# sqlite_modern_cpp/ sub-header directory). gcov also emits coverage for
# gtest, libsqlite3 system headers, and every libstdc++ header that got
# expanded into the test binary, but none of that reflects on the agent's
# implementation.
#
# Headers not transitively #include'd by any code path the test driver
# exercises (e.g. log.h, sqlcipher.h, function_traits.h on v3.2) will
# appear in headers_missing in the resulting coverage.json — that's an
# honest data point about which sub-headers the test suite exercises, not
# a measurement bug.
python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_DIR" \
    --out /logs/verifier/coverage.json \
    --header sqlite_modern_cpp.h \
    --header errors.h \
    --header error_codes.h \
    --header log.h \
    --header sqlcipher.h \
    --header function_traits.h \
    --header uncaught_exceptions.h \
    --header variant.h \
  || echo "coverage_summarize failed (non-fatal)"

# Dump coverage.json into stdout so it lands in the grader's debug.log
# (the grader only downloads /logs/verifier/ctrf.json + reward.txt; this
# is currently the only way to surface per-file coverage numbers in the
# eval outputs without changing the grader).
echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="

if [ $TEST_EXIT -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
