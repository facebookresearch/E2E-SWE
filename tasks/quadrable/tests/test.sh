#!/bin/bash
# WRG verifier driver for the quadrable gtest-pattern task. Runs OFFLINE
# (allow_internet = false) on the per-task quadrable image (FROM the shared
# C++ base + apt-installed liblmdb-dev + libb2-dev). That base already ships
# gcc + cmake + build-essential + gtest v1.15.2 (headers + .so + .a), so this
# driver does ZERO installs at grade time. The two Python converters
# (junit_to_ctrf.py, coverage_summarize.py) live in tests/ alongside this
# script and get uploaded into /tests/ by the grader.
#
# Modular pipeline (nine per-module test binaries: basic_kv / keys / heads /
# proofs / iterator / sync / memstore / transport / gc_and_diff):
#   1. source ./setup.sh to install the agent's quadrable headers.
#   2. Compile all 9 modules IN PARALLEL against the agent's headers.
#      Each module produces its own instrumented binary and its own
#      per-module CTRF file. A per-module compile failure only sinks THAT
#      module -- other modules that compiled contribute their passing tests
#      to the aggregate reward.
#   3. For each module that compiled: run the binary, emit JUnit XML,
#      translate to per-module CTRF. For each module that failed to
#      compile: write a fallback CTRF with the first ~2 KB of g++ stderr
#      embedded in the message field.
#   4. Merge all 9 per-module CTRFs into a single /logs/verifier/ctrf.json
#      (concatenate .results.tests, sum .results.summary counts).
#   5. Run gcov over the shared build dir (any module that compiled
#      contributes coverage) and summarize with coverage_summarize.py.
#   6. Final reward = 1 iff all 30 declared tests passed (no failed/other/
#      skipped), else 0.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# Install the agent's quadrable headers onto the system include path.
bash ./setup.sh
# `source` doesn't isolate shell options -- if the agent's setup.sh set -e,
# it propagates into this script. Reset so a per-module compile failure
# doesn't kill the whole run before we get a chance to emit its fallback CTRF.
set +e

# All build artifacts land here so gcov + coverage aggregation can find them.
COV_DIR=/tmp/cov_build
rm -rf "$COV_DIR"
mkdir -p "$COV_DIR"

MODULES=(basic_kv keys heads proofs iterator sync memstore transport gc_and_diff)

# ---- Step 1: compile every module IN PARALLEL. ----
# Link order: -llmdb + -lb2 (system C libs from liblmdb-dev + libb2-dev in the
# per-task image) then gtest + pthread. -O0 -g --coverage: gcov instrumentation
# for the header-coverage report. Include path: only /usr/local/include (agent's
# setup.sh puts quadrable.h + quadrable/ + lmdbxx/lmdb++.h + hoytech/hex.h
# there) + /usr/include (system libb2 + libmdb) -- no -I flags on the g++ line.
declare -A COMPILE_PIDS
for m in "${MODULES[@]}"; do
    (
        g++ -std=c++17 -O0 -g --coverage \
            "/tests/test_${m}.cpp" \
            -llmdb -lb2 \
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
        ERR_JSON=$(head -c 2048 "/tmp/compile_${m}_stderr.log" \
            | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.buffer.read().decode("utf-8", "replace")))')
        printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":0,"passed":0,"failed":0,"other":1},"tests":[{"name":"<compile:%s>","status":"failed","message":%s}]}}\n' \
            "$m" "$ERR_JSON" > "$MOD_CTRF"
    fi
done

# ---- Step 3: merge all per-module CTRFs into one aggregated CTRF. ----
python3 - <<'PYEOF' > /logs/verifier/ctrf.json
import json, sys
modules = ['basic_kv', 'keys', 'heads', 'proofs', 'iterator', 'sync', 'memstore', 'transport', 'gc_and_diff']
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
# .gcno lookup issue. Do NOT pass -r/--relative-only -- it silently drops
# absolute-path sources (our case: sources under /tests, headers under
# /usr/local/include).
( cd "$COV_DIR" && gcov *.gcda >/tmp/gcov.log 2>&1 ) || true

# Header allowlist: every public + impl header quadrable ships. gcov filters
# out gtest, libc++, and system headers automatically via the basename match.
python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_DIR" \
    --out /logs/verifier/coverage.json \
    --header quadrable.h \
    --header Quadrable.h \
    --header Key.h \
    --header structsPublic.h \
    --header transport.h \
    --header utils.h \
    --header varint.h \
    --header debug.h \
    --header BuiltNode.h \
    --header diff.h \
    --header gc.h \
    --header get.h \
    --header heads.h \
    --header internal.h \
    --header Iterator.h \
    --header leafKeys.h \
    --header MemStore.h \
    --header ParsedNode.h \
    --header proof.h \
    --header stats.h \
    --header sync.h \
    --header update.h \
    --header walk.h \
  || echo "coverage_summarize failed (non-fatal)"

echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="

# ---- Step 5: binary reward -- 1 iff every declared test ran and passed. ----
python3 - <<'PYEOF' > /logs/verifier/reward.txt
import json
CANONICAL_TOTAL = 30
try:
    with open('/logs/verifier/ctrf.json') as f:
        c = json.load(f)
    s = c['results']['summary']
except Exception:
    s = {}
passed = s.get('passed', 0)
failed = s.get('failed', 0)
other = s.get('other', 0)
skipped = s.get('skipped', 0)
ok = (passed == CANONICAL_TOTAL and failed == 0 and other == 0 and skipped == 0)
print(1 if ok else 0)
PYEOF
