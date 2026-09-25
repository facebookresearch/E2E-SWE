#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/pytest-dev/pytest-bdd.git /tmp/repo
cd /tmp/repo
git checkout 6cdd340504decb0bbe660639cc78788d244b498c

# cp -a carries .git too, but pytest-bdd's version is static (8.1.0) so no scm resolution is needed.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the poetry-core build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
