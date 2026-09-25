#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it; the grading container stays offline).
git clone https://github.com/vshulcz/deja-vu.git /tmp/repo
cd /tmp/repo
git checkout 1b1a97533f5f8d906bd63e50a03e20927dc900da

# The hidden suite is black-box (it builds and drives the compiled `deja` binary), so the upstream
# in-tree Go tests are not needed and must not run at grading time. deja-vu is a zero-dependency
# stdlib-only module (empty go.sum), so removing the tests does not change the build graph.
find . -name '*_test.go' -delete

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo
# Drop VCS metadata so `go build` does not stamp a git-derived version into the binary.
rm -rf /app/.git

# setup.sh is SOURCED by the grading harness (it must not call `exit`). It performs the OFFLINE
# build of the CLI. The image bakes the Go 1.25 toolchain and forces GOPROXY=off; the module has no
# external dependencies, so this needs no network. This mirrors what the agent is expected to produce.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOSUMDB=off GOCACHE="${GOCACHE:-/tmp/gocache}"
go build ./cmd/deja || return 1
EOF
chmod +x /app/setup.sh
