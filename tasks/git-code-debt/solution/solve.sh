#!/bin/bash
set -e

git clone https://github.com/asottile/git-code-debt.git /tmp/repo
cd /tmp/repo
git checkout 11f1b4af74a9b4b0ec44e1051d401d845213239c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

echo 'pip install -e . --no-build-isolation' > ./setup.sh
