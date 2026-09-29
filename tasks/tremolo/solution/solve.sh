#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/nggit/tremolo.git /tmp/repo
cd /tmp/repo
git checkout ad3b9c5063b9aa6e7a90ba62b487e5c2f1a72cd2

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# tremolo has zero runtime dependencies beyond the Python standard library. The build backend
# (setuptools + wheel) is pre-baked and the image sets PIP_NO_INDEX=1, so the editable install
# must run with --no-build-isolation (offline build isolation can never fetch the backend).
# The dynamic version reads tremolo.__version__ from the copied source, so it resolves offline.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
