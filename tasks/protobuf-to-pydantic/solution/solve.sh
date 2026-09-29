#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/so1n/protobuf_to_pydantic.git /tmp/repo
cd /tmp/repo
git checkout c21fa34ae6a3f81b0274291d839ab6a90959e141

# Python 3.13 compatibility shim: the reference repo targets py3.8-3.10 and calls
# `Annotated.__class_getitem__(tuple(...))`. `Annotated[tuple(...)]` is semantically identical and
# works on every Python version, so this is harmless on the image's Python too.
sed -i 's/Annotated\.__class_getitem__(tuple(type_param))/Annotated[tuple(type_param)]/g' \
    protobuf_to_pydantic/customer_con_type/v2.py

# cp -a carries .git into /app so the poetry-dynamic-versioning build backend can resolve a version
# offline (the repo also ships a committed __version__.py, so no git tags are required).
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (poetry-core +
# poetry-dynamic-versioning) are pre-baked and the image sets PIP_NO_INDEX. --no-build-isolation is
# REQUIRED so pip uses the baked backend instead of trying to fetch an isolated build env.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
