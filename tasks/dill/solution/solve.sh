#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/uqfoundation/dill.git /tmp/repo
cd /tmp/repo
git checkout d16e482b7a0e6c1a8359f13130d7e71092049d21

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs dill offline: it is pure Python and the build backend (setuptools/wheel) is
# pre-baked, with PIP_NO_INDEX set in the image. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of trying to fetch an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
