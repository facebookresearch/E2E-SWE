#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/juergenH87/python-can-j1939.git /tmp/repo
cd /tmp/repo
git checkout v2.0.12 2>/dev/null || git checkout 2.0.12

# cp -a carries .git too; the repo's version is exec'd from j1939/version.py (not scm-derived), so
# the offline editable build resolves it from the working tree without needing the index.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + setuptools build backend are pre-baked and
# the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which always fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
