#!/bin/bash
set -e

# git is pre-baked in the image. The GT solve runs in Container A (internet on); the grading
# Container B is offline and builds from the vendor/ dir shipped to /app.
git clone https://github.com/tdewolff/minify.git /tmp/repo
cd /tmp/repo
git checkout 98dea98c57f463c8bb4b2b3bf756717ffa404ed3

# Vendor third-party deps from the module cache baked into the image (GOPROXY=off), so this needs no
# module proxy. (Alternative if you did NOT bake a cache: GOPROXY="https://proxy.golang.org,direct"
# to vendor over Container A's network.) The baked newer Go SDK satisfies the go>=X.Y requirement.
GOFLAGS= GOPROXY=off GOSUMDB=off go mod vendor

# Ship the source (with vendor/) to a SUBDIR of /app, not /app itself: the repo contains a top-level
# `minify/` package directory, so copying it to /app root would make /app/minify a directory and
# `go build -o /app/minify` would then write the binary *inside* it. Building from /app/gtsrc keeps
# the binary path /app/minify free for the executable.
mkdir -p /app/gtsrc
cp -a /tmp/repo/. /app/gtsrc/
rm -rf /tmp/repo

# Offline build from the shipped vendor/ dir. Produces /app/minify — exactly the artifact the agent
# must produce (the agent, using only stdlib, writes `go build -o /app/minify .`).
echo 'cd /app/gtsrc && go build -mod=vendor -o /app/minify ./cmd/minify' > /app/setup.sh
