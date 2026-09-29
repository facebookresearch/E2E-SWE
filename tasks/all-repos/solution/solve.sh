#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on just for it).
git clone https://github.com/asottile/all-repos.git /tmp/repo
cd /tmp/repo
git checkout a21dd7fcfb0a472f40a6866216bfcfa1861f156d

# cp -a carries .git too, but all-repos uses a static setup.cfg version (no scm-derived version), so
# .git is not needed for the build — it just preserves the checkout faithfully.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the image
# sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools backend
# instead of trying to fetch an isolated build env (which would fail offline). test.sh runs
# `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
