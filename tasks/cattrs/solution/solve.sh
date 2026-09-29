#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/python-attrs/cattrs.git /tmp/repo
cd /tmp/repo
git checkout v26.1.0

# cp -a carries .git into /app so cattrs' hatch-vcs (VCS-derived dynamic version) resolves offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the hatchling build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which always fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
