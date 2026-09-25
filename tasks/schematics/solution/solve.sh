#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/schematics/schematics.git /tmp/repo
cd /tmp/repo
git checkout 3a144be0aa50f68a4da917e8d957b924dedf9a52

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the build backend (setuptools/wheel) is pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead
# of trying to fetch an isolated build env (which would fail offline). test.sh runs
# `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
