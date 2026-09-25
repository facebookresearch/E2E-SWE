#!/bin/bash
set -e

# Ground-truth setup. This is the ONLY container with network in the eval flow
# (GT eval keeps internet on for this clone). git is pre-baked in the per-task image.
git clone https://github.com/orchestr7/ktoml.git /tmp/repo
cd /tmp/repo
git checkout 267f5dfc4b7caa667d687dce136f86cbb2f6e2ec

# Assemble a flat, JVM-only source tree under /app/src from ktoml-core
# (commonMain + jvmMain). The non-JVM source sets, buildSrc plugins, publishing,
# diktat and the ktoml-file / ktoml-source modules are not library logic and are
# dropped (they are out of scope and hostile to an offline build).
mkdir -p /app/src
cp -a /tmp/repo/ktoml-core/src/commonMain/kotlin/com /app/src/
cp -a /tmp/repo/ktoml-core/src/jvmMain/kotlin/com/. /app/src/com/ 2>/dev/null || true

# Adapt the multiplatform sources into a JVM-only, offline-buildable tree:
#   * fold the two expect/actual declarations into plain JVM functions
#   * remove the kotlinx-datetime dependency (datetimes are recognized at the
#     grammar level and stored as strings; decoding into concrete date types is
#     out of scope). This mirrors exactly what the task asks the agent to do.
# The patch script is shipped alongside this solution.
cp "$(dirname "$0")/patch_offline.py" /app/patch_offline.py
python3 /app/patch_offline.py /app/src

rm -rf /tmp/repo

cd /app

# setup.sh performs the OFFLINE build (kotlinc-direct, no Gradle, no network).
# It is sourced by test.sh in the (offline) grading container. We only WRITE it
# here; we do not run it.
cat > /app/setup.sh <<'SETUP'
#!/bin/bash
# Offline build of the ktoml library with kotlinc + the bundled kotlinx-serialization
# compiler plugin and runtime. No Gradle, no network. Produces /app/ktoml.jar and
# exports KTOML_CP for the grader.
KOTLIN_LIB=/root/.sdkman/candidates/kotlin/2.3.20/lib
SER_PLUGIN=$KOTLIN_LIB/kotlinx-serialization-compiler-plugin.jar
SER_CORE=/root/.sdkman/candidates/gradle/9.4.1/lib/kotlinx-serialization-core-jvm-1.9.0.jar

kotlinc /app/src -Xplugin="$SER_PLUGIN" -cp "$SER_CORE" -d /app/ktoml.jar

export SER_CORE
export KTOML_JAR=/app/ktoml.jar
export KTOML_CP="/app/ktoml.jar:$SER_CORE"
SETUP
chmod +x /app/setup.sh
