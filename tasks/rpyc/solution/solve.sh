#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on just for it).
git clone https://github.com/tomerfiliba/rpyc.git /tmp/repo
cd /tmp/repo
git checkout 14f20a77845309ee555c21b6f6cc3be9d7e29c57

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (plumbum) + the build backend (hatchling +
# editables) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip
# uses the baked backend instead of trying to fetch an isolated build env (which fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
