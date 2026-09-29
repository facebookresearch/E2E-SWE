#!/bin/bash
# Offline grading driver for the Swift `swiftsoup` task.
#
# The Swift toolchain and python3 are pre-baked in the per-task image (see
# environment/Dockerfile); there is NO network. Do not add apt-get/curl/download steps.
#
# Strategy: the candidate's library lives at /app as a SwiftPM package (a single module
# named `SwiftSoup`). We do NOT trust the candidate's Package.swift -- instead we assemble a
# clean, dependency-free grader package whose `SwiftSoup` target IS the candidate's *.swift
# sources, plus one hidden XCTest file, and run it.
#
# Two layers of isolation:
#  (1) Per-LAYER compile isolation: each hidden test class is built in its OWN grader package,
#      so a compile error in one layer (e.g. a missing Whitelist or Entities API) cannot zero
#      the other layers' tests.
#  (2) Per-TEST runtime isolation: within a layer we build the test bundle once, then run each
#      test method in its own process under a hard `timeout`. A model HTML parser can
#      infinite-loop on malformed input; isolating each method means such a hang fails only
#      that one test instead of the whole layer. (`swift test --parallel`/xunit would hang the
#      entire layer on a single looping test, over-penalizing the candidate.)
#
# results_to_ctrf.py folds the per-method results into the single CTRF report the grader reads,
# using the baked expected_tests.txt as the canonical denominator (any expected test with no
# recorded pass -- build failure / crash / timeout -- is failed).
#
# No `set -e`: we must run every layer/method and the merge regardless of individual exit codes.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

cd /tmp 2>/dev/null || cd /

LOGDIR=/logs/verifier
mkdir -p "$LOGDIR"
RESULTS="$LOGDIR/results.txt"; : > "$RESULTS"   # lines: "<method> passed|failed"

BUILD_TIMEOUT=300     # per-layer test-bundle build cap (GT builds in ~15s; generous headroom)
TEST_TIMEOUT=20       # per-test-method run cap (a correct test finishes in <1s; a hung parser
                      # gains nothing from waiting, so 20s detects hangs while keeping the whole
                      # suite fast -- worst case 39 x 20s + 6 builds stays far under verifier.timeout_sec)
TEST_MEM_KB=4194304   # per-test-method virtual-memory cap (4 GB). A correct test uses <100 MB; a
                      # candidate parser can infinite-loop while ALLOCATING (e.g. appending in a
                      # loop), which would OOM-kill the whole grading container faster than the time
                      # cap fires. Capping each test process well below container RAM makes such a
                      # runaway crash only that one test (recorded failed) instead of zeroing the task.

run_layer () {
    local name="$1" testfile="$2"
    local dir="/grader-$name"
    rm -rf "$dir"
    mkdir -p "$dir/Sources/SwiftSoup" "$dir/Tests/SwiftSoupTests"
    # Candidate library sources (Swift only). Preserve each file's path relative to
    # /app/Sources so that same-named files in different candidate subdirectories don't
    # overwrite each other (a candidate may legitimately split its single module across
    # folders). Package.grader.swift's SwiftSoup target globs *.swift recursively, so nested
    # files still compile into the `SwiftSoup` module regardless of the candidate's folders.
    find /app/Sources -name '*.swift' 2>/dev/null | while IFS= read -r f; do
        rel="${f#/app/Sources/}"
        mkdir -p "$dir/Sources/SwiftSoup/$(dirname "$rel")"
        cp "$f" "$dir/Sources/SwiftSoup/$rel"
    done
    cp "/tests/$testfile" "$dir/Tests/SwiftSoupTests/"
    cp /tests/Package.grader.swift "$dir/Package.swift"

    # Discover the test class + its methods directly from the hidden test file.
    local cls methods
    cls=$(grep -oE 'final class [A-Za-z0-9_]+' "/tests/$testfile" | head -1 | awk '{print $3}')
    methods=$(grep -oE 'func (test[A-Za-z0-9_]+)' "/tests/$testfile" | awk '{print $2}')

    # Build the test bundle once. If it fails/times out, every method in this layer is failed.
    # `-j 1` serializes compilation: one swiftc at a time keeps peak RAM bounded so a large or
    # RAM-hungry candidate library can't OOM-kill the grading container (which would otherwise
    # zero the whole task -- an unfair artifact rather than a real score).
    if ( cd "$dir" && timeout --signal=SIGKILL "$BUILD_TIMEOUT" \
            swift build --build-tests -j 1 --disable-sandbox >/dev/null 2>&1 ); then
        local m
        for m in $methods; do
            local log="/tmp/run_${name}_${m}.log"
            ( ulimit -v "$TEST_MEM_KB" 2>/dev/null; cd "$dir" && timeout --signal=SIGKILL "$TEST_TIMEOUT" \
                swift test --skip-build -j 1 --disable-sandbox --filter "${cls}/${m}\$" >"$log" 2>&1 )
            # A method passed only if XCTest reported it passing and nothing failed.
            if grep -qF "$m' passed" "$log" && ! grep -qF "$m' failed" "$log"; then
                echo "$m passed" >> "$RESULTS"
            else
                echo "$m failed" >> "$RESULTS"
            fi
            rm -f "$log"
        done
    else
        local m
        for m in $methods; do echo "$m failed" >> "$RESULTS"; done
    fi
    rm -rf "$dir"
}

run_layer parsing  ParsingTests.swift
run_layer selector SelectorTests.swift
run_layer dom      TraversalManipulationTests.swift
run_layer output   OutputTests.swift
run_layer sanitize SanitizeTests.swift
run_layer entities EntitiesTests.swift

python3 /tests/results_to_ctrf.py "$RESULTS" /tests/expected_tests.txt "$LOGDIR/ctrf.json"

# Reward gate: 1 IFF the task is fully solved, i.e. every one of the CANONICAL_TOTAL
# declared tests passed and nothing failed / errored / was skipped. Never fractional.
CANONICAL_TOTAL=39
REWARD=$(python3 -c "
import json, sys
total = int(sys.argv[2])
try:
    s = json.load(open(sys.argv[1]))['results']['summary']
except Exception:
    print(0); raise SystemExit
ok = (int(s.get('passed', 0)) == total
      and int(s.get('failed', 0)) == 0
      and int(s.get('other', 0)) == 0
      and int(s.get('skipped', 0)) == 0
      and int(s.get('pending', 0)) == 0)
print(1 if ok else 0)
" "$LOGDIR/ctrf.json" "$CANONICAL_TOTAL" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > "$LOGDIR/reward.txt" ;;
    *) echo 0 > "$LOGDIR/reward.txt" ;;
esac
