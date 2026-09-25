#!/bin/bash
# Offline grading driver for the mqttx_cli task. No `set -e` — we must always reach the CTRF summary
# so the grader gets a result even when the build or a test fails.
#
# Pipeline: locate the agent's project -> provide the baked node_modules (symlink) -> run the agent's
# setup.sh (tsc build) -> start the baked mosquitto broker -> run the hidden jest suite (which spawns
# the built CLI against 127.0.0.1 and/or imports built modules) -> jest-ctrf-json-reporter writes
# /logs/verifier/ctrf.json (native CTRF). Everything runs with NO network; Node 20, mosquitto, and a
# self-contained node_modules (CLI deps + jest + ts-jest + CTRF reporter) are pre-baked in the image.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

HARNESS_MODULES="${HARNESS_MODULES:-/opt/node_modules}"
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(pwd)"
mkdir -p /logs/verifier /opt/harness

# 1. Locate the project (dir containing setup.sh) — the working dir or a single nested project dir.
if [ -f "$WORK_DIR/setup.sh" ]; then
    PROJ="$WORK_DIR"
else
    SP="$(find "$WORK_DIR" -maxdepth 3 -name setup.sh -print -quit 2>/dev/null)"
    PROJ="$([ -n "$SP" ] && dirname "$SP" || echo "$WORK_DIR")"
fi
echo "project dir: $PROJ"

# 2. Provide the baked dependencies (offline). Symlink unless the agent already has node_modules.
if [ ! -e "$PROJ/node_modules" ]; then
    ln -sfn "$HARNESS_MODULES" "$PROJ/node_modules"
fi

# 3. Build the project (the agent's setup.sh: tsc -> dist/).
echo "=== setup.sh (build) ==="
( cd "$PROJ" && bash ./setup.sh )
echo "setup.sh exit: $?"

# 4. Locate the built CLI entry point (contract: bin/index.js at the project root).
CLI="$PROJ/bin/index.js"
if [ ! -f "$CLI" ]; then
    FOUND="$(find "$PROJ" -path '*/bin/index.js' -not -path '*/node_modules/*' -print -quit 2>/dev/null)"
    [ -n "$FOUND" ] && CLI="$FOUND"
fi
export MQTTX_CLI="$CLI"
echo "CLI entry: $MQTTX_CLI"

# 5. Start the baked MQTT broker (offline). Deterministically (re)start OUR broker with OUR config —
#    don't trust a pre-existing mosquitto. TCP on 127.0.0.1:1883 and WebSocket on 127.0.0.1:8083.
printf 'listener 1883 127.0.0.1\nallow_anonymous true\nlistener 8083 127.0.0.1\nprotocol websockets\nallow_anonymous true\n' > /tmp/mosquitto.conf
pkill -x mosquitto >/dev/null 2>&1
sleep 1
/usr/sbin/mosquitto -c /tmp/mosquitto.conf -d
sleep 2
echo "mosquitto running: $(pgrep -xc mosquitto)"
#    Probe BOTH listeners so a broker that never came up (or came up without websockets) is visible
#    here instead of surfacing only as one mystery test timeout.
node -e 'const net=require("net");for(const p of [1883,8083]){const s=net.connect(p,"127.0.0.1");s.setTimeout(3000);s.on("connect",()=>{console.log("listener "+p+": OK");s.destroy()});s.on("timeout",()=>{console.log("listener "+p+": TIMEOUT");s.destroy()});s.on("error",(e)=>console.log("listener "+p+": "+e.code))}'

