#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/rawpython/remi.git /tmp/repo
cd /tmp/repo
git checkout 0cdcf9f6b57269e69fb6a5b8f84d3df775110197

# cp -a carries .git too, so remi's setuptools_scm-derived version resolves offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the build backend (setuptools/wheel/setuptools_scm) is
# pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked
# backend instead of trying to fetch an isolated build env (offline build isolation always fails).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
