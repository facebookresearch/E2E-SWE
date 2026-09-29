#!/bin/bash
# Offline build of the ktoml library with kotlinc + the bundled kotlinx-serialization
# compiler plugin and runtime. No Gradle, no network. Produces /app/ktoml.jar and
# exports KTOML_CP for the grader. (This is the file the ground-truth solve.sh writes;
# the agent is expected to provide an equivalent setup.sh that compiles its own /app/src.)
KOTLIN_LIB=/root/.sdkman/candidates/kotlin/2.3.20/lib
SER_PLUGIN=$KOTLIN_LIB/kotlinx-serialization-compiler-plugin.jar
SER_CORE=/root/.sdkman/candidates/gradle/9.4.1/lib/kotlinx-serialization-core-jvm-1.9.0.jar

kotlinc /app/src -Xplugin="$SER_PLUGIN" -cp "$SER_CORE" -d /app/ktoml.jar

export SER_CORE
export KTOML_JAR=/app/ktoml.jar
export KTOML_CP="/app/ktoml.jar:$SER_CORE"
