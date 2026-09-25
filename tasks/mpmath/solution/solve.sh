#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/mpmath/mpmath.git /tmp/repo
cd /tmp/repo
git checkout c1131e2d64abcbb57728ca8a499c920c0c69e67f

# cp -a carries .git into /app so the setuptools_scm-derived dynamic version resolves offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the build backend (setuptools + wheel + setuptools_scm)
# is pre-baked and the image sets PIP_NO_INDEX=1. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of trying to fetch an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
