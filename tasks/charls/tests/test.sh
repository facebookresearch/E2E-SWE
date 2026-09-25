#!/bin/bash
# WRG verifier driver for the charls JPEG-LS gtest-pattern task (Tier 2 coverage).
# Runs OFFLINE (allow_internet = false) on the per-task charls image, which is
# built from a shared C++ base image. That base ships gcc + cmake + build-essential + gtest v1.15.2
# (headers + .so + .a), so this driver does ZERO installs at grade time. The two
# Python converters (junit_to_ctrf.py, coverage_summarize.py) live in tests/
# alongside this script and get uploaded into /tests/ by the grader. Fixture
# data (the tulips reference .jls file) lives under tests/data/ and lands at
# /tests/data/.
#
# Modular pipeline (fifteen per-module test binaries covering the full charls
# API surface):
#   1. source ./setup.sh to build+install the agent's libcharls.so (uninstrumented).
#   2. Compile all modules IN PARALLEL against the agent's headers + shared lib.
#      Each module produces its own binary and its own per-module CTRF file. A
#      per-module compile failure only sinks THAT module — other modules that
#      compiled contribute their passing tests to the aggregate reward.
#   3. For each module that compiled: run the binary (120s timeout to contain
#      agent-code infinite loops), emit JUnit XML, translate to per-module CTRF.
#      For each module that failed to compile: write a fallback CTRF with the
#      first ~2 KB of g++ stderr embedded in the message field.
#   4. Merge all per-module CTRFs into a single /logs/verifier/ctrf.json.
#   5. Binary reward: 1 iff passed == 60 (task.toml test_case_count) and
#      failed == other == skipped == 0; otherwise 0.
#
# Coverage pass (Tier 2 — measures line coverage of the agent's library):
#   6. Wipe the agent's install (/usr/local/{include,lib}) + cached /app/build.
#   7. Install gcc/g++ shims that append `--coverage -O0 -g` to every invocation
#      AND snapshot every .gcno the compiler emits to /tmp/gcno_safe/. The
#      snapshot is necessary because many agent setup.sh scripts wipe the build
#      dir before installing, which strands the .gcno files.
#   8. Re-run /app/setup.sh with CC=CXX=/usr/local/bin/g++ + CFLAGS/CXXFLAGS/
#      LDFLAGS carrying --coverage. This rebuilds libcharls.so INSTRUMENTED and
#      reinstalls the public headers to /usr/local/include/charls/.
#   9. Rebuild each per-module test binary with --coverage, run it under GCOV_
#      PREFIX so redirected .gcda land in /tmp/gcov_runtime/, emit XML (though
#      pass-rate already captured in step 4).
#  10. Restore snapshotted .gcno + relocate redirected .gcda back to their
#      original build paths so gcov can find matching pairs.
#  11. gcov every .gcda, aggregate .gcov files, summarize via coverage_summarize.py
#      against the upstream charls source-file allowlist. Non-fatal.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

set -u
mkdir -p /logs/verifier

# ---- Step 1: build + install the agent's libcharls.so. ----
bash ./setup.sh
# `source` doesn't isolate shell options -- if the agent's setup.sh set -e,
# it propagates into this script. Reset so a per-module compile failure
# doesn't kill the whole run before we get a chance to emit its fallback CTRF.
set +e

# All build artifacts land here so gcov can find them.
COV_DIR=/tmp/cov_build
rm -rf "$COV_DIR"
mkdir -p "$COV_DIR"

MODULES=(version error_codes encoder_setup encode_lossless encode_near_lossless
         encode_color_interleave encode_color_transform decode_reference spiff
         cpp_wrappers error_paths extra_segments wire_format byte_stuffing
         preset_params_lse)

