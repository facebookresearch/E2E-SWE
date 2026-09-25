#!/bin/bash
# Offline grading for the staedi task.
#
# The agent implements the whole StAEDI library under /app/src and provides /app/setup.sh that
# compiles it against the baked jars in /opt/staedi/lib into /app/out. This script builds the
# agent's code, compiles + runs each Java test driver (Harness*.java) against it to produce per-test
# JSON results, then converts those into the CTRF report the grader reads. Uses only the JDK +
# python3 already in the per-task image -- no pip, no network.
#
# No `set -e`: every stage must run so a CTRF report is always produced (a broken submission yields
# an all-fail report with the denominator preserved, i.e. reward 0, rather than a grader error).

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier /tmp/h
LIB=/opt/staedi/lib
CP=$(ls $LIB/*.jar | paste -sd:)

# 1. Build the agent's StAEDI source (offline) via the setup.sh it wrote (or solve.sh for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2-3. Compile + run each test driver INDEPENDENTLY against the agent's classes. Splitting drivers
# per-capability (e.g. tokenizer vs validation vs schema) means a compile failure in one capability
# does not zero the others -- fair partial credit. Drivers are auto-discovered (Harness*.java), so
# adding a driver needs no edit here. Each driver emits only its own cases; results are concatenated.
# Missing cases (driver failed to compile/run) are recorded as failed by make_ctrf, preserving the
# denominator.
: > /logs/verifier/staedi_results.jsonl
for DRIVER_FILE in /tests/Harness*.java; do
    [ -e "$DRIVER_FILE" ] || continue          # no drivers yet (scaffold) -> empty results
    DRIVER=$(basename "$DRIVER_FILE" .java)
    rm -rf /tmp/h && mkdir -p /tmp/h
    if javac -cp "/app/out:$CP" -d /tmp/h /tests/Runner.java "$DRIVER_FILE" 2>"/logs/verifier/${DRIVER}_compile.log"; then
        EXPECTED_TSV=/tests/expected.tsv java -cp "/tmp/h:/app/out:$CP" "$DRIVER" \
            >> /logs/verifier/staedi_results.jsonl 2>"/logs/verifier/${DRIVER}_run.log" || true
    fi
done

# 4. Convert results to CTRF (canonical case list = names in /tests/expected.tsv; missing -> failed).
python3 /tests/make_ctrf.py /logs/verifier/staedi_results.jsonl /logs/verifier/ctrf.json /tests/expected.tsv \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: binary all-or-nothing. 1 iff every canonical case passed (passed == CANONICAL_TOTAL,
# the number of cases in /tests/expected.tsv) and there are no failed/other/skipped cases.
CANONICAL_TOTAL=$(grep -cP '\t' /tests/expected.tsv 2>/dev/null || echo 0)
REWARD=$(CANONICAL_TOTAL="${CANONICAL_TOTAL:-0}" python3 - <<'PY' 2>/dev/null || echo 0
import json, os
total = int(os.environ.get("CANONICAL_TOTAL") or 0)
s = json.load(open("/logs/verifier/ctrf.json"))["results"]["summary"]
ok = (
    total > 0
    and int(s.get("passed", 0)) == total
    and int(s.get("failed", 0)) == 0
    and int(s.get("other", 0)) == 0
    and int(s.get("skipped", 0)) == 0
    and int(s.get("pending", 0)) == 0
)
print(1 if ok else 0)
PY
)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
