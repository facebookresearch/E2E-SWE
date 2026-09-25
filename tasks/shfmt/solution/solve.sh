#!/bin/bash
set -e

# git is pre-baked in the image. The GT solve runs in Container A (internet on); the grading
# Container B is offline and builds from the vendor/ dir shipped to /app.
git clone https://github.com/mvdan/sh.git /tmp/repo
cd /tmp/repo
git checkout 2f3f5e36d9b0f8f14c998d50aa20a28832205ae8

# Vendor third-party deps from the module cache baked into the image (GOPROXY=off), so this needs no
# module proxy. (Alternative if you did NOT bake a cache: GOPROXY="https://proxy.golang.org,direct"
# to vendor over Container A's network.) The baked newer Go SDK satisfies the go>=X.Y requirement.
GOFLAGS= GOPROXY=off GOSUMDB=off go mod vendor

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Offline build from the shipped vendor/ dir. ./cmd/shfmt is the main package (e.g. "./cmd/shfmt").
# Produces /app/shfmt — exactly the artifact the agent must produce (the agent, using only stdlib,
# writes `go build -o /app/shfmt .`).
echo 'go build -mod=vendor -o /app/shfmt ./cmd/shfmt' > ./setup.sh
