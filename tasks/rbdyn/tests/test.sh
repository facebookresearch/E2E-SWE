#!/bin/bash
# WRG verifier driver for the RBDyn Boost.Test pattern task (Phase-5 v5).
# Runs OFFLINE (allow_internet = false) on the per-task rbdyn:v5 image,
# which pre-installs every dependency (Eigen, Boost.Test/Filesystem,
# yaml-cpp, tinyxml2, SpaceVecAlg) and pre-builds the RBDyn CORE fixture
# static library at /opt/rbdyn_fixture/lib/libRBDyn_core.a. This driver
# does ZERO installs at grade time.
#
# The 5 test modules are Boost.Test .cpp files:
#   Narrow-RBDyn tests (link agent's 4 rbdyn_narrow .o files):
#     IDIMTest, CoriolisTest, JacobianTest, ExpandTest, IntegrationTest
#
# Every test module links against the fixture libRBDyn_core.a (supplies
# FK/FV/FA/CoM/ID/IK/IS/FD/MultiBody/Momentum symbols the agent's code
# and the tests both call into) plus SpaceVecAlg + system deps.
#
# Modular pipeline:
#   1. source ./setup.sh -> agent's narrow-scope compile step.
#   2. Compile all 5 modules IN PARALLEL. Per-module compile failure only
#      sinks THAT module (compile-failure fallback CTRF preserves signal
#      from the other modules).
#   3. For each module that compiled: run the binary with Boost.Test's
#      JUnit output, translate to per-module CTRF. For each module that
#      failed to compile: write a fallback CTRF with the first ~2 KB of
#      g++ stderr embedded in the message field.
#   4. Merge all 5 per-module CTRFs into a single /logs/verifier/ctrf.json.
#   5. Run gcov over agent's .o files (fixture built without --coverage
#      contributes nothing to coverage) and summarize with
#      coverage_summarize.py.
#   6. Final reward = 1 iff all 24 declared test cases passed (no failures,
#      no errors, no skips); otherwise 0.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# Run the agent's setup.sh, which is contracted to produce:
#   /app/build/rbdyn_narrow/{IDIM,Coriolis,Jacobian,NumericalIntegration}.o
# If setup.sh fails or a specific .o is missing, the corresponding
# per-module compile will fail and the CTRF fallback for that module
# will surface the g++ error.
bash ./setup.sh
# `source` doesn't isolate shell options -- if agent's setup.sh set -e,
# it propagates into this script. Reset so a per-module compile failure
# doesn't kill the whole run before we get a chance to emit its fallback.
set +e

# Build artifact dir for per-test binaries (separate from /app/build to
# keep agent's build tree clean; agent's build tree also holds gcov data).
BLD_DIR=/tmp/rbdyn_grade
rm -rf "$BLD_DIR"
mkdir -p "$BLD_DIR"

# Object sets. Compile_module below appends only the files that actually
# exist on disk, so a partially-successful agent build still produces
# runnable binaries for the modules whose required .o files are present.
#
# Every narrow-RBDyn test module links all 4 .o files -- some tests use
# symbols across multiple files (e.g. CoriolisTest uses Jacobian,
# IntegrationTest uses NumericalIntegration+Jacobian).
RBDYN_OBJS=(
    /app/build/rbdyn_narrow/IDIM.o
    /app/build/rbdyn_narrow/Coriolis.o
    /app/build/rbdyn_narrow/Jacobian.o
    /app/build/rbdyn_narrow/NumericalIntegration.o
)

# Fixture core lib supplies MultiBody/MultiBodyConfig/MultiBodyGraph/
# FK/FV/FA/ID/IK/IS/FD/CoM/Momentum symbols both the tests and the
# agent's own code link against.
FIXTURE_LIB=/opt/rbdyn_fixture/lib/libRBDyn_core.a

# Common flags mirror the reference repo's tests/CMakeLists which uses
#   Boost::unit_test_framework Boost::filesystem
# with -DBOOST_TEST_DYN_LINK. --coverage on the link line pulls in
# libgcov so gcov can process the agent's .gcda counts.
COMMON_LINK_FLAGS=(
    -std=c++17 -O0 -g --coverage
    -I/usr/local/include
    -I/usr/include/eigen3
    -DBOOST_TEST_DYN_LINK
)
LIBS_TAIL=(
    -lboost_unit_test_framework
    -lboost_filesystem
    -lboost_system
    -lpthread
    -ldl
)

