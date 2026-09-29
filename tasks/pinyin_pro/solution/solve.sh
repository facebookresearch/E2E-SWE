#!/bin/bash
set -e

# Ground-truth setup for the pinyin_pro task (TypeScript Chinese-pinyin library).
# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). Pin to the exact commit for reproducibility.
git clone https://github.com/zh-lx/pinyin-pro.git /tmp/repo
cd /tmp/repo
git checkout 2056ff9a37712c8423be84d7e8d393184f93371f

# SCOPE: the graded surface is the ALGORITHM — lib/core/ + lib/common/ + the public entry lib/index.ts
# (~3.2k LOC). The ~44k LOC of dictionary DATA (lib/data/*) is PROVIDED to the agent (baked into the
# image at /app/lib/data), NOT reproduced. For GT we copy the full lib/ (algorithm + data + entry);
# the provided data files are identical to the baked ones. The repo's own tests/, benchmark/, docs/
# and build tooling are NOT part of the graded surface and are not copied.
mkdir -p /app/lib
cp -a /tmp/repo/lib/. /app/lib/

cd /app
rm -rf /tmp/repo

# No build step: the vitest harness (baked at /opt/harness) runs the TypeScript source directly via
# vite. The library has NO runtime dependencies. setup.sh is therefore a no-op — exactly what the
# agent is expected to produce (there is nothing to install/build offline). test.sh runs
# `source ./setup.sh` in the offline grading container, then runs the hidden vitest suite.
cat > ./setup.sh <<'SETUP'
#!/bin/bash
set -e
# No-op: the library runs directly from TypeScript source under the baked vitest harness; there are
# no runtime dependencies to install and no build step.
SETUP
chmod +x ./setup.sh
