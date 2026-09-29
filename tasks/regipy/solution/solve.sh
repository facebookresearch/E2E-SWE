#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for the solve.sh container only).
git clone https://github.com/mkorman90/regipy.git /tmp/repo
cd /tmp/repo
git checkout f315415864889c3ee2a03d8a9e5c52486dcb631b

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the setuptools build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env. The runtime deps (incl. the cli extra: click,
# tabulate) are already installed in the image, so a plain `pip install -e .` resolves them locally.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
