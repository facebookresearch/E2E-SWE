#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/imr-framework/pypulseq.git /tmp/repo
cd /tmp/repo
git checkout f5160a23e70fecf654df35bda9b5108585e7912d

# cp -a carries .git too; pypulseq's version is read from package metadata at build time, so the
# editable install resolves offline without the index.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the setuptools build backend are pre-baked
# and the image sets PIP_NO_INDEX=1. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of fetching an isolated build env (which would fail offline). test.sh runs
# `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
