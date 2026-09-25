#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/dateutil/dateutil.git /tmp/repo
cd /tmp/repo
git checkout c981f9c7aa91b83cc9bd33a09ecee9e751b06e8d

# cp -a carries .git too, so setuptools_scm can derive dateutil's version offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the runtime dep (six) + the build backend (setuptools,
# wheel, setuptools_scm) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is
# REQUIRED so pip uses the baked backend instead of trying to fetch an isolated build env (offline
# build isolation always fails). test.sh runs `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
