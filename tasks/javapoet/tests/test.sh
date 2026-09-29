#!/bin/bash
# Offline grading for the javapoet task.
#
# The agent implements the whole JavaPoet library (package com.squareup.javapoet) under /app/src and
# provides /app/setup.sh that compiles it into /app/out. This script builds the agent's code, then
# compiles + runs the Java test drivers (*Harness.java) against it to produce per-test JSON results,
# and converts those into the CTRF report the grader reads. Uses only the JDK + python3 already in
# the per-task image -- no pip, no network. JavaPoet has no external runtime dependencies, so the
# harness compiles against /app/out alone (plus the JDK's javax.lang.model).
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

# 1. Build the agent's javapoet source (offline) via the setup.sh it wrote (or solve.sh's for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2-3. Compile + run each harness INDEPENDENTLY against the agent's classes. Splitting the API into
# per-capability drivers means a compile failure in one capability (e.g. a missing CodeBlock method)
# does not zero the others -- a submission implementing only TypeName/TypeSpec still scores those
# cases. Each driver emits only its own cases; results are concatenated. Missing cases (driver failed
# to compile/run) are recorded as failed by make_ctrf, preserving the denominator.
: > /logs/verifier/results.jsonl
for DRIVER in TypeNameHarness MemberHarness MethodHarness TypeSpecHarness CodeBlockHarness JavaFileHarness AnnotationHarness NameAllocatorHarness WrapImportHarness TypeAnnoHarness WrapGenericHarness; do
    rm -rf /tmp/h && mkdir -p /tmp/h
    if javac -cp "/app/out" -d /tmp/h /tests/Runner.java "/tests/$DRIVER.java" 2>"/logs/verifier/${DRIVER}_compile.log"; then
        EXPECTED_TSV=/tests/expected.tsv java -cp "/tmp/h:/app/out" "$DRIVER" \
            >> /logs/verifier/results.jsonl 2>"/logs/verifier/${DRIVER}_run.log" || true
    fi
done

# 4. Convert results to CTRF (canonical case list = names in /tests/expected.tsv; missing -> failed).
python3 /tests/make_ctrf.py /logs/verifier/results.jsonl /logs/verifier/ctrf.json /tests/expected.tsv \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: all-or-nothing. 1 iff every canonical case passed (passed == 130, the task's
# test_case_count) with no failures, skips, or other statuses; 0 otherwise.
CANONICAL_TOTAL=130
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 - <<'PY' 2>/dev/null || echo 0
import json, os
total = int(os.environ["CANONICAL_TOTAL"])
s = json.load(open("/logs/verifier/ctrf.json"))["results"]["summary"]
ok = (int(s.get("passed", 0)) == total
      and int(s.get("failed", 0)) == 0
      and int(s.get("other", 0)) == 0
      and int(s.get("skipped", 0)) == 0
      and int(s.get("pending", 0)) == 0)
print(1 if ok else 0)
PY
)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
