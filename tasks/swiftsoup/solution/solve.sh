#!/bin/bash
# Ground-truth setup for the `swiftsoup` task.
#
# Clones the reference implementation at the pinned commit and lays its Swift package down
# at /app, exactly as a candidate agent would produce one. The grader (tests/test.sh)
# compiles every *.swift under /app/Sources into a module named `SwiftSoup` and runs the
# hidden XCTest suites against it. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it); model eval runs fully offline.
set -e

git clone https://github.com/scinfu/SwiftSoup.git /tmp/repo
cd /tmp/repo
git checkout 49dcadd93161f4a44b4994d3a3e8de9f085aface   # tag 2.13.5

# Copy the full tree into /app (the reference keeps all library code under Sources/ as a
# single `SwiftSoup` module -- the same layout candidates are asked to produce). The grader
# ignores /app/Package.swift and the Tools/Tests trees; only /app/Sources/*.swift is used.
cp -a /tmp/repo/. /app/
rm -rf /tmp/repo
