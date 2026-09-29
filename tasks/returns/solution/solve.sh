#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/dry-python/returns.git /tmp/repo
cd /tmp/repo
git checkout 9358390343990a2f55b5a22af1ab04fa37eeed32

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the runtime dep (typing-extensions) and the build backend
# (poetry-core) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked poetry-core instead of fetching an isolated build env (offline build isolation
# always fails). The cp -a above carried /app/.git, so any scm-derived metadata resolves offline.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
