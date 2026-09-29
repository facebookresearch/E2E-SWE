#!/bin/bash
set -e

git clone https://github.com/asottile/pyupgrade.git /tmp/repo   # git is pre-baked in the image
cd /tmp/repo
git checkout 75992aaa40730136014f34227e0135f63fc951b4          # pinned for reproducibility

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline; test.sh runs `source ./setup.sh` in the grading
# container. --no-build-isolation is required (the image bakes setuptools/wheel + sets
# PIP_NO_INDEX, and offline build isolation would fail trying to fetch the backend). pyupgrade's
# one runtime dep, tokenize-rt, is baked into the image, so the install is fully offline.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
