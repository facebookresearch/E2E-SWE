#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/iteratec/kcwarden.git /tmp/repo
cd /tmp/repo
git checkout f3592e0b8016ff45aab1a8ee024685030cdfcef6

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline. The build backend (hatchling + uv-dynamic-versioning)
# is pre-baked and PIP_NO_INDEX is set, so --no-build-isolation is required. kcwarden declares
# requires-python>=3.11 but uses no 3.11-only features; the base image ships 3.10, so
# --ignore-requires-python lets it install and run there. test.sh runs `source ./setup.sh`.
echo 'pip install -e . --no-build-isolation --ignore-requires-python' > ./setup.sh
