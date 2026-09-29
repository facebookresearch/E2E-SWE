#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). cp -a carries .git into /app as well.
git clone https://github.com/grappa-py/grappa.git /tmp/repo
cd /tmp/repo
git checkout 70b5b2448cc22d1c629bcbb72578cecb7948c1d6

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs grappa offline: runtime deps (colorama, six) + the setuptools build backend are
# pre-baked and PIP_NO_INDEX is set. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of fetching an isolated build env (which always fails offline). test.sh runs
# `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
