#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/nose-devs/nose2.git /tmp/repo
cd /tmp/repo
git checkout af9419dd97f586289546dcaac29116196f891285

# The base image ships an empty /app/repo directory. setuptools flat-layout auto-discovery would
# treat it as a second top-level package alongside nose2 and abort with PackageDiscoveryError, so
# clear /app of any pre-existing contents before copying the reference implementation in.
rm -rf /app/* /app/.[!.]* /app/..?* 2>/dev/null || true

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the build backend (setuptools) is pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead
# of trying to fetch an isolated build env (which always fails offline). test.sh runs
# `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
