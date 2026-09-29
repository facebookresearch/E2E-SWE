#!/bin/bash
# Offline grading for the quickfixj task.
#
# The agent implements the `io.fix` library under /app/src and provides /app/setup.sh that
# compiles it into /app/out. This script builds the agent's code, then compiles + runs each Java
# test driver against it (independently, so one off-signature symbol only zeroes its own small
# cluster), and converts per-case JSON results to CTRF via the stdlib python3 bridge. Uses only
# the JDK + python3 in the per-task image -- no pip, no network.
#
# No `set -e`: every stage must run so a CTRF report is always produced (a broken submission
# yields an all-fail report with the denominator preserved, i.e. reward 0, rather than a grader
# error).

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier /tmp/h

# 1. Build the agent's library (offline) via the setup.sh it wrote (or solve.sh for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2-3. Compile + run each driver INDEPENDENTLY against the agent's classes + baked SLF4J JARs.
: > /logs/verifier/qfj_results.jsonl
for DRIVER in \
    MessageBasicsHarness \
    OrderingHarness \
    FieldMapHarness \
    RepeatingGroupHarness \
    CharsetHarness \
    DataFieldHarness \
    DictionaryLoadHarness \
    ValidationHarness \
    DualDictHarness \
    WireHarness \
    ParseValidateHarness \
    Fixt50Harness \
    SessionFlowHarness \
    ApplicationCallbackHarness \
    FieldTypesHarness \
    SessionIdHarness \
    ParserPathsHarness \
    SpecEdgeCasesHarness \
    DecimalHarness \
    HeaderOrderingHarness \
    MessageStoreHarness \
    ApiTypesHarness \
    ParseMalformedHarness \
    ; do
    [ -f "/tests/$DRIVER.java" ] || continue
    rm -rf /tmp/h && mkdir -p /tmp/h
    # Search common Java build-output locations so the agent isn't forced into one convention.
    # /app/out (bare javac -d out), /app/build/classes (Gradle default), /app/target/classes
    # (Maven default). Every JAR under /app/build/libs or /app/target is also on the classpath.
    APP_CP="/app/out:/app/build/classes:/app/target/classes:/app/build/libs/*:/app/target/*"
    if javac -cp "$APP_CP:/opt/deps/*" -d /tmp/h /tests/Runner.java "/tests/$DRIVER.java" 2>"/logs/verifier/${DRIVER}_compile.log"; then
        # /app/dictionaries/ on the RUNTIME classpath so DataDictionary("FIX44.xml") resolves via
        # the classloader (spec: "provided on the test classpath"). Also /opt/deps/* for SLF4J.
        EXPECTED_TSV=/tests/expected.tsv java -cp "/tmp/h:$APP_CP:/opt/deps/*:/app/dictionaries" "$DRIVER" \
            >> /logs/verifier/qfj_results.jsonl 2>"/logs/verifier/${DRIVER}_run.log" || true
    fi
done

# 4. Convert results to CTRF (canonical case list = names in /tests/expected.tsv).
python3 /tests/make_ctrf.py /logs/verifier/qfj_results.jsonl /logs/verifier/ctrf.json /tests/expected.tsv \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: all-or-nothing. 1 iff every canonical case passed (passed == CANONICAL_TOTAL and
#    failed == other == skipped == 0); otherwise 0. Never a fraction.
CANONICAL_TOTAL=136
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os
try:
    s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    total = int(os.environ['CANONICAL_TOTAL'])
    ok = (int(s.get('passed', 0)) == total
          and int(s.get('failed', 0)) == 0
          and int(s.get('other', 0)) == 0
          and int(s.get('skipped', 0)) == 0
          and int(s.get('pending', 0)) == 0
          and int(s.get('tests', 0)) == total)
except Exception:
    ok = False
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
