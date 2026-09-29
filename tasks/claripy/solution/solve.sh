#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/angr/claripy.git /tmp/repo
cd /tmp/repo
git checkout v9.2.221

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (cachetools, z3-solver) + the build backend
# (setuptools/wheel) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED
# so pip uses the baked backend instead of trying to fetch it (offline build isolation always
# fails). test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
