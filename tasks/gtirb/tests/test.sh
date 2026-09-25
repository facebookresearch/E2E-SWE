#!/bin/bash
# WRG verifier driver for the gtirb gtest-pattern task — per-subsystem
# binaries variant. Runs OFFLINE (allow_internet = false) on the per-task
# gtirb:v1 image (FROM repomate cpp_base + apt-installed libprotobuf-dev
# + protobuf-compiler + libboost-all-dev + pkg-config). cpp_base already
# ships gcc + cmake + build-essential + gtest v1.15.2 (headers + .so +
# .a), so this driver does ZERO installs at grade time. The Python
# helpers (junit_to_ctrf.py, coverage_summarize.py, emit_synthetic_junit.py)
# live in tests/ alongside this script and get uploaded into /tests/ by
# the grader (called via python3 below).
#
# Per-subsystem harness:
#   Previously all 25 TESTs lived in one file, compiling to one binary.
#   Any single TEST that failed to compile aborted the whole binary,
#   collapsing 25 tests to 0 in the CTRF report — a compile cascade.
#   Now the tests are split into 6 subsystem files, each compiled to its
#   own binary. A compile error in one subsystem is surfaced only for
#   THAT subsystem's tests (via emit_synthetic_junit.py, which enumerates
#   the file's TEST(...) macros and marks each as compile-failed). The
#   other subsystems still build, run, and score normally.
#
# Pipeline:
#   1. source ./setup.sh to build+install the agent's libgtirb + headers.
#   2. For each subsystem file (test_core, test_module_section, ...):
#      a. Compile it standalone with -O0 -g --coverage. On failure:
#         write a synthetic JUnit XML marking every TEST() in the file
#         as compile-failed. Continue with the next subsystem.
#      b. On success: run the binary with --gtest_output=xml:...
#         per-subsystem so gcov coverage files land alongside the .gcno.
#   3. Merge all per-subsystem JUnit XMLs into one CTRF JSON.
#   4. Aggregate gcov coverage from all binaries.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# 1. Build + install the agent's libgtirb + headers.
# Sourcing propagates the agent's shell options into our shell. Agents
# commonly write `set -e` at the top of setup.sh, which would then make
# our own error-handling below (checking exit codes explicitly) impossible
# — the first non-zero from g++ would kill test.sh and no CTRF file would
# be produced. Explicitly disable errexit AND recapture setup's exit code
# BEFORE any other command that could clobber $?.
bash ./setup.sh 2>/logs/verifier/setup.log
SETUP_EXIT=$?
set +e

COV_DIR=/tmp/cov_build
JUNIT_DIR=/tmp/junit_per_subsys
mkdir -p "$COV_DIR" "$JUNIT_DIR"

# The six subsystem test files — split from the original monolithic
# test_gtirb.cpp. Each file has 3-6 gtest TEST()s; combined they still
# cover the same 25 assertions the monolith did. Order chosen for a
# best-effort ~ascending complexity ordering.
SUBSYSTEMS=(core module_section byte_intervals blocks_symbols cfg aux_offset_serialize)

COMPILE_FLAGS="-std=c++17 -O0 -g --coverage \
    -DGTIRB_WRAP_UTILS_IN_NAMESPACE \
    -I/usr/local/include \
    -I/tests"
LINK_FLAGS="-lgtirb -lprotobuf -lgtest -lgtest_main -lpthread"

ANY_TEST_FAILED=0

for subsys in "${SUBSYSTEMS[@]}"; do
    SRC="/tests/test_${subsys}.cpp"
    BIN="$COV_DIR/test_${subsys}"
    JUNIT="$JUNIT_DIR/junit_${subsys}.xml"
    CLOG="/logs/verifier/compile_${subsys}.log"
    RLOG="/logs/verifier/run_${subsys}.log"

    # 2a. Compile this subsystem file.
    g++ $COMPILE_FLAGS "$SRC" $LINK_FLAGS -o "$BIN" 2>"$CLOG"
    CEXIT=$?

    if [ $CEXIT -ne 0 ]; then
        ANY_TEST_FAILED=1
        # Enumerate TEST()s in the failing file, emit a synthetic JUnit
        # marking each as compile-failed. Downstream CTRF conversion will
        # count them as failed rather than silently missing.
        python3 /tests/emit_synthetic_junit.py \
            "$subsys" "$SRC" "$JUNIT" --kind=compile --log "$CLOG"
        echo "=== compile_${subsys}.log ==="
        cat "$CLOG" 2>/dev/null || true
        echo "=== end compile_${subsys}.log ==="
        continue
    fi

    # 2b. Run the subsystem binary from $COV_DIR so its .gcda files land
    # alongside the .gcno files (gcov needs both side by side to produce
    # a .gcov report). Capture stdout+stderr into $RLOG so a hard crash
    # (SIGSEGV, abort, unhandled exception through main) still leaves a
    # forensic trail even though gtest never wrote its JUnit output.
    ( cd "$COV_DIR" && "./test_${subsys}" --gtest_output="xml:$JUNIT" ) \
        > "$RLOG" 2>&1
    TEXIT=$?
    # gtest normally writes JUnit even when individual TESTs fail. A
    # missing JUnit means the binary crashed hard before it could
    # finalize output; fall through to synthetic-JUnit emission with a
    # runtime-crash reason so those tests are counted as failed rather
    # than silently missing from the aggregate CTRF.
    if [ ! -f "$JUNIT" ]; then
        ANY_TEST_FAILED=1
        python3 /tests/emit_synthetic_junit.py \
            "$subsys" "$SRC" "$JUNIT" --kind=runtime_crash --log "$RLOG"
        echo "=== run_${subsys}.log (binary crashed, exit=$TEXIT) ==="
        cat "$RLOG" 2>/dev/null || true
        echo "=== end run_${subsys}.log ==="
    elif [ $TEXIT -ne 0 ]; then
        # Binary ran + wrote JUnit but some tests failed. Real per-test
        # signal is in the JUnit; the aggregate reward should not be 1.
        ANY_TEST_FAILED=1
    fi
