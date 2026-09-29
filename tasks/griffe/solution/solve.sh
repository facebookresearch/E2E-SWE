#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/mkdocstrings/griffe.git /tmp/repo
cd /tmp/repo
git checkout 5dc97b78

# cp -a carries the .git directory into /app, so the repo's scm-derived dynamic version
# (uv-dynamic-versioning) resolves offline at editable-build time.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# The `griffe` package the tests import lives in packages/griffelib (its wheel ships src/griffe).
# Install it editable, offline: the build backend (hatchling + uv-dynamic-versioning + editables)
# is pre-baked and PIP_NO_INDEX is set, so --no-build-isolation is REQUIRED — pip must use the baked
# backend instead of fetching an isolated build env. The griffecli sub-package is intentionally NOT
# installed: it is the CLI front-end (not exercised by the tests), and its exact `griffelib==<scm
# version>` pin cannot be satisfied offline.
echo 'pip install -e packages/griffelib --no-build-isolation' > ./setup.sh
