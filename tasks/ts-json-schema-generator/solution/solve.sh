#!/bin/bash
set -e

# GROUND-TRUTH setup. git + the toolchain are pre-baked in the per-task image. This clone is the
# ONLY network operation in the GT flow (GT eval keeps internet on for Container A).
git clone https://github.com/vega/ts-json-schema-generator.git /tmp/repo
cd /tmp/repo
git checkout 51e4c05253c203033b2623261849508c8b0f050e   # pinned v2.0.0 HEAD

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo .git

# setup.sh installs+builds the project OFFLINE: it symlinks the pre-baked global toolchain
# (typescript pinned + all deps) as ./node_modules, then runs the TypeScript build (tsc → dist/).
# test.sh runs `source ./setup.sh` in the offline grading container. The agent is expected to
# produce an equivalent setup.sh (the spec tells it the toolchain is provided at /opt/toolchain).
cat > ./setup.sh <<'EOF'
ln -sfn /opt/toolchain/node_modules ./node_modules
npm run build
EOF
