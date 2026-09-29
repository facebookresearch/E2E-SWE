#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/programa-stic/barf-project.git /tmp/repo
cd /tmp/repo
git checkout 9547ef843b8eb021c2c32c140e36173c0b4eafa3

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: barf's runtime deps (capstone==4.0.2 pinned to the 4.x API
# the code targets, plus pyelftools/pefile/pyparsing/networkx/pydot/future/pygments) and the
# setuptools/wheel build backend are pre-baked, and the image sets PIP_NO_INDEX=1.
# --no-build-isolation is REQUIRED so pip uses the baked backend instead of trying to fetch an
# isolated build env (which would fail offline). test.sh runs `source ./setup.sh` in the offline
# grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
