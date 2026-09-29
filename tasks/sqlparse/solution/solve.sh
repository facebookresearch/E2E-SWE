#!/bin/bash
set -e

git clone https://github.com/andialbrecht/sqlparse.git /tmp/repo   # git is pre-baked in the image
cd /tmp/repo
git checkout f80af6a4007f11ada847218df8c29dc859238290              # pinned for reproducibility

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline; test.sh runs `source ./setup.sh` in the grading container.
# --no-build-isolation is required: the image bakes sqlparse's hatchling build backend (+ editables)
# and sets PIP_NO_INDEX, so offline build isolation would otherwise fail trying to fetch the backend.
# sqlparse has NO third-party runtime dependencies (Python stdlib only), so the install is fully
# offline against the baked backend.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
