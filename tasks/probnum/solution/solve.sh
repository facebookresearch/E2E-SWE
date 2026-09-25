#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/probabilistic-numerics/probnum.git /tmp/repo
cd /tmp/repo
git checkout 41951df4366163b2568791d72ead0a9a1a8efe5c

# Copy the full tree INCLUDING .git — probnum's build-system resolves its version via
# setuptools_scm, which reads git metadata at install time.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the
# image sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked backend instead
# of trying to fetch it (offline build isolation always fails). test.sh runs `source ./setup.sh`
# in the (offline) grading container. For a non-Python repo, write the language-appropriate offline
# build/install command instead.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
