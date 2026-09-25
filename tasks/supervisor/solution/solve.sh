#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/Supervisor/supervisor.git /tmp/repo
cd /tmp/repo
git checkout abc60468ea4b78c446cf3a194f6fccb83d90f670

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: there are no runtime deps and the setuptools/wheel build
# backend is pre-baked; the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses
# the baked backend instead of trying to fetch an isolated build env (offline build isolation always
# fails). test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
