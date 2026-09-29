#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/eliben/pycparser.git /tmp/repo
cd /tmp/repo
git checkout 9cd0027f874fcceacca87fdfb163a387bf4d56b6

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: there are no runtime deps and the build backend
# (setuptools/wheel) is pre-baked, with PIP_NO_INDEX set in the image. --no-build-isolation is
# REQUIRED so pip uses the baked backend instead of trying to fetch an isolated build env
# (which always fails offline). test.sh runs `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
