#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/datafolklabs/cement.git /tmp/repo
cd /tmp/repo
git checkout 9768476f1fd905a7ef56e19cb2146e7054b7e5b9

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: cement's build backend (pdm-backend) is pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead of
# trying to fetch an isolated build env (which would fail offline). test.sh runs `source ./setup.sh`
# in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
