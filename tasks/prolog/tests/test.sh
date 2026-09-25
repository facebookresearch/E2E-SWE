#!/bin/bash
# Offline grading for the Prolog processor task.
#
# The agent implements com.wrg.prolog.PrologEngine (String solve(String program, String query)) under
# /app/src and a setup.sh that compiles it into /app/out. This script builds it, compiles + runs the
# Java Harness (which loads the agent's class and runs the baked behavioral corpus with a per-case
# timeout), then converts results to CTRF. Uses only the JDK + python3 in the image -- no network.
#
# For GT eval, solve.sh's setup.sh populates /app/gt-lib (projog jars) and writes a reference engine;
# that classpath entry is empty in the agent flow, so the agent never has Projog.
#
# No `set -e`: every stage must run so a CTRF report is always produced (denominator preserved).

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier /tmp/h

CP="/app/out:/app/gt-lib/*"

# 0. Anti-cheat: a Prolog engine must be implemented in-language. Reject any solution that shells out
#    to an external process (e.g. a wrapper around a system swipl/gprolog that may exist on the base
#    image). Spawning a subprocess in Java requires ProcessBuilder or Runtime.getRuntime(), so those
#    two tokens are matched precisely. A from-scratch pure-JDK implementation never needs this, and the
#    GT reference uses the Projog *library* (no subprocess), so GT is unaffected.
if grep -rEl 'ProcessBuilder|Runtime[[:space:]]*\.[[:space:]]*getRuntime|getRuntime[[:space:]]*\(' /app/src >/logs/verifier/anticheat.log 2>&1; then
    echo "external-process invocation detected in /app/src -> reward 0 (see matches above)" >>/logs/verifier/anticheat.log
    python3 /tests/make_ctrf.py /dev/null 373 /logs/verifier/ctrf.json >/logs/verifier/ctrf.log 2>&1 || true
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

# 1. Build the agent's PrologEngine (offline) via the setup.sh it wrote (or solve.sh's for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2. Compile the Harness (pure JDK; loads PrologEngine reflectively at run time).
javac -encoding UTF-8 -d /tmp/h /tests/Harness.java 2>/logs/verifier/harness_compile.log || true

# 3. Run the Harness -> one JSON line per case (20s per-case timeout, 1650s overall budget).
#    20s (vs the sibling tasks' 8s) because each case constructs a fresh engine and the reference
#    Projog re-bootstraps its whole knowledge base per case; on the 1-CPU grading container the
#    heaviest queries need the headroom (GT must reach 100%).
java -Dfile.encoding=UTF-8 -cp "/tmp/h:$CP" Harness /tests/cases.dat /logs/verifier/results.jsonl 20000 1650000 \
    2>/logs/verifier/harness_run.log || true

# 4. Convert results to CTRF (373 canonical cases; missing -> failed, denominator preserved).
python3 /tests/make_ctrf.py /logs/verifier/results.jsonl 373 /logs/verifier/ctrf.json \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: 1 iff every one of the 373 canonical cases passed (no failures/skips/others).
SUMMARY=$(python3 -c "
import json
s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
print(s.get('passed', 0), s.get('failed', 1), s.get('skipped', 1), s.get('other', 1))
" 2>/dev/null) || SUMMARY=""
set -- ${SUMMARY:-0 1 1 1}
PASSED=${1:-0}; FAILED=${2:-1}; SKIPPED=${3:-1}; OTHER=${4:-1}
if [ "$PASSED" = "373" ] && [ "$FAILED" = "0" ] && [ "$SKIPPED" = "0" ] && [ "$OTHER" = "0" ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
