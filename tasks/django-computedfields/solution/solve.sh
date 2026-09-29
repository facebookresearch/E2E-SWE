#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/netzkolchose/django-computedfields.git /tmp/repo
cd /tmp/repo
git checkout ca10125d19adf4ff907c054a65df79e491049beb   # patch release 0.3.6

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps (Django 5.2 line, typing_extensions,
# django-fast-update) and the setuptools/wheel build backend are pre-baked, and the image sets
# PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead of fetching
# an isolated build env (offline build isolation always fails). The baked Django is the validated
# 5.2 line, so the install_requires `Django>=5.0,<7.0` resolves deterministically to it offline.
# test.sh runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
