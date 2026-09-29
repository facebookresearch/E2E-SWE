#!/bin/bash
set -e

# Ground-truth setup for the canvas-editor task (TypeScript rich-text editor).
# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). Pin to the exact commit for reproducibility.
git clone https://github.com/Hufe921/canvas-editor.git /tmp/repo
cd /tmp/repo
git checkout a92a4061788a0917fd5e1ac3c983363501edbdfb

# SCOPE: only the library source is graded — the self-contained editor library at src/editor/
# (~36.7k LOC, entry src/editor/index.ts). The demo app (src/main.ts, src/mock.ts, src/components,
# src/plugins, src/utils, index.html), the repo's own tests/, cypress/, docs/, and build tooling are
# NOT part of the graded surface and are not copied — the agent implements the library, not the app.
mkdir -p /app/src
cp -a /tmp/repo/src/editor /app/src/editor

# The library entry imports a version string from `../../package.json`; provide a minimal one so the
# offline run resolves it WITHOUT leaking the real npm package name (anti-contamination — the neutral
# import alias used by the hidden tests is configured in tests/test.sh).
printf '{ "version": "0.9.137" }\n' > /app/package.json

cd /app
rm -rf /tmp/repo

# No build step: the vitest harness (baked in the image at /opt/harness) runs the TypeScript source
# directly via vite, and the sole runtime dep (prismjs) is baked at /opt/libs/node_modules and
# resolved through the harness config. setup.sh is therefore a no-op — exactly what the agent is
# expected to produce (there is nothing to install/build offline). test.sh runs `source ./setup.sh`
# in the offline grading container, then runs the hidden vitest suite.
cat > ./setup.sh <<'SETUP'
#!/bin/bash
set -e
# No-op: the editor library is run directly from TypeScript source by the baked vitest harness;
# the only runtime dependency (prismjs) is pre-installed in the image.
SETUP
chmod +x ./setup.sh
