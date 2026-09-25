#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/ideoforms/isobar.git /tmp/repo
cd /tmp/repo
git checkout 56fd6bc201fdc644a91c2e3c89d8e26eabef781e  # tag v0.2.1

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs isobar offline: its runtime deps (numpy, mido, python-osc, python-rtmidi,
# LinkPython-extern) and the setuptools build backend are pre-baked, and the image sets
# PIP_NO_INDEX=1. --no-build-isolation is REQUIRED so pip uses the baked backend instead of trying
# to fetch an isolated build env (which always fails offline). test.sh runs `source ./setup.sh`.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
