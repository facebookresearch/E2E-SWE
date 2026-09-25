#!/bin/bash
set -e

# GROUND-TRUTH setup. Assemble /app from the reference implementation, borgar/numfmt
# (https://github.com/borgar/numfmt). Cloning it is the ONLY network operation in the GT flow (GT
# keeps internet on in Container A for this; the grading container is offline).
git clone https://github.com/borgar/numfmt.git /tmp/repo
cd /tmp/repo
git checkout c2cfdfa01bb1f24df51e985825671eb480daed4c   # pinned v3.2.6

# numfmt has ZERO runtime deps and ships a committed CommonJS bundle at dist/numfmt.js (its package
# `main`). Expose it at /app/numfmt.js so that require("/app/numfmt.js") returns the numfmt API (the
# surface the hidden suite uses: format, parseValue, dateToSerial, getFormatInfo, ...). No build step
# is needed at grade time. The agent is expected to produce an equivalent /app/numfmt.js offline.
cp /tmp/repo/dist/numfmt.js /app/numfmt.js
rm -rf /tmp/repo

# setup.sh is SOURCED (not executed) by the grading harness, so it must not call `exit`. This module
# is plain Node.js with no build step, so setup is a no-op.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
# No build step: the module is loaded directly with require("/app/numfmt.js").
:
EOF
chmod +x /app/setup.sh
