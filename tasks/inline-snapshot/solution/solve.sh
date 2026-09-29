#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on just for it).
git clone https://github.com/15r10nk/inline-snapshot.git /tmp/repo
cd /tmp/repo
git checkout c70375eaeabfc45abb6bb53d47ec5f6a5abfcacc

# cp -a carries .git too, but inline-snapshot's version is read from a static src file by hatchling,
# so no scm metadata is needed offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the hatchling build backend (and editables)
# are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of fetching an isolated build env (which would fail offline). test.sh runs
# `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
