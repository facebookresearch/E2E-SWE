#!/bin/bash
set -e

# Ground-truth solution: clone the real django-migration-linter at its v6.0.0 release commit and
# install it editable. git is pre-baked in the per-task image; this clone is the ONLY network
# operation in the GT flow (the GT eval keeps internet on solely for it). cp -a carries .git into
# /app as well.
git clone https://github.com/3YOURMIND/django-migration-linter.git /tmp/repo
cd /tmp/repo
git checkout d55ba66d440f183c6875285b3fec758a696903fa  # v6.0.0

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (setuptools/wheel) are
# pre-baked and the image sets PIP_NO_INDEX=1. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of fetching an isolated build env (which offline would always fail).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
