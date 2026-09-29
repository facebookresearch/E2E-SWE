#!/bin/bash
set -e

# Ground-truth solution for the `jtoon` task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE JToon core library source as the agent's deliverable and writes the offline build
# script. Pinned to a specific commit for reproducibility (Java 17 source; JDK 17 base compiles it).
git clone https://github.com/toon-format/toon-java.git /tmp/repo
cd /tmp/repo
git checkout 3eb8a64df96a90c1afb04b2b8c603a021e0229c5

# The agent's deliverable = the whole core library under src/main/java (package dev.toonformat.jtoon
# and its subpackages). Tests, benchmarks, conformance fixtures, and the Gradle plugin config are
# out of scope. Compile in classpath mode: drop module-info if present so a PARTIAL agent submission
# still compiles.
mkdir -p /app/src
cp -a /tmp/repo/src/main/java/. /app/src/
find /app/src -name 'module-info.java' -delete

cd /app
rm -rf /tmp/repo

# setup.sh builds the library OFFLINE with plain javac against the baked Jackson 3 + JSpecify jars
# (/opt/jtoon/libs). It is SOURCED (not executed) by the grading harness, so it must not call `exit`.
# This mirrors what the agent is expected to produce from instruction.md. No NullAway/ErrorProne --
# those are Gradle-only compile checks and are irrelevant to a plain javac build.
cat > /app/setup.sh <<'EOF'
CP=$(ls /opt/jtoon/libs/*.jar | tr '\n' ':')
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -encoding UTF-8 -cp "$CP" -d /app/out || return 1
EOF
chmod +x /app/setup.sh
