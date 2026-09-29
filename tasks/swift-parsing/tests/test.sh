#!/bin/bash
# Offline grading driver for the Swift `swift-parsing` task.
#
# The Swift 6.0 toolchain and python3 are pre-baked in the per-task image (see
# environment/Dockerfile); there is NO network. Do not add apt-get/curl/download steps.
#
# Strategy: the candidate's library lives at /app as a SwiftPM package exposing a module named
# `Parsing`. We do NOT trust the candidate's Package.swift -- we assemble a clean, dependency-free
# grader package whose `Parsing` target IS the candidate's *.swift sources (copied preserving
# relative subdirs so a split-across-folders layout with repeated file basenames still compiles),
# plus the hidden test case files.
#
# Each hidden test is a single consolidated scenario living in its OWN <Class>.swift file with a
# uniquely-named XCTestCase. This gives PER-TEST COMPILE ISOLATION: because Swift compiles a whole
# module at once, a candidate that implements most of the library but gets ONE API's shape wrong
# would, if all tests shared one test target, fail to compile the entire target and score 0. Giving
# each test its own file+target means such a mismatch zeros only the tests that actually use that
# API, not unrelated ones.
#
# Grading has a fast path and a fallback:
#   * FAST PATH -- build ONE combined package with the candidate + ALL test files (serialized,
#     `-j 1`, to bound peak RAM). If it builds, run each test method alone under a time cap
#     (`timeout`) AND a virtual-memory cap (`ulimit -v`), so a runaway test fails cleanly while the
#     container survives and everything else still scores. This is the common case (ground truth and
#     any candidate that compiles cleanly) and costs a single build.
#   * FALLBACK -- if the combined build fails, build the candidate LIBRARY once (populating the
#     SwiftPM build cache); if the library itself doesn't compile every test fails. Otherwise,
#     compile each test file's target against the cached library and run its method(s). SwiftPM
#     reuses the cached library build across files, so this stays cheap even with many files.
#
# A baked expected_tests.txt is the canonical denominator: any expected test with no recorded pass
# (build failure / crash / hang / OOM / missing) is counted failed by results_to_ctrf.py.
#
# No `set -e`: we must run every step and the converter regardless of individual exit codes.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

cd /tmp 2>/dev/null || cd /   # stable cwd; we rm -rf the grader dirs below

LOGDIR=/logs/verifier
mkdir -p "$LOGDIR"
RESULTS="$LOGDIR/results.txt"; : > "$RESULTS"

BUILD_TIMEOUT=1500      # serialized build cap (seconds)
TEST_TIMEOUT=25         # per-method run cap (seconds)
TEST_VMEM_KB=4194304    # per-method virtual-memory cap (4 GB)

# Copy the candidate library sources into a grader package dir, preserving relative subdirs.
copy_candidate_sources () {
    local dir="$1"
    ( cd /app/Sources 2>/dev/null && find . -name '*.swift' -print0 | while IFS= read -r -d '' f; do
        mkdir -p "$dir/Sources/Parsing/$(dirname "$f")"
        cp "$f" "$dir/Sources/Parsing/$f"
      done )
}

# Run one test method alone, under time + virtual-memory caps. Records PASSED/FAILED.
run_method () {
    local dir="$1" cls="$2" method="$3"
    local out
    out=$( cd "$dir" && ( ulimit -v "$TEST_VMEM_KB"; timeout --signal=SIGKILL "$TEST_TIMEOUT" \
        swift test --skip-build -j 1 --disable-sandbox --filter "$cls/$method\$" 2>&1 ) )
    # XCTest on Linux prints: Test Case 'Class.method' passed (N seconds)
    if printf '%s' "$out" | grep -qF "'$cls.$method' passed"; then
        echo "$cls.$method PASSED" >> "$RESULTS"
    else
        echo "$cls.$method FAILED" >> "$RESULTS"
    fi
}

# The list of expected "Class.method" pairs (canonical denominator).
mapfile -t EXPECTED < <(grep -v '^#' /tests/expected_tests.txt | grep -v '^[[:space:]]*$')

