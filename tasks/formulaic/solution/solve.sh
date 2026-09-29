#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (the GT eval keeps internet on solely for this clone).
git clone https://github.com/matthewwardrop/formulaic.git /tmp/repo
cd /tmp/repo
git checkout v1.2.2

# cp -a carries the .git directory too, so hatch-vcs can resolve formulaic's dynamic version offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the hatchling/hatch-vcs backend are pre-baked
# and the image sets PIP_NO_INDEX=1. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which always fails with no network).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
