#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on solely for it).
git clone https://github.com/kvesteri/sqlalchemy-continuum.git /tmp/repo
cd /tmp/repo
git checkout 1.6.0

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: SQLAlchemy + the setuptools build backend are pre-baked and
# the image sets PIP_NO_INDEX=1. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of fetching an isolated build env (which offline always fails).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
