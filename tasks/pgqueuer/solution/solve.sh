#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). cp -a carries .git so setuptools_scm can resolve the version
# offline during the editable install.
git clone https://github.com/janbjorge/pgqueuer.git /tmp/repo
cd /tmp/repo
git checkout bf16a6964e07940068f10061995e639a79c9ed2d

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the setuptools/setuptools_scm build backend
# are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the
# baked backend instead of trying to fetch an isolated build env (which would fail offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
