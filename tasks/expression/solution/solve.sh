#!/bin/bash
# Ground-truth setup for the `expression` task.
#
# Clones the reference implementation at the pinned commit and lays its Swift package down
# at /app, exactly as a candidate agent would produce one. The grader (tests/test.sh)
# compiles the *.swift under /app/Sources into a module named `Expression` and runs the
# hidden XCTest suite against it. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it); model eval runs fully offline.
set -e

git clone https://github.com/nicklockwood/Expression.git /tmp/repo
cd /tmp/repo
git checkout e9a9623aa5a0709179a6cd1cb3697f90aa8bdafd

# Copy the full tree into /app (the reference package keeps all library code under Sources/
# as a single `Expression` module — the same layout candidates are asked to produce).
cp -a /tmp/repo/. /app/
rm -rf /tmp/repo
