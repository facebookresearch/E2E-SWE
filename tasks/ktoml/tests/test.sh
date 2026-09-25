#!/bin/bash
# Offline grading for the ktoml task. Everything (kotlinc, the kotlinx-serialization
# compiler plugin + runtime, JUnit 5, kotlin stdlib/reflect, python3) is pre-baked in
# the per-task image. There is NO network — no apt-get / curl / gradle here.
#
# No `set -e`: we capture the build/run exit codes for the reward.
#
# Build contract: the implementation lives as Kotlin sources under /app/src. The grader
# compiles those sources itself (offline, with the bundled serialization compiler plugin
# + runtime) so grading does not depend on the exact artifact an agent's setup.sh emits.
# We still `source ./setup.sh` first so any code-generation the agent put there runs.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

KOTLIN_LIB=/root/.sdkman/candidates/kotlin/2.3.20/lib
GROOVY_LIB=/root/.sdkman/candidates/groovy/5.0.5/lib
SER_PLUGIN=$KOTLIN_LIB/kotlinx-serialization-compiler-plugin.jar
SER_CORE=/root/.sdkman/candidates/gradle/9.4.1/lib/kotlinx-serialization-core-jvm-1.9.0.jar
JUNIT_CP="$GROOVY_LIB/junit-jupiter-api-5.14.3.jar:$GROOVY_LIB/junit-jupiter-engine-5.14.3.jar:$GROOVY_LIB/junit-platform-commons-1.14.3.jar:$GROOVY_LIB/junit-platform-engine-1.14.3.jar:$GROOVY_LIB/junit-platform-launcher-1.14.3.jar:$GROOVY_LIB/opentest4j-1.3.0.jar"
RUNTIME_CP="$KOTLIN_LIB/kotlin-stdlib.jar:$KOTLIN_LIB/kotlin-reflect.jar"
TESTS_DIR=/tests

emit_failed_ctrf() {
    local reason="$1"
    echo "$reason"
    python3 - "$reason" <<'PY'
import json, os, sys
os.makedirs("/logs/verifier", exist_ok=True)
reason = sys.argv[1]
out = {"results": {"tool": {"name": "junit5"},
                   "summary": {"tests": 0, "passed": 0, "failed": 1, "skipped": 0,
                               "pending": 0, "other": 0, "start": 0, "stop": 0},
                   "tests": [{"name": "build", "status": "failed", "duration": 0,
                              "message": reason}]}}
json.dump(out, open("/logs/verifier/ctrf.json", "w"))
PY
    echo 0 > /logs/verifier/reward.txt
}

cd /app

# Run the agent's setup.sh if present (harmless side effects / codegen). We ignore its
# build output and recompile /app/src ourselves below for a deterministic classpath.
if [ -f ./setup.sh ]; then
    bash ./setup.sh >/dev/null 2>&1
fi

# 1. Compile the implementation sources under /app/src into a jar.
if [ ! -d /app/src ]; then
    emit_failed_ctrf "no implementation sources found under /app/src"
    exit 0
fi

if [ -z "$(find /app/src -name '*.kt')" ]; then
    emit_failed_ctrf "no .kt files found under /app/src"
    exit 0
fi

kotlinc /app/src -Xplugin="$SER_PLUGIN" -cp "$SER_CORE" -d /app/agent_ktoml.jar
if [ $? -ne 0 ] || [ ! -f /app/agent_ktoml.jar ]; then
    emit_failed_ctrf "implementation under /app/src failed to compile"
    exit 0
fi
KTOML_CP="/app/agent_ktoml.jar:$SER_CORE"

# 2. Compile the hidden tests + TestRunner against the agent's library.
kotlinc "$TESTS_DIR/KtomlTest.kt" "$TESTS_DIR/TestRunner.kt" \
    -Xplugin="$SER_PLUGIN" \
    -cp "$KTOML_CP:$JUNIT_CP" \
    -d /app/tests.jar
if [ $? -ne 0 ] || [ ! -f /app/tests.jar ]; then
    emit_failed_ctrf "hidden test suite failed to compile against the implementation (missing or wrong public API)"
    exit 0
fi

# 3. Run the tests; TestRunner writes the CTRF report directly.
java -cp "/app/tests.jar:$KTOML_CP:$JUNIT_CP:$RUNTIME_CP" \
    com.akuleshov7.ktoml.hidden.TestRunnerKt /logs/verifier/ctrf.json
RUN_RC=$?

if [ ! -f /logs/verifier/ctrf.json ]; then
    emit_failed_ctrf "test runner did not produce CTRF (exit code $RUN_RC)"
fi

# 4. Reward: 1 iff the runner produced a CTRF in which all 35 declared tests passed
#    (no failures, no skips, no other) — anything else is 0.
python3 - "$RUN_RC" <<'PY'
import json, sys
CANONICAL_TOTAL = 35
rc = int(sys.argv[1])
try:
    s = json.load(open("/logs/verifier/ctrf.json"))["results"]["summary"]
    ok = rc == 0 and s.get("passed", 0) == CANONICAL_TOTAL \
        and s.get("failed", 1) == 0 and s.get("other", 0) == 0 \
        and s.get("skipped", 0) == 0
except Exception as e:
    print("could not read ctrf:", e)
    ok = False
open("/logs/verifier/reward.txt", "w").write("1" if ok else "0")
print("reward =", "1" if ok else "0")
PY
