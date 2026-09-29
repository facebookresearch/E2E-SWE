#!/bin/bash
set -e

git clone https://github.com/hhatto/autopep8.git /tmp/repo   # git is pre-baked in the image
cd /tmp/repo
git checkout 4046ad49e25b7fa1db275bf66b1b7d60600ac391          # pinned for reproducibility

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline; test.sh runs `source ./setup.sh` in the grading
# container. --no-build-isolation is required (the image bakes setuptools/wheel + sets
# PIP_NO_INDEX, and offline build isolation would fail trying to fetch the backend). autopep8's
# runtime dep, pycodestyle==2.14.0 (pinned for deterministic violation detection), is baked into
# the image, so the install is fully offline.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
