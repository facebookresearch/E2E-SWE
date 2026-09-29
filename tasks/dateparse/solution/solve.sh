#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT
# flow (GT eval keeps internet on for it; the grading container stays offline).
git clone https://github.com/araddon/dateparse.git /tmp/repo
cd /tmp/repo
git checkout 6b43995a97dee4b2c7fc0bdff8e124da9f31a57e   # pinned master (no release tags)

# Drop out-of-scope code so the ground truth matches the task scope:
#   dateparse/ - the demo CLI (pulls scylladb/termtables) — non-eval tooling
#   example/   - example program
#   *_test.go  - the upstream test suite (only the hidden tests run at grading time)
#   bench_test.go
rm -rf dateparse example
find . -name '*_test.go' -delete

# Hide the upstream identity: rewrite the module path to the neutral name the hidden tests
# import (`dateparse`). The core is pure stdlib, so the require block is unnecessary — write a
# minimal go.mod so the offline build needs no go.sum / module downloads.
find . -name '*.go' -exec sed -i 's,github.com/araddon/dateparse,dateparse,g' {} +
cat > go.mod <<'EOF'
module dateparse

go 1.12
EOF
rm -f go.sum

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh builds the module OFFLINE. The module has no external dependencies, and the image
# pins GOPROXY=off / GOFLAGS=-mod=mod, so this never touches the network. test.sh runs
# `source ./setup.sh` in the (offline) grading container before compiling the hidden tests.
echo 'go build ./... >/dev/null 2>&1 || true' > ./setup.sh
