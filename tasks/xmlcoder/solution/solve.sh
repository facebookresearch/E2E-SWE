#!/bin/bash
# Ground-truth setup for the `xmlcoder` task.
#
# Clones the reference implementation at the pinned commit and lays its Swift package down
# at /app, exactly as a candidate agent would produce one. The grader (tests/test.sh)
# compiles every *.swift under /app/Sources into a module named `XMLCoder` and runs the
# hidden XCTest suites against it. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it); model eval runs fully offline.
set -e

git clone https://github.com/CoreOffice/XMLCoder.git /tmp/repo
cd /tmp/repo
git checkout 42f62383dbcd074440cb1f6a750b9c02df9e7325   # tag 0.18.2

# Copy the full tree into /app (the reference keeps all library code under Sources/ as a
# single `XMLCoder` module -- the same layout candidates are asked to produce). The grader
# ignores /app/Package.swift and the Benchmarks/Tests trees; only /app/Sources/*.swift is used.
cp -a /tmp/repo/. /app/
rm -rf /tmp/repo
