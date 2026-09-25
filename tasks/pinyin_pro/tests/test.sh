#!/bin/bash
# Offline grading driver for the pinyin_pro task. No `set -e` — we must always reach the CTRF summary
# so the grader gets a result even when the build or a test fails.
#
# Pipeline: run the agent's setup.sh (a no-op — vitest runs the TS source directly) -> discover the
# library entry (contract: lib/index.ts at the project root) -> symlink the baked harness node_modules
# so test files resolve bare deps (e.g. @pinyin-pro/data) -> write a vitest config mapping the neutral
# alias `pinyinlib` to that entry (anti-contamination) and `@` -> the lib dir (so the reproduced code's
# `@/data/*` imports resolve to the PROVIDED dictionaries) -> run the hidden vitest suite from the baked
# harness at /opt/harness under the node environment -> convert vitest's JSON to CTRF at
# /logs/verifier/ctrf.json. Everything runs with NO network; Node 20 + the harness (vitest +
# @vitest/coverage-v8 + @pinyin-pro/data + the CTRF converter) are pre-baked in the per-task image.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

HARNESS_DIR="${HARNESS_DIR:-/opt/harness}"
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(pwd)"
mkdir -p /logs/verifier

# 1. Locate the project's setup.sh (the working dir, or a single nested project dir) and run it.
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

# 2. Discover the library entry point. Contract: lib/index.ts under the project root.
ENTRY="$BUILD_DIR/lib/index.ts"
if [ ! -f "$ENTRY" ]; then
    FOUND="$(find "$WORK_DIR" -path '*/lib/index.ts' -not -path '*/node_modules/*' -print -quit 2>/dev/null)"
    [ -n "$FOUND" ] && ENTRY="$FOUND"
fi
LIB_DIR="$(dirname "$ENTRY")"           # .../lib  (the `@` alias target: @/data, @/common, ...)
echo "library entry: $ENTRY"
echo "@ alias -> $LIB_DIR"

# 3. Provide the baked harness node_modules to the test + project trees so bare imports resolve
#    (e.g. the tests may `require('@pinyin-pro/data/...')`).
[ -e "$TESTS_DIR/node_modules" ] || ln -sfn "$HARNESS_DIR/node_modules" "$TESTS_DIR/node_modules"
[ -e "$BUILD_DIR/node_modules" ] || ln -sfn "$HARNESS_DIR/node_modules" "$BUILD_DIR/node_modules"

# 4. Write the vitest config. The hidden tests import the library under the neutral alias `pinyinlib`
#    (anti-contamination — the real package name is never shown to the agent).
cat > "$HARNESS_DIR/vitest.config.mjs" <<CFG
import { defineConfig } from 'vitest/config'
export default defineConfig({
  resolve: { alias: { pinyinlib: '$ENTRY', '@': '$LIB_DIR' } },
  server: { fs: { strict: false, allow: ['$TESTS_DIR', '$LIB_DIR', '$BUILD_DIR', '$HARNESS_DIR', '/app', '/tests'] } },
  test: {
    environment: 'node',
    globals: false,
    include: ['$TESTS_DIR/**/*.test.ts'],
    testTimeout: 20000
  }
})
CFG

# 5. Run the tests offline, emitting vitest's JSON report.
echo "=== run vitest ==="
rm -f /tmp/vitest-results.json
( cd "$HARNESS_DIR" && ./node_modules/.bin/vitest run -c "$HARNESS_DIR/vitest.config.mjs" \
    --reporter=json --outputFile=/tmp/vitest-results.json )
echo "vitest exit: $?"

# 6. Convert vitest JSON -> CTRF for the grader.
if [ -f /tmp/vitest-results.json ]; then
    node "$HARNESS_DIR/ctrf_from_vitest.js" /tmp/vitest-results.json /logs/verifier/ctrf.json
fi

# 7. Fallback: if no CTRF was produced (e.g. the build failed so no test could run), write a
#    schema-valid zero-passed CTRF so the grader scores the attempt 0 rather than erroring.
if [ ! -f /logs/verifier/ctrf.json ]; then
    echo "=== no ctrf.json produced — writing zero-result fallback ==="
    node -e 'const fs=require("fs");fs.mkdirSync("/logs/verifier",{recursive:true});const t=Date.now();fs.writeFileSync("/logs/verifier/ctrf.json",JSON.stringify({results:{tool:{name:"vitest"},summary:{tests:0,passed:0,failed:0,pending:0,skipped:0,other:0,start:t,stop:t},tests:[]}}))'
fi

# 8. reward.txt — the authoritative score. 1 IFF every declared test ran and passed
#    (passed == CANONICAL_TOTAL, no failures, no skips, no other); 0 otherwise.
CANONICAL_TOTAL=55
CANONICAL_TOTAL="$CANONICAL_TOTAL" node -e '
try {
  const total = Number(process.env.CANONICAL_TOTAL);
  const s = require("/logs/verifier/ctrf.json").results.summary;
  const ok = s.passed === total && s.failed === 0 && (s.other || 0) === 0 &&
             (s.skipped || 0) === 0 && (s.pending || 0) === 0;
  require("fs").writeFileSync("/logs/verifier/reward.txt", ok ? "1" : "0");
} catch (e) { require("fs").writeFileSync("/logs/verifier/reward.txt", "0"); }
'
echo "=== reward.txt: $(cat /logs/verifier/reward.txt 2>/dev/null) ==="
