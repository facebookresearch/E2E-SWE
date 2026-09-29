#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on solely for it).
git clone https://github.com/vutran1710/PyrateLimiter.git /tmp/pyratelimiter
cd /tmp/pyratelimiter
git checkout 2c4343484c12c15993e1479aa986020cdc93399e

# cp -a carries .git, so uv-dynamic-versioning can derive the dynamic version offline.
cp -a /tmp/pyratelimiter/. /app/
cd /app
rm -rf /tmp/pyratelimiter

# setup.sh installs the project offline: runtime deps + the hatchling build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which always fails offline).
echo 'pip install -e . --no-build-isolation' > ./setup.sh
