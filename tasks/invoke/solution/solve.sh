#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/pyinvoke/invoke.git /tmp/repo
cd /tmp/repo
git checkout ba193d1a8d8bbf2f225facc5c7bbe9326482f542

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: invoke has no runtime deps and its build backend
# (setuptools) is pre-baked, with PIP_NO_INDEX set. --no-build-isolation is REQUIRED so pip uses
# the baked backend instead of fetching an isolated build env (which fails offline). test.sh runs
# `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
