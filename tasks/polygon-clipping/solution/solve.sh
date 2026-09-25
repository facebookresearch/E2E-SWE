#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). Pin to the exact commit for reproducibility.
git clone https://github.com/mfogel/polygon-clipping.git /tmp/repo
cd /tmp/repo
git checkout 82b0ac2c35304bfea9cac24eabcbda32a808ee55

# polygon-clipping is a single-package library. Only the library source (src/) is in scope: the
# public API lives at src/index.js (default export with union/intersection/xor/difference). Copy the
# source into /app so /app/src/index.js is the entry. (The repo's own test/, bench/, docs/, rollup /
# babel build config, and the pre-built dist/ are NOT part of the graded surface and are not copied
# — the agent implements the library, not the repo's tooling.)
cp -a /tmp/repo/src /app/src
cd /app
rm -rf /tmp/repo /app/.git

# setup.sh builds the project OFFLINE — exactly what the agent is expected to produce. The library
# source is ES-module .js that imports two THIRD-PARTY runtime deps by bare specifier (`splaytree`
# and `robust-predicates`); those are pre-installed in the image at /opt/libs/node_modules and are
# NOT reimplemented. The build is a plain `tsc --allowJs` transpile of the ES-module sources into a
# CommonJS bundle at /app/build/, whose entry point is /app/build/index.js. test.sh runs
# `bash ./setup.sh` in the (offline) grading container, then runs the hidden Jest tests, which
# import the built package as `polygon-clipping` (mapped to /app/build/index.js) and reach the baked
# deps via the harness's module resolution.
cat > ./setup.sh <<'SETUP'
#!/bin/bash
set -e
rm -rf build
tsc src/index.js \
  --allowJs \
  --outDir build \
  --module commonjs \
  --target es2019 \
  --esModuleInterop \
  --skipLibCheck \
  --noEmitOnError false \
  --declaration false
SETUP
chmod +x ./setup.sh
