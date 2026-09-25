#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/grantjenks/python-diskcache.git /tmp/repo
cd /tmp/repo
git checkout ebfa37cd99d7ef716ec452ad8af4b4276a8e2233

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (none) + the build backend are pre-baked and
# the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools
# backend instead of trying to fetch it (offline build isolation always fails).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
