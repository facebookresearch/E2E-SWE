#!/bin/bash
# Offline WRG grader for the bosphorus task.
#
# Runs the candidate's `setup.sh` to build & install /usr/local/bin/bosphorus +
# /usr/local/lib/libbosphorus.so + /usr/local/include/bosphorus/bosphorus.hpp,
# then invokes the pure-stdlib-python3 test driver at /tests/run_tests.py which
# exercises ~30 CLI + library-API cases against the installed binary/lib.
#
# The driver emits a CTRF JSON to /logs/verifier/ctrf.json regardless of
# individual test outcomes; reward is binary: 1 only if all declared tests pass.
# No `set -e`: a per-test failure must still let subsequent tests run and let
# the aggregate CTRF be written.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# Build & install the candidate's bosphorus. The agent's setup.sh may or may
# not `set -e` internally; we source it so any exported env vars (e.g.
# CMAKE_PREFIX_PATH tweaks) propagate to the pytest step, then reset our own
# shell's error mode so a per-test failure inside the python driver doesn't
# short-circuit the rest of the suite.
bash ./setup.sh 2>&1 | tail -40
set +e

# Safety-net for the CTRF path so a crash in setup or the driver still leaves
# a graded-zero record behind. Overwritten by the driver on success.
write_fail_ctrf() {
    local reason="$1"
    python3 -c "
import json, sys
report = {
    'reportFormat': 'CTRF',
    'specVersion': '0.0.0',
    'results': {
        'tool': {'name': 'bosphorus_pytest_lite'},
        'summary': {'tests': 1, 'passed': 0, 'failed': 1,
                    'pending': 0, 'skipped': 0, 'other': 0},
        'tests': [{'name': '<harness>', 'status': 'failed',
                   'message': sys.argv[1]}],
    },
}
print(json.dumps(report))
" "$reason" > /logs/verifier/ctrf.json
}

# Sanity check: the agent must have installed the CLI where we can find it.
if [ ! -x /usr/local/bin/bosphorus ]; then
    echo "[test.sh] /usr/local/bin/bosphorus not found after setup.sh"
    write_fail_ctrf "candidate setup.sh did not install /usr/local/bin/bosphorus"
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

# Ensure ldconfig picks up any shared libs the agent installed.
ldconfig 2>/dev/null || true

# Run the test suite. The driver writes /logs/verifier/ctrf.json itself and
# exits 0 (reward is derived from the CTRF summary counts, not the exit code).
CTRF_OUT=/logs/verifier/ctrf.json python3 /tests/run_tests.py
DRIVER_EXIT=$?

if [ ! -s /logs/verifier/ctrf.json ]; then
    echo "[test.sh] driver did not produce a CTRF (exit $DRIVER_EXIT)"
    write_fail_ctrf "run_tests.py did not emit a CTRF (exit $DRIVER_EXIT)"
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

# Compute the binary reward from the CTRF summary and write reward.txt.
# Reward is 1 if and only if the task is fully solved: every one of the
# CANONICAL_TOTAL declared tests ran and passed, with nothing failed, skipped,
# pending or otherwise unaccounted for. Anything else is 0 (never a fraction).
CANONICAL_TOTAL=33 python3 - <<'PYEOF' > /logs/verifier/reward.txt
import json, os
total_expected = int(os.environ['CANONICAL_TOTAL'])
try:
    with open('/logs/verifier/ctrf.json') as f:
        c = json.load(f)
    s = c['results']['summary']
except Exception:
    s = {}
passed = s.get('passed', 0)
solved = (
    passed == total_expected
    and s.get('failed', 0) == 0
    and s.get('other', 0) == 0
    and s.get('skipped', 0) == 0
    and s.get('pending', 0) == 0
)
print(1 if solved else 0)
PYEOF
