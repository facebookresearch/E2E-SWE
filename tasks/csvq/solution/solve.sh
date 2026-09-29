#!/bin/bash
set -e

# git is pre-baked in the image. The GT solve runs in Container A (internet on); the grading
# Container B is offline and builds from the vendor/ dir shipped to /app.
git clone https://github.com/mithrandie/csvq.git /tmp/repo
cd /tmp/repo
git checkout a76c52e1ee576566abfd93a39b04eb33ad163410

# Vendor third-party deps from the module cache baked into the image (GOPROXY=off), so this needs no
# module proxy. (Alternative if you did NOT bake a cache: GOPROXY="https://proxy.golang.org,direct"
# to vendor over Container A's network.) The baked newer Go SDK satisfies the go>=X.Y requirement.
GOFLAGS= GOPROXY=off GOSUMDB=off go mod vendor

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Offline build from the shipped vendor/ dir. . is the main package (e.g. "./cmd/csvq").
# Produces /app/csvq — exactly the artifact the agent must produce (the agent, using only stdlib,
# writes `go build -o /app/csvq .`).
echo 'go build -mod=vendor -o /app/csvq .' > ./setup.sh