# ---- FAST PATH: one combined grader package with every case file. ----
COMBINED=/grader-all
rm -rf "$COMBINED"
mkdir -p "$COMBINED/Sources/Parsing" "$COMBINED/Tests/ParsingTests"
copy_candidate_sources "$COMBINED"
cp /tests/*Tests.swift "$COMBINED/Tests/ParsingTests/" 2>/dev/null
cp /tests/Package.grader.swift "$COMBINED/Package.swift"

( cd "$COMBINED" && timeout --signal=SIGKILL "$BUILD_TIMEOUT" \
    swift build --build-tests -j 1 --disable-sandbox >/dev/null 2>&1 )
COMBINED_BUILT=$?

if [ "$COMBINED_BUILT" -eq 0 ]; then
    for pair in "${EXPECTED[@]}"; do
        cls="${pair%%.*}"; method="${pair#*.}"
        run_method "$COMBINED" "$cls" "$method"
    done
else
    # ---- FALLBACK: build the library once (cached), then per-file test targets. ----
    ISO=/grader-iso
    rm -rf "$ISO"
    mkdir -p "$ISO/Sources/Parsing" "$ISO/Tests/ParsingTests"
    copy_candidate_sources "$ISO"
    cp /tests/Package.grader.swift "$ISO/Package.swift"

    # Build the candidate library alone. If it doesn't compile, nothing can be graded.
    ( cd "$ISO" && timeout --signal=SIGKILL "$BUILD_TIMEOUT" \
        swift build -j 1 --disable-sandbox >/dev/null 2>&1 )
    LIB_BUILT=$?

    if [ "$LIB_BUILT" -ne 0 ]; then
        for pair in "${EXPECTED[@]}"; do echo "$pair FAILED" >> "$RESULTS"; done
    else
        # Unique test classes (one file per class, "<Class>.swift").
        declare -A SEEN_CLS
        for pair in "${EXPECTED[@]}"; do SEEN_CLS["${pair%%.*}"]=1; done
        for cls in "${!SEEN_CLS[@]}"; do
            rm -f "$ISO/Tests/ParsingTests/"*.swift
            cp "/tests/$cls.swift" "$ISO/Tests/ParsingTests/" 2>/dev/null
            ( cd "$ISO" && timeout --signal=SIGKILL "$BUILD_TIMEOUT" \
                swift build --build-tests -j 1 --disable-sandbox >/dev/null 2>&1 )
            BUILT=$?
            for pair in "${EXPECTED[@]}"; do
                c="${pair%%.*}"; m="${pair#*.}"
                [ "$c" = "$cls" ] || continue
                if [ "$BUILT" -eq 0 ]; then run_method "$ISO" "$cls" "$m"; else echo "$cls.$m FAILED" >> "$RESULTS"; fi
            done
        done
    fi
fi

python3 /tests/results_to_ctrf.py "$RESULTS" /tests/expected_tests.txt "$LOGDIR/ctrf.json"

# Reward: 1 iff the task is FULLY solved -- every expected test passed and nothing
# failed/errored/was skipped. Any other outcome (including a missing/unparsable ctrf.json) is 0.
CANONICAL_TOTAL=36
REWARD=$(python3 - "$LOGDIR/ctrf.json" "$CANONICAL_TOTAL" <<'PY' 2>/dev/null || echo 0
import json, sys
try:
    s = json.load(open(sys.argv[1]))["results"]["summary"]
    total = int(sys.argv[2])
    ok = (
        int(s.get("passed", 0)) == total
        and int(s.get("failed", 0)) == 0
        and int(s.get("other", 0)) == 0
        and int(s.get("skipped", 0)) == 0
    )
except Exception:
    ok = False
print(1 if ok else 0)
PY
)
case "$REWARD" in
    1) echo 1 > "$LOGDIR/reward.txt" ;;
    *) echo 0 > "$LOGDIR/reward.txt" ;;
esac
