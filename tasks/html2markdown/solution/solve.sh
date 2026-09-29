#!/bin/bash
set -e

# git is pre-baked in the image. The GT solve runs in Container A (internet on); the grading
# Container B is offline and builds from the vendor/ dir shipped to /app.
git clone https://github.com/JohannesKaufmann/html-to-markdown.git /tmp/repo
cd /tmp/repo
git checkout 290df46a279e3d7d9011dbbb199658dfcb5ec272

# Vendor third-party deps from the module cache baked into the image (GOPROXY=off), so this needs no
# module proxy. (Alternative if you did NOT bake a cache: GOPROXY="https://proxy.golang.org,direct"
# to vendor over Container A's network.) The baked newer Go SDK satisfies the go>=X.Y requirement.
GOFLAGS= GOPROXY=off GOSUMDB=off go mod vendor

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Offline build from the shipped vendor/ dir. ./cli/html2markdown is the main package.
# Produces /app/html2markdown — exactly the artifact the agent must produce (the agent uses only the
# Go standard library + golang.org/x/net/html, so its setup.sh is `go build -o /app/html2markdown .`).
echo 'go build -mod=vendor -o /app/html2markdown ./cli/html2markdown' > ./setup.sh
