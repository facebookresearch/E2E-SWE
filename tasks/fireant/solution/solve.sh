#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). cp -a carries .git into /app so hatchling can read the repo.
git clone https://github.com/kayak/fireant.git /tmp/repo
cd /tmp/repo
git checkout e183ecb

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs fireant offline: its runtime deps + the hatchling build backend (and editables)
# are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of trying to fetch an isolated build env (which fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
