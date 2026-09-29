#!/bin/bash
set -e

git clone --filter=blob:none https://github.com/wwkimball/yamlpath.git /tmp/repo
cd /tmp/repo
git checkout 666504c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

echo 'pip install -e . --no-build-isolation' > ./setup.sh
