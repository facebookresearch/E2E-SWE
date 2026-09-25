#!/bin/bash
set -e

# Ground-truth solution: clone jolt at the pinned SHA and copy the full jolt-core
# transform source into /app/src. This clone is the ONLY network operation in the GT
# flow (GT eval keeps internet on for it). The grading container is offline and compiles
# /app/src against the baked jars in /opt/jolt-lib.
git clone https://github.com/bazaarvoice/jolt.git /tmp/repo
cd /tmp/repo
git checkout 990aee98233362dd0a1c8975056f280c55305c19

mkdir -p /app/src
cp -a /tmp/repo/jolt-core/src/main/java/. /app/src/
cd /app
rm -rf /tmp/repo
