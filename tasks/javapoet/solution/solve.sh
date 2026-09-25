#!/bin/bash
set -e

# Ground-truth solution for the javapoet task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE JavaPoet source as the agent's deliverable and writes the offline build script.

git clone https://github.com/square/javapoet.git /tmp/repo
cd /tmp/repo
# JavaPoet release tags are unprefixed (e.g. 1.13.0). Pin defensively across prefix variants.
git checkout 1.13.0 2>/dev/null \
  || git checkout javapoet-1.13.0 2>/dev/null \
  || git checkout v1.13.0 2>/dev/null \
  || { echo "ERROR: no 1.13.0 release tag found; available tags:"; git tag | tail -20; exit 1; }

# The agent's deliverable = the entire JavaPoet library source (package com.squareup.javapoet).
mkdir -p /app/src
cp -a /tmp/repo/src/main/java/. /app/src/

cd /app
rm -rf /tmp/repo

# setup.sh builds the whole library OFFLINE -- exactly what the agent must produce. JavaPoet has no
# external runtime dependencies, so plain javac against the JDK suffices. No `set -e` here so a
# compile failure cannot abort the (no-set-e) test.sh that sources it.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
EOF
