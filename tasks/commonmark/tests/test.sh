#!/bin/bash
# Offline grading for the commonmark task.
#
# The core `org.mdcore` library (Markdown parser + AST + HTML/Markdown/text renderers) has ZERO
# external deps, so there is NO baked-jar classpath -- the agent's compiled classes in /app/out are
# the only classpath. The agent implements the library under /app/src and provides /app/setup.sh
# that compiles it into /app/out (and stages the HTML5 named-entity data table onto the classpath).
# This script builds the agent's code, then compiles + runs each Java test driver against it to
# produce per-test JSON, and converts that to CTRF. Uses only the JDK + python3 in the per-task
# image -- no pip, no network.
#
# No `set -e`: every stage must run so a CTRF report is always produced (a broken submission yields
# an all-fail report with the denominator preserved, i.e. reward 0, rather than a grader error).
#
# Independently-compiled per-capability drivers: a compile failure (one off-signature symbol) only
# zeroes its own small cluster instead of the whole suite.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier /tmp/h

# 1. Build the agent's library (offline) via the setup.sh it wrote (or solve.sh for GT).
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2-3. Compile + run each driver INDEPENDENTLY against the agent's classes (no external jars).
: > /logs/verifier/cm_results.jsonl
for DRIVER in \
    BlockHtmlHarness \
    EmphasisHarness \
    CodeHarness \
    ListQuoteHarness \
    LinkImageHarness \
    HtmlEntityHarness \
    HtmlOptionsHarness \
    AstHarness \
    SourceSpanHarness \
    MarkdownRenderHarness \
    TextRenderHarness \
    LinkRefDefHarness \
    SpecialInputHarness \
    RawHtmlHarness \
    ; do
    [ -f "/tests/$DRIVER.java" ] || continue
    rm -rf /tmp/h && mkdir -p /tmp/h
    if javac -cp "/app/out" -d /tmp/h /tests/Runner.java "/tests/$DRIVER.java" 2>"/logs/verifier/${DRIVER}_compile.log"; then
        EXPECTED_TSV=/tests/expected.tsv java -cp "/tmp/h:/app/out" "$DRIVER" \
            >> /logs/verifier/cm_results.jsonl 2>"/logs/verifier/${DRIVER}_run.log" || true
    fi
done

# 4. Convert results to CTRF (canonical case list = names in /tests/expected.tsv; missing -> failed).
python3 /tests/make_ctrf.py /logs/verifier/cm_results.jsonl /logs/verifier/ctrf.json /tests/expected.tsv \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: 1 IFF every canonical case passed (passed == 159, no failed/other/skipped), else 0.
CANONICAL_TOTAL=159
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os
try:
    s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    total = int(os.environ['CANONICAL_TOTAL'])
    ok = (int(s.get('passed', 0)) == total
          and int(s.get('failed', 0)) == 0
          and int(s.get('other', 0)) == 0
          and int(s.get('skipped', 0)) == 0
          and int(s.get('pending', 0)) == 0)
    print(1 if ok else 0)
except Exception:
    print(0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
