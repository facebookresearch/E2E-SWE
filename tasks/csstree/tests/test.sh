#!/bin/bash
# Offline grading driver for the stylesheet-tree task. No `set -e` — we must always reach the CTRF
# summary so the grader gets a result even when the build or a test throws.
#
# Pipeline: build the project (the agent's setup.sh, which links the pre-baked runtime deps in as
# ./node_modules) -> expose the built library to the hidden drivers under its aliased package name
# `stylesheet-tree` via a tests-local node_modules symlink -> run the self-contained Node ESM runner
# (tests/run.mjs), which reads the committed manifest.json oracle, runs every case with a per-case
# timeout, and writes /logs/verifier/ctrf.json directly. Everything runs with NO network; Node 20
# and the two runtime deps (mdn-data + source-map-js at /opt/deps) are pre-baked in the per-task
# image.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

DEPS_DIR="${DEPS_DIR:-/opt/deps/node_modules}"
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
( cd "$BUILD_DIR" && DEPS_DIR="$DEPS_DIR" bash ./setup.sh )
echo "setup.sh exit: $?"

# 1b. ANTI-CONTAMINATION GUARD (defense in depth). The per-task image purges the real css-tree, but
#     guard here too: if the target library is resolvable from the build dir at grade time (e.g. a
#     regressed image, or the agent vendored/fetched a real copy), the submission could pass by
#     importing it instead of implementing. In that case, refuse to grade: write a zero-result CTRF
#     and exit so the attempt scores 0 rather than being credited for wrapping the real library.
if ( cd "$BUILD_DIR" && node -e "require.resolve('css-tree')" ) >/dev/null 2>&1; then
    echo "=== CONTAMINATION: 'css-tree' is resolvable at grade time — refusing to grade, scoring 0 ==="
    node -e 'const fs=require("fs");const now=Date.now();fs.writeFileSync("/logs/verifier/ctrf.json",JSON.stringify({results:{tool:{name:"stylesheet-tree-runner",reason:"css-tree resolvable at grade time (contamination guard)"},summary:{tests:0,passed:0,failed:0,pending:0,skipped:0,other:0,start:now,stop:now},tests:[]}}))'
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

# 2. Locate the built ESM entry point. The contract is src/index.js at the project root; search
#    defensively so a project nested one level deep is still found.
ENTRY="$BUILD_DIR/src/index.js"
if [ ! -f "$ENTRY" ]; then
    FOUND="$(find "$WORK_DIR" -path '*/src/index.js' -not -path '*/node_modules/*' -print -quit 2>/dev/null)"
    [ -n "$FOUND" ] && ENTRY="$FOUND"
fi
ENTRY_DIR="$(dirname "$ENTRY")"
echo "stylesheet-tree entry: $ENTRY"

# 3. Expose the built library to the hidden drivers under its aliased package name. The drivers do
#    `import ... from 'stylesheet-tree'`; a tests-local node_modules symlink resolves that bare
#    specifier to the freshly built entry directory. (The library's OWN deps resolve separately via
#    the ./node_modules that setup.sh linked into the project dir.)
mkdir -p "$TESTS_DIR/node_modules"
ln -sfn "$ENTRY_DIR" "$TESTS_DIR/node_modules/stylesheet-tree"

# 4. Run the tests offline, emitting CTRF directly.
echo "=== run drivers ==="
( cd "$TESTS_DIR" && CTRF_DIR=/logs/verifier node "$TESTS_DIR/run.mjs" )
echo "runner exit: $?"

# 5. Fallback: if the runner never produced a CTRF file, write a schema-valid zero-result CTRF so
#    the grader scores the attempt 0 rather than erroring.
if [ ! -f /logs/verifier/ctrf.json ]; then
    echo "=== no ctrf.json produced — writing zero-result fallback ==="
    node -e 'const fs=require("fs");const now=Date.now();fs.writeFileSync("/logs/verifier/ctrf.json",JSON.stringify({results:{tool:{name:"stylesheet-tree-runner"},summary:{tests:0,passed:0,failed:0,pending:0,skipped:0,other:0,start:now,stop:now},tests:[]}}))'
fi

# 6. reward.txt — the authoritative score. 1 IFF the task is fully solved: every one of the
#    CANONICAL_TOTAL declared cases passed, with no failures, no skips, no "other". Anything else
#    (partial pass, crash, missing/zero CTRF, skipped case) is 0.
CANONICAL_TOTAL=86 node -e '
try {
  const total = Number(process.env.CANONICAL_TOTAL);
  const s = require("/logs/verifier/ctrf.json").results.summary;
  const ok = Number(s.passed) === total
    && Number(s.failed || 0) === 0
    && Number(s.other || 0) === 0
    && Number(s.skipped || 0) === 0
    && Number(s.pending || 0) === 0;
  require("fs").writeFileSync("/logs/verifier/reward.txt", ok ? "1" : "0");
} catch (e) { require("fs").writeFileSync("/logs/verifier/reward.txt", "0"); }
'
echo "=== reward.txt: $(cat /logs/verifier/reward.txt 2>/dev/null) ==="