# collect_existing "${ARRAY[@]}" -> prints only the paths that exist.
collect_existing() {
    for f in "$@"; do
        [ -f "$f" ] && printf '%s ' "$f"
    done
}

# Assign each test module its required agent .o set.
declare -A AGENT_OBJS
AGENT_OBJS[IDIMTest]="$(collect_existing "${RBDYN_OBJS[@]}")"
AGENT_OBJS[CoriolisTest]="$(collect_existing "${RBDYN_OBJS[@]}")"
AGENT_OBJS[JacobianTest]="$(collect_existing "${RBDYN_OBJS[@]}")"
AGENT_OBJS[ExpandTest]="$(collect_existing "${RBDYN_OBJS[@]}")"
AGENT_OBJS[IntegrationTest]="$(collect_existing "${RBDYN_OBJS[@]}")"

compile_module() {
    local name="$1"
    local out="$BLD_DIR/${name}_runner"
    local stderr="/tmp/compile_${name}_stderr.log"
    # Word-splitting on ${AGENT_OBJS[$name]} is intentional; paths are
    # written by collect_existing without spaces. SpaceVecAlg is
    # header-only (no .so/.a to link), so no `-lSpaceVecAlg` needed --
    # every sva:: symbol resolves in-header at compile time.
    g++ "${COMMON_LINK_FLAGS[@]}" \
        "/tests/${name}.cpp" \
        -I/tests \
        ${AGENT_OBJS[$name]} \
        "$FIXTURE_LIB" \
        "${LIBS_TAIL[@]}" \
        -o "$out" 2>"$stderr"
    return $?
}

MODULES=(
    IDIMTest CoriolisTest JacobianTest ExpandTest IntegrationTest
)

# ---- Step 1: compile every module IN PARALLEL. ----
declare -A COMPILE_PIDS
for m in "${MODULES[@]}"; do
    ( compile_module "$m" ) &
    COMPILE_PIDS[$m]=$!
done

declare -A COMPILE_EXITS
for m in "${MODULES[@]}"; do
    wait "${COMPILE_PIDS[$m]}"
    COMPILE_EXITS[$m]=$?
done

# ---- Step 2: for each module, run OR write compile-failure CTRF. ----
# Deadline for the whole run phase, in seconds since it started. A module binary that never
# terminates would otherwise consume the entire `[verifier] timeout_sec` (1800 s) and leave the
# merge below unreached — producing no CTRF at all instead of a scored partial. A fixed per-module
# cap can't work here: IntegrationTest legitimately takes ~500 s under -O0 -g --coverage, so the
# cap is whatever budget remains, letting slow-but-correct runs finish while still bounding a hang.
RUN_BUDGET_SEC=1500
RUN_START=$SECONDS

for m in "${MODULES[@]}"; do
    MOD_CTRF="/tmp/ctrf_${m}.json"
    if [ "${COMPILE_EXITS[$m]}" -eq 0 ]; then
        # Compiled OK: run the binary with Boost.Test JUnit output.
        # --log_level=test_suite includes passing test-case entries in the
        #   JUnit XML (default 'error' only emits failures).
        # --report_level=no keeps the "assertions passed" summary off stdout.
        # --catch_system_errors=yes so a signal (SIGSEGV etc.) in one test
        #   case doesn't kill the whole binary.
        MOD_JUNIT="/tmp/junit_${m}.xml"
        MOD_REMAIN=$(( RUN_BUDGET_SEC - (SECONDS - RUN_START) ))
        [ "$MOD_REMAIN" -lt 30 ] && MOD_REMAIN=30
        timeout "$MOD_REMAIN" "$BLD_DIR/${m}_runner" \
            --log_format=JUNIT \
            --log_sink="$MOD_JUNIT" \
            --log_level=test_suite \
            --report_level=no \
            --catch_system_errors=yes \
            >/tmp/run_${m}_stdout.log 2>&1
        RUN_RC=$?
        # Boost.Test writes the JUnit sink at exit, so a hang or hard crash leaves no XML. Emit a
        # fallback so every module always yields an artifact for the merge.
        if [ ! -s "$MOD_JUNIT" ] || ! python3 /tests/junit_to_ctrf.py "$MOD_JUNIT" -o "$MOD_CTRF"; then
            RUN_ERR_JSON=$(tail -c 2048 "/tmp/run_${m}_stdout.log" \
                | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.buffer.read().decode("utf-8", "replace")))')
            printf '{"results":{"tool":{"name":"boost-test"},"summary":{"tests":1,"passed":0,"failed":1,"other":0},"tests":[{"name":"<crash:%s exit=%s>","status":"failed","message":%s}]}}\n' \
                "$m" "$RUN_RC" "$RUN_ERR_JSON" > "$MOD_CTRF"
        fi
    else
        # Compile failed: embed the first ~2 KB of g++ stderr in the CTRF
        # message field, JSON-escaped via python3's json.dumps.
        ERR_JSON=$(head -c 2048 "/tmp/compile_${m}_stderr.log" \
            | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.buffer.read().decode("utf-8", "replace")))')
        printf '{"results":{"tool":{"name":"boost-test"},"summary":{"tests":1,"passed":0,"failed":1,"other":0},"tests":[{"name":"<compile:%s>","status":"failed","message":%s}]}}\n' \
            "$m" "$ERR_JSON" > "$MOD_CTRF"
    fi
