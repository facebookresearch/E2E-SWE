#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it). cp -a carries .git into /app too.
git clone https://github.com/ethereum/py-trie.git /tmp/repo
cd /tmp/repo
git checkout v3.1.0

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools/wheel
# instead of fetching an isolated build env (which would fail offline). pycryptodome (the eth-hash
# keccak backend) is baked into the image, so no extra install is needed here.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
