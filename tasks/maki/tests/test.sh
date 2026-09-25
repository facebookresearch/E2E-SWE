#!/bin/bash
# WRG verifier driver for the maki gtest-pattern task. Runs OFFLINE
# (allow_internet = false). Uses the C++ base image directly — it
# already ships gcc + gtest v1.15.2 — so this driver does ZERO installs at
# grade time. The two Python converters (junit_to_ctrf.py,
# coverage_summarize.py) live in tests/ alongside this script and get
# uploaded into /tests/ by the grader.
#
# Modular pipeline (per module: basic / transitions / composite /
# exceptions / advanced):
#   1. source ./setup.sh to install the agent's maki headers.
#   2. Compile all 5 modules IN PARALLEL against the agent's headers.
#      Each module produces its own instrumented binary and its own
#      per-module CTRF file. A per-module compile failure only sinks
#      THAT module — other modules that compiled contribute their
#      passing tests to the aggregate reward.
#   3. For each module that compiled: run the binary (bounded by `timeout`),
#      emit JUnit XML, translate to per-module CTRF. For each module that
#      failed to compile, crashed, or hung: write a fallback CTRF with the
#      last ~2 KB of its stderr embedded in the message field. Every module
#      therefore always produces an artifact for the merge in step 4.
#   4. Merge all 5 per-module CTRFs into a single /logs/verifier/ctrf.json
#      (concatenate .results.tests, sum .results.summary counts).
#   5. Run gcov over the shared build dir (any module that compiled
#      contributes coverage) and summarize with coverage_summarize.py.
#   6. Final reward is binary: 1 only if all declared tests pass, else 0.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# Install the agent's maki headers onto the system include path.
bash ./setup.sh
# `source` doesn't isolate shell options — if the agent's setup.sh set -e,
# it propagates into this script. Reset so a per-module compile failure
# doesn't kill the whole run before we get a chance to emit its fallback CTRF.
set +e

# All build artifacts land here so gcov + coverage aggregation can find them.
COV_DIR=/tmp/cov_build
rm -rf "$COV_DIR"
mkdir -p "$COV_DIR"

MODULES=(basic transitions composite exceptions rtc defer state_data state_activity event_set)

# ---- Step 1: compile every module IN PARALLEL. ----
declare -A COMPILE_PIDS
for m in "${MODULES[@]}"; do
    (
        g++ -std=c++17 -O0 -g --coverage \
            "/tests/test_${m}.cpp" \
            -lgtest -lgtest_main -lpthread \
            -o "$COV_DIR/test_${m}_runner" 2>"/tmp/compile_${m}_stderr.log"
    ) &
    COMPILE_PIDS[$m]=$!
done

declare -A COMPILE_EXITS
for m in "${MODULES[@]}"; do
    wait "${COMPILE_PIDS[$m]}"
    COMPILE_EXITS[$m]=$?
done

# ---- Step 2: for each module, run OR write compile-failure CTRF. ----
for m in "${MODULES[@]}"; do
    MOD_CTRF="/tmp/ctrf_${m}.json"
    if [ "${COMPILE_EXITS[$m]}" -eq 0 ]; then
        # Compiled OK: run the binary and translate JUnit XML to CTRF.
        MOD_JUNIT="/tmp/junit_${m}.xml"
        # gtest writes its JUnit XML only at process exit, so a crash or hang mid-test leaves no
        # XML at all. Bound the run and fall back to a synthetic CTRF so this module's failure
        # cannot starve the merge below of an artifact.
        ( cd "$COV_DIR" && timeout 120 "./test_${m}_runner" --gtest_output=xml:"$MOD_JUNIT" ) \
            >"/tmp/run_${m}.log" 2>&1
        RUN_RC=$?
        if [ ! -s "$MOD_JUNIT" ] || ! python3 /tests/junit_to_ctrf.py "$MOD_JUNIT" -o "$MOD_CTRF"; then
            RUN_ERR_JSON=$(tail -c 2048 "/tmp/run_${m}.log" \
                | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.buffer.read().decode("utf-8", "replace")))')
            printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":0,"passed":0,"failed":0,"other":1},"tests":[{"name":"<crash:%s exit=%s>","status":"failed","message":%s}]}}\n' \
                "$m" "$RUN_RC" "$RUN_ERR_JSON" > "$MOD_CTRF"
        fi
    else
        # Compile failed: embed the first ~2 KB of g++ stderr in the CTRF
        # message field, JSON-escaped via python3's json.dumps.
        # Decode with errors="replace": g++ emits multibyte ‘smart quotes’, and a 2 KB cut landing
        # mid-sequence would otherwise raise UnicodeDecodeError, leaving ERR_JSON empty and the
        # printf below emitting malformed JSON ("message":}) — the same empty-CTRF outcome.
        ERR_JSON=$(head -c 2048 "/tmp/compile_${m}_stderr.log" \
            | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.buffer.read().decode("utf-8", "replace")))')
        printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":0,"passed":0,"failed":0,"other":1},"tests":[{"name":"<compile:%s>","status":"failed","message":%s}]}}\n' \
            "$m" "$ERR_JSON" > "$MOD_CTRF"
    fi
