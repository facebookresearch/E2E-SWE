#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on solely for it).
git clone https://github.com/lemon24/reader.git /tmp/repo
cd /tmp/repo
git checkout c6e55cfcf92b34b4784e39ca42201c41572fddd0

# cp -a carries .git too, so an attr-based dynamic version ({attr = "reader.__version__"}) resolves.
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: runtime deps + build backend are pre-baked and the image
# sets PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools/wheel instead
# of fetching an isolated build env (which can never succeed with no network). The .[cli] extra pulls
# in click, which the CLI (`python -m reader`) needs.
cat > ./setup.sh <<'EOF'
pip install -e ".[cli]" --no-build-isolation
EOF
