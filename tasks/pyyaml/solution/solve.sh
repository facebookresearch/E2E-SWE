#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/yaml/pyyaml.git /tmp/repo
cd /tmp/repo
git checkout d51d8a1

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: there are no runtime deps and the build backend
# (setuptools + Cython, for setup.py's optional C-extension build) is pre-baked, with PIP_NO_INDEX
# set. --no-build-isolation is REQUIRED so pip uses the baked backend instead of fetching an
# isolated build env (offline build isolation always fails).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
