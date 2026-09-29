#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/tobgu/pyrsistent.git /tmp/repo
cd /tmp/repo
git checkout 0c0b7aec8cd25b1d2d8ba07b10acdefd0f38f2c7

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: there are no runtime deps and the build backend
# (setuptools + wheel) is pre-baked; the image sets PIP_NO_INDEX. --no-build-isolation is
# REQUIRED so pip uses the baked backend instead of trying to fetch an isolated build env
# (offline build isolation always fails). test.sh runs `source ./setup.sh` in the offline
# grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
