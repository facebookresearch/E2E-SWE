#!/bin/bash
# Offline grading driver for the polygon-clipping task. No `set -e` — we must always reach the CTRF
# summary so the grader gets a result even when the build or a test fails.
#
# Pipeline: build the project (the agent's setup.sh, which transpiles the ES-module src/ -> CommonJS
# build/ with tsc --allowJs) -> run the hidden Jest tests from the baked harness at /opt/harness,
# importing the built library under its aliased name `planar-boolean` (mapped to the built CommonJS
# entry) -> the
# native CTRF reporter writes /logs/verifier/ctrf.json directly. Everything runs with NO network;
# Node, a pinned tsc, the two runtime deps (splaytree + robust-predicates at /opt/libs), and the
# Jest harness (+ babel transform + CTRF reporter) are pre-baked in the per-task image.
#
# robust-predicates ships as an ES module; jest's CommonJS runtime cannot parse it natively, so
# babel-jest transpiles it on the fly (transformIgnorePatterns whitelists it). splaytree provides a
# CommonJS entry and is required directly. The baked deps live at /opt/libs/node_modules and are
# reached via jest's modulePaths / moduleDirectories.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

HARNESS_DIR="${HARNESS_DIR:-/opt/harness}"
LIBS_DIR="${LIBS_DIR:-/opt/libs/node_modules}"
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

# 2. Locate the built CommonJS entry point (wherever setup.sh placed it). The contract is
#    build/index.js at the project root, but we search defensively so a project nested one level
#    deep, or a differently-named outDir that still yields an index.js, is still found.
ENTRY="$BUILD_DIR/build/index.js"
if [ ! -f "$ENTRY" ]; then
    FOUND="$(find "$WORK_DIR" -path '*/build/index.js' -not -path '*/node_modules/*' -print -quit 2>/dev/null)"
    [ -n "$FOUND" ] && ENTRY="$FOUND"
fi
echo "polygon-clipping entry: $ENTRY"

# 3. Resolve the CTRF reporter and babel-jest transformer to absolute paths (jest resolves custom
#    reporters/transformers relative to rootDir, which is the tests dir, so bare module names would
#    not resolve).
REPORTER="$(cd "$HARNESS_DIR" && node -e 'process.stdout.write(require.resolve("jest-ctrf-json-reporter"))')"
BABELJEST="$(cd "$HARNESS_DIR" && node -e 'process.stdout.write(require.resolve("babel-jest"))')"
echo "ctrf reporter: $REPORTER"
echo "babel-jest: $BABELJEST"

# 4. Write the Jest config into the harness dir (so its reporter/env/transform peers resolve
#    locally). The hidden tests import the library under its aliased package name `planar-boolean`
#    (anti-contamination — the real npm package name is never shown to the agent); map that bare
#    specifier to the freshly built entry. The baked runtime deps are reached via
#    modulePaths/moduleDirectories, and the ES-module robust-predicates is transpiled by babel-jest.
cat > "$HARNESS_DIR/jest.config.js" <<CFG
module.exports = {
  rootDir: "$TESTS_DIR",
  roots: ["$TESTS_DIR"],
  testMatch: ["**/*.test.js"],
  moduleNameMapper: { "^planar-boolean\$": "$ENTRY" },
  modulePaths: ["$LIBS_DIR"],
  moduleDirectories: ["node_modules", "$LIBS_DIR"],
  transform: { "^.+\\\\.[cm]?js\$": ["$BABELJEST", { configFile: "$HARNESS_DIR/babel.config.js" }] },
  transformIgnorePatterns: ["/node_modules/(?!(robust-predicates)/)"],
  testEnvironment: "node",
  // Per-case wall-clock cap. Catches an agent implementation that hangs asynchronously (awaiting a
  // promise that never resolves, a runaway timer, etc.): Jest aborts just that case and marks it
  // failed, so the denominator stays fixed. A purely SYNCHRONOUS infinite loop blocks the event loop
  // and cannot be interrupted here — that case is instead bounded by the verifier's timeout_sec
  // (900s) and the zero-result CTRF fallback below, so the grader still scores the attempt 0 rather
  // than crashing. (The reference engine terminates on all inputs, so GT is unaffected.)
  testTimeout: 20000,
  reporters: [
    "default",
    ["$REPORTER", { outputDir: "/logs/verifier", outputFile: "ctrf.json" }],
  ],
};
CFG

# 5. Run the tests offline, emitting CTRF directly. --ci for stable output.
echo "=== run jest ==="
( cd "$HARNESS_DIR" && "$HARNESS_DIR/node_modules/.bin/jest" -c "$HARNESS_DIR/jest.config.js" --ci )
echo "jest exit: $?"

# 6. Fallback: if jest never produced a CTRF file (e.g. the build failed so no test could run),
#    write a schema-valid zero-passed CTRF so the grader scores the attempt 0 rather than erroring.
if [ ! -f /logs/verifier/ctrf.json ]; then
    echo "=== no ctrf.json produced — writing zero-result fallback ==="
    node -e 'const fs=require("fs");const now=Date.now();fs.writeFileSync("/logs/verifier/ctrf.json",JSON.stringify({results:{tool:{name:"jest"},summary:{tests:0,passed:0,failed:0,pending:0,skipped:0,other:0,start:now,stop:now},tests:[]}}))'
fi

# 7. reward.txt — binary all-or-nothing gate. 1 iff every one of the 130 declared cases actually ran
#    and passed; a skipped/pending case means a declared test never ran, so it scores 0.
CANONICAL_TOTAL=130 node -e '
try {
  const total = Number(process.env.CANONICAL_TOTAL);
  const s = require("/logs/verifier/ctrf.json").results.summary;
  const ok = s.passed === total && s.failed === 0 && (s.other||0) === 0 &&
             (s.skipped||0) === 0 && (s.pending||0) === 0;
  require("fs").writeFileSync("/logs/verifier/reward.txt", ok ? "1" : "0");
} catch (e) { require("fs").writeFileSync("/logs/verifier/reward.txt", "0"); }
'
echo "=== reward.txt: $(cat /logs/verifier/reward.txt 2>/dev/null) ==="
