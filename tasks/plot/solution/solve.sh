#!/bin/bash
# Ground-truth setup for the `plot` task.
#
# Clones the reference implementation at the pinned commit and lays its Swift package down at
# /app, exactly as a candidate agent would produce one. The grader (tests/test.sh) compiles
# every *.swift under /app/Sources into a module named `Plot` and runs the hidden XCTest suites
# against it. This clone is the ONLY network operation in the GT flow (GT eval keeps internet on
# for it); model eval runs fully offline.
#
# Plot has NO third-party dependencies (Foundation only), so -- unlike some other Swift tasks --
# there is nothing to strip: the reference compiles offline as-is. The pinned commit is the tip
# of `master` (= tag 0.14.0 + the commit adding the Details/Main/Summary components), which the
# hidden Component tests exercise.
set -e

git clone https://github.com/JohnSundell/Plot.git /tmp/repo
cd /tmp/repo
git checkout 431c27c9ac97f8bcf6047b5bdbaef91b95a5330b   # tip of master (0.14.0 + Details/Main/Summary)

# Copy the full tree into /app (the reference keeps all library code under Sources/Plot as a
# single `Plot` module -- the same layout candidates are asked to produce). The grader ignores
# /app/Package.swift and the Tests tree; only /app/Sources/*.swift is used.
cp -a /tmp/repo/. /app/
rm -rf /tmp/repo