done

# ---- Step 3: merge all per-module CTRFs into one aggregated CTRF. ----
python3 - <<'PYEOF' > /logs/verifier/ctrf.json
import json, sys
modules = [
    'IDIMTest', 'CoriolisTest', 'JacobianTest', 'ExpandTest',
    'IntegrationTest',
]
merged_tests = []
tot = {'tests': 0, 'passed': 0, 'failed': 0, 'other': 0, 'skipped': 0, 'pending': 0}
for m in modules:
    # The stdout redirect on this heredoc truncates ctrf.json BEFORE this code runs, so an
    # unguarded read here turns one missing/corrupt module artifact into a 0-byte ctrf.json and
    # a no-grade for the whole task. Degrade to a failed entry instead.
    try:
        with open(f'/tmp/ctrf_{m}.json') as f:
            c = json.load(f)
    except Exception as e:
        c = {'results': {'summary': {'tests': 1, 'passed': 0, 'failed': 1, 'other': 0},
                         'tests': [{'name': f'<missing:{m}>', 'status': 'failed', 'message': str(e)}]}}
    s = c['results']['summary']
    for k in tot:
        tot[k] += s.get(k, 0)
    merged_tests.extend(c['results']['tests'])
out = {'results': {'tool': {'name': 'boost-test'}, 'summary': tot, 'tests': merged_tests}}
json.dump(out, sys.stdout)
PYEOF

# ---- Step 4: coverage aggregation over agent's .o files. ----
# Agent's .o files were emitted alongside their .gcno metadata in
# /app/build/rbdyn_narrow/. Test-binary execution emitted .gcda alongside
# those. gcov reads .gcda + .gcno and writes .gcov files into the current
# working dir.
COV_DIR=/tmp/rbdyn_gcov
rm -rf "$COV_DIR"
mkdir -p "$COV_DIR"
(
    cd "$COV_DIR"
    for obj in "${RBDYN_OBJS[@]}"; do
        [ -f "$obj" ] || continue
        base=$(basename "$obj" .o)
        objdir=$(dirname "$obj")
        gcov -o "$objdir" "/app/src/RBDyn/${base}.cpp" >/dev/null 2>&1 || true
    done
) >/tmp/gcov.log 2>&1

# Header allowlist maps to the 4 agent source .cpp files.
python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_DIR" \
    --out /logs/verifier/coverage.json \
    --header IDIM.cpp \
    --header Coriolis.cpp \
    --header Jacobian.cpp \
    --header NumericalIntegration.cpp \
    || echo "coverage_summarize failed (non-fatal)"

echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="

# ---- Step 5: binary reward. 1 iff the task is fully solved: every one of
# the CANONICAL_TOTAL declared test cases ran and passed, with no failures,
# no errors/other, and no skips. Anything else scores 0. ----
CANONICAL_TOTAL=24 python3 - <<'PYEOF' > /logs/verifier/reward.txt
import json, os
canonical_total = int(os.environ['CANONICAL_TOTAL'])
try:
    with open('/logs/verifier/ctrf.json') as f:
        s = json.load(f)['results']['summary']
except Exception:
    s = {}
passed = s.get('passed', 0)
failed = s.get('failed', 0)
other = s.get('other', 0)
skipped = s.get('skipped', 0)
solved = (
    passed == canonical_total
    and failed == 0
    and other == 0
    and skipped == 0
)
print(1 if solved else 0)
PYEOF
