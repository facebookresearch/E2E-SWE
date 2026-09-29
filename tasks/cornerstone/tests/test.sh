#!/bin/bash
# WRG verifier driver for the cornerstone gtest-pattern task. Runs OFFLINE
# (allow_internet = false). The task base image already ships gcc, gtest and
# asio — so this driver does ZERO
# installs at grade time. The two Python converters (junit_to_ctrf.py,
# coverage_summarize.py) live in tests/ and are uploaded into /tests/.
#
# Modular pipeline (per module: buffer / serialization / log_store / utility /
# raft_cluster):
#   1. source ./setup.sh so the agent's libcornerstone.a + headers land under
#      /usr/local/lib and /usr/local/include/cornerstone/.
#   2. Compile all 5 modules IN PARALLEL against the agent's install. Each
#      module produces its own instrumented binary + its own per-module CTRF.
#      A per-module compile failure only sinks THAT module; other modules that
#      compiled contribute their passing tests to the aggregate reward.
#   3. For each module that compiled: run the binary, emit JUnit XML,
#      translate to per-module CTRF. For each module that failed to compile:
#      write a fallback CTRF with the first ~2 KB of g++ stderr embedded in
#      the message field.
#   4. Merge all 5 per-module CTRFs into a single /logs/verifier/ctrf.json
#      (concatenate .results.tests, sum .results.summary counts).
#   5. Run gcov over the shared build dir (any module that compiled contributes
#      coverage) and summarize with coverage_summarize.py.
#   6. Final reward is binary: 1 IFF passed == 34 (the canonical
#      [verifier].test_case_count) and failed == other == skipped == 0.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# Install the agent's cornerstone lib + headers onto the system paths.
bash ./setup.sh
# `source` doesn't isolate shell options — if the agent's setup.sh set -e,
# it propagates into this script. Reset so a per-module compile failure
# doesn't kill the whole run before we get a chance to emit its fallback CTRF.
set +e

# All build artifacts land here so gcov + coverage aggregation can find them.
COV_DIR=/tmp/cov_build
rm -rf "$COV_DIR"
mkdir -p "$COV_DIR"

MODULES=(buffer serialization log_store utility raft_cluster)

# ---- Step 1: compile every module IN PARALLEL. ----
declare -A COMPILE_PIDS
for m in "${MODULES[@]}"; do
    (
        # -rdynamic exports dynamic symbols so glibc backtrace_symbols_fd
        # shows readable function names for our SIGSEGV backtrace handler
        # in test_raft_cluster.cpp (needed to diagnose the install path
        # crash). Zero size/perf cost for the other test binaries.
        g++ -std=c++17 -O0 -g -rdynamic -fno-omit-frame-pointer --coverage \
            -DASIO_STANDALONE -DASIO_HAS_STD_CHRONO \
            "/tests/test_${m}.cpp" \
            -lcornerstone -lgtest -lgtest_main -lpthread \
            -o "$COV_DIR/test_${m}_runner" 2>"/tmp/compile_${m}_stderr.log"
    ) &
    COMPILE_PIDS[$m]=$!
done

declare -A COMPILE_EXITS
for m in "${MODULES[@]}"; do
    wait "${COMPILE_PIDS[$m]}"
    COMPILE_EXITS[$m]=$?
done

# raft_cluster tests are run one-per-subprocess so a segfault in any single
# test (e.g. install_snapshot flow tripping over cornerstone's internal state)
# only sinks THAT test — the other 5 still contribute their pass rate. Every
# other module runs as a single binary for speed.
RAFT_TESTS=(
    "RaftCluster.ElectsLeaderFromColdStart"
    "RaftCluster.CommitsClientRequestPayload"
    "RaftCluster.AddServerJoinsAndCatchesUp"
    "RaftCluster.RemoveServerLeavesClusterFunctional"
    "RaftCluster.SnapshotCreationFiresAtDistance"
    "RaftCluster.LateFollowerCatchesUpViaSnapshot"
    "RaftCluster.PrevotePreventsTermInflationOnPartition"
    "RaftCluster.LeaderFailoverElectsNewLeaderAndKeepsCommitting"
    "RaftCluster.ElectionSafetyAtMostOneLeaderPerTerm"
    "RaftCluster.LogMatchingAllNodesAgreeOnCommittedEntries"
    "RaftCluster.MinorityPartitionCannotCommit"
    "RaftCluster.LeaderStepsDownOnHigherTermSeen"
    "RaftCluster.LogDivergenceForcesFollowerTruncation"
    "RaftCluster.ElectionRestrictionStaleCandidateLoses"
)