# 6. Write the jest config plus a HARNESS-OWNED tsconfig for the hidden tests. ts-jest is pointed at
#    that tsconfig by PATH, not by an inline options object: given an object ts-jest still discovers
#    the nearest tsconfig.json above rootDir — the project's own — so a single compiler option that
#    tree's TypeScript does not accept aborts every hidden suite (0 tests collected) instead of
#    failing tests individually. rootDir stays the project so ts-jest / the CTRF reporter resolve
#    from its node_modules; roots = the hidden tests dir, which spawns the CLI via $MQTTX_CLI.
cat > /opt/harness/tsconfig.harness.json <<'TSCFG'
{
  "compilerOptions": {
    "esModuleInterop": true,
    "target": "es2019",
    "module": "commonjs",
    "skipLibCheck": true,
    "types": ["node", "jest"]
  }
}
TSCFG
cat > /opt/harness/jest.config.js <<CFG
module.exports = {
  testEnvironment: 'node',
  rootDir: '$PROJ',
  roots: ['$TESTS_DIR'],
  testMatch: ['**/*.test.ts'],
  testTimeout: 30000,
  transform: {
    '^.+\\\\.ts\$': ['ts-jest', { isolatedModules: true, tsconfig: '/opt/harness/tsconfig.harness.json' }]
  },
  reporters: ['default', ['jest-ctrf-json-reporter', { outputDir: '/logs/verifier', outputFile: 'ctrf.json' }]]
}
CFG

# 7. Run the hidden jest suite offline. Flags:
#    --runInBand: run tests serially in one process. The suite is timing-sensitive (spawns CLI
#      subprocesses that pub/sub against a single broker on a 1-CPU container); parallel workers
#      contend for CPU/broker and cause spurious timeouts. Serial execution is deterministic.
#    --forceExit: the tests spawn CLI subprocesses that hold open MQTT connections; force jest to exit
#      once tests finish rather than hang on live handles.
echo "=== run jest ==="
( cd "$PROJ" && ./node_modules/.bin/jest -c /opt/harness/jest.config.js --ci --runInBand --forceExit ) \
    > /logs/verifier/jest.log 2>&1
echo "jest exit: $?"
tail -n 150 /logs/verifier/jest.log

# 8. Fallback + collection guard. Write a diagnostic CTRF if jest produced no report at all (e.g. the
#    build failed), or produced one reporting ZERO collected tests — the signature of every suite
#    failing to LOAD, which must never be scored as a silent, undiagnosable 0.
node -e '
const fs = require("fs");
const p = "/logs/verifier/ctrf.json";
let tests = null;
try { tests = require(p).results.summary.tests; } catch (e) {}
if (typeof tests === "number" && tests > 0) process.exit(0);
const why = tests === null ? "jest produced no CTRF report" : "jest ran but collected 0 tests (every suite failed to load)";
let log = "";
try { log = fs.readFileSync("/logs/verifier/jest.log", "utf8").slice(-4000); } catch (e) {}
const t = Date.now();
fs.mkdirSync("/logs/verifier", { recursive: true });
fs.writeFileSync(p, JSON.stringify({ results: { tool: { name: "jest" },
  summary: { tests: 1, passed: 0, failed: 1, pending: 0, skipped: 0, other: 0, start: t, stop: t },
  tests: [{ name: "HARNESS ERROR: " + why, status: "failed", duration: 0, message: why, trace: log }] } }));
console.log("=== harness error: " + why + " ===");
console.log(log);
'

# 9. reward.txt — binary gate derived from ctrf.json. 1 IFF every declared test ran and passed:
#    passed == TOTAL (task.toml [verifier].test_case_count) and no failed / other / skipped / pending.
node -e '
const TOTAL = 60;
try {
  const s = require("/logs/verifier/ctrf.json").results.summary;
  const ok = s.passed === TOTAL
    && (s.failed || 0) === 0
    && (s.other || 0) === 0
    && (s.skipped || 0) === 0
    && (s.pending || 0) === 0;
  require("fs").writeFileSync("/logs/verifier/reward.txt", ok ? "1" : "0");
} catch (e) { require("fs").writeFileSync("/logs/verifier/reward.txt", "0"); }
'
echo "=== reward.txt: $(cat /logs/verifier/reward.txt 2>/dev/null) ==="
