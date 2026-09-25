#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/smarie/python-pytest-cases.git /tmp/repo
cd /tmp/repo
git checkout d495c03c1beffd03dfa893acad70c6af6d5bf906  # tag 3.10.1

# cp -a carries .git so the setuptools_scm dynamic version resolves offline during the build.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (setuptools<82,
# setuptools_scm, wheel) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is
# REQUIRED so pip uses the baked backend instead of fetching an isolated build env (which offline
# always fails). test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
