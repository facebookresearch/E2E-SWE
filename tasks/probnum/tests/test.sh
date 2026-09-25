#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — do not add
# apt-get / curl / download steps.
#
# Per-FILE isolation: each test file runs in its own process, hard-wrapped in `timeout`. This is
# deliberate. probnum is a numerics library, and a candidate implementation can make a single
# subsystem (e.g. the ODE solver) blow up memory or hang; in one shared pytest process that would
# OOM-kill / hang the whole run and zero all 68 tests. Running per file (fresh, low-baseline
# process) turns such a blow-up into a clean per-file failure while every other subsystem still
# scores. merge_ctrf.py then combines the per-file CTRF reports into the single report the grader
# reads, recording any crashed/timed-out file's tests as failed so the denominator stays at 68.
#
# Note: no `set -e` — we must run every file and the merge regardless of individual exit codes.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project (offline) from the setup.sh written by the agent (or solve.sh for GT).
bash ./setup.sh

# Keep BLAS single-threaded so memory/CPU stay bounded and reproducible.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1

PARTS=/logs/verifier/parts
rm -rf "$PARTS"; mkdir -p "$PARTS" /logs/verifier

FILES="test_randvars test_linops test_linalg test_functions test_randprocs test_diffeq test_filtsmooth test_filtsmooth_nonlinear test_quad"

# Canonical list of every collected test (so files that later crash still count toward the total).
python -m pytest /tests/ -p no:cacheprovider --collect-only -q 2>/dev/null \
    | grep '::' > /logs/verifier/collected.txt || true

# Run each file in its own process; hard-kill (SIGKILL) any file that exceeds the wall-clock cap.
for f in $FILES; do
    timeout --signal=SIGKILL 150 python -m pytest "/tests/$f.py" -p no:cacheprovider \
        --timeout=30 --timeout-method=signal --ctrf "$PARTS/$f.json" -q >/dev/null 2>&1 || true
done

# Merge per-file CTRF reports into the single report the grader reads.
python3 /tests/merge_ctrf.py "$PARTS" /logs/verifier/collected.txt /logs/verifier/ctrf.json

# Reward: all-or-nothing. 1 iff every one of the CANONICAL_TOTAL tests passed and nothing
# failed / errored / was skipped; 0 otherwise (including a missing or unreadable ctrf.json).
CANONICAL_TOTAL=80
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os
try:
    s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    total = int(os.environ['CANONICAL_TOTAL'])
    ok = (int(s.get('passed', 0)) == total
          and int(s.get('failed', 0)) == 0
          and int(s.get('other', 0)) == 0
          and int(s.get('skipped', 0)) == 0)
except Exception:
    ok = False
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