done

# ---- Step 3: merge all per-module CTRFs into one aggregated CTRF. ----
python3 - <<'PYEOF' > /logs/verifier/ctrf.json
import json, sys
modules = ['basic', 'transitions', 'composite', 'exceptions', 'rtc', 'defer', 'state_data', 'state_activity', 'event_set']
merged_tests = []
tot = {'tests': 0, 'passed': 0, 'failed': 0, 'other': 0, 'skipped': 0, 'pending': 0}
for m in modules:
    # The stdout redirect on this heredoc truncates ctrf.json BEFORE this code runs, so an
    # unguarded read here turns one missing/corrupt module artifact into a 0-byte ctrf.json and
    # a no-grade for the whole task. Degrade to a failed entry instead.
    try:
        with open(f'/tmp/ctrf_{m}.json') as f:
            c = json.load(f)
    except Exception as e:
        c = {'results': {'summary': {'tests': 0, 'passed': 0, 'failed': 0, 'other': 1},
                         'tests': [{'name': f'<missing:{m}>', 'status': 'failed', 'message': str(e)}]}}
    s = c['results']['summary']
    for k in tot:
        tot[k] += s.get(k, 0)
    merged_tests.extend(c['results']['tests'])
out = {'results': {'tool': {'name': 'gtest'}, 'summary': tot, 'tests': merged_tests}}
json.dump(out, sys.stdout)
PYEOF

# ---- Step 4: coverage aggregation across every module that compiled. ----
# gcov writes .gcov files into the CURRENT WORKING DIRECTORY. Passing .gcda
# filenames directly (rather than sources) avoids the g++ binary-prefixed
# .gcno lookup issue. Do NOT pass -r/--relative-only — it silently drops
# absolute-path sources (our case: sources under /tests, headers under
# /usr/local/include).
( cd "$COV_DIR" && gcov *.gcda >/tmp/gcov.log 2>&1 ) || true

python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_DIR" \
    --out /logs/verifier/coverage.json \
    --header maki.hpp \
    --header action.hpp \
    --header context.hpp \
    --header event_set.hpp \
    --header events.hpp \
    --header fin.hpp \
    --header guard.hpp \
    --header ini.hpp \
    --header machine.hpp \
    --header machine_conf.hpp \
    --header null.hpp \
    --header state.hpp \
    --header state_mold.hpp \
    --header state_set.hpp \
    --header transition_table.hpp \
    --header undefined.hpp \
  || echo "coverage_summarize failed (non-fatal)"

echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="

# ---- Step 5: binary reward — 1 iff the task is fully solved. ----
# Fully solved means every declared test case ran and passed:
#   passed == CANONICAL_TOTAL and failed == 0 and other == 0 and skipped == 0.
# A skip counts as NOT solved (a declared test did not actually run).
CANONICAL_TOTAL=24 python3 - <<'PYEOF' > /logs/verifier/reward.txt
import json, os
total_expected = int(os.environ['CANONICAL_TOTAL'])
try:
    with open('/logs/verifier/ctrf.json') as f:
        s = json.load(f)['results']['summary']
except Exception:
    s = {}
ok = (
    s.get('passed', 0) == total_expected
    and s.get('failed', 0) == 0
    and s.get('other', 0) == 0
    and s.get('skipped', 0) == 0
)
print(1 if ok else 0)
PYEOF
