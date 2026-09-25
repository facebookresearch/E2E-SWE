#!/bin/bash
# Ground-truth setup for the `swift-parsing` task.
#
# Clones the reference implementation at the pinned commit and lays the Parsing library down at
# /app as a single SwiftPM module named `Parsing`, exactly as a candidate agent is asked to
# produce one. The grader (tests/test.sh) compiles every *.swift under /app/Sources/Parsing into
# a module named `Parsing` and runs the hidden XCTest suites against it. This clone is the ONLY
# network operation in the GT flow (GT eval keeps internet on for it); model eval runs fully
# offline.
#
# One GT-specific transform keeps the reference build dependency-free (matching the offline,
# zero-external-dependency library the candidate is asked to produce):
#   * Strip Conversions/Enum.swift. It is the ONLY file that `import`s the external
#     swift-case-paths package (the `Conversion.case(...)` enum-case sugar). It is out of scope,
#     so removing it makes the reference compile with Foundation only -- no external deps.
set -e

git clone https://github.com/pointfreeco/swift-parsing.git /tmp/repo
cd /tmp/repo
git checkout 3432cb81164dd3d69a75d0d63205be5fbae2c34b   # tag 0.14.1

mkdir -p /app/Sources/Parsing

# Core library sources (preserve the Builders/ Conversions/ Internal/ ParserPrinters/ Parsers/
# subdir layout -- the grader globs *.swift recursively into the single `Parsing` module).
cp -a /tmp/repo/Sources/Parsing/. /app/Sources/Parsing/

# Drop the DocC catalog (documentation, not source) and the CasePaths-gated enum conversion
# (the only external-dependency code -- out of scope for this offline task).
rm -rf /app/Sources/Parsing/Documentation.docc
rm -f /app/Sources/Parsing/Conversions/Enum.swift

# Sanity: the reference must no longer reference the external CasePaths package.
if grep -rn "import CasePaths" /app/Sources/Parsing >/dev/null 2>&1; then
  echo "ERROR: residual 'import CasePaths' in GT sources after stripping Enum.swift" >&2
  exit 1
fi

rm -rf /tmp/repo
