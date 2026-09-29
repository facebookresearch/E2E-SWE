#!/bin/bash
# Offline grading driver for the Swift `expression` task.
#
# The Swift toolchain and python3 are pre-baked in the per-task image (see
# environment/Dockerfile); there is NO network. Do not add apt-get/curl/download steps.
#
# Strategy: the candidate's library lives at /app as a SwiftPM package (a single module
# named `Expression`). We do NOT trust the candidate's Package.swift — instead we assemble a
# clean, dependency-free grader package whose `Expression` target IS the candidate's *.swift
# sources, plus one hidden XCTest file, and run `swift test`.
#
# Each hidden test class is compiled+run in its OWN grader package so that a compile error in
# one layer (e.g. an incomplete AnyExpression API) cannot zero the other layer's tests. A
# per-build `timeout` turns a hang/crash into a clean per-layer failure. junit_to_ctrf.py then
# folds the per-layer JUnit XML into the single CTRF report the grader reads, marking every
# expected test whose XML is missing (compile failure / crash / timeout) as failed so the
# denominator always reflects the full suite.
#
# No `set -e`: we must run every layer and the merge regardless of individual exit codes.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

cd /tmp 2>/dev/null || cd /   # stable cwd; build_and_run rm -rf's the grader dirs

LOGDIR=/logs/verifier
mkdir -p "$LOGDIR"
PARTS="$LOGDIR/parts"; rm -rf "$PARTS"; mkdir -p "$PARTS"

build_and_run () {
    local name="$1" testfile="$2" out="$3"
    local dir="/grader-$name"
    rm -rf "$dir"
    mkdir -p "$dir/Sources/Expression" "$dir/Tests/ExpressionTests"
    # Candidate library sources (Swift only; flattened so any Sources/<module>/ layout works).
    find /app/Sources -name '*.swift' -exec cp {} "$dir/Sources/Expression/" \; 2>/dev/null
    cp "/tests/$testfile" "$dir/Tests/ExpressionTests/"
    cp /tests/Package.grader.swift "$dir/Package.swift"
    # NOTE: SwiftPM only writes --xunit-output when running in --parallel mode.
    ( cd "$dir" && timeout --signal=SIGKILL 600 \
        swift test --parallel --disable-sandbox --xunit-output "$out" >/dev/null 2>&1 )
}

build_and_run core ExpressionCoreTests.swift       "$PARTS/core.xml"
build_and_run any  AnyExpressionFeatureTests.swift "$PARTS/any.xml"

python3 /tests/junit_to_ctrf.py "$PARTS" /tests/expected_tests.txt "$LOGDIR/ctrf.json"

# Reward: 1 iff the whole suite ran and every test passed, else 0.
CANONICAL_TOTAL=35
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os, sys
try:
    s = json.load(open('$LOGDIR/ctrf.json'))['results']['summary']
    total = int(os.environ['CANONICAL_TOTAL'])
    ok = (int(s.get('passed', 0)) == total
          and int(s.get('failed', 0)) == 0
          and int(s.get('other', 0)) == 0
          and int(s.get('skipped', 0)) == 0)
except Exception:
    ok = False
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > "$LOGDIR/reward.txt" ;;
    *) echo 0 > "$LOGDIR/reward.txt" ;;
esac
