#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/antoinecarme/pyaf.git /tmp/repo
cd /tmp/repo
git checkout 0163880ee6045ec8a4205ffa529f3dc764326fb3

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools/wheel
# instead of trying to fetch them (offline build isolation always fails). test.sh runs
# `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
