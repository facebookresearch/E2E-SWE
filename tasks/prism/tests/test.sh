#!/bin/bash
# Offline grading driver for the prism task. No `set -e` — we must always reach the CTRF summary so the
# grader gets a result even when the build or a test fails.
#
# Pipeline: run the agent's setup.sh (no-op — ts-jest runs the TS source directly) -> discover the
# engine entry (contract: src/index.ts at the project root) -> symlink the baked node_modules so all
# deps + jest/ts-jest resolve -> write a jest config that maps the neutral alias `prismhttp` to the
# engine entry and `@stoplight/prism-core` to the provided core, transforms .ts AND faker's ESM .js via
# ts-jest, and emits CTRF -> run the hidden jest suite. Everything runs offline; Node 20 + the full
# dependency tree + prism-core are pre-baked at /opt/prism.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

PROVIDED="${PROVIDED:-/opt/prism}"
HARNESS_NM="$PROVIDED/node_modules"
CORE_ENTRY="$PROVIDED/packages/core/src/index.ts"
TS_CONFIG="$PROVIDED/packages/tsconfig.test.json"
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(pwd)"
mkdir -p /logs/verifier

# 1. Locate the project's setup.sh and run it.
echo "=== setup.sh (build) ==="
if [ -f "$WORK_DIR/setup.sh" ]; then
    BUILD_DIR="$WORK_DIR"
else
    SETUP_PATH="$(find "$WORK_DIR" -maxdepth 3 -name setup.sh -print -quit 2>/dev/null)"
    BUILD_DIR="$([ -n "$SETUP_PATH" ] && dirname "$SETUP_PATH" || echo "$WORK_DIR")"
fi
echo "build dir: $BUILD_DIR"
( cd "$BUILD_DIR" && bash ./setup.sh )
echo "setup.sh exit: $?"

# 2. Discover the engine entry point. Contract: src/index.ts under the project root. Also accept a
#    JavaScript entry (src/index.js) — ts-jest transforms .js too (allowJs), so an implementation
#    written in plain JS grades identically; only the file extension differs.
ENTRY=""
for cand in "$BUILD_DIR/src/index.ts" "$BUILD_DIR/src/index.js"; do
    [ -f "$cand" ] && { ENTRY="$cand"; break; }
done
if [ -z "$ENTRY" ]; then
    FOUND="$(find "$WORK_DIR" \( -path '*/src/index.ts' -o -path '*/src/index.js' \) -not -path '*/node_modules/*' -print -quit 2>/dev/null)"
    [ -n "$FOUND" ] && ENTRY="$FOUND"
fi
echo "engine entry: $ENTRY"

# 3. Provide the baked node_modules to the project + test trees (force, so a stray agent node_modules
#    can't shadow the harness). The engine also needs a package.json at its root (forwarder reads it).
rm -rf "$TESTS_DIR/node_modules" 2>/dev/null; ln -sfn "$HARNESS_NM" "$TESTS_DIR/node_modules"
rm -rf "$BUILD_DIR/node_modules" 2>/dev/null; ln -sfn "$HARNESS_NM" "$BUILD_DIR/node_modules"
[ -f "$BUILD_DIR/package.json" ] || printf '%s\n' '{ "name": "http-engine", "version": "0.0.0" }' > "$BUILD_DIR/package.json"

# 4. Write the jest config. `prismhttp` -> the engine entry (anti-contamination alias);
#    `@stoplight/prism-core` -> the provided core src. ts-jest transpile-only for .ts and .js (faker's
#    ESM dist must be transformed; whitelisted in transformIgnorePatterns).
#    Generated with node from a QUOTED heredoc: the config is authored as plain JS (regexes written
#    naturally, e.g. '^.+\.ts$') and JSON.stringify handles all escaping. Runtime values are passed
#    via the environment, so there is no shell backslash/`$` escaping in the heredoc to misread.
ENTRY="$ENTRY" CORE_ENTRY="$CORE_ENTRY" PROVIDED="$PROVIDED" HARNESS_NM="$HARNESS_NM" \
TS_CONFIG="$TS_CONFIG" BUILD_DIR="$BUILD_DIR" TESTS_DIR="$TESTS_DIR" \
node <<'NODE' > "$PROVIDED/jest.task.config.js"
const e = process.env;
const config = {
  rootDir: e.BUILD_DIR,
  roots: [e.TESTS_DIR],
  testMatch: ['**/*.test.ts'],
  testEnvironment: 'node',
  moduleNameMapper: {
    '^prismhttp$': e.ENTRY,
    '^@stoplight/prism-core$': e.CORE_ENTRY,
    '^@stoplight/prism-core/(.*)$': e.PROVIDED + '/packages/core/src/$1',
  },
  transform: {
    '^.+\\.ts$': [e.HARNESS_NM + '/ts-jest', { isolatedModules: true, tsconfig: e.TS_CONFIG }],
    '^.+\\.js$': [e.HARNESS_NM + '/ts-jest', { isolatedModules: true, tsconfig: { allowJs: true } }],
  },
  transformIgnorePatterns: ['node_modules/(?!@faker-js/faker|http-proxy-agent|https-proxy-agent|agent-base)'],
  reporters: ['default', ['jest-ctrf-json-reporter', { outputDir: '/logs/verifier', outputFile: 'ctrf.json' }]],
};
process.stdout.write('module.exports = ' + JSON.stringify(config, null, 2) + '\n');
NODE

# 5. Run the hidden jest suite offline.
echo "=== run jest ==="
( cd "$BUILD_DIR" && "$HARNESS_NM/.bin/jest" -c "$PROVIDED/jest.task.config.js" --ci --runInBand )
echo "jest exit: $?"

# 6. Fallback: if no CTRF was produced, write a schema-valid zero-passed CTRF.
if [ ! -f /logs/verifier/ctrf.json ]; then
    echo "=== no ctrf.json produced — writing zero-result fallback ==="
    node -e 'const fs=require("fs");fs.mkdirSync("/logs/verifier",{recursive:true});const t=Date.now();fs.writeFileSync("/logs/verifier/ctrf.json",JSON.stringify({results:{tool:{name:"jest"},summary:{tests:0,passed:0,failed:0,pending:0,skipped:0,other:0,start:t,stop:t},tests:[]}}))'
fi

# 7. reward.txt — binary gate: 1 iff every declared test ran and passed.
CANONICAL_TOTAL=56 node -e '
try {
  const total = Number(process.env.CANONICAL_TOTAL);
  const s = require("/logs/verifier/ctrf.json").results.summary;
  const ok = s.passed === total && s.failed === 0 && (s.other || 0) === 0 && (s.skipped || 0) === 0 && (s.pending || 0) === 0;
  require("fs").writeFileSync("/logs/verifier/reward.txt", ok ? "1" : "0");
} catch (e) { require("fs").writeFileSync("/logs/verifier/reward.txt", "0"); }
'
echo "=== reward.txt: $(cat /logs/verifier/reward.txt 2>/dev/null) ==="
