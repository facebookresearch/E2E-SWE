#!/bin/bash
set -e

git clone https://github.com/optibus/playback.git /tmp/repo
cd /tmp/repo
git checkout ef05d7156d1a2a5bc1e1b7c3131ee6e95713209f

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

echo 'pip install -e . --no-build-isolation' > ./setup.sh
