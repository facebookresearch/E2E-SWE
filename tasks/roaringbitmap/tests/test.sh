#!/bin/bash
# Offline grading for the chunkbits task (io.chunkbits, aliased RoaringBitmap core module).
#
# The library has ZERO external runtime deps, so the agent's OWN compiled classes are the only
# classpath. The agent implements the library under /app (any layout it likes) and provides
# /app/setup.sh to build it. This script sources that setup.sh, then discovers the agent's compiled
# classes REGARDLESS of build layout (and, as a guaranteed fallback, compiles the agent's /app
# sources itself), compiles + runs each Java test driver against them to produce per-test JSON, and
# converts that to CTRF. Uses only the JDK + python3 in the per-task image -- no pip, no network.
#
# No `set -e`: every stage must run so a CTRF report is always produced (a broken submission yields
# an all-fail report with the denominator preserved -> reward 0, rather than a grader error).
#
# Independently-compiled drivers, split into SMALL self-contained per-capability files so a compile
# failure (one off-signature symbol) only zeroes its own small cluster instead of the whole suite.
# The DRIVERS list is kept in lockstep with the *Harness.java files in this directory.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier /tmp/h

cd /app 2>/dev/null || cd "$(pwd)"

# 1. Build the agent's source (offline) via the setup.sh it wrote (or solve.sh for GT). Capture any
#    CLASSPATH it exports so we can reuse its chosen build location.
bash ./setup.sh 2>/logs/verifier/setup.log || true
AGENT_EXPORTED_CP="${CLASSPATH}"

# 2. Layout-agnostic classpath to the agent's compiled classes: (a) reuse any CLASSPATH its setup.sh
#    exported, (b) add every common output dir that exists, (c) as a guaranteed fallback, compile ALL
#    of the agent's *.java under /app ourselves into /app/out so grading never depends on the build
#    choice. The fallback keeps grading fair: a correct implementation is judged on behavior, not on
#    whether it built to the exact directory the harness expected.
FALLBACK_OUT=/app/out
mkdir -p "$FALLBACK_OUT"
AGENT_SRCS=$(find /app -name '*.java' \
    -not -path '*/test/*' -not -path '*/tests/*' -not -path '*/example*/*' 2>/dev/null)
if [ -n "$AGENT_SRCS" ]; then
    echo "$AGENT_SRCS" | xargs javac -d "$FALLBACK_OUT" 2>/logs/verifier/fallback_compile.log || true
fi

AGENT_CP="${FALLBACK_OUT}"
for d in /app/out /app/build/classes /app/build/classes/java/main /app/target/classes /app/bin /app/classes; do
    [ -d "$d" ] && AGENT_CP="${AGENT_CP}:${d}"
done
[ -n "$AGENT_EXPORTED_CP" ] && AGENT_CP="${AGENT_CP}:${AGENT_EXPORTED_CP}"
echo "AGENT_CP=$AGENT_CP" > /logs/verifier/agent_cp.log

# 3. Compile + run each driver INDEPENDENTLY against the agent's classes (no external jars).
#    TESTDATA_DIR points the 64-bit portable-fixture cases at the committed /tests/testdata.
: > /logs/verifier/results.jsonl
for DRIVER in \
    BasicOpsHarness \
    SetAlgebraHarness \
    RankSelectHarness \
    FlipHarness \
    IteratorHarness \
    RangeConsumerHarness \
    OptimizeHarness \
    SerializationHarness \
    AggregationHarness \
    WriterHarness \
    BitSetInteropHarness \
    RangeIndexHarness \
    RunEncodingHarness \
    BufferHarness \
    BufferAggregationHarness \
    InsightsHarness \
    Long64Harness \
    Long64NavHarness; do
    [ -f "/tests/$DRIVER.java" ] || continue
    rm -rf /tmp/h && mkdir -p /tmp/h
    if javac -cp "$AGENT_CP" -d /tmp/h /tests/Runner.java "/tests/$DRIVER.java" 2>"/logs/verifier/${DRIVER}_compile.log"; then
        EXPECTED_TSV=/tests/expected.tsv TESTDATA_DIR=/tests/testdata \
            java -cp "/tmp/h:$AGENT_CP" "$DRIVER" \
            >> /logs/verifier/results.jsonl 2>"/logs/verifier/${DRIVER}_run.log" || true
    fi
done

# 4. Convert results to CTRF (canonical case list = names in /tests/expected.tsv; missing -> failed).
python3 /tests/make_ctrf.py /logs/verifier/results.jsonl /logs/verifier/ctrf.json /tests/expected.tsv \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: 1 iff the whole suite passed (passed == CANONICAL_TOTAL and nothing failed/skipped/other).
CANONICAL_TOTAL=200
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os
total = int(os.environ['CANONICAL_TOTAL'])
try:
    s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    ok = (int(s.get('passed', 0)) == total
          and int(s.get('failed', 0)) == 0
          and int(s.get('skipped', 0)) == 0
          and int(s.get('pending', 0)) == 0
          and int(s.get('other', 0)) == 0)
except Exception:
    ok = False
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
