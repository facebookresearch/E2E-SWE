#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it).
git clone https://github.com/scottrogowski/mongita.git /tmp/repo
cd /tmp/repo
git checkout abda34e4d51532e58fa1f0ca86e9703dd637a440

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (pymongo, sortedcontainers) + the setuptools
# build backend are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked backend instead of fetching an isolated build env (which always fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
