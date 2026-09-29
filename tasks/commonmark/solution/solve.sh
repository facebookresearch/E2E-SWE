#!/bin/bash
set -e

# Ground-truth solution for the commonmark task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE commonmark-java core-module source as the agent's deliverable and writes the
# offline build script.
#
# Pinned to the commonmark-parent-0.29.0 release tag (Java 11 source -> compiles on the JDK 17
# base). The core `commonmark` module has ZERO external runtime dependencies (pure Java); its only
# data dependency is a table of HTML5 named character references (entities.txt), which is baked
# into the image at /app/entities.txt and placed on the classpath here for the reference impl.

git clone https://github.com/commonmark/commonmark-java.git /tmp/repo
cd /tmp/repo
git checkout commonmark-parent-0.29.0

# The agent's deliverable = the whole core `commonmark` module (all packages under org/commonmark/**).
# The other repo modules (extensions, test-util, integration-test) are out of scope.
mkdir -p /app/src
cp -a /tmp/repo/commonmark/src/main/java/. /app/src/
# Compile in classpath mode: drop module-info so a PARTIAL agent submission still compiles.
find /app/src -name 'module-info.java' -delete

# Alias the package org.commonmark -> org.mdcore (anti-contamination): the agent implements the
# `org.mdcore` library per instruction.md and never sees the real library name. Behaviour is
# identical; only the package identifier changes. The hidden tests import org.mdcore.* and compile
# against this. Two forms are rewritten: the dotted form (package/import/qualified refs) and the
# slash form (the classpath-resource path string in Html5Entities: "/org/commonmark/.../entities.txt").
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's/org\.commonmark/org.mdcore/g'
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's#org/commonmark#org/mdcore#g'
mv /app/src/org/commonmark /app/src/org/mdcore

cd /app
rm -rf /tmp/repo

# setup.sh builds the whole module OFFLINE with plain javac (ZERO external deps). It also stages the
# HTML5 named-entity data table (baked at /app/entities.txt) onto the classpath at the aliased
# resource path the reference Html5Entities loader expects. No `set -e` here so a compile failure
# cannot abort the (no-set-e) test.sh that sources it.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out/org/mdcore/internal/util
cp /app/entities.txt /app/out/org/mdcore/internal/util/entities.txt
find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
EOF
