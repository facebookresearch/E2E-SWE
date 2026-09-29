#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/ag2ai/faststream.git /tmp/repo
cd /tmp/repo
git checkout 5948d1f8ec3b1f43ee287af78601be429c9a3c43

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the core runtime deps (fast-depends[pydantic],
# anyio, typing-extensions), the redis client, and the uv_build backend are all pre-baked,
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked
# uv_build backend instead of trying to fetch it (offline build isolation always fails).
# test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