# ---- Step 2: compile every module IN PARALLEL against the uninstrumented libcharls. ----
declare -A COMPILE_PIDS
for m in "${MODULES[@]}"; do
    (
        g++ -std=c++17 -O0 -g \
            "/tests/test_${m}.cpp" \
            -lcharls \
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

# ---- Step 3: run each module OR emit compile/timeout fallback CTRF. ----
# Per-module 120s cap contains agent-code infinite loops (e.g. an encoder that
# deadlocks on high-entropy input); killed runners emit a <timeout:MODULE> CTRF
# so the module registers as 1 failure rather than silently dropping.
for m in "${MODULES[@]}"; do
    MOD_CTRF="/tmp/ctrf_${m}.json"
    if [ "${COMPILE_EXITS[$m]}" -eq 0 ]; then
        MOD_JUNIT="/tmp/junit_${m}.xml"
        ( cd "$COV_DIR" && timeout --signal=KILL 120s "./test_${m}_runner" --gtest_output=xml:"$MOD_JUNIT" )
        RUNNER_EXIT=$?
        if [ "$RUNNER_EXIT" = "137" ] && [ ! -s "$MOD_JUNIT" ]; then
            printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":1,"passed":0,"failed":1,"other":0,"skipped":0,"pending":0},"tests":[{"name":"<timeout:%s>","status":"failed","message":"module test runner killed by 120s timeout"}]}}\n' \
                "$m" > "$MOD_CTRF"
        elif [ ! -s "$MOD_JUNIT" ]; then
            printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":1,"passed":0,"failed":1,"other":0,"skipped":0,"pending":0},"tests":[{"name":"<crash:%s>","status":"failed","message":"module runner exited rc=%d with no/empty junit XML (crashed/hung without gtest flush)"}]}}\n' \
                "$m" "$RUNNER_EXIT" > "$MOD_CTRF"
        else
            python3 /tests/junit_to_ctrf.py "$MOD_JUNIT" -o "$MOD_CTRF" \
                || echo "junit_to_ctrf failed for module ${m}"
        fi
    else
        ERR_JSON=$(head -c 2048 "/tmp/compile_${m}_stderr.log" \
            | python3 -c 'import sys, json; sys.stdout.write(json.dumps(sys.stdin.read()))')
        printf '{"results":{"tool":{"name":"gtest"},"summary":{"tests":0,"passed":0,"failed":0,"other":1},"tests":[{"name":"<compile:%s>","status":"failed","message":%s}]}}\n' \
            "$m" "$ERR_JSON" > "$MOD_CTRF"
    fi
done

# ---- Step 4: merge all per-module CTRFs into one aggregated CTRF. ----
python3 - <<'PYEOF' > /logs/verifier/ctrf.json
import json, sys, glob
merged_tests = []
tot = {'tests': 0, 'passed': 0, 'failed': 0, 'other': 0, 'skipped': 0, 'pending': 0}
for path in sorted(glob.glob('/tmp/ctrf_*.json')):
    with open(path) as f:
        c = json.load(f)
    s = c['results']['summary']
    for k in tot:
        tot[k] += s.get(k, 0)
    merged_tests.extend(c['results']['tests'])
out = {'results': {'tool': {'name': 'gtest'}, 'summary': tot, 'tests': merged_tests}}
json.dump(out, sys.stdout)
PYEOF

# ---- Step 5: binary all-or-nothing reward. ----
# reward is exactly 1 iff every declared test ran and passed:
#   passed == CANONICAL_TOTAL (task.toml [verifier].test_case_count) and
#   failed == 0 and other == 0 and skipped == 0.  Otherwise exactly 0.
CANONICAL_TOTAL=60 python3 - <<'PYEOF' > /logs/verifier/reward.txt
import json, os
canonical = int(os.environ['CANONICAL_TOTAL'])
try:
    with open('/logs/verifier/ctrf.json') as f:
        c = json.load(f)
    s = c['results']['summary']
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

# ============================================================
# COVERAGE PASS (Tier 2: grader-side library rebuild with --coverage).
# Non-fatal — preserves the pass-rate signal from above no matter what.
# ============================================================

# 6. Wipe agent's install + cached build dir. charls install footprint:
#    headers under /usr/local/include/charls/ + libcharls.{a,so*} under
#    /usr/local/lib/.
rm -rf /usr/local/include/charls
rm -f /usr/local/lib/libcharls.*
rm -rf /app/build /app/cmake_build

# 7. Install gcc + g++ shims that append --coverage -O0 -g to every invocation
#    AND snapshot every .gcno the compiler emits to /tmp/gcno_safe/<abs-path>.
GCNO_SAFE=/tmp/gcno_safe
mkdir -p "$GCNO_SAFE"

cat > /usr/local/bin/_cov_snapshot_gcno <<'SNAP_EOF'
#!/bin/bash
SAFE=/tmp/gcno_safe
mkdir -p "$SAFE"
snap_dir() {
  local d="$1"
  [ -d "$d" ] || return 0
  local abs
  abs=$(cd "$d" 2>/dev/null && pwd) || return 0
  for f in "$abs"/*.gcno; do
    [ -e "$f" ] || continue
    local rel="$abs/$(basename "$f")"
    local target="$SAFE$rel"
    mkdir -p "$(dirname "$target")"
    cp -uf "$f" "$target" 2>/dev/null
  done
}
snap_dir "."
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    snap_dir "$(dirname "$arg")"
  fi
  prev="$arg"
done
SNAP_EOF
chmod +x /usr/local/bin/_cov_snapshot_gcno

cat > /usr/local/bin/gcc <<'GCC_EOF'
#!/bin/bash
/usr/bin/gcc "$@" --coverage -O0 -g
rc=$?
/usr/local/bin/_cov_snapshot_gcno "$@"
exit $rc
GCC_EOF
chmod +x /usr/local/bin/gcc

cat > /usr/local/bin/g++ <<'GXX_EOF'
#!/bin/bash
/usr/bin/g++ "$@" --coverage -O0 -g
rc=$?
/usr/local/bin/_cov_snapshot_gcno "$@"
exit $rc
GXX_EOF
chmod +x /usr/local/bin/g++

# 8. Re-run the agent's setup.sh with CC/CXX pointing at the wrappers.
CC=/usr/local/bin/gcc CXX=/usr/local/bin/g++ \
CFLAGS="--coverage -O0 -g" CXXFLAGS="--coverage -O0 -g" \
LDFLAGS="--coverage" \
  bash /app/setup.sh

# 9. Rebuild each per-module test binary with --coverage and re-run.
GCOV_PREFIX=/tmp/gcov_runtime
mkdir -p "$GCOV_PREFIX"
for m in "${MODULES[@]}"; do
    /usr/local/bin/g++ -std=c++17 \
        "/tests/test_${m}.cpp" \
        -lcharls -lgtest -lgtest_main -lpthread \
        -o "$COV_DIR/test_${m}_cov" 2>/dev/null
    [ -x "$COV_DIR/test_${m}_cov" ] || continue
    ( cd "$COV_DIR" && GCOV_PREFIX="$GCOV_PREFIX" GCOV_PREFIX_STRIP=0 \
        timeout --signal=KILL 120s \
        "./test_${m}_cov" --gtest_output=xml:"/tmp/junit_cov_${m}.xml" ) || true
done

# 10. Restore snapshotted .gcno + relocate redirected .gcda back to their
#     original build paths so gcov can find matching (.gcno, .gcda) pairs.
SNAPSHOT_GCNO=$(find "$GCNO_SAFE" -name '*.gcno' 2>/dev/null)
if [ -n "$SNAPSHOT_GCNO" ]; then
  for s in $SNAPSHOT_GCNO; do
    orig="${s#$GCNO_SAFE}"
    orig_dir=$(dirname "$orig")
    mkdir -p "$orig_dir"
    cp -nf "$s" "$orig" 2>/dev/null
  done
fi
RELOCATED_GCDA=$(find "$GCOV_PREFIX" -name '*.gcda' 2>/dev/null)
if [ -n "$RELOCATED_GCDA" ]; then
  for g in $RELOCATED_GCDA; do
    orig="${g#$GCOV_PREFIX}"
    orig_dir=$(dirname "$orig")
    mkdir -p "$orig_dir"
    cp -f "$g" "$orig"
  done
fi

# 11. gcov everything, aggregate .gcov files, summarize.
COV_GCOV_DIR=/tmp/all_gcov
mkdir -p "$COV_GCOV_DIR"
: > /tmp/gcov.log
run_gcov_in_dir() {
  local gcda_path="$1"
  local gcda_dir
  gcda_dir=$(dirname "$gcda_path")
  local gcda_base
  gcda_base=$(basename "$gcda_path")
  ( cd "$gcda_dir" && gcov "$gcda_base" >> /tmp/gcov.log 2>&1 ) || true
  find "$gcda_dir" -maxdepth 1 -name '*.gcov' -exec mv -f {} "$COV_GCOV_DIR/" \; 2>/dev/null
}
for g in "$COV_DIR"/*.gcda; do
  [ -e "$g" ] || continue
  run_gcov_in_dir "$g"
done
LIB_GCDA=$(find /app -name '*.gcda' 2>/dev/null)
if [ -n "$LIB_GCDA" ]; then
  for g in $LIB_GCDA; do
    run_gcov_in_dir "$g"
  done
fi

# Target set matches upstream v2.4.4 src/ + selected internal .hpp files.
# Agents that follow upstream layout hit every target; agents that consolidate
# into a monolithic single-file impl (e.g. charls_impl.cpp) will show many
# targets_missing — that's expected and correctly reported.
python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_GCOV_DIR" \
    --out /logs/verifier/coverage.json \
    --source charls_jpegls_encoder.cpp \
    --source charls_jpegls_decoder.cpp \
    --source jpeg_stream_reader.cpp \
    --source jpeg_stream_writer.cpp \
    --source golomb_lut.cpp \
    --source quantization_lut.cpp \
    --source jpegls_error.cpp \
    --source make_scan_codec.cpp \
    --source validate_spiff_header.cpp \
    --source version.cpp \
    --source charls_jpegls_encoder.h \
    --source charls_jpegls_decoder.h \
    --source jpegls_error.h \
    --source scan_encoder_impl.hpp \
    --source scan_decoder_impl.hpp \
    --source regular_mode_context.hpp \
    --source run_mode_context.hpp \
    --source default_traits.hpp \
    --source lossless_traits.hpp \
    --source sample_traits.hpp \
    --source color_transform.hpp \
    --source jpegls_algorithm.hpp \
    --source copy_from_line_buffer.hpp \
    --source copy_to_line_buffer.hpp \
    --source coding_parameters.hpp \
    --source jpegls_preset_coding_parameters.hpp \
    --source golomb_lut.hpp \
    --source quantization_lut.hpp \
  || echo "coverage_summarize failed (non-fatal)"

echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || true
echo "=== end coverage.json ==="
