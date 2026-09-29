#!/bin/bash
set -e

# git is pre-baked in the per-task image; this clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). cp -a carries .git too, but icontract pins a static version
# so no scm metadata is actually needed offline.
git clone https://github.com/Parquery/icontract.git /tmp/repo
cd /tmp/repo
git checkout 3e733f9e790359036c4da2cc550c599107710b60

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead
# of trying to fetch an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