done

# 3. Emit CTRF. If NO subsystem produced any JUnit at all (e.g. setup.sh
# catastrophically failed) — write a single <setup> failure entry so the
# grader still receives a well-formed CTRF.
if ! ls "$JUNIT_DIR"/*.xml >/dev/null 2>&1; then
    echo "{\"results\":{\"tool\":{\"name\":\"gtest\"},\"summary\":{\"tests\":0,\"passed\":0,\"failed\":0,\"other\":1},\"tests\":[{\"name\":\"<setup>\",\"status\":\"failed\",\"message\":\"setup.sh failed and no subsystem produced JUnit output; see setup.log\"}]}}" \
        > /logs/verifier/ctrf.json
    echo 0 > /logs/verifier/reward.txt
    echo "=== setup.log ==="
    cat /logs/verifier/setup.log 2>/dev/null || true
    echo "=== end setup.log ==="
    echo "=== /tmp/cmake.log (last 100 lines) ==="
    tail -100 /tmp/cmake.log 2>/dev/null || echo "(missing)"
    echo "=== end /tmp/cmake.log ==="
    echo "=== /tmp/make.log (last 100 lines) ==="
    tail -100 /tmp/make.log 2>/dev/null || echo "(missing)"
    echo "=== end /tmp/make.log ==="
    echo "=== installed gtirb headers under /usr/local/include/gtirb ==="
    ls -la /usr/local/include/gtirb/ 2>&1 | head -40 || true
    echo "=== end installed gtirb headers ==="
    echo "=== installed gtirb libs under /usr/local/lib ==="
    ls -la /usr/local/lib/ 2>&1 | grep -iE "gtirb|protobuf" | head -20 || true
    echo "=== end installed gtirb libs ==="
    exit 0
fi

# Merge all per-subsystem JUnit XMLs -> single CTRF JSON.
python3 /tests/junit_to_ctrf.py "$JUNIT_DIR"/*.xml -o /logs/verifier/ctrf.json

# 4. Aggregate gcov output over ALL subsystems' .gcda files.
# gcov writes .gcov files into the CURRENT WORKING DIRECTORY, so cd into
# $COV_DIR first. Every subsystem binary was built + run there, so all
# .gcda / .gcno files are co-located; a single `gcov *.gcda` aggregates
# coverage across all of them.
# `gcov -r/--relative-only` SILENTLY drops sources with absolute paths;
# test sources are at /tests/, headers at /usr/local/include/gtirb/. We
# MUST NOT pass -r.
( cd "$COV_DIR" && gcov *.gcda >/tmp/gcov.log 2>&1 ) || true

# Summarize gcov output into a single JSON. We restrict to gtirb's shipped
# public headers under /usr/local/include/gtirb/. Headers not transitively
# #include'd by any code path the aggregated test drivers exercise will
# appear in headers_missing.
python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_DIR" \
    --out /logs/verifier/coverage.json \
    --header Addr.hpp \
    --header AuxData.hpp \
    --header AuxDataContainer.hpp \
    --header AuxDataSchema.hpp \
    --header ByteInterval.hpp \
    --header Casting.hpp \
    --header CFG.hpp \
    --header CfgNode.hpp \
    --header CodeBlock.hpp \
    --header Context.hpp \
    --header DataBlock.hpp \
    --header DecodeMode.hpp \
    --header ErrorOr.hpp \
    --header Export.hpp \
    --header gtirb.hpp \
    --header IR.hpp \
    --header Module.hpp \
    --header Node.hpp \
    --header Offset.hpp \
    --header ProxyBlock.hpp \
    --header Section.hpp \
    --header Symbol.hpp \
    --header SymbolicExpression.hpp \
    --header Utility.hpp \
  || echo "coverage_summarize failed (non-fatal)"

# Dump coverage.json into stdout so it lands in the grader's debug.log
# (the grader only downloads /logs/verifier/ctrf.json + reward.txt).
echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="

if [ $ANY_TEST_FAILED -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
