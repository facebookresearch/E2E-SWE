#!/bin/bash
# Ground-truth setup for the `swift-argument-parser` task.
#
# Clones the reference implementation at the pinned commit and lays the ArgumentParser library
# down at /app as a single flattened SwiftPM module named `ArgumentParser`, exactly as a
# candidate agent is asked to produce one. The grader (tests/test.sh) compiles the *.swift under
# /app/Sources into a module named `ArgumentParser` and runs the hidden XCTest suite against it.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it);
# model eval runs fully offline.
#
# Two GT-specific transforms make the real reference match the single-module layout candidates
# produce (dump-help/ToolInfo are out of scope, so the candidate writes one module):
#   1. Merge the internal `ArgumentParserToolInfo` sources into the same `ArgumentParser` module.
#   2. Strip the `import ArgumentParserToolInfo` lines — those symbols are now same-module.
set -e

git clone https://github.com/apple/swift-argument-parser.git /tmp/repo
cd /tmp/repo
git checkout 6a52f3251125d74daf04fcbd5e6f08a75d074382  # tag 1.8.2

mkdir -p /app/Sources/ArgumentParser

# Core library sources.
cp -a /tmp/repo/Sources/ArgumentParser/. /app/Sources/ArgumentParser/

# Merge the internal ToolInfo target into the same module (Completions + DumpHelpGenerator
# reference it via `internal import ArgumentParserToolInfo`).
cp /tmp/repo/Sources/ArgumentParserToolInfo/*.swift /app/Sources/ArgumentParser/

# Now that ToolInfo symbols live in the same module, drop the cross-module import lines.
grep -rl "import ArgumentParserToolInfo" /app/Sources/ArgumentParser \
  | xargs -r sed -i '/import ArgumentParserToolInfo/d'

# Drop non-source artifacts that would confuse a bare SwiftPM target.
find /app/Sources/ArgumentParser -name 'CMakeLists.txt' -delete
rm -rf /app/Sources/ArgumentParser/Documentation.docc

rm -rf /tmp/repo
