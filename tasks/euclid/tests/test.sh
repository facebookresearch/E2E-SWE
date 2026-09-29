#!/bin/bash
# Offline grading driver for the Euclid task.
#
# Invoked by the grader as `cd /app && bash /tests/test.sh`. There is NO network: the Swift toolchain
# and python3 are pre-baked in the per-task image.
#
# Robustness is critical here: a malformed agent package (e.g. a Package.swift whose test target has
# overlapping sources) or an agent setup.sh that runs `set -e` must NOT prevent a CTRF from being
# written — otherwise the grader reports "CTRF not found" (an infra error) instead of a fair score of
# 0. So we (a) run setup.sh in an isolated subshell, (b) put a timeout on `swift test` to contain
# hangs/infinite loops in the agent's CSG, and (c) ALWAYS write a CTRF, falling back to an empty one.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# 1. Build the agent's package (best effort, isolated so its shell options/errors can't abort us).
bash ./setup.sh > /tmp/setup.log 2>&1 || true

# 2. Run the hidden XCTest suite (path-depends on /app). `--parallel` is REQUIRED for SwiftPM to emit
#    the --xunit-output XML. `timeout` contains hanging agent implementations.
cd /tests
XUNIT=/tmp/xunit.xml
rm -f "$XUNIT"
timeout 1200 swift test --parallel --xunit-output "$XUNIT" 2>&1 | tail -80

# 3. Convert JUnit XML -> CTRF. The converter writes an empty (tests=0) report if the XML is missing
#    (e.g. the agent package failed to build), so a broken submission scores 0 rather than erroring.
mkdir -p /logs/verifier
python3 /tests/xunit_to_ctrf.py "$XUNIT" /logs/verifier/ctrf.json || true

# 4. Guarantee a CTRF exists no matter what, so the grader never reports "CTRF not found".
if [ ! -f /logs/verifier/ctrf.json ]; then
  echo '{"results":{"tool":{"name":"swift-test"},"summary":{"tests":0,"passed":0,"failed":0,"pending":0,"skipped":0,"other":0,"start":0,"stop":0},"tests":[]}}' > /logs/verifier/ctrf.json
fi

# 5. reward.txt (secondary; authoritative detail is in ctrf.json).
python3 - <<'PY' 2>/dev/null || echo 0 > /logs/verifier/reward.txt
import json

CANONICAL_TOTAL = 32  # must match [verifier].test_case_count in task.toml

s = json.load(open("/logs/verifier/ctrf.json"))["results"]["summary"]
solved = (
    s.get("passed", 0) == CANONICAL_TOTAL
    and s.get("failed", 0) == 0
    and s.get("other", 0) == 0
    and s.get("skipped", 0) == 0
)
open("/logs/verifier/reward.txt", "w").write("1" if solved else "0")
PY
