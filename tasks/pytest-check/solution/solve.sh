#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). cp -a carries .git too, though pytest-check uses a static
# version so it is not needed for version resolution.
git clone https://github.com/okken/pytest-check.git /tmp/repo
cd /tmp/repo
git checkout c356b52493e6d65f4b5adc68fb7b675f14a707d8

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the hatchling build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which always fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
