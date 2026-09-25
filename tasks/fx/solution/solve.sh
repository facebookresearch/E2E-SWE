#!/bin/bash
set -e

# GROUND-TRUTH setup. Assemble /app from the reference implementation, borgar/fx
# (https://github.com/borgar/fx). Network operations here run in Container A, which keeps internet on
# for GT (the grading container is offline).
git clone https://github.com/borgar/fx.git /tmp/repo
cd /tmp/repo
git checkout 01cf243033a356e4bf75830b166b770aef48fbe4   # pinned v5.0.5

# fx is TypeScript with ZERO runtime dependencies. Bundle its entry (lib/index.ts) into a single
# CommonJS module at /app/fx.js so that require("/app/fx.js") returns the fx API (the surface the
# hidden suite uses). esbuild (its native binary is baked into the per-task image) resolves the .ts
# imports and strips types; no npm install or network fetch of the toolchain is required. The agent
# is expected to produce an equivalent /app/fx.js offline.
esbuild lib/index.ts --bundle --format=cjs --platform=node --target=node20 --outfile=/app/fx.js
rm -rf /tmp/repo

# setup.sh is SOURCED (not executed) by the grading harness, so it must not call `exit`. This module
# is plain Node.js with no build step at grade time, so setup is a no-op.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
# No build step: the module is loaded directly with require("/app/fx.js").
:
EOF
chmod +x /app/setup.sh
