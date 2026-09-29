#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/google/fiddle.git /tmp/repo
cd /tmp/repo
git checkout a54c8b705c79c4f82fe75a7b39dc146e90e3fd03

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the runtime deps + the setuptools/wheel build backend are
# pre-baked and the image sets PIP_NO_INDEX=1. --no-build-isolation is REQUIRED so pip uses the baked
# backend instead of fetching an isolated build env (which would fail offline). test.sh runs
# `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
