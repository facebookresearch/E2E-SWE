#!/bin/bash
# OFFLINE grading for the TypeScript task. Toolchain (typescript pinned + vitest + tsx) is baked at
# /opt/toolchain and symlinked by setup.sh. No network. No `set -e` — reward logic needs the exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Build/install the project offline (setup.sh written by the agent, or by solve.sh for GT):
# symlinks /opt/toolchain/node_modules as /app/node_modules and runs the TypeScript build (tsc).
# Run in a separate process (NOT `source`) so a `set -e` inside the agent's setup.sh cannot leak
# into this script and abort grading before we emit CTRF. Filesystem effects (node_modules symlink,
# dist/) persist regardless.
bash ./setup.sh || true

set +e
mkdir -p /logs/verifier

# Wire up resolution for the hidden suite (mirrors the verified dev harness):
#  - expose the built implementation under its package name so tests can `import 'ts-json-schema-generator'`
#  - make the toolchain (vitest, deps) resolvable from /tests
ln -sfn /app /opt/toolchain/node_modules/ts-json-schema-generator
ln -sfn /opt/toolchain/node_modules /tests/node_modules

cd /tests
./node_modules/.bin/vitest run --config /tests/vitest.config.mts \
    --reporter=json --outputFile=/tmp/vitest.json
TEST_EXIT=$?

# Convert vitest JSON → CTRF (the schema the grader reads).
node /opt/toolchain/vitest2ctrf.mjs /tmp/vitest.json

if [ $TEST_EXIT -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
