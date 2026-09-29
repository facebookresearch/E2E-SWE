#!/bin/bash
# Offline grading for the `jtoon` task. Everything (JDK 17, Jackson 3 + JSpecify jars under
# /opt/jtoon/libs, JUnit 5) is pre-baked in the per-task image. There is NO network -- no apt-get /
# curl / gradle here.
#
# No `set -e`: we capture the build/run exit codes for the reward, and always emit a CTRF report.
#
# Build contract: the implementation lives as Java sources under /app/src, package
# `dev.toonformat.jtoon` (+ subpackages). The grader compiles those sources itself (offline,
# javac-direct) against the baked jars so grading does not depend on the exact artifact an agent's
# setup.sh emits. We still `source ./setup.sh` first so any codegen the agent put there runs.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

LIBS=$(ls /opt/jtoon/libs/*.jar | paste -sd: -)
GROOVY_LIB=/root/.sdkman/candidates/groovy/current/lib
if [ ! -d "$GROOVY_LIB" ]; then
  GROOVY_LIB=/root/.sdkman/candidates/groovy/5.0.5/lib
fi
JUNIT_CP=$(ls "$GROOVY_LIB"/junit-*.jar "$GROOVY_LIB"/opentest4j-*.jar "$GROOVY_LIB"/apiguardian-api-*.jar 2>/dev/null | paste -sd: -)
TESTS_DIR=/tests

emit_failed_ctrf() {
  echo "GRADING FAILURE: $1"
  printf '{"results":{"tool":{"name":"junit5"},"summary":{"tests":1,"passed":0,"failed":1,"skipped":0,"pending":0,"other":0,"start":0,"stop":0},"tests":[{"name":"build","status":"failed","duration":0}]}}\n' > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
}

cd /app

# Run the agent's setup.sh if present (harmless side effects / codegen). We ignore its build output
# and recompile /app/src ourselves below for a deterministic classpath.
if [ -f ./setup.sh ]; then
  bash ./setup.sh >/dev/null 2>&1
fi

# 1. Compile the implementation sources under /app/src into /app/out.
if [ ! -d /app/src ] || [ -z "$(find /app/src -name '*.java' 2>/dev/null)" ]; then
  emit_failed_ctrf "no implementation sources found under /app/src"
  exit 0
fi
rm -rf /app/out && mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -encoding UTF-8 -cp "$LIBS" -d /app/out
if [ $? -ne 0 ] || [ -z "$(ls -A /app/out 2>/dev/null)" ]; then
  emit_failed_ctrf "implementation under /app/src failed to compile"
  exit 0
fi
IMPL_CP="/app/out:$LIBS"

# 2. Compile the hidden test suite + runner against the freshly built library.
rm -rf /app/testout && mkdir -p /app/testout
javac -encoding UTF-8 -cp "$IMPL_CP:$JUNIT_CP" -d /app/testout "$TESTS_DIR/JToonTest.java" "$TESTS_DIR/TestRunner.java"
if [ $? -ne 0 ] || [ -z "$(ls -A /app/testout 2>/dev/null)" ]; then
  emit_failed_ctrf "hidden test suite failed to compile against the implementation (missing or wrong public API)"
  exit 0
fi

# 3. Run the suite; TestRunner writes CTRF directly and exits non-zero on any failure.
java -cp "/app/testout:$IMPL_CP:$JUNIT_CP" wrg.hidden.TestRunner /logs/verifier/ctrf.json
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
