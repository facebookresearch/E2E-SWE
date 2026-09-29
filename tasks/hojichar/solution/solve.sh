#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/HojiChar/HojiChar.git /tmp/repo
cd /tmp/repo
git checkout f9f926d563b2df505887aaa770c8d2105a431288

# cp -a carries .git too, so hojichar's uv-dynamic-versioning resolves its version offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (hatchling +
# uv-dynamic-versioning + editables) are pre-baked and the image sets PIP_NO_INDEX.
# --no-build-isolation is REQUIRED so pip uses the baked backend instead of fetching it.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
