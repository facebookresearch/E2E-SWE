#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for Container A only).
git clone https://github.com/benhoyt/goawk.git /tmp/repo
cd /tmp/repo
git checkout 4390cf51dc984f757d0bba72be0f5e4d372897d1

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Offline build. goawk is pure Go stdlib (no third-party modules), so `go build` needs no network.
# The image sets GOPROXY=off / GOTOOLCHAIN=local. This produces the CLI binary at /app/goawk —
# exactly the artifact the agent's own setup.sh must produce. test.sh runs `source ./setup.sh` in
# the (offline) grading container.
echo 'go build -o /app/goawk .' > ./setup.sh
