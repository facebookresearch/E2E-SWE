#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/pysmt/pysmt.git /tmp/repo
cd /tmp/repo
git checkout 29bdb9c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs pySMT offline: the build backend (setuptools + wheel) is pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead
# of trying to fetch an isolated build env (offline build isolation always fails). pySMT has no
# runtime deps, so nothing else needs installing.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
