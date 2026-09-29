#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/pydantic/pydantic-ai.git /tmp/repo
cd /tmp/repo
git checkout f9f8b951

# cp -a carries .git so the hatchling uv-dynamic-versioning (git-derived) version resolves offline.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the hatchling build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of fetching an isolated build env (which always fails offline). This is a monorepo with
# two packages: install pydantic_graph first (pydantic_ai_slim pins an exact == on it), then
# pydantic_ai_slim. test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e ./pydantic_graph --no-build-isolation && pip install -e ./pydantic_ai_slim --no-build-isolation' > ./setup.sh
