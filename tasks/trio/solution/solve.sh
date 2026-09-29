#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). cp -a carries .git too, but trio's version is read from the
# committed src/trio/_version.py attribute, so the build resolves offline regardless.
git clone https://github.com/python-trio/trio.git /tmp/repo
cd /tmp/repo
git checkout 8ecba055808f09dae9ee4b232e628696ef53eb04

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs trio offline: its runtime deps + the setuptools build backend are pre-baked and
# the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
