#!/bin/bash
# Offline grading for the whatwg-url task.
#
# The agent implements a WHATWG URL parser and a setup.sh that builds it into the executable
# /app/urlparse (URL on stdin, optional base as argv[1] -> JSON components + exit 0, or non-zero on
# parse failure). This script builds it, then runs every WPT url-test case through it and grades the
# result, emitting one CTRF entry per case. The harness is stdlib python3 only; each case runs the
# parser as a fresh subprocess so a crash/hang fails only that case.
#
# No `set -e`: every stage must run so a CTRF report is always produced (a broken submission yields
# an all-fail report with the denominator preserved, i.e. reward 0, rather than a grader error).

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

# 1. Build the agent's parser (offline) via the setup.sh it wrote (or solve.sh for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2. Run the WPT url-test conformance harness -> /logs/verifier/ctrf.json (813 entries).
python3 /tests/url_ctrf.py /tests/urltestdata.json "/app/urlparse" /logs/verifier/ctrf.json 15 \
    >/logs/verifier/harness.log 2>&1 || true

# 3. Reward: all-or-nothing, derived from ctrf.json's summary. 1 iff every one of the
#    CANONICAL_TOTAL declared cases ran and passed; anything else (missing report, a single
#    failure, a skip, an "other") is 0.
CANONICAL_TOTAL=813
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os
total = int(os.environ['CANONICAL_TOTAL'])
s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
ok = (int(s.get('passed', 0)) == total
      and int(s.get('failed', 0)) == 0
      and int(s.get('other', 0)) == 0
      and int(s.get('skipped', 0)) == 0
      and int(s.get('pending', 0)) == 0
      and int(s.get('tests', 0)) == total)
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
