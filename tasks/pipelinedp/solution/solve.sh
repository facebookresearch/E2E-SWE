#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/OpenMined/PipelineDP.git /tmp/repo
cd /tmp/repo
git checkout 9b24617ad49dcdf842c2eafed373a8ec8d544eca

# cp -a carries .git too, so a poetry-core editable build resolves the version offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the poetry-core build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of fetching an isolated build env (which would fail offline). test.sh runs
# `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
