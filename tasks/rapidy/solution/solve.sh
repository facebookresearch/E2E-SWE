#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/rAPIdy-org/rAPIdy.git /tmp/repo
cd /tmp/repo
git checkout 51599ec2cb65176e2972597bd09394c707b1e18c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (poetry-core) are
# pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of trying to fetch an isolated build env (which always fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
