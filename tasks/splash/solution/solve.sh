#!/bin/bash
# Ground-truth setup for the `splash` task.
#
# Clones the reference implementation at the pinned commit and lays its Swift library down at
# /app, exactly as a candidate agent is asked to produce one. The grader (tests/test.sh) compiles
# every *.swift under /app/Sources into a module named `Splash` and runs the hidden XCTest suites
# against it. This clone is the ONLY network operation in the GT flow (GT eval keeps internet on
# for it); model eval runs fully offline.
#
# Splash (github.com/JohnSundell/Splash) has NO third-party dependencies (Foundation only), so
# there is nothing to strip for the offline build. We copy ONLY the `Splash` library module
# (Sources/Splash) -- NOT the four executable frontends (SplashHTMLGen/Markdown/ImageGen/Tokenizer),
# which each carry a `main.swift` and, for SplashImageGen, macOS-only AppKit/CoreGraphics APIs that
# do not belong in (and would not compile into) the graded library module. The library's own
# macOS-only pieces (AttributedStringOutputFormat + the Theming types) are gated behind
# `#if !os(Linux)` and simply compile to nothing on the Linux grading container, so copying the
# whole Sources/Splash tree is safe.
#
# The pinned commit is the tip of `master` -- "Correctly highlight the 'any' keyword when used
# within other type references (#130)".
set -e

git clone https://github.com/JohnSundell/Splash.git /tmp/repo
cd /tmp/repo
git checkout 2e3f17c2d09689c8bf175c4a84ff7f2ad3353301   # tip of master

mkdir -p /app/Sources
cp -a /tmp/repo/Sources/Splash /app/Sources/Splash
rm -rf /tmp/repo
