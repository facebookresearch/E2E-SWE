#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/XKNX/xknx.git /tmp/repo
cd /tmp/repo
git checkout 50fdf8af8e29b84b96de4487f5bd4f060f7c502c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the setuptools build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which would fail offline). The .git copied above
# is not needed for the version (xknx uses an attr-based dynamic version), but is harmless.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
