#!/bin/bash
set -e

# Ground-truth setup for the prism task (TypeScript OpenAPI mock/validation engine).
# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on for it). Pin to the exact commit for reproducibility.
git clone https://github.com/stoplightio/prism.git /tmp/repo
cd /tmp/repo
git checkout 92ea2fa635e98ffda13672f16386f40f1d1a3876

# SCOPE: the graded surface is the HTTP engine — packages/http/src (router + validator + mocker +
# utils + forwarder + the createInstance/createAndCallPrismInstanceWithSpec entry), ~4k LOC. The heavy
# dependencies (ajv, faker, json-schema-faker, the @stoplight/* platform, fp-ts, ...) and the sibling
# @stoplight/prism-core package are PROVIDED (baked at /opt/prism), NOT reproduced. The CLI,
# http-server, docs, and the repo's own tests are out of scope and not copied.
rm -rf /app/src
cp -a /tmp/repo/packages/http/src /app/src

cd /app
rm -rf /tmp/repo

# The forwarder reads the package version from `../../package.json`; provide a minimal one at the
# project root (also required for the agent — baked in the image, re-written here for GT parity).
printf '%s\n' '{ "name": "http-engine", "version": "0.0.0" }' > /app/package.json

# No build step: the jest+ts-jest harness (baked at /opt/prism/node_modules) runs the TypeScript source
# directly; all deps + prism-core are baked. setup.sh is a no-op — exactly what the agent produces.
cat > ./setup.sh <<'SETUP'
#!/bin/bash
set -e
# No-op: the engine runs directly from TypeScript source under the baked jest+ts-jest harness; all
# dependencies and @stoplight/prism-core are pre-provided. Nothing to install or build.
SETUP
chmod +x ./setup.sh
