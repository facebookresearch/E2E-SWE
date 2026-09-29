#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). Pin the Clipper2_2.0.1 release for reproducibility
# (SHA 21ebba05db8894f0c7217ad35ea518080f324946).
git clone --depth 1 --branch Clipper2_2.0.1 https://github.com/AngusJohnson/Clipper2.git /tmp/repo
cd /tmp/repo

# The library the candidate must reproduce is the C# Clipper2Lib (the public sources under
# CSharp/Clipper2Lib: Clipper.Core/Engine/Offset/RectClip/Triangulation/Minkowski + Clipper.cs and the
# HashCode/PooledList helpers).
mkdir -p /app
cp -a /tmp/repo/CSharp/Clipper2Lib/. /app/
cd /app
rm -rf /tmp/repo

# C# is compiled by the grader (test.sh) with the baked .NET 8 SDK; setup.sh is therefore a no-op.
echo ': # C# library; the grader compiles the sources under /app' > ./setup.sh
