#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/tortoise/tortoise-orm.git /tmp/repo
cd /tmp/repo
git checkout e272ab02a90d539cbae7b35e18eeea3135295d88

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (pypika-tortoise, aiosqlite, iso8601, anyio,
# tomlkit, typing-extensions) and the pdm-backend build backend are pre-baked, and the image sets
# PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead of fetching
# it. tortoise's version is read statically from tortoise/__init__.py (no VCS), so the editable
# install needs no git history. test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
