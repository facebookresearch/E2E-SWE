#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/Instagram/MonkeyType.git /tmp/repo
cd /tmp/repo
git checkout 15e7bca60146a7afbde46ee8782a0c650f781c74

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (mypy_extensions, libcst) + the setuptools
# build backend are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked backend instead of fetching an isolated build env (which fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
