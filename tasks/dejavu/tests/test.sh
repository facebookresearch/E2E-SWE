#!/bin/bash
# Offline grading driver for the `dejavu` Go task. There is NO network at grading time; the Go 1.25
# toolchain, git, and the sqlite3 CLI are all pre-baked into the per-task image
# (environment/Dockerfile). Do NOT add apt-get / go get / curl.
#
# The hidden suite is BLACK-BOX: it builds the agent's `deja` binary and drives it through the CLI
# (index / search / mcp / promote / forget / blame / handoff / resume / install / doctor), so it
# lives in its own stdlib-only Go module under /tests and never imports the agent's packages.
#
# No `set -e` — we always want to emit a CTRF report (even on a build failure) and score from it.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier
export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOSUMDB=off
export GOCACHE="${GOCACHE:-/tmp/gocache}"

# --- Locate the agent's Go module root (shallowest directory holding a go.mod). ---
MODROOT=""
first="$(find /app -name go.mod 2>/dev/null | awk '{print length, $0}' | sort -n | cut -d' ' -f2- | head -1)"
[ -n "$first" ] && MODROOT="$(dirname "$first")"
[ -z "$MODROOT" ] && MODROOT=/app

# Best-effort: run the agent's (or GT's) setup.sh so its build steps happen in this environment.
if [ -f "$MODROOT/setup.sh" ]; then
  ( cd "$MODROOT" && bash ./setup.sh ) >/tmp/setup.log 2>&1
fi

# --- Build the `deja` binary (the black-box target). Try the repo's layout first, then a plain
#     module-root build, then search for any package main. ---
rm -f /tmp/deja
cd "$MODROOT"
go build -o /tmp/deja ./cmd/deja >/tmp/build.log 2>&1
if [ ! -x /tmp/deja ]; then
  go build -o /tmp/deja . >>/tmp/build.log 2>&1
fi
if [ ! -x /tmp/deja ]; then
  while IFS= read -r pkg; do
    [ -z "$pkg" ] && continue
    if go build -o /tmp/deja "$pkg" >>/tmp/build.log 2>&1; then
      break
    fi
  done < <(go list -f '{{if eq .Name "main"}}{{.ImportPath}}{{end}}' ./... 2>/dev/null)
fi

# --- Run the hidden black-box suite (separate module in /tests). ---
cd /tests
DEJA_BIN=/tmp/deja go test -json -timeout 600s . > /tmp/gotest.json 2>&1

# --- Convert `go test -json` -> CTRF and compute reward (stdlib-only Go converter). ---
go run ./ctrf /tmp/gotest.json /logs/verifier/ctrf.json /logs/verifier/reward.txt >/tmp/ctrf.log 2>&1

# Safety net: if the converter itself failed to write a reward, mark failure.
[ -f /logs/verifier/reward.txt ] || echo 0 > /logs/verifier/reward.txt
