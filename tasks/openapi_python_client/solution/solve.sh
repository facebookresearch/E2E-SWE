#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/openapi-generators/openapi-python-client.git /tmp/repo
cd /tmp/repo
git checkout 7939364adafa2b1d32164e67a77853daa85aa4b3  # Release 0.29.0

# The task presents this tool under the neutral CLI name `pyclientgen`. The only
# surface the tests touch is the console-script command and the *generated* code
# (whose package name comes from the OpenAPI document title, not the generator).
# Renaming the entry-point script is therefore sufficient to make the reference
# implementation answer to `pyclientgen`; the internal package name is never
# imported by the tests.
sed -i 's/^openapi-python-client = /pyclientgen = /' pyproject.toml

# cp -a carries .git too, so hatchling can resolve the project at install time offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the runtime deps + the build backend (hatchling +
# editables) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked backend instead of trying to fetch an isolated build env (which would fail
# offline). test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
