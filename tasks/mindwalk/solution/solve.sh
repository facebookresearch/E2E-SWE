#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it; the grading container stays offline).
git clone https://github.com/cosmtrek/mindwalk.git /tmp/repo
cd /tmp/repo
git checkout e208b6b8504138843f671e031f28129b66003a67

# The hidden suite is black-box (it builds and drives the compiled binary), so the upstream in-tree
# Go tests are not needed and must not run at grading time. Removing them also drops the only import
# of the jsonschema test dependency from the module's own build graph.
find . -name '*_test.go' -delete

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo
# Drop VCS metadata so `go build` does not stamp a git-derived version and so the citymap builder,
# when pointed at a freshly created fixture, is exercised the same way the agent's build is.
rm -rf /app/.git

# setup.sh is SOURCED by the grading harness (it must not call `exit`). It performs the OFFLINE
# build of the CLI. The image bakes the Go 1.25 toolchain and every module dependency and forces
# GOPROXY=off, so this needs no network. This mirrors what the agent is expected to produce.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOSUMDB=off GOCACHE="${GOCACHE:-/tmp/gocache}"
go build ./cmd/mindwalk || return 1
EOF
chmod +x /app/setup.sh
