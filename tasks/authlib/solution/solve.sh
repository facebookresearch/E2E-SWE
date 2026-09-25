#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/lepture/authlib.git /tmp/repo
cd /tmp/repo
git checkout 2b4502791e0bf67ba65ab82281fb29e00559008a

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (cryptography, joserfc) + the setuptools/wheel
# build backend are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked backend instead of trying to fetch it (offline build isolation always fails).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
