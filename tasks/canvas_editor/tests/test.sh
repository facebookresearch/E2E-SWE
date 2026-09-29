#!/bin/bash
# Offline grading driver for the canvas-editor task. No `set -e` — we must always reach the CTRF
# summary so the grader gets a result even when the build or a test fails.
#
# Pipeline: run the agent's setup.sh (a no-op build — vitest runs the TS source directly) -> discover
# the library entry (contract: src/editor/index.ts at the project root) -> write a vitest config that
# maps the neutral alias `richdoc` to that entry (anti-contamination) -> run the hidden vitest suite
# from the baked harness at /opt/harness under jsdom + mocked canvas -> convert vitest's JSON to CTRF
# at /logs/verifier/ctrf.json. Everything runs with NO network; Node 24, and the harness (vitest +
# jsdom + vitest-canvas-mock + vite + the CTRF converter) are pre-baked in the per-task image.

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

# 2. Discover the library entry point. Contract: src/editor/index.ts under the project root. Search
#    defensively so a project nested one level deep, or a differently-organised editor dir, is found.
ENTRY="$BUILD_DIR/src/editor/index.ts"
if [ ! -f "$ENTRY" ]; then
    FOUND="$(find "$WORK_DIR" -path '*/src/editor/index.ts' -not -path '*/node_modules/*' -print -quit 2>/dev/null)"
    [ -n "$FOUND" ] && ENTRY="$FOUND"
fi
if [ ! -f "$ENTRY" ]; then
    FOUND="$(find "$WORK_DIR" \( -path '*/editor/index.ts' -o -path '*/src/index.ts' \) -not -path '*/node_modules/*' -print -quit 2>/dev/null)"
    [ -n "$FOUND" ] && ENTRY="$FOUND"
fi
# `@` alias -> the src/ dir two levels above the entry (src/editor/index.ts -> src/), matching the
# library's internal `@/*` -> `./src/*` convention.
APP_SRC="$(dirname "$(dirname "$ENTRY")")"
echo "library entry: $ENTRY"
echo "@ alias -> $APP_SRC"

# 3. Write the vitest config with the discovered entry. The hidden tests import the library under the
#    neutral alias `richdoc` (anti-contamination — the real package name is never shown to the agent).
cat > "$HARNESS_DIR/vitest.config.mjs" <<CFG
import { defineConfig } from 'vitest/config'
export default defineConfig({
  resolve: { alias: { richdoc: '$ENTRY', '@': '$APP_SRC' } },
  server: { fs: { strict: false, allow: ['$TESTS_DIR', '$APP_SRC', '$HARNESS_DIR', '/app', '/tests'] } },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['$HARNESS_DIR/setup.ts'],
    include: ['$TESTS_DIR/**/*.test.ts'],
    css: false,
    // Per-case wall-clock cap: aborts a case whose async work never settles (marks it failed) so the
    // denominator stays fixed. A purely synchronous infinite loop cannot be interrupted here and is
    // instead bounded by the verifier's timeout_sec + the zero-result CTRF fallback below.
    testTimeout: 20000
  }
})
CFG

# 4. Run the tests offline, emitting vitest's JSON report.
echo "=== run vitest ==="
rm -f /tmp/vitest-results.json
( cd "$HARNESS_DIR" && ./node_modules/.bin/vitest run -c "$HARNESS_DIR/vitest.config.mjs" \
    --reporter=json --outputFile=/tmp/vitest-results.json )
echo "vitest exit: $?"

# 5. Convert vitest JSON -> CTRF for the grader.
if [ -f /tmp/vitest-results.json ]; then
    node "$HARNESS_DIR/ctrf_from_vitest.js" /tmp/vitest-results.json /logs/verifier/ctrf.json
fi

# 6. Fallback: if no CTRF was produced (e.g. the build failed so no test could run), write a
#    schema-valid zero-passed CTRF so the grader scores the attempt 0 rather than erroring.
if [ ! -f /logs/verifier/ctrf.json ]; then
    echo "=== no ctrf.json produced — writing zero-result fallback ==="
    node -e 'const fs=require("fs");fs.mkdirSync("/logs/verifier",{recursive:true});const t=Date.now();fs.writeFileSync("/logs/verifier/ctrf.json",JSON.stringify({results:{tool:{name:"vitest"},summary:{tests:0,passed:0,failed:0,pending:0,skipped:0,other:0,start:t,stop:t},tests:[]}}))'
fi

# 7. reward.txt — binary all-or-nothing gate: 1 iff every declared test ran and passed.
node -e '
const TOTAL = 48;
try {
  const s = require("/logs/verifier/ctrf.json").results.summary;
  const ok = s.passed === TOTAL && s.failed === 0 && (s.other || 0) === 0 &&
             (s.skipped || 0) === 0 && (s.pending || 0) === 0;
  require("fs").writeFileSync("/logs/verifier/reward.txt", ok ? "1" : "0");
} catch (e) { require("fs").writeFileSync("/logs/verifier/reward.txt", "0"); }
'
echo "=== reward.txt: $(cat /logs/verifier/reward.txt 2>/dev/null) ==="
