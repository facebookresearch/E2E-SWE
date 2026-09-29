#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/seperman/deepdiff.git /tmp/repo
cd /tmp/repo
git checkout 0d07ec21d12b46ef4e489383b363eadc22d990fb

# cp -a carries .git too; deepdiff pins a static version in pyproject.toml, so the flit_core build
# does not need .git, but keeping it is harmless and matches the offline template.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: orderly-set + the flit_core build backend are pre-baked and
# the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead
# of fetching an isolated build env (which would fail offline). test.sh runs `source ./setup.sh`.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
