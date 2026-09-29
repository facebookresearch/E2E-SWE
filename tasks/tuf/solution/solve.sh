#!/bin/bash
set -e

# Reference solution: the published python-tuf repository IS the reference
# implementation. GT eval keeps the network on ONLY for this clone.
# Pin to the v7.0.0 release commit for reproducibility.
# The full clone (with .git) is copied into /app; the package version is read statically
# from tuf/__init__.py by hatchling, so .git is not strictly required, but copying it is
# harmless and mirrors a normal checkout.
git clone https://github.com/theupdateframework/python-tuf.git /tmp/repo
cd /tmp/repo
git checkout 353bdb767db56fd4667c9bcf56b710d50fdc2ac0

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (hatchling + editables)
# are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of trying to fetch an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
