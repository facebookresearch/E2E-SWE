#!/bin/bash
# Offline grading for the commons-compress replication task.
#
# The agent implements com.wrg.compress.Archives (list/decompress/compress/write/detect) under
# /app/src and a setup.sh that compiles it into /app/out. This script builds it, compiles + runs the
# Java Harness (which loads the agent's class and runs the baked behavioral corpus with a per-case
# timeout), then converts results to CTRF. Uses only the JDK + python3 -- no network.
#
# For GT eval, solve.sh's setup.sh populates /app/gt-lib (commons-compress + deps) and writes a
# reference Archives; that classpath entry is empty in the agent flow, so the agent never has
# commons-compress.
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

# 1. Build the agent's Archives (offline) via the setup.sh it wrote (or solve.sh's for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2. Compile the Harness (pure JDK; loads Archives reflectively at run time).
javac -encoding UTF-8 -d /tmp/h /tests/Harness.java 2>/logs/verifier/harness_compile.log || true

# 3. Run the Harness -> one JSON line per case (10s per-case timeout, 1500s overall budget).
java -Dfile.encoding=UTF-8 -cp "/tmp/h:$CP" Harness /tests/cases.dat /logs/verifier/results.jsonl 10000 1500000 \
    2>/logs/verifier/harness_run.log || true

# 4. Convert results to CTRF (102 canonical cases; missing -> failed, denominator preserved).
python3 /tests/make_ctrf.py /logs/verifier/results.jsonl 102 /logs/verifier/ctrf.json \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: binary, 1 iff every one of the 102 canonical cases passed (no failed/other/skipped).
REWARD=$(python3 -c "
import json,sys
try:
    s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    ok = (int(s.get('passed', 0)) == 102 and int(s.get('failed', 0)) == 0
          and int(s.get('other', 0)) == 0 and int(s.get('skipped', 0)) == 0
          and int(s.get('pending', 0)) == 0)
except Exception:
    ok = False
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
