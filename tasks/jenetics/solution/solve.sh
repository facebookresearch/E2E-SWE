#!/bin/bash
set -e

# Ground-truth solution for the jenetics task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE jenetics core-module source as the agent's deliverable and writes the offline build.
#
# Pinned to the v7.2.0 release tag (Java 17 source — builds on the JDK 17 base). HEAD targets Java 25
# which the base cannot compile, hence the tag pin.

git clone https://github.com/jenetics/jenetics.git /tmp/repo
cd /tmp/repo
git checkout v7.2.0

# The agent's deliverable = the whole core `jenetics` module (all packages under io/jenetics/**).
# The other repo modules (jenetics.ext/prog/xml/...) are out of scope.
mkdir -p /app/src
cp -a /tmp/repo/jenetics/src/main/java/. /app/src/
# Compile in classpath mode: drop module-info so a PARTIAL agent submission still compiles.
find /app/src -name 'module-info.java' -delete
# doc-files are javadoc resources, not sources.
rm -rf /app/src/io/jenetics/doc-files 2>/dev/null || true

# Alias the package io.jenetics -> io.evolab (anti-contamination): the agent implements `evolab` per
# instruction.md and never sees the real library name. Behaviour is identical; only the package
# identifier changes. The hidden tests import io.evolab.* and compile against this.
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's/io\.jenetics/io.evolab/g'
mv /app/src/io/jenetics /app/src/io/evolab

cd /app
rm -rf /tmp/repo

# setup.sh builds the whole module OFFLINE with plain javac -- jenetics core has ZERO external deps.
# No `set -e` here so a compile failure cannot abort the (no-set-e) test.sh that sources it.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
EOF
