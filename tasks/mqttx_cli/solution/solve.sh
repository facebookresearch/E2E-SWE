#!/bin/bash
set -e

# Ground-truth setup for the mqttx_cli task (an MQTT 5.0 command-line client, TypeScript).
# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow.
git clone https://github.com/emqx/MQTTX.git /tmp/repo
cd /tmp/repo
git checkout a8a9087fd6a9b434300bf4882c7978c9196ac674

# SCOPE: only the CLI package (cli/) is graded — the self-contained MQTT command-line client
# (~4.6k LOC: commands conn/pub/sub/ls/init + utils for multi-format payload conversion, SCRAM auth,
# payload generation, formatting, simulation, and MQTT client/benchmark orchestration). The Electron/
# Vue desktop app (src/), web/, docs, and repo tooling are NOT part of the graded surface. Copy the
# CLI package's contents into /app (so the entry is /app/bin/index.js, package at /app/package.json).
cp -a /tmp/repo/cli/. /app/

cd /app
rm -rf /tmp/repo node_modules dist

# setup.sh builds the project OFFLINE — exactly what the agent is expected to produce. Dependencies
# are pre-installed by the grader (node_modules is present at build time; the image bakes them), so
# setup.sh only compiles the TypeScript to dist/ with the project's own build (tsc). test.sh runs
# `source ./setup.sh` in the offline grading container after ensuring node_modules is present.
cat > ./setup.sh <<'SETUP'
#!/bin/bash
set -e
# Dependencies are pre-installed (node_modules present). Compile TypeScript -> dist/.
npx tsc
SETUP
chmod +x ./setup.sh
