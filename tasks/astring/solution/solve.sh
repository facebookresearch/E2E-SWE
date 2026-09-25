#!/bin/bash
set -e

# Assemble the groundtruth /app from the reference implementation: davidbonnet/astring (npm `astring`),
# a JavaScript code generator (ESTree AST -> source). astring has NO runtime dependencies. We download
# the published tarball with `curl` (fast; the proven approach — `npm install` is slow/unreliable
# here). This curl is the ONLY network operation in the GT flow (GT keeps internet on in Container A;
# the grading container is offline).
cd /tmp && rm -rf awdl && mkdir awdl && cd awdl
curl -sSL -o astring.tgz "https://registry.npmjs.org/astring/-/astring-1.9.0.tgz"
mkdir -p /app/node_modules/astring
tar xzf astring.tgz -C /app/node_modules/astring --strip-components=1
cd /app && rm -rf /tmp/awdl

# The tests load the generator at /app/astring.js via its CommonJS `generate(node)` API; re-export the
# installed package.
cat > /app/astring.js <<'EOF'
module.exports = require("astring");
EOF

# setup.sh is SOURCED (not executed) by the grading harness, so it must not call `exit`. No build step.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
:
EOF
chmod +x /app/setup.sh
