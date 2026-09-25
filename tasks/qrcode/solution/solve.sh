#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/lincolnloop/python-qrcode.git /tmp/repo
cd /tmp/repo
git checkout 316f820d3ea62667d927b99226cbb4a077db0c92

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (pillow, deprecation) and the build backend
# (poetry-core) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked poetry-core instead of trying to fetch an isolated build env (offline build
# isolation always fails). The bare `.` install (no [pil] extra) is sufficient because pillow is
# baked directly into the image.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
