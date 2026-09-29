#!/bin/bash
# Offline grading for jamal (Java macro language).
# Compiles agent's source, then compiles + runs hidden test harness against it.
# No `set -e` — always produce CTRF.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

# 1. Build agent's source via setup.sh
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2. Find agent's compiled classes — try multiple locations
AGENT_CP=""
# Check common build output dirs
for d in /app/out /app/build/classes/java/main /app/target/classes /app/repo/build/classes/java/main /app/repo/target/classes; do
  if [ -d "$d" ] && find "$d" -name "*.class" 2>/dev/null | head -1 | grep -q .; then
    AGENT_CP="$d"
    break
  fi
done

# Fallback: compile all Java sources ourselves
if [ -z "$AGENT_CP" ]; then
  mkdir -p /app/out
  find /app -name "*.java" ! -path "*/test*/*" ! -name "module-info.java" > /tmp/sources.txt 2>/dev/null
  javac -d /app/out @/tmp/sources.txt 2>/dev/null || true
  AGENT_CP="/app/out"
fi

# Copy META-INF/services into classpath if they exist elsewhere
if [ ! -d "$AGENT_CP/META-INF/services" ]; then
  for rdir in $(find /app -path "*/META-INF/services" -type d 2>/dev/null); do
    mkdir -p "$AGENT_CP/META-INF/services"
    cp -n "$rdir"/* "$AGENT_CP/META-INF/services/" 2>/dev/null
  done
fi

# 3. Compile hidden test harness against agent's classes
mkdir -p /tmp/testout
javac -cp "$AGENT_CP" -d /tmp/testout /tests/TestJamal.java 2>/logs/verifier/test_compile.log

if [ $? -ne 0 ] || [ ! -f /tmp/testout/TestJamal.class ]; then
  # Test compilation failed — emit all-fail CTRF
  printf '{"results":{"tool":{"name":"java-test"},"summary":{"tests":1,"passed":0,"failed":1,"pending":0,"skipped":0,"other":0},"tests":[{"name":"BUILD","status":"failed","message":"test compilation failed"}]}}' \
    > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi

# 4. Run tests — outputs JSON lines to stdout
java -cp "/tmp/testout:$AGENT_CP" TestJamal > /logs/verifier/test_results.jsonl 2>/logs/verifier/test_run.log

# 5. Convert JSONL results to CTRF
python3 - <<'PY'
import json, sys

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

# 6. Reward
python3 -c "
import json
TOTAL = 57  # [verifier].test_case_count in task.toml
s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
ok = (s.get('passed', 0) == TOTAL and s.get('failed', 0) == 0
      and s.get('other', 0) == 0 and s.get('skipped', 0) == 0)
open('/logs/verifier/reward.txt', 'w').write('1' if ok else '0')
" 2>/dev/null || echo 0 > /logs/verifier/reward.txt
