#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/invariantlabs-ai/invariant.git /tmp/repo
cd /tmp/repo
git checkout 2340fe2d9cd619f73d5b67fa05bf8a08c7cad515

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools backend
# instead of trying to fetch an isolated build env (which would fail with no network).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
