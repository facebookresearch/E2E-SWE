#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile), so no apt-get is needed.
# This clone is the ONLY network operation in the GT flow (GT eval keeps internet on for it).
git clone https://github.com/facebook/sapp.git /tmp/repo
cd /tmp/repo
git checkout e788ed7d1a8e313da409f4bf2e32cb6f8a624a62  # fb-sapp 0.5.9

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline. The parser-layer runtime deps + the build backend are
# pre-baked and the image sets PIP_NO_INDEX, so --no-build-isolation is REQUIRED (offline build
# isolation can never fetch the backend). --no-deps is also REQUIRED: the repo's requirements.txt
# pins the out-of-scope DB/UI stack (Flask, ipython, ...) which is intentionally not baked, so
# letting pip resolve it offline would fail; the baked parser deps are sufficient for the tests.
echo 'pip install -e . --no-deps --no-build-isolation' > ./setup.sh
