#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/laixintao/pingtop.git /tmp/repo
cd /tmp/repo
git checkout 57f13f394551970a68094d3db4aeee3d755df37c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the poetry-core build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch it (offline build isolation always fails). test.sh runs
# `source ./setup.sh` in the (offline) grading container. pingtop uses an src layout with a static
# version, so the editable install resolves entirely offline.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
