#!/bin/bash
set -e

git clone https://github.com/explosion/confection.git /tmp/repo
cd /tmp/repo
git checkout a98f9d6f8efd875fbd158965793334f5b25f9eeb

# The task presents this library under the neutral import name `cfgforge`.
# The package uses only relative imports and is discovered via find_packages(),
# so renaming the top-level package directory is sufficient to make the
# reference implementation importable as `cfgforge`.
mv /tmp/repo/confection /tmp/repo/cfgforge

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend (setuptools) are
# pre-baked in the per-task image and PIP_NO_INDEX=1 is set. --no-build-isolation is REQUIRED so
# pip uses the baked backend instead of trying to fetch an isolated build env (which would fail
# with no network). cp -a above carried .git, so any scm-derived metadata resolves offline too.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
