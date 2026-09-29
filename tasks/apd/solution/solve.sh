#!/bin/bash
set -e

# Assemble the groundtruth /app from the reference implementation:
# github.com/cockroachdb/apd/v3 (pinned tag). The clone is the ONLY network operation in the GT
# flow — GT eval keeps internet on in Container A for it; the grading container is offline.
PIN=v3.2.3
git clone https://github.com/cockroachdb/apd.git /tmp/repo
cd /tmp/repo
git checkout "$PIN"

# The task surface is the single root package `apd` — pure-stdlib (only math/big). Copy every
# non-test .go file into /app and drop all upstream tests (the hidden suite replaces them). The
# testdata/ dectest vectors and the lib/pq-dependent sql_test.go are upstream-test-only, out of
# scope, and never copied.
cp /tmp/repo/*.go /app/
rm -f /app/*_test.go

# Module manifest: pure-stdlib, zero external requires, `go` directive matching the baked toolchain.
cat > /app/go.mod <<'EOF'
module github.com/cockroachdb/apd/v3

go 1.22
EOF

cd /app
rm -rf /tmp/repo

# setup.sh is SOURCED (not executed) by the grading harness — it must not call `exit`. It performs
# the OFFLINE build of the package. The image bakes the toolchain and forces GOPROXY=off, so this
# needs no network. This mirrors what the agent is expected to produce.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOCACHE="${GOCACHE:-/tmp/gocache}"
go build ./... || return 1
EOF
chmod +x /app/setup.sh
