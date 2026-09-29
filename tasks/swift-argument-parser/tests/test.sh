#!/bin/bash
# Offline grading driver for the Swift `swift-argument-parser` task.
#
# The Swift 6.0 toolchain and python3 are pre-baked in the per-task image (see
# environment/Dockerfile); there is NO network. Do not add apt-get/curl/download steps.
#
# Strategy: the candidate's library lives at /app as a SwiftPM package exposing a module named
# `ArgumentParser`. We do NOT trust the candidate's Package.swift — we assemble a clean,
# dependency-free grader package whose `ArgumentParser` target IS the candidate's *.swift sources
# (copied preserving relative subdirs so a split-across-folders layout with repeated file
# basenames still compiles), plus the hidden test case files.
#
# Each hidden test lives in its OWN <Class>.swift case file with a uniquely-named XCTestCase.
# This gives PER-TEST COMPILE ISOLATION: a candidate missing one documented feature (e.g. default
# values, an `Int`-counting flag) breaks only the case files that use that feature, not unrelated
# tests. That matters because the candidate under evaluation is a command-line PARSER and a
# broken one can also infinite-loop or allocate without bound at RUNTIME.
#
# Grading has a fast path and a fallback:
#   * FAST PATH — build ONE grader package containing the candidate + ALL case files (serialized,
#     `-j 1`, to bound peak RAM). If it builds, run each test method alone under a time cap
#     (`timeout`) AND a virtual-memory cap (`ulimit -v`), so a runaway test fails cleanly while
#     the container survives and everything else still scores. This is the common case (ground
#     truth and any candidate that compiles cleanly) and costs a single build.
#   * FALLBACK — if the combined build fails (a candidate that doesn't compile every case), build
#     ONE grader package PER case file. A compile error then zeros only that file's tests. Each
#     file's tests are still run under the per-test time/memory caps.
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

BUILD_TIMEOUT=1500      # serialized test-build cap (seconds)
TEST_TIMEOUT=25         # per-method run cap (seconds)
TEST_VMEM_KB=4194304    # per-method virtual-memory cap (4 GB)

# The grader manifest pins the lenient Swift 5 language mode; keep a Swift 6 twin next to it. The
# language mode is a harness detail the spec does not constrain, and neither mode subsumes the
# other (v5 is lenient about concurrency, v6 accepts constructs v5 rejects), so every build below
# tries v5 first and retries under v6 rather than zeroing a candidate over the mode alone.
MANIFESTS=/grader-manifests
rm -rf "$MANIFESTS"; mkdir -p "$MANIFESTS"
PKG_V5="$MANIFESTS/Package.v5.swift"
PKG_V6="$MANIFESTS/Package.v6.swift"
cp /tests/Package.grader.swift "$PKG_V5"
sed 's/\.swiftLanguageMode(\.v5)/.swiftLanguageMode(.v6)/' /tests/Package.grader.swift > "$PKG_V6"

# Build one grader package, v5 language mode then v6. Leaves the manifest that built in place so
# the later `swift test --skip-build` reuses it. Returns 0 iff one of the two builds succeeded.
build_pkg () {
    local dir="$1" manifest
    for manifest in "$PKG_V5" "$PKG_V6"; do
        cp "$manifest" "$dir/Package.swift"
        ( cd "$dir" && timeout --signal=SIGKILL "$BUILD_TIMEOUT" \
            swift build --build-tests -j 1 --disable-sandbox >/dev/null 2>&1 ) && return 0
    done
    return 1
}

# Copy the candidate library sources into a grader package dir, preserving relative subdirs.
copy_candidate_sources () {
    local dir="$1"
    ( cd /app/Sources 2>/dev/null && find . -name '*.swift' -print0 | while IFS= read -r -d '' f; do
        mkdir -p "$dir/Sources/ArgumentParser/$(dirname "$f")"
        cp "$f" "$dir/Sources/ArgumentParser/$f"
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
mkdir -p "$COMBINED/Sources/ArgumentParser" "$COMBINED/Tests/ArgumentParserTests"
copy_candidate_sources "$COMBINED"
cp /tests/*Tests.swift "$COMBINED/Tests/ArgumentParserTests/" 2>/dev/null

build_pkg "$COMBINED"
COMBINED_BUILT=$?

if [ "$COMBINED_BUILT" -eq 0 ]; then
    for pair in "${EXPECTED[@]}"; do
        cls="${pair%%.*}"; method="${pair#*.}"
        run_method "$COMBINED" "$cls" "$method"
    done
else
    # ---- FALLBACK: one grader package per case file. ----
    for pair in "${EXPECTED[@]}"; do
        cls="${pair%%.*}"; method="${pair#*.}"
        casefile="/tests/$cls.swift"
        dir="/grader-$cls"
        if [ ! -d "$dir" ]; then
            rm -rf "$dir"
            mkdir -p "$dir/Sources/ArgumentParser" "$dir/Tests/ArgumentParserTests"
            copy_candidate_sources "$dir"
            cp "$casefile" "$dir/Tests/ArgumentParserTests/" 2>/dev/null
            build_pkg "$dir"
            echo "$?" > "$dir/.built"
        fi
        if [ "$(cat "$dir/.built" 2>/dev/null)" = "0" ]; then
            run_method "$dir" "$cls" "$method"
        else
            echo "$cls.$method FAILED" >> "$RESULTS"
        fi
    done
fi

python3 /tests/results_to_ctrf.py "$RESULTS" /tests/expected_tests.txt "$LOGDIR/ctrf.json"

# Reward: all-or-nothing. 1 iff every one of the CANONICAL_TOTAL expected tests passed and
# nothing failed, errored, or was skipped; 0 otherwise.
CANONICAL_TOTAL=34
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
        and int(s.get("pending", 0)) == 0
    )
except Exception:
    ok = False
print(1 if ok else 0)
PY
)
case "$REWARD" in 1) echo 1 > "$LOGDIR/reward.txt" ;; *) echo 0 > "$LOGDIR/reward.txt" ;; esac
