#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/pdfminer/pdfminer.six.git /tmp/repo
cd /tmp/repo
git checkout a18de2a9c479b4c847538500017b449ddaec177e

# cp -a carries .git too, so the setuptools_scm dynamic version resolves offline at build time.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (setuptools, wheel,
# setuptools_scm) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED
# so pip uses the baked backend instead of fetching an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
