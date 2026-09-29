#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/wagtail/django-modelcluster.git /tmp/repo
cd /tmp/repo
git checkout fef1604656d9c146077958e32a86cd8138ee30de

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: the runtime deps (Django 5.2 + django-taggit) and the
# setuptools/wheel build backend are pre-baked, and the image sets PIP_NO_INDEX. --no-build-isolation
# is REQUIRED so pip uses the baked backend instead of trying to fetch an isolated build env (which
# would fail offline). django-taggit is already baked, so `import taggit` (the contrib.taggit
# subsystem) works without requesting the package's optional [taggit] extra.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
