#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow.
git clone https://github.com/nicklockwood/Euclid.git /tmp/repo
cd /tmp/repo
# Pinned to 0.8.15. tools-version 5.7; Apple-framework interop (SceneKit/CoreGraphics/simd/...) is
# all `#if canImport`-guarded, so the core geometry/CSG compiles on the Linux Swift 5.10 base image.
git checkout c8537c7ad0df2b7d0f09ee251aa153d7c381776c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Pure Swift, no external SwiftPM dependencies; builds offline.
echo 'swift build --product Euclid' > ./setup.sh
