#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/your-tools/tsrc.git /tmp/repo
cd /tmp/repo
git checkout 99b4424

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs tsrc offline: runtime deps + the poetry-core build backend are pre-baked and
# the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch it (offline build isolation always fails). test.sh runs
# `source ./setup.sh` in the (offline) grading container. The cp -a above carries .git, but tsrc's
# version is static in pyproject.toml so no scm lookup is needed.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