# ---- Step 2: for each module, run OR write compile-failure CTRF. ----
for m in "${MODULES[@]}"; do
    MOD_CTRF="/tmp/ctrf_${m}.json"
    if [ "${COMPILE_EXITS[$m]}" -ne 0 ]; then
        # Compile failed: embed g++ stderr in the CTRF message field.
        ERR_JSON=$(head -c 2048 "/tmp/compile_${m}_stderr.log" \
            | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.read()))')
        printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":0,"passed":0,"failed":0,"other":1,"skipped":0,"pending":0},"tests":[{"name":"<compile:%s>","status":"failed","duration":0,"message":%s}]}}\n' \
            "$m" "$ERR_JSON" > "$MOD_CTRF"
        continue
    fi

    if [ "$m" = "raft_cluster" ]; then
        # Per-test isolation: run each test in its own subprocess so a
        # segfault only affects that one test's result.
        RAFT_MERGE_ARGS=()
        for tname in "${RAFT_TESTS[@]}"; do
            SAFE=$(echo "$tname" | tr '.' '_')
            SUB_XML="/tmp/junit_${SAFE}.xml"
            SUB_ERR="/tmp/run_${SAFE}_stderr.log"
            ( cd "$COV_DIR" && timeout 60s "./test_${m}_runner" \
                --gtest_filter="$tname" --gtest_output=xml:"$SUB_XML" ) \
                >/dev/null 2>"$SUB_ERR"
            SUB_RC=$?
            if [ ! -s "$SUB_XML" ]; then
                # Subprocess crashed before writing JUnit — synthesize a
                # failed <testsuite>/<testcase> XML that the merge below can
                # translate into a normal failed-test entry. Also print the
                # stderr tail to stdout so the grader captures it in
                # debug.log for post-mortem.
                echo "=== STDERR from ${tname} (crashed with exit ${SUB_RC}) ==="
                tail -c 4096 "$SUB_ERR" 2>/dev/null
                echo ""
                echo "=== END STDERR (${tname}) ==="
                # Built in python so the embedded stderr tail can never break
                # the document: raw crash output (SIGSEGV backtraces) carries
                # control bytes XML 1.0 forbids and invalid UTF-8, which
                # previously yielded an unparseable file.
                python3 - "$SUB_XML" "$SUB_ERR" "$tname" "$SUB_RC" <<'PYEOF'
import html, sys


def legal_in_xml(c):
    o = ord(c)
    return o in (0x09, 0x0A, 0x0D) or 0x20 <= o <= 0xD7FF or 0xE000 <= o <= 0xFFFD or o >= 0x10000


xml_path, err_path, tname, rc = sys.argv[1:5]
cls, _, nm = tname.partition('.')
try:
    with open(err_path, 'rb') as f:
        raw = f.read()[-512:]
except OSError:
    raw = b''
text = ''.join(c for c in raw.decode('utf-8', 'replace') if legal_in_xml(c))
with open(xml_path, 'w', encoding='utf-8') as f:
    f.write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<testsuites tests="1" failures="1" errors="0" name="AllTests">\n'
        f'<testsuite name="{html.escape(cls)}" tests="1" failures="1" errors="0">\n'
        f'<testcase name="{html.escape(nm)}" classname="{html.escape(cls)}">\n'
        f'<failure message="binary crashed with exit {html.escape(rc)}">'
        f'{html.escape(text)}</failure>\n'
        '</testcase>\n</testsuite>\n</testsuites>\n'
    )
PYEOF
            fi
            RAFT_MERGE_ARGS+=("${tname}=${SUB_XML}=${SUB_ERR}")
        done
        # Merge the per-test JUnit XMLs into this module's CTRF. Keyed by test
        # NAME (name=xml=stderr triples) so the module always contributes one
        # entry per name in RAFT_TESTS: an XML that is missing, truncated or
        # otherwise unparseable is scored as a failure instead of silently
        # vanishing and shrinking the denominator.
        python3 - "$MOD_CTRF" "${RAFT_MERGE_ARGS[@]}" <<'PYEOF'
