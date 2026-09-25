#!/bin/bash
# Offline grading for the `seckit` task (JDBC connection-string filtering subsystem). Everything
# (JDK, lombok 1.18.36 + slf4j-api 2.0.16 under /opt/seckit/libs, JUnit 5) is pre-baked in the
# per-task image. There is NO network -- no apt-get / curl / maven here.
#
# No `set -e`: we capture the build/run exit codes for the reward, and always emit a CTRF report.
#
# Build contract: the implementation lives as Java sources under /app/src, package
# javac-direct) against the baked jars so grading does not depend on the exact artifact an agent's
# setup.sh emits. Lombok is on the compile classpath (and thus auto-discovered as an annotation
# processor) so the ground-truth reference (which uses lombok annotations) compiles; a plain-Java
# agent submission compiles equally well (an unused processor is a no-op). We still run the agent's
# setup.sh in a subshell first so any codegen the agent put there executes.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

LOMBOK=$(ls /opt/seckit/libs/lombok-*.jar 2>/dev/null | head -1)
SLF4J=$(ls /opt/seckit/libs/slf4j-api-*.jar 2>/dev/null | head -1)
# lombok must be on the COMPILE classpath (the reference sources `import lombok.*`); on the classpath
# javac also auto-discovers it as an annotation processor. slf4j-api is needed at compile time (for
# the @Slf4j-generated Logger references) and at runtime (NOP logger when no binding is present).
COMPILE_CP="$SLF4J:$LOMBOK"
IMPL_DEPS="$SLF4J"

GROOVY_LIB=/root/.sdkman/candidates/groovy/current/lib
if [ ! -d "$GROOVY_LIB" ]; then
  GROOVY_LIB=$(ls -d /root/.sdkman/candidates/groovy/*/lib 2>/dev/null | head -1)
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
  bash -c 'bash ./setup.sh' >/dev/null 2>&1
fi

# 1. Compile the implementation sources under /app/src into /app/out.
if [ ! -d /app/src ] || [ -z "$(find /app/src -name '*.java' 2>/dev/null)" ]; then
  emit_failed_ctrf "no implementation sources found under /app/src"
  exit 0
fi
rm -rf /app/out && mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac --release 8 -encoding UTF-8 -cp "$COMPILE_CP" -d /app/out
if [ $? -ne 0 ] || [ -z "$(ls -A /app/out 2>/dev/null)" ]; then
  emit_failed_ctrf "implementation under /app/src failed to compile"
  exit 0
fi
IMPL_CP="/app/out:$IMPL_DEPS"

# 2. Compile the hidden test suite + runner against the freshly built library.
rm -rf /app/testout && mkdir -p /app/testout
javac -encoding UTF-8 -cp "$IMPL_CP:$JUNIT_CP" -d /app/testout "$TESTS_DIR/SeckitTest.java" "$TESTS_DIR/TestRunner.java"
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
