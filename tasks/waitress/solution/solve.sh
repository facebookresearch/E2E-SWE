#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). `cp -a` carries .git into /app too.
git clone https://github.com/Pylons/waitress.git /tmp/repo
cd /tmp/repo
git checkout 3af6388f530596e8fa5831f315501b15f900bd40

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the setuptools build backend is pre-baked and the image
# sets PIP_NO_INDEX, so --no-build-isolation is REQUIRED (offline build isolation can never fetch
# the backend). test.sh runs `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
