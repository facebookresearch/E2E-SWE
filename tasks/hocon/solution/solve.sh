#!/bin/bash
set -e

# Ground-truth solution for the hocon task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE lightbend/config core-module source as the agent's deliverable and writes the
# offline build script.
#
# Pinned to the v1.4.9 release tag (Java 8 source -> compiles on the JDK 17 base). The core
# `config` module has ZERO external runtime dependencies (pure Java on the JDK); the Scala test
# suite and lift-json/junit are test-only and are NOT part of the deliverable.

git clone https://github.com/lightbend/config.git /tmp/repo
cd /tmp/repo
git checkout v1.4.9

# The agent's deliverable = the whole core `config` module (all packages under com/typesafe/config/**:
# the public API package, plus .impl and .parser). The other repo modules (examples, test-lib) are
# out of scope.
mkdir -p /app/src
cp -a /tmp/repo/config/src/main/java/. /app/src/
# Compile in classpath mode: drop module-info so a PARTIAL agent submission still compiles.
find /app/src -name 'module-info.java' -delete
# package.html / package-info are javadoc-only; harmless to keep, but package.html is not a source.
find /app/src -name 'package.html' -delete 2>/dev/null || true

# Alias the package com.typesafe.config -> com.lattice.config (anti-contamination): the agent
# implements the `com.lattice.config` library per instruction.md and never sees the real library
# name. Behaviour is identical; only the package identifier changes. The hidden tests import
# com.lattice.config.* and compile against this. The core module has no resource files and no
# slash-form package references, so a single dotted-form rewrite plus the directory move suffices.
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's/com\.typesafe\.config/com.lattice.config/g'
mkdir -p /app/src/com/lattice
mv /app/src/com/typesafe/config /app/src/com/lattice/config
rmdir /app/src/com/typesafe 2>/dev/null || true

cd /app
rm -rf /tmp/repo

# setup.sh builds the whole module OFFLINE with plain javac -- the config core has ZERO external
# deps. The reference source targets Java 8 and compiles cleanly on the JDK 17 base at the default
# source level. No `set -e` here so a compile failure cannot abort the (no-set-e) test.sh that
# sources it.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
EOF
