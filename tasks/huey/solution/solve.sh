#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/coleifer/huey.git /tmp/repo
cd /tmp/repo
git checkout 374f09ef7f6ba3d8e352567fd8703f6c91146832

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the build backend (setuptools/wheel) is pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead
# of trying to fetch an isolated build env (which always fails offline). test.sh runs
# `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
