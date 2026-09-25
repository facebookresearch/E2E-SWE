#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
# Use a blobless partial clone (--filter=blob:none) for speed — it fetches only the trees and
# commits needed to check out the pinned commit instead of the full history. The .git dir is
# carried into /app via `cp -a` so a tree-based build sees it.
git clone --filter=blob:none https://github.com/rthalley/dnspython.git /tmp/repo
cd /tmp/repo
git checkout 04ef19a280101f7c815162ee121e4bcd03d02012

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: there are no runtime deps, and the `uv_build` build
# backend is pre-baked while the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so
# pip uses the baked backend instead of trying to fetch it (offline build isolation always
# fails). test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
