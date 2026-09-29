#!/bin/bash
set -e

# git is pre-baked in the image. This clone is the only network op in the GT flow (GT eval keeps
# internet on for Container A only; the grading Container B is offline).
git clone https://github.com/d5/tengo.git /tmp/repo
cd /tmp/repo
git checkout c461a7fe6043d451d222406fdda3d39438653fea

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Offline build. tengo is pure Go stdlib, so `go build` needs no network. ./cmd/tengo is the
# main package (e.g. "." for a root main, or "./cmd/tengo"). Produces /app/tengo — exactly the
# artifact the agent's own setup.sh must produce.
echo 'go build -o /app/tengo ./cmd/tengo' > ./setup.sh
