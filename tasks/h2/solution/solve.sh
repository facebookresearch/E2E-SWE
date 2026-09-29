#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/python-hyper/h2.git /tmp/repo
cd /tmp/repo
git checkout 1cd9ce0c1c9862df948318b12c3b75d72537abd4

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (hyperframe, hpack) + the setuptools/wheel
# build backend are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked backend instead of trying to fetch an isolated build env (which would fail
# offline). test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
