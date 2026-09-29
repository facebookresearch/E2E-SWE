#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/mapillary/mapillary_tools.git /tmp/repo
cd /tmp/repo
git checkout e515c5afc804f8717c29f3091aeacc3cd08924e1

# cp -a carries .git too, but mapillary_tools' version is a plain literal (mapillary_tools.VERSION),
# so the build does not need an scm tag.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + the build backend are pre-baked and the image
# sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools/wheel backend
# instead of trying to fetch an isolated build env (offline build isolation always fails). test.sh
# runs `source ./setup.sh` in the (offline) grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
