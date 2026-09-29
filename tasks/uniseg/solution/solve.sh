#!/bin/bash
set -e

# Assemble the groundtruth /app from the reference implementation: github.com/rivo/uniseg (pinned
# tag). The clone is the ONLY network operation in the GT flow — GT eval keeps internet on in
# Container A for it; the grading container is offline.
PIN=v0.4.7
git clone https://github.com/rivo/uniseg.git /tmp/repo
cd /tmp/repo
git checkout "$PIN"

# The task surface is the single root package `uniseg` — pure standard library (only unicode/utf8).
# Copy every non-test .go file into /app (this includes both the PROVIDED data-layer files, which
# also ship pre-baked in the image, and the algorithm files the agent must otherwise write). Drop
# all upstream tests (the hidden suite replaces them) and the code generators (gen_*.go, which are
# `//go:build ignore` package-main tools and out of scope).
cp /tmp/repo/*.go /app/
rm -f /app/*_test.go /app/gen_*.go

# Module manifest: pure-stdlib, zero external requires, `go` directive matching the baked toolchain.
cat > /app/go.mod <<'EOF'
module github.com/rivo/uniseg

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
