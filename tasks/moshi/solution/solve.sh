#!/bin/bash
set -e

# Assemble the groundtruth /app from the reference implementation:
# github.com/square/moshi (pinned commit = tag 2.0.0-alpha.1), CORE module only. The clone is the
# ONLY network operation in the GT flow — GT eval keeps internet on in Container A for it; the
# grading container is offline.
PIN=e721d8a4807e989696bc577091900e35d739987b
git clone https://github.com/square/moshi.git /tmp/repo
cd /tmp/repo
git checkout "$PIN"

# The task surface is the `moshi` module core (package com.squareup.moshi + its .internal
# subpackage). We deliberately drop:
#   * src/main/java16/  — Java-Records support requires a Multi-Release JAR; niche corner, out of
#     scope for this task.
#   * moshi-kotlin/, moshi-kotlin-codegen/, moshi-adapters/, examples/, moshi-kotlin-tests/,
#     records-tests/ — not the target surface.
#   * internal/LinkedHashTreeMap.kt — bespoke red-black BST kept for Java 6 compat. Both call
#     sites (-JsonValueWriter.kt, MapJsonAdapter.kt) only need a Map<K,V>; we swap to LinkedHashMap
#     in solve.sh below. Drops ~770 LOC of internal-only code that is untestable through the
#     public API, without changing observable behavior.
#   * -MoshiKotlinExtensions.kt — @Deprecated (HIDDEN) shims left for source compat with the
#     pre-2.x extension API. Not part of the task surface. (Its sibling
#     -MoshiKotlinTypesExtensions.kt is KEPT: it defines Type.rawType / Type.asArrayType /
#     Set<Annotation>.nextAnnotations — used all over Util.kt and StandardJsonAdapters.kt.)
mkdir -p /app/src
cp -r /tmp/repo/moshi/src/main/java/com /app/src/

# Also include the moshi-kotlin module — the KotlinJsonAdapterFactory. Moshi core's ClassJsonAdapter
# explicitly refuses to reflect on Kotlin classes (throws IllegalArgumentException), so any
# realistic Kotlin usage of moshi requires this factory. The 7 files under
# com/squareup/moshi/kotlin/reflect/ merge cleanly into /app/src alongside the core (no path
# collisions). The deprecated top-level shim moshi-kotlin/.../com/squareup/moshi/KotlinJsonAdapterFactory.kt
# is dropped (see below).
cp -r /tmp/repo/moshi-kotlin/src/main/java/com/squareup/moshi/kotlin /app/src/com/squareup/moshi/

# Drop the files we're excluding from scope.
rm -f /app/src/com/squareup/moshi/internal/LinkedHashTreeMap.kt
rm -f /app/src/com/squareup/moshi/-MoshiKotlinExtensions.kt
# Drop the deprecated top-level KotlinJsonAdapterFactory shim from moshi-kotlin (the real class
# lives at com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory, copied above).
rm -f /app/src/com/squareup/moshi/KotlinJsonAdapterFactory.kt
# Drop the Java package-info (Nullable-annotation metadata; not a compilation unit we care about
# in an offline kotlinc build).
rm -f /app/src/com/squareup/moshi/package-info.java

# Swap the LinkedHashTreeMap call sites to LinkedHashMap. Both files only use it as `Map<K,V>`;
# LinkedHashMap preserves insertion order which matches moshi's observable behavior.
sed -i \
    -e 's/import com.squareup.moshi.internal.LinkedHashTreeMap/import java.util.LinkedHashMap/' \
    -e 's/LinkedHashTreeMap</LinkedHashMap</g' \
    /app/src/com/squareup/moshi/-JsonValueWriter.kt \
    /app/src/com/squareup/moshi/internal/MapJsonAdapter.kt

cd /app
rm -rf /tmp/repo

# setup.sh is SOURCED (not executed) by the grading harness — it must not call `exit`. It performs
# the OFFLINE build of the library into /app/moshi.jar (the interface test.sh compiles the hidden
# suite against). The image bakes the toolchain (kotlinc 2.3.20 + kotlin-reflect) and the sole
# runtime dep (okio-jvm-3.17.0.jar at /opt/libs/); kotlinc uses only local jars, so this needs no
# network. This mirrors what the agent is expected to produce from instruction.md.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
# Offline build: compile the com.squareup.moshi sources under src/ into /app/moshi.jar.
KOTLIN_LIB="${KOTLIN_HOME:-/root/.sdkman/candidates/kotlin/current}/lib"
OKIO=/opt/libs/okio-jvm-3.17.0.jar
JSR305=/opt/libs/jsr305-3.0.2.jar
INTELLIJ_ANN="$KOTLIN_LIB/annotations-13.0.jar"
KOTLIN_METADATA="$KOTLIN_LIB/kotlin-metadata-jvm.jar"
kotlinc \
  -jvm-default=enable \
  -opt-in=kotlin.contracts.ExperimentalContracts \
  -cp "$OKIO:$KOTLIN_LIB/kotlin-reflect.jar:$JSR305:$INTELLIJ_ANN:$KOTLIN_METADATA" \
  src -d /app/moshi.jar || return 1
EOF
chmod +x /app/setup.sh
