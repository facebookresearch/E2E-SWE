#!/bin/bash
# Offline grading driver for the Swift `splash` task.
#
# The Swift toolchain and python3 are pre-baked in the per-task image (see environment/Dockerfile);
# there is NO network. Do not add apt-get/curl/download steps.
#
# Strategy: the candidate's library lives at /app as a SwiftPM package (a single module named
# `Splash`). We do NOT trust the candidate's Package.swift -- instead we assemble a clean,
# dependency-free grader package whose `Splash` target IS the candidate's *.swift sources, plus one
# hidden XCTest file, and run it.
#
# Two layers of isolation:
#  (1) Per-LAYER compile isolation: each hidden test file (e.g. StringLiteralTests.swift) is built
#      in its OWN grader package, so a compile error in one layer cannot zero the other layers'
#      tests. (For Splash every test hits the same tiny public API -- SyntaxHighlighter +
#      HTMLOutputFormat.highlight, MarkdownDecorator.decorate -- so per-test compile divergence is
#      minimal; the real signal is the exact HTML each `highlight` call produces.)
#  (2) Per-TEST runtime isolation: within a layer we build the test bundle once, then run each test
#      method in its own process under a hard `timeout` + virtual-memory `ulimit`. A candidate's
#      hand-rolled tokenizer can infinite-loop (e.g. on malformed string/comment nesting) or
#      allocate without bound; isolating each method means such a hang/OOM fails only that one test
#      instead of the whole layer or the whole grading container. (`swift test --parallel`/xunit
#      would hang the entire layer on a single looping test, over-penalizing the candidate.)
#
# Layers are AUTO-DISCOVERED from /tests/*Tests.swift, so adding/removing a hidden test file needs
# no edit here. results_to_ctrf.py folds the per-method results into the single CTRF report the
# grader reads, using the baked expected_tests.txt as the canonical denominator (any expected test
# with no recorded pass -- build failure / crash / timeout -- is failed).
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

BUILD_TIMEOUT=400     # per-layer test-bundle build cap (GT builds each layer in ~20-40s; headroom)
TEST_TIMEOUT=20       # per-test-method run cap (a correct test finishes in <1s; a hung tokenizer
                      # gains nothing from waiting, so 20s detects hangs while keeping the suite fast)
TEST_MEM_KB=4194304   # per-test-method virtual-memory cap (4 GB). A correct test uses <100 MB; a
                      # candidate tokenizer can infinite-loop while ALLOCATING, which would OOM-kill
                      # the whole grading container faster than the time cap fires. Capping each test
                      # process well below container RAM makes such a runaway crash only that one
                      # test (recorded failed) instead of zeroing the task.

run_layer () {
    local name="$1" testfile="$2"
    local dir="/grader-$name"
    rm -rf "$dir"
    mkdir -p "$dir/Sources/Splash" "$dir/Tests/SplashTests"
    # Candidate library sources (Swift only). Preserve each file's path relative to /app/Sources
    # so that same-named files in different candidate subdirectories don't overwrite each other (a
    # candidate may legitimately split the module across folders, as the reference does with
    # Grammar/, Tokenizing/, Output/, etc.). Package.grader.swift's Splash target globs *.swift
    # recursively, so nested files still compile into the `Splash` module regardless of folders.
    find /app/Sources -name '*.swift' 2>/dev/null | while IFS= read -r f; do
        rel="${f#/app/Sources/}"
        mkdir -p "$dir/Sources/Splash/$(dirname "$rel")"
        cp "$f" "$dir/Sources/Splash/$rel"
    done
    cp "/tests/$testfile" "$dir/Tests/SplashTests/"
    cp /tests/Package.grader.swift "$dir/Package.swift"

    # Discover the test class + its methods directly from the hidden test file.
    local cls methods
    cls=$(grep -oE 'final class [A-Za-z0-9_]+' "/tests/$testfile" | head -1 | awk '{print $3}')
    methods=$(grep -oE 'func (test[A-Za-z0-9_]+)' "/tests/$testfile" | awk '{print $2}')

    # Build the test bundle once. If it fails/times out, every method in this layer is failed.
    # `-j 1` serializes compilation: one swiftc at a time keeps peak RAM bounded so a large or
    # RAM-hungry candidate library can't OOM-kill the grading container (which would otherwise zero
    # the whole task -- an unfair artifact rather than a real score).
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

# Auto-discover every hidden test layer (/tests/*Tests.swift); layer name = filename stem.
for testpath in /tests/*Tests.swift; do
    [ -e "$testpath" ] || continue
    base=$(basename "$testpath" .swift)
    run_layer "$base" "$base.swift"
done

python3 /tests/results_to_ctrf.py "$RESULTS" /tests/expected_tests.txt "$LOGDIR/ctrf.json"

# Reward: 1 iff the task is FULLY solved -- every one of the 34 declared tests passed and
# nothing failed / errored / was skipped. Any other outcome (including a missing/unparsable
# ctrf.json) is 0.
CANONICAL_TOTAL=34
python3 - "$LOGDIR/ctrf.json" "$CANONICAL_TOTAL" > "$LOGDIR/reward.txt" <<'PY'
import json, sys
try:
    s = json.load(open(sys.argv[1]))["results"]["summary"]
    total = int(sys.argv[2])
    ok = (int(s.get("passed", 0)) == total
          and int(s.get("failed", 0)) == 0
          and int(s.get("other", 0)) == 0
          and int(s.get("skipped", 0)) == 0)
except Exception:
    ok = False
print(1 if ok else 0)
PY
