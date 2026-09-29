#!/bin/bash
# Offline grading for a Deno task. Deno + python3 are pre-baked in the per-task image and the module
# cache under $DENO_DIR is pre-populated at build time. NO network — no `deno cache` / curl here.
#
# No `set -e` — every stage must run so a CTRF report is always produced (a broken submission yields
# an all-fail report with the denominator preserved, i.e. reward 0, not a grader error).

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

# The image bakes the Deno module cache at /deno-dir, but `deno test` must WRITE compiled output
# (gen/, analysis caches) for the agent's own module — and the baked /deno-dir may be read-only /
# root-owned for the grading user. Copy it to a writable location and point DENO_DIR there so deno
# can compile the submission offline. (Cheap: ~9MB.)
export DENO_DIR=/tmp/deno-dir
cp -r /deno-dir /tmp/deno-dir 2>/dev/null || true
chmod -R u+rwX /tmp/deno-dir 2>/dev/null || true

# Run the agent's setup.sh (a no-op for this Deno module; it loads directly).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# Run the hidden Deno suite offline; emit JUnit XML. --cached-only forces offline (hard-fail if a dep
# is not already cached); --allow-import lets cached remote specifiers (jsr:@std/assert) resolve;
# --allow-read lets the engine read template/include files. --no-check grades RUNTIME behavior (a
# submission with minor TS type errors but correct behavior should not be zeroed).
# NO_COLOR=1 keeps ANSI escape codes out of the JUnit <failure> messages (raw ESC bytes are invalid
# XML tokens and would corrupt the report on any failing test).
NO_COLOR=1 deno test \
  --no-check --cached-only --allow-import --allow-read \
  --junit-path=/logs/verifier/vento_report.xml \
  /tests/vento.test.ts > /logs/verifier/deno_stdout.log 2>&1 || true

# Convert JUnit XML -> CTRF using the committed canonical name list as the fixed denominator (a case
# with no <testcase> -> failed, so a Deno crash scores 0 rather than shrinking the denominator).
python3 /tests/make_ctrf.py \
  /logs/verifier/vento_report.xml /logs/verifier/ctrf.json /tests/expected.txt \
  > /logs/verifier/ctrf.log 2>&1 || true

# Reward: all-or-nothing, derived from ctrf.json's summary. 1 iff every one of the
# CANONICAL_TOTAL declared cases passed (no failures, no skips, no "other"); otherwise 0.
# CANONICAL_TOTAL must match [verifier].test_case_count in task.toml (and the line count of
# /tests/expected.txt, which is the CTRF denominator).
CANONICAL_TOTAL=68
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os
total = int(os.environ['CANONICAL_TOTAL'])
s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
ok = (s.get('passed', 0) == total and s.get('failed', 0) == 0
      and s.get('other', 0) == 0 and s.get('skipped', 0) == 0
      and s.get('pending', 0) == 0)
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in 1) echo 1 > /logs/verifier/reward.txt ;; *) echo 0 > /logs/verifier/reward.txt ;; esac
