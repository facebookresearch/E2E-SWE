#!/bin/bash
# Offline grading for the moshi task. Everything (kotlinc, kotlin stdlib/reflect, JUnit 5, and
# okio-jvm-3.17.0.jar) is pre-baked in the per-task image. There is NO network — no apt-get /
# curl / gradle here.
#
# No `set -e`: we capture the build/run exit codes for the reward.
#
# Build contract: the implementation lives as Kotlin sources under /app/src, in package
# `com.squareup.moshi` (+ its `.internal` subpackage). The grader compiles those sources itself
# (offline, kotlinc-direct) so grading does not depend on the exact artifact an agent's setup.sh
# emits. We still `source ./setup.sh` first so any codegen the agent put there runs.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

KOTLIN_LIB="${KOTLIN_HOME:-/root/.sdkman/candidates/kotlin/current}/lib"
GROOVY_LIB=/root/.sdkman/candidates/groovy/5.0.5/lib
REFLECT="$KOTLIN_LIB/kotlin-reflect.jar"
OKIO=/opt/libs/okio-jvm-3.17.0.jar
JSR305=/opt/libs/jsr305-3.0.2.jar
INTELLIJ_ANN="$KOTLIN_LIB/annotations-13.0.jar"
KOTLIN_METADATA="$KOTLIN_LIB/kotlin-metadata-jvm.jar"
RUNTIME_CP="$KOTLIN_LIB/kotlin-stdlib.jar:$REFLECT:$OKIO:$KOTLIN_METADATA"
JUNIT_CP="$GROOVY_LIB/junit-jupiter-api-5.14.3.jar:$GROOVY_LIB/junit-jupiter-engine-5.14.3.jar:$GROOVY_LIB/junit-platform-commons-1.14.3.jar:$GROOVY_LIB/junit-platform-engine-1.14.3.jar:$GROOVY_LIB/junit-platform-launcher-1.14.3.jar:$GROOVY_LIB/opentest4j-1.3.0.jar"
TESTS_DIR=/tests
KOTLINC_FLAGS="-jvm-default=enable -opt-in=kotlin.contracts.ExperimentalContracts"

emit_failed_ctrf() {
  echo "GRADING FAILURE: $1"
  printf '{"results":{"tool":{"name":"junit5"},"summary":{"tests":0,"passed":0,"failed":1,"skipped":0,"pending":0,"other":0,"start":0,"stop":0},"tests":[{"name":"build","status":"failed","duration":0}]}}\n' > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
}

cd /app

# Run the agent's setup.sh if present (harmless side effects / codegen). We ignore its build output
# and recompile /app/src ourselves below for a deterministic classpath.
if [ -f ./setup.sh ]; then
  bash ./setup.sh >/dev/null 2>&1
fi

# 1. Compile the implementation sources under /app/src into a jar.
if [ ! -d /app/src ] || [ -z "$(ls -A /app/src 2>/dev/null)" ]; then
  emit_failed_ctrf "no implementation sources found under /app/src"
  exit 0
fi

kotlinc $KOTLINC_FLAGS -cp "$OKIO:$REFLECT:$JSR305:$INTELLIJ_ANN:$KOTLIN_METADATA" /app/src -d /app/moshi.jar
if [ $? -ne 0 ] || [ ! -f /app/moshi.jar ]; then
  emit_failed_ctrf "implementation under /app/src failed to compile"
  exit 0
fi
LIB_CP="/app/moshi.jar:$OKIO:$REFLECT"

# 2. Compile the hidden tests + runner against the freshly built library.
kotlinc "$TESTS_DIR/test_moshi.kt" "$TESTS_DIR/TestRunner.kt" \
  -cp "$LIB_CP:$JUNIT_CP" -d /app/tests.jar
if [ $? -ne 0 ] || [ ! -f /app/tests.jar ]; then
  emit_failed_ctrf "hidden test suite failed to compile against the implementation (missing or wrong public API)"
  exit 0
fi

# 3. Run the suite; TestRunner writes the CTRF report directly and exits non-zero on any failure.
java -cp "/app/tests.jar:$LIB_CP:$JUNIT_CP:$RUNTIME_CP" wrg.hidden.TestRunnerKt /logs/verifier/ctrf.json
run_rc=$?

if [ ! -f /logs/verifier/ctrf.json ]; then
  emit_failed_ctrf "test runner did not produce CTRF (exit $run_rc)"
  exit 0
fi

# 4. Reward: 1 iff the runner reported every test passed (exit 0).
if [ "$run_rc" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
