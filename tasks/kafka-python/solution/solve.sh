#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/dpkp/kafka-python.git /tmp/repo
cd /tmp/repo
git checkout ce47b25f55c85e5998ccc80c7caf4aaebc1e3132

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: kafka-python's optional compression deps (crc32c, lz4,
# python-snappy, zstandard) and the setuptools build backend are pre-baked, and the image sets
# PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead of trying to
# fetch an isolated build env (which would fail offline). No extras are needed here because the
# compression libs are already installed in the image.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
