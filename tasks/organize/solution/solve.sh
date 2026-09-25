#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/tfeldmann/organize.git /tmp/repo
cd /tmp/repo
git checkout 36a54572488d89dc9279d79848ecc067b632f1a5

# cp -a carries .git into /app too (harmless; organize-tool uses a static version, not scm-derived).
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the setuptools build backend are pre-baked
# and the image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend
# instead of trying to fetch an isolated build env (which always fails offline).
#
# The eval harness owns an empty /app/repo scratch dir that persists through setup. setuptools
# flat-layout auto-discovery would otherwise see two top-level packages ('repo' + 'organize') and
# refuse to build ("Multiple top-level packages discovered in a flat-layout"). The upstream repo has
# no top-level `repo/` package, so removing this stray empty dir right before the install is safe and
# lets discovery resolve `organize` cleanly. It is done inside setup.sh (which test.sh sources just
# before pytest) so it runs regardless of when the harness creates the dir.
echo 'rm -rf ./repo && pip install -e . --no-build-isolation' > ./setup.sh
