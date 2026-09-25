#!/bin/bash
set -e

# Ground-truth solution for the dyn4j task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE dyn4j source as the agent's deliverable and writes the offline build script.

git clone https://github.com/dyn4j/dyn4j.git /tmp/repo
cd /tmp/repo
git checkout 1a3a5872dca5bc65fd9a2376100e33bed5d3cde6   # pinned (v5.0.2) for reproducibility

# The agent's deliverable = the entire dyn4j library source (all packages under org/dyn4j).
mkdir -p /app/src
cp -a /tmp/repo/src/main/java/. /app/src/
# Compile in CLASSPATH mode, not the Java module system: drop module-info so that a PARTIAL agent
# submission (missing packages) still compiles cleanly. META-INF holds only resources, not sources.
rm -f /app/src/module-info.java
rm -rf /app/src/META-INF

# Alias the package org.dyn4j -> org.physkit (anti-contamination): the agent implements `physkit`
# per instruction.md and never sees the real library name. Behaviour is identical; only the package
# identifier changes. This is what the hidden tests (which import org.physkit.*) compile against.
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's/org\.dyn4j/org.physkit/g'
mv /app/src/org/dyn4j /app/src/org/physkit

cd /app
rm -rf /tmp/repo

# setup.sh builds the whole library OFFLINE with plain javac -- dyn4j has ZERO external deps, so no
# classpath jars are needed. No `set -e` here so a compile failure cannot abort the (no-set-e)
# test.sh that sources it.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
EOF
