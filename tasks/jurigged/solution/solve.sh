#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it). cp -a carries .git into /app too.
git clone https://github.com/breuleux/jurigged.git /tmp/repo
cd /tmp/repo
git checkout 52d937776c6d57435777ee61c14bf5b56bd5fb26

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs jurigged offline against the pre-baked runtime deps (codefind, ovld, watchdog,
# blessed) and the baked hatchling build backend; the image sets PIP_NO_INDEX. --no-build-isolation
# is REQUIRED so pip uses the baked backend instead of fetching an isolated build env (which would
# fail offline). test.sh runs `source ./setup.sh` in the offline grading container.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