import sys, json, xml.etree.ElementTree as ET
out_ctrf = sys.argv[1]
specs = [a.split('=', 2) for a in sys.argv[2:]]
tests = []
tot = {'tests': 0, 'passed': 0, 'failed': 0, 'other': 0, 'skipped': 0, 'pending': 0}
for tname, x, err_path in specs:
    try:
        root = ET.parse(x).getroot()
        suites = root.findall('testsuite') if root.tag == 'testsuites' else [root]
    except Exception:
        suites = []
    found = 0
    for suite in suites:
        for tc in suite.findall('testcase'):
            found += 1
            name = f"{tc.get('classname','')}.{tc.get('name','')}"
            failure = tc.find('failure')
            error = tc.find('error')
            skipped = tc.find('skipped')
            if failure is not None:
                status = 'failed'
                message = failure.get('message', '')
                trace = (failure.text or '').strip()
                tot['failed'] += 1
            elif error is not None:
                status = 'failed'
                message = error.get('message', '')
                trace = (error.text or '').strip()
                tot['failed'] += 1
            elif skipped is not None:
                status = 'skipped'
                message = skipped.get('message', '')
                trace = ''
                tot['skipped'] += 1
            else:
                status = 'passed'
                message = ''
                trace = ''
                tot['passed'] += 1
            entry = {'name': name, 'status': status, 'duration': 0}
            if message: entry['message'] = message
            if trace: entry['trace'] = trace
            tests.append(entry)
    if not found:
        # Fail closed: no readable result for a test that was launched.
        try:
            with open(err_path, 'rb') as f:
                trace = f.read()[-512:].decode('utf-8', 'replace').strip()
        except OSError:
            trace = ''
        entry = {'name': tname, 'status': 'failed', 'duration': 0,
                 'message': 'no readable JUnit result (XML missing or unparseable)'}
        if trace: entry['trace'] = trace
        tests.append(entry)
        tot['failed'] += 1
tot['tests'] = tot['passed'] + tot['failed'] + tot['skipped'] + tot['other']
ctrf = {'results': {'tool': {'name': 'gtest', 'version': ''}, 'summary': tot, 'tests': tests}}
with open(out_ctrf, 'w') as f:
    json.dump(ctrf, f, indent=2)
PYEOF
        continue
    fi

    # Non-raft module: single-binary run (fast).
    MOD_JUNIT="/tmp/junit_${m}.xml"
    ( cd "$COV_DIR" && timeout 120s "./test_${m}_runner" --gtest_output=xml:"$MOD_JUNIT" ) \
        2>"/tmp/run_${m}_stderr.log"
    RUN_EXIT=$?
    if [ -f "$MOD_JUNIT" ]; then
        python3 /tests/junit_to_ctrf.py "$MOD_JUNIT" -o "$MOD_CTRF" \
            || echo "junit_to_ctrf failed for module ${m}"
    else
        ERR_JSON=$(tail -c 2048 "/tmp/run_${m}_stderr.log" 2>/dev/null \
            | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.read()))')
        printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":1,"passed":0,"failed":1,"other":0,"skipped":0,"pending":0},"tests":[{"name":"<crash:%s>","status":"failed","duration":0,"message":"binary crashed with exit %d","trace":%s}]}}\n' \
            "$m" "$RUN_EXIT" "$ERR_JSON" > "$MOD_CTRF"
    fi
done

# ---- Step 3: merge all per-module CTRFs into one aggregated CTRF. ----
python3 - <<'PYEOF' > /logs/verifier/ctrf.json
import json, sys
modules = ['buffer', 'serialization', 'log_store', 'utility', 'raft_cluster']
merged_tests = []
tot = {'tests': 0, 'passed': 0, 'failed': 0, 'other': 0, 'skipped': 0, 'pending': 0}
for m in modules:
    with open(f'/tmp/ctrf_{m}.json') as f:
        c = json.load(f)
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

# Coverage measured on cornerstone's public headers (installed at
# /usr/local/include/cornerstone/*.hxx). The library's compiled sources
# (.cxx files) are inside libcornerstone.a — Tier-2 coverage would need a
# grader-side rebuild with --coverage; we skip that here since the header
# coverage already reflects test breadth across the public API.
python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_DIR" \
    --out /logs/verifier/coverage.json \
    --header buffer.hxx \
    --header cluster_config.hxx \
    --header srv_config.hxx \
    --header snapshot.hxx \
    --header snapshot_sync_req.hxx \
    --header log_entry.hxx \
    --header log_store.hxx \
    --header fs_log_store.hxx \
    --header ptr.hxx \
    --header strfmt.hxx \
    --header async.hxx \
    --header raft_server.hxx \
    --header raft_params.hxx \
    --header state_mgr.hxx \
    --header state_machine.hxx \
    --header msg_base.hxx \
    --header req_msg.hxx \
    --header resp_msg.hxx \
  || echo "coverage_summarize failed (non-fatal)"

echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="

# ---- Step 5: binary reward. 1 IFF every declared test ran and passed. ----
CANONICAL_TOTAL=34
python3 - "$CANONICAL_TOTAL" <<'PYEOF' > /logs/verifier/reward.txt
import json, sys
canonical = int(sys.argv[1])
try:
    with open('/logs/verifier/ctrf.json') as f:
        s = json.load(f)['results']['summary']
except Exception:
    s = {}
ok = (
    s.get('passed', 0) == canonical
    and s.get('failed', 0) == 0
    and s.get('other', 0) == 0
    and s.get('skipped', 0) == 0
)
print(1 if ok else 0)
PYEOF
