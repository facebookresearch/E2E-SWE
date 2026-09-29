#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it). cp -a carries .git into /app too.
git clone https://github.com/masoniteframework/orm.git /tmp/repo
cd /tmp/repo
git checkout 501825047422e533e65c301f4a2e8a86b59685f6

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools/wheel
# instead of fetching an isolated build env. --no-deps is kept from the reference install: the
# baked runtime set (esp. pendulum 3.x, which is newer than setup.py's <3.1 bound) must NOT be
# re-resolved by the package's own metadata.
echo 'pip install -e . --no-build-isolation --no-deps' > ./setup.sh
