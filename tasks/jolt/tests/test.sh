#!/bin/bash
# Offline grading for jolt (Java JSON-transformation DSL).
# Compiles the agent's source against the baked jars, then compiles + runs the hidden
# test harness (which reads fixtures from /tests/fixtures and compares parsed JSON trees).
# No `set -e` — always produce CTRF.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

LIB=/opt/jolt-lib
CP=$(ls "$LIB"/*.jar | paste -sd:)

# 1. Compile agent's Java source (exclude any tests the agent may have written).
mkdir -p /app/out
find /app -name "*.java" ! -path "*/test/*" ! -path "*/tests/*" ! -name "module-info.java" \
  ! -path "*/out/*" > /tmp/sources.txt 2>/dev/null
javac -cp "$CP" -d /app/out @/tmp/sources.txt 2>/logs/verifier/agent_compile.log
AGENT_CP=/app/out

# Fallback: if nothing compiled, try common build-output dirs the agent may have used.
if ! find "$AGENT_CP" -name "*.class" 2>/dev/null | head -1 | grep -q .; then
  for d in /app/build/classes/java/main /app/target/classes /app/repo/target/classes; do
    if [ -d "$d" ] && find "$d" -name "*.class" 2>/dev/null | head -1 | grep -q .; then
      AGENT_CP="$d"; break
    fi
  done
fi

# 2. Compile the hidden test harness against the agent's classes + provided jars.
mkdir -p /tmp/testout
javac -cp "$AGENT_CP:$CP" -d /tmp/testout /tests/TestJolt.java 2>/logs/verifier/test_compile.log

if [ $? -ne 0 ] || [ ! -f /tmp/testout/TestJolt.class ]; then
  printf '{"results":{"tool":{"name":"java-test"},"summary":{"tests":1,"passed":0,"failed":1,"pending":0,"skipped":0,"other":0},"tests":[{"name":"BUILD","status":"failed","message":"agent source or test harness failed to compile"}]}}' \
    > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi

# 3. Run the harness — one JSON line per test to stdout.
java -cp "/tmp/testout:$AGENT_CP:$CP" TestJolt > /logs/verifier/test_results.jsonl 2>/logs/verifier/test_run.log

# 4. Convert JSONL results to CTRF.
python3 - <<'PY'
import json

results = []
passed = failed = 0
try:
    for line in open("/logs/verifier/test_results.jsonl"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        results.append(r)
        if r.get("status") == "passed":
            passed += 1
        else:
            failed += 1
except Exception as e:
    if not results:
        results.append({"name": "HARNESS", "status": "failed", "message": str(e)})
        failed = 1

report = {
    "results": {
        "tool": {"name": "java-test"},
        "summary": {
            "tests": passed + failed,
            "passed": passed,
            "failed": failed,
            "pending": 0, "skipped": 0, "other": 0
        },
        "tests": results
    }
}
json.dump(report, open("/logs/verifier/ctrf.json", "w"), indent=2)
PY

# 5. Reward: 1 only if every declared test ran and passed.
TOTAL=50
python3 -c "
import json
s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
ok = (s.get('passed', 0) == $TOTAL and s.get('failed', 0) == 0
      and s.get('other', 0) == 0 and s.get('skipped', 0) == 0)
open('/logs/verifier/reward.txt', 'w').write('1' if ok else '0')
" 2>/dev/null || echo 0 > /logs/verifier/reward.txt
