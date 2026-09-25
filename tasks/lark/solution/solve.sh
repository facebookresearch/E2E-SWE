#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/lark-parser/lark.git /tmp/repo
cd /tmp/repo
git checkout 52ef09d

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs lark offline: it has no runtime deps and the build backend
# (setuptools + setuptools-scm + wheel) is pre-baked, with PIP_NO_INDEX set in the image.
# --no-build-isolation is REQUIRED so pip uses the baked backend instead of fetching an isolated
# build env (which always fails offline). The cp -a above also carries .git, so any scm lookup
# resolves locally.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
