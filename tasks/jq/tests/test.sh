#!/bin/bash
# Offline grading for the jq processor task.
#
# The agent implements com.wrg.jq.JqEngine (String evaluate(String program, String inputJson)) under
# /app/src and a setup.sh that compiles it into /app/out. This script builds it, compiles + runs the
# Java Harness (which loads the agent's class and runs the baked behavioral corpus with a per-case
# timeout), then converts results to CTRF. Uses only the JDK + python3 in the image -- no network.
#
# For GT eval, solve.sh's setup.sh populates /app/gt-lib (jackson-jq + deps) and writes a reference
# engine; that classpath entry is empty in the agent flow, so the agent never has jackson-jq.
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

# 0. Anti-cheat: a jq processor must be implemented in-language. Reject any solution that shells out
#    to an external process -- e.g. a thin wrapper around a system `jq`/`gojq` binary that may be
#    present on the general-purpose base image. Spawning a subprocess in Java requires either
#    `ProcessBuilder` or `Runtime.getRuntime()`, so matching those two tokens is precise (it does not
#    trip on an interpreter's own `exec()` method). A from-scratch pure-JDK implementation never needs
#    this, and the GT reference engine uses the jackson-jq *library* (no subprocess), so GT is
#    unaffected. On a hit: force a 0-reward CTRF (denominator preserved) and stop.
if grep -rEl 'ProcessBuilder|Runtime[[:space:]]*\.[[:space:]]*getRuntime|getRuntime[[:space:]]*\(' /app/src >/logs/verifier/anticheat.log 2>&1; then
    echo "external-process invocation detected in /app/src -> reward 0 (see matches above)" >>/logs/verifier/anticheat.log
    python3 /tests/make_ctrf.py /dev/null 316 /logs/verifier/ctrf.json >/logs/verifier/ctrf.log 2>&1 || true
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

# 1. Build the agent's JqEngine (offline) via the setup.sh it wrote (or solve.sh's for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2. Compile the Harness (pure JDK; loads JqEngine reflectively at run time).
javac -encoding UTF-8 -d /tmp/h /tests/Harness.java 2>/logs/verifier/harness_compile.log || true

# 3. Run the Harness -> one JSON line per case (8s per-case timeout, 1500s overall budget).
java -Dfile.encoding=UTF-8 -cp "/tmp/h:$CP" Harness /tests/cases.dat /logs/verifier/results.jsonl 8000 1500000 \
    2>/logs/verifier/harness_run.log || true

# 4. Convert results to CTRF (316 canonical cases; missing -> failed, denominator preserved).
python3 /tests/make_ctrf.py /logs/verifier/results.jsonl 316 /logs/verifier/ctrf.json \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: all-or-nothing. 1 iff every one of the 316 canonical cases passed and nothing
#    failed / errored / was skipped; otherwise 0.
REWARD=$(python3 - 316 /logs/verifier/ctrf.json <<'PY' 2>/dev/null || echo 0
import json, sys
total = int(sys.argv[1])
s = json.load(open(sys.argv[2]))["results"]["summary"]
g = lambda k: int(s.get(k, 0) or 0)
print(1 if (g("passed") == total and g("failed") == 0 and g("other") == 0
            and g("skipped") == 0 and g("pending") == 0) else 0)
PY
)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
