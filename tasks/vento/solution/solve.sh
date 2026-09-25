#!/bin/bash
set -e

# Assemble the groundtruth /app from the reference implementation: ventojs/vento, a bespoke Deno
# template engine. vento has ZERO runtime dependencies. We git clone at a pinned commit (the only
# network op in the GT flow; GT keeps internet on in Container A, the grading container is offline)
# and lay out the engine so the tests can `import tmpl from "/app/mod.ts"`.
cd /tmp && rm -rf vento-src
git clone --quiet https://github.com/ventojs/vento.git vento-src
cd vento-src && git checkout --quiet 90a135acbaabb031382278e0903eea0e2c34857f
# Copy the engine (mod.ts re-exports from ./core, ./plugins, ./loaders — preserve structure).
cp mod.ts /app/
cp -r core plugins loaders /app/
cd /app && rm -rf /tmp/vento-src

# setup.sh is SOURCED (offline) before tests; no build step for Deno. Must not `exit`.
cat > /app/setup.sh <<'SHEOF'
#!/bin/bash
:
SHEOF
chmod +x /app/setup.sh
