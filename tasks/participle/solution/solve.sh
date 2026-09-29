#!/bin/bash
set -e

# Assemble the groundtruth /app from the reference implementation:
# github.com/alecthomas/participle/v2 (pinned commit). The clone is the ONLY network operation in
# the GT flow — GT eval keeps internet on in Container A for it; the grading container is offline.
PIN=e68cd76cca1249da498f3d34b82ec964967424af
git clone https://github.com/alecthomas/participle.git /tmp/repo
cd /tmp/repo
git checkout "$PIN"

# The task surface is the two core packages — `participle` (root) and `participle/lexer` — both
# pure-stdlib. Copy them into /app and drop all upstream tests (the hidden suite replaces them).
# Everything else upstream (cmd/, ebnf/, _examples/, lexer/internal/) is out of scope.
mkdir -p /app/lexer
cp /tmp/repo/*.go /app/
rm -f /app/*_test.go
for f in api.go doc.go errors.go peek.go simple.go stateful.go text_scanner.go; do
  cp "/tmp/repo/lexer/$f" /app/lexer/
done

# Module manifest: pure-stdlib, zero external requires, `go` directive matching the baked toolchain.
cat > /app/go.mod <<'EOF'
module github.com/alecthomas/participle/v2

go 1.22
EOF

cd /app
rm -rf /tmp/repo

# setup.sh is SOURCED (not executed) by the grading harness — it must not call `exit`. It performs
# the OFFLINE build of both packages. The image bakes the toolchain and forces GOPROXY=off, so this
# needs no network. This mirrors what the agent is expected to produce.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOCACHE="${GOCACHE:-/tmp/gocache}"
go build ./... || return 1
EOF
chmod +x /app/setup.sh
