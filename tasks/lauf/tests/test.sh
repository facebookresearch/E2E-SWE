#!/bin/bash
# WRG grading driver for the lauf task. Runs OFFLINE — every dep is baked in
# the per-task image (clang, cmake, ninja, libstdc++). The two arguments below
# are constant, only the group list changes when we add or remove a group.
#
# Pipeline:
#   1. source ./setup.sh — the agent's script builds lauf and installs headers
#      to /usr/local/include/lauf/ + static libs to /usr/local/lib/.
#   2. Compile every test group binary INDEPENDENTLY. A per-group compile
#      failure only sinks that group's tests — the rest still contribute.
#   3. Run each compiled binary; each writes a JSON array of its per-test
#      results to /tmp/frag_<group>.json. Runtime crashes are trapped by the
#      harness (each test forks) so we always get a CTRF entry.
#   4. Merge all per-group fragments into /logs/verifier/ctrf.json.
#   5. Binary reward (1 only if all declared tests pass), written to /logs/verifier/reward.txt.
#
# No `set -e` — we intentionally continue past per-group compile failures so
# other groups' passing tests still count.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier
CTRF=/logs/verifier/ctrf.json
REWARD=/logs/verifier/reward.txt

# The order below matches how groups are declared for readability only — the
# CTRF ordering is preserved but the grader averages, so order doesn't matter.
#
# The array is deliberately NOT named `GROUPS` — that is a bash built-in
# read-only-write variable holding the caller's supplementary group IDs, and
# assigning to it silently fails, leaving the loop iterating over "0". See
# `help bash-builtins` / bash(1) SHELL VARIABLES.
TEST_GROUPS=(
    asm_module
    asm_builder
    asm_inst
    asm_program
    reader_writer
    vm_execute
    vm_process
    runtime_memory
    runtime_alloc
    runtime_process
    frontend_text
    backend_dump
    backend_qbe
    lib_int
    lib_bits
    lib_memory
    lib_heap
    lib_fiber
    end_to_end
)

# The test_case_count in task.toml MUST equal the sum of test methods across
# groups (grader zeroes reward if the CTRF passed count does not meet that
# threshold on full pass). If you add or remove a test, update task.toml.

# Build a static list of the names each group is EXPECTED to emit, in the
# same order the harness registers them. This lets the compile-failure fallback
# emit a stable list of per-test "failed" entries instead of silently zeroing
# a whole group's slot count on a compile error.
declare -A GROUP_TESTS
GROUP_TESTS[asm_module]="test_module_create_and_query test_add_globals_permissions_and_layout test_add_functions_lookup_and_chunks test_layout_array_and_aggregate"
GROUP_TESTS[asm_builder]="test_build_simple_function test_build_string_literal_dedup test_build_branch_and_jump test_build_data_literal_dedup test_build_get_function_and_vstack_size test_entry_block_and_local_layout"
GROUP_TESTS[asm_inst]="test_inst_jump test_inst_pop_pick_roll test_inst_select test_inst_bytes_and_null test_inst_layout_push test_inst_condition_codes test_inst_call_indirect test_inst_panic_if test_inst_aggregate_member test_inst_array_element test_inst_value_stable_id test_inst_fiber_suspend_and_transfer"
GROUP_TESTS[asm_program]="test_create_program_from_function_and_chunk test_link_modules_and_resolve_extern test_link_modules_plural test_define_native_global_overlays"
GROUP_TESTS[reader_writer]="test_string_reader_reads_bytes test_string_writer_append_and_format test_file_reader_missing_returns_null test_file_writer_roundtrip test_stdout_writer_created"
GROUP_TESTS[vm_execute]="test_execute_oneshot_noop test_execute_oneshot_identity_2args test_execute_oneshot_returns_multiple_outputs test_execute_panic_handler_invoked test_vm_execute_non_oneshot_can_reexecute test_vm_user_data_roundtrip test_vm_allocator_swap test_vstack_grow_under_pressure test_pick_and_roll_execute"
GROUP_TESTS[vm_process]="test_start_process_resume_noop test_start_process_resume_with_input_output test_resume_until_completion_finishes"
GROUP_TESTS[runtime_memory]="test_static_const_allocation_readable test_static_mut_allocation_writable test_get_global_address_of_program_global"
GROUP_TESTS[runtime_alloc]="test_add_heap_allocation_and_get_metadata test_poison_unpoison_gates_access test_split_merge_roundtrip test_gc_frees_unreachable_bytes test_get_cstr_and_get_address test_reachability_and_leak_flags"
GROUP_TESTS[runtime_process]="test_get_vm_and_program_from_process test_native_function_panic_message test_iterate_fibers_includes_current test_runtime_call_from_native test_get_function_ptr_signature_check test_step_limit_enforced test_get_vm_user_data_and_vstack_bounds test_create_destroy_fiber_from_native"
GROUP_TESTS[frontend_text]="test_parse_and_execute_module test_parse_syntax_error_returns_null test_parse_recursive_fib_and_execute"
GROUP_TESTS[backend_dump]="test_dump_module_produces_output test_dump_chunk_produces_output"
GROUP_TESTS[backend_qbe]="test_qbe_default_options_expose_default_externs test_qbe_defined_function_name_appears test_qbe_undefined_function_is_not_emitted test_qbe_export_marker_for_exported_function test_qbe_function_signature_matches_output_count test_qbe_global_produces_data_section test_qbe_custom_extern_replaces_builtin_call"
GROUP_TESTS[lib_int]="test_uadd_wrap_bytecode test_sdiv_by_zero_panics test_scmp_less_than_via_cc test_smul_and_ssub_wrap test_sabs_and_uabs test_udiv_by_zero_panics test_umul_saturating_and_wrap test_srem_and_urem test_uadd_panic_overflow test_stou_and_utos_conversion"
GROUP_TESTS[lib_bits]="test_bits_and_or_xor test_bits_shl_ushr_sshr"
GROUP_TESTS[lib_memory]="test_memory_copy_between_locals test_memory_fill_and_cmp test_addr_add_offsets_within_allocation test_lib_memory_poison_and_unpoison"
GROUP_TESTS[lib_heap]="test_heap_alloc_returns_writable_address test_heap_alloc_free_roundtrip test_heap_alloc_array_writable test_heap_gc_returns_uint"
GROUP_TESTS[lib_fiber]="test_fiber_create_and_query_status test_fiber_resume_suspend_from_bytecode test_lib_fiber_current_returns_handle test_lib_fiber_done_after_completion test_lib_fiber_destroy_ready test_bytecode_fiber_suspend_and_resume"
GROUP_TESTS[end_to_end]="test_recursive_fib_builder test_iterative_sum_builder test_global_variable_read_write"

# Source the agent's setup.sh in the current shell so any environment / cwd
# adjustments take effect for the compile step below. `source` propagates the
# script's `set -e` if it uses one; explicitly clear it after.
if [ -f ./setup.sh ]; then
    bash ./setup.sh
fi
set +e

# Fallback CTRF emitter — used if we hit a truly unrecoverable pipeline error
# (e.g. every group's compile failed and we cannot produce even a fragment).
# The grader treats missing CTRF as a grading error rather than reward 0.
write_empty_all_failed_ctrf() {
    python3 - <<'PYEOF' > "$CTRF"
import json
groups = {
    "asm_module": ["test_module_create_and_query","test_add_globals_permissions_and_layout","test_add_functions_lookup_and_chunks","test_layout_array_and_aggregate"],
    "asm_builder": ["test_build_simple_function","test_build_string_literal_dedup","test_build_branch_and_jump","test_build_data_literal_dedup","test_build_get_function_and_vstack_size","test_entry_block_and_local_layout"],
    "asm_inst": ["test_inst_jump","test_inst_pop_pick_roll","test_inst_select","test_inst_bytes_and_null","test_inst_layout_push","test_inst_condition_codes","test_inst_call_indirect","test_inst_panic_if","test_inst_aggregate_member","test_inst_array_element","test_inst_value_stable_id","test_inst_fiber_suspend_and_transfer"],
    "asm_program": ["test_create_program_from_function_and_chunk","test_link_modules_and_resolve_extern","test_link_modules_plural","test_define_native_global_overlays"],
    "reader_writer": ["test_string_reader_reads_bytes","test_string_writer_append_and_format","test_file_reader_missing_returns_null","test_file_writer_roundtrip","test_stdout_writer_created"],
    "vm_execute": ["test_execute_oneshot_noop","test_execute_oneshot_identity_2args","test_execute_oneshot_returns_multiple_outputs","test_execute_panic_handler_invoked","test_vm_execute_non_oneshot_can_reexecute","test_vm_user_data_roundtrip","test_vm_allocator_swap","test_vstack_grow_under_pressure","test_pick_and_roll_execute"],
    "vm_process": ["test_start_process_resume_noop","test_start_process_resume_with_input_output","test_resume_until_completion_finishes"],
    "runtime_memory": ["test_static_const_allocation_readable","test_static_mut_allocation_writable","test_get_global_address_of_program_global"],
    "runtime_alloc": ["test_add_heap_allocation_and_get_metadata","test_poison_unpoison_gates_access","test_split_merge_roundtrip","test_gc_frees_unreachable_bytes","test_get_cstr_and_get_address","test_reachability_and_leak_flags"],
    "runtime_process": ["test_get_vm_and_program_from_process","test_native_function_panic_message","test_iterate_fibers_includes_current","test_runtime_call_from_native","test_get_function_ptr_signature_check","test_step_limit_enforced","test_get_vm_user_data_and_vstack_bounds","test_create_destroy_fiber_from_native"],
    "frontend_text": ["test_parse_and_execute_module","test_parse_syntax_error_returns_null","test_parse_recursive_fib_and_execute"],
    "backend_dump": ["test_dump_module_produces_output","test_dump_chunk_produces_output"],
    "backend_qbe": ["test_qbe_default_options_expose_default_externs","test_qbe_defined_function_name_appears","test_qbe_undefined_function_is_not_emitted","test_qbe_export_marker_for_exported_function","test_qbe_function_signature_matches_output_count","test_qbe_global_produces_data_section","test_qbe_custom_extern_replaces_builtin_call"],
    "lib_int": ["test_uadd_wrap_bytecode","test_sdiv_by_zero_panics","test_scmp_less_than_via_cc","test_smul_and_ssub_wrap","test_sabs_and_uabs","test_udiv_by_zero_panics","test_umul_saturating_and_wrap","test_srem_and_urem","test_uadd_panic_overflow","test_stou_and_utos_conversion"],
    "lib_bits": ["test_bits_and_or_xor","test_bits_shl_ushr_sshr"],
    "lib_memory": ["test_memory_copy_between_locals","test_memory_fill_and_cmp","test_addr_add_offsets_within_allocation","test_lib_memory_poison_and_unpoison"],
    "lib_heap": ["test_heap_alloc_returns_writable_address","test_heap_alloc_free_roundtrip","test_heap_alloc_array_writable","test_heap_gc_returns_uint"],
    "lib_fiber": ["test_fiber_create_and_query_status","test_fiber_resume_suspend_from_bytecode","test_lib_fiber_current_returns_handle","test_lib_fiber_done_after_completion","test_lib_fiber_destroy_ready","test_bytecode_fiber_suspend_and_resume"],
    "end_to_end": ["test_recursive_fib_builder","test_iterative_sum_builder","test_global_variable_read_write"],
}
tests = []
for g, names in groups.items():
    for n in names:
        tests.append({"name": f"{g}::{n}", "status": "failed", "duration": 0, "message": "test.sh could not run any group"})
n = len(tests)
out = {"results": {"tool": {"name": "lauf-tests"},
                   "summary": {"tests": n, "passed": 0, "failed": n, "skipped": 0, "pending": 0, "other": 0, "start": 0, "stop": 0},
                   "tests": tests}}
import json, sys
sys.stdout.write(json.dumps(out))
PYEOF
    echo 0 > "$REWARD"
}

# Emit a compile-failure fragment for one group. Records each expected test as
# failed with the same "compile failed" message and includes the first ~1 KB
# of stderr so the reader (report.txt / debug.log) can see the actual error.
emit_compile_failed_fragment() {
    local group="$1"
    local errlog="$2"
    local outpath="$3"
    local names="${GROUP_TESTS[$group]}"
    python3 - "$group" "$errlog" "$outpath" <<'PYEOF'
import json, sys, os
group, errlog, outpath = sys.argv[1], sys.argv[2], sys.argv[3]
names = os.environ.get("NAMES", "").split()
try:
    with open(errlog) as f:
        err = f.read(1024)
except Exception:
    err = ""
tests = []
for n in names:
    tests.append({"name": n, "status": "failed", "duration": 0,
                  "message": f"compile failed: {err}"[:900]})
with open(outpath, "w") as f:
    json.dump(tests, f)
PYEOF
    return 0
}

# All build artifacts land here so we can nuke them in one shot across groups.
BUILD_TMP=/tmp/lauf_test_build
rm -rf "$BUILD_TMP"
mkdir -p "$BUILD_TMP"

# Shared clang flags. -std=c99 + -Wno-* to tolerate the C API (config.h forces
# clang). Explicit -pthread for the fork-based harness and -lstdc++ / -lm since
# lauf's core is C++. --start-group / --end-group let the linker resolve cyclic
# refs between lauf's own archives and the lexy archives (either order works,
# but grouping avoids symbol-order surprises across compilers).
compile_group() {
    local group="$1"
    local src="/tests/test_${group}.c"
    local bin="${BUILD_TMP}/test_${group}"
    local errlog="/tmp/compile_${group}.err"
    if [ ! -f "$src" ]; then
        echo "compile_group: missing source $src"
        return 1
    fi

    # Gather every lauf and lexy static library the agent installed.
    local lauf_libs
    lauf_libs=$(ls /usr/local/lib/liblauf*.a 2>/dev/null)
    local lexy_libs
    lexy_libs=$(ls /usr/local/lib/liblexy*.a 2>/dev/null)

    if [ -z "$lauf_libs" ]; then
        echo "no liblauf*.a found under /usr/local/lib — did setup.sh install them?" > "$errlog"
        return 2
    fi

    # -D_GNU_SOURCE exposes MAP_ANONYMOUS / MAP_ANON in <sys/mman.h> under
    # -std=c99 (they're a GNU extension). tests/harness.h uses MAP_ANONYMOUS
    # for its fork+shared-memory per-test isolation.
    clang -std=c99 -D_GNU_SOURCE -O0 -g -Wno-implicit-function-declaration \
          -I/usr/local/include -I/tests \
          "$src" \
          -Wl,--start-group $lauf_libs $lexy_libs -Wl,--end-group \
          -lstdc++ -lm -lpthread \
          -o "$bin" 2> "$errlog"
    return $?
}

# --- Step 1: compile every group. Collect exit codes; do not run yet. ---
# Declare COMPILE_EXITS as an associative array (-A) so string group names are
# used as keys directly. Without -A, bash treats non-numeric subscripts as
# arithmetic expressions (evaluating "asm_module" to 0) and every group would
# overwrite index 0.
declare -A COMPILE_EXITS
for g in "${TEST_GROUPS[@]}"; do
    compile_group "$g"
    COMPILE_EXITS[$g]=$?
done

# --- Step 2: for each group, either run the binary or emit a compile-failed
#             fragment. Every group leaves a /tmp/frag_<g>.json when done. ---
#
# We wrap each group binary run in `timeout` so a stuck group cannot consume
# the entire test.sh budget. The per-test harness has its own per-test
# timeout; this outer cap is a defense-in-depth for the group binary itself
# (e.g. crashes in the harness setup that don't yield to the child watchdog).
for g in "${TEST_GROUPS[@]}"; do
    frag="/tmp/frag_${g}.json"
    if [ "${COMPILE_EXITS[$g]}" -eq 0 ]; then
        # bash -c wraps the binary so a SIGSEGV from lauf_run_group itself (as
        # opposed to a per-test child) is caught and the fragment is still
        # populated by whatever the group managed to emit before the crash.
        timeout --kill-after=10s 180s "${BUILD_TMP}/test_${g}" "$frag" 2> "/tmp/run_${g}.err" || {
            echo "group ${g}: binary exited non-zero ($?), see /tmp/run_${g}.err"
            head -20 "/tmp/run_${g}.err"
        }
        # If the binary crashed BEFORE writing any tests, the frag file is
        # missing or malformed. Fall back to an all-failed fragment so the
        # group still contributes stable slot counts to the aggregate CTRF.
        if [ ! -s "$frag" ]; then
            NAMES="${GROUP_TESTS[$g]}" emit_compile_failed_fragment "$g" "/tmp/run_${g}.err" "$frag"
        fi
    else
        echo "group ${g}: COMPILE FAILED"
        head -20 "/tmp/compile_${g}.err"
        NAMES="${GROUP_TESTS[$g]}" emit_compile_failed_fragment "$g" "/tmp/compile_${g}.err" "$frag"
    fi
done

# --- Step 3: merge every group's fragment into one CTRF. ---
if ! python3 - <<'PYEOF' > "$CTRF"
import json, glob, sys, os
tests = []
for frag in sorted(glob.glob("/tmp/frag_*.json")):
    group = os.path.basename(frag)[len("frag_"):-len(".json")]
    try:
        with open(frag) as f:
            arr = json.load(f)
    except Exception as e:
        # Malformed fragment — skip it; the group is already accounted for by
        # the compile-failed fallback path above, so the count is stable.
        print(f"skip malformed frag {frag}: {e}", file=sys.stderr)
        continue
    for t in arr:
        # Prefix the group name so tests from different groups don't collide
        # on identically-named entries (e.g. two groups may each have a
        # "test_basic" name).
        t = dict(t)
        t["name"] = f"{group}::{t['name']}"
        tests.append(t)

p = sum(1 for t in tests if t.get("status") == "passed")
f = sum(1 for t in tests if t.get("status") == "failed")
s = sum(1 for t in tests if t.get("status") == "skipped")
o = sum(1 for t in tests if t.get("status") not in ("passed","failed","skipped"))
n = len(tests)

out = {"results": {"tool": {"name": "lauf-tests"},
                   "summary": {"tests": n, "passed": p, "failed": f, "skipped": s,
                               "pending": 0, "other": o, "start": 0, "stop": 0},
                   "tests": tests}}
sys.stdout.write(json.dumps(out))
PYEOF
then
    write_empty_all_failed_ctrf
fi

# Defensive: if the CTRF is missing/empty at this point, still emit reward 0
# rather than letting the grader see a grading error.
if [ ! -s "$CTRF" ]; then
    write_empty_all_failed_ctrf
fi

# --- Step 4: binary reward. 1 iff every declared test ran and passed. ---
# CANONICAL_TOTAL must match [verifier].test_case_count in task.toml (101) and
# the sum of GROUP_TESTS above. A skipped test means a declared test never ran,
# so it counts as NOT solved.
CANONICAL_TOTAL=101
python3 - "$CANONICAL_TOTAL" <<'PYEOF' > "$REWARD"
import json, sys
canonical = int(sys.argv[1])
try:
    with open("/logs/verifier/ctrf.json") as f:
        c = json.load(f)
    s = c["results"]["summary"]
    passed = s.get("passed", 0)
    failed = s.get("failed", 0)
    skipped = s.get("skipped", 0)
    other = s.get("other", 0)
    ok = (passed == canonical and failed == 0 and skipped == 0 and other == 0)
except Exception:
    ok = False
print(1 if ok else 0)
PYEOF

echo "=== ctrf summary ==="
python3 -c "import json; print(json.load(open('/logs/verifier/ctrf.json'))['results']['summary'])"
echo "=== reward ==="
cat "$REWARD"

# ============================================================
# TIER-2 COVERAGE PASS
# ============================================================
# Runs strictly AFTER the pass-rate collection above. Any failure here is
# non-fatal — /logs/verifier/ctrf.json + /logs/verifier/reward.txt are the
# grader's inputs, and both were already written by the code above. This
# pass writes /logs/verifier/coverage.json as an ADDITIONAL informational
# artifact, but the grader auto-uploads only ctrf.json + reward.txt, so we
# also cat coverage.json to stdout so it lands in debug.log for readers.
#
# Pipeline:
#   1. Wipe agent install (headers, static libs) + /app/build so the shim'd
#      setup.sh rebuilds from scratch.
#   2. Install /usr/local/bin/clang + /usr/local/bin/clang++ shims that
#      forward to /usr/bin/clang{,++} with `--coverage -O0 -g -DNDEBUG`
#      appended. -DNDEBUG matters: page_allocator.cpp / vm_execute.cpp fire
#      `assert()`s in unoptimized builds that abort() before .gcda flushes
#      to disk (feedback-wrg-cpp-tier2-ndebug).
#   3. The shims also snapshot every .gcno they observe alongside a -o
#      argument, so any later `rm -rf build` in setup.sh can't lose the
#      symbol tables gcov needs.
#   4. Re-run bash /app/setup.sh with CC/CXX/CFLAGS/CXXFLAGS/LDFLAGS
#      pointing at the shims. If this fails, skip the rest (non-fatal).
#   5. Rebuild the 19 test group binaries with the shim'd clang (adds
#      --coverage to the test-driver compile too, so header inline code
#      the drivers touch also gets counted).
#   6. Run each instrumented binary with GCOV_PREFIX pointing at a
#      deterministic dir; ignore exit codes (baseline reward is authoritative).
#   7. Restore snapshotted .gcno + relocate .gcda back to compile-time paths.
#   8. Run `gcov -p` per .gcda from its own directory (`-p` mangles output
#      names with the full source path, avoiding collision between
#      lib/memory.cpp and runtime/memory.cpp).
#   9. Feed all .gcov files to coverage_summarize.py, which reads gcov's
#      Source: header line to identify each file and filters by
#      path-suffix (lauf/lib/memory.cpp vs lauf/runtime/memory.cpp).
#  10. cat coverage.json so it lands in debug.log for offline audit.
#
# Both clang AND clang++ shims are installed because lauf's CMakeLists
# declares `project(lauf LANGUAGES C CXX)` — CMake probes both compilers on
# configure. A missing clang shim would make CMake fall back to
# /usr/bin/clang for the C probe, and any C source (config.h etc) would
# compile uninstrumented.

echo "=== Tier-2 coverage pass ==="

# Step 1: wipe agent install + cached build so shim'd setup.sh rebuilds fresh.
rm -rf /usr/local/include/lauf
rm -f /usr/local/lib/liblauf*.a
rm -f /usr/local/lib/liblexy*.a
rm -rf /app/build

# Step 2 + 3: install clang/clang++ shims + .gcno snapshotter.
GCNO_SAFE=/tmp/gcno_safe
mkdir -p "$GCNO_SAFE"

cat > /usr/local/bin/_cov_snapshot_gcno <<'SNAP_EOF'
#!/bin/bash
# Copy every .gcno the compiler just emitted to /tmp/gcno_safe/<abs-path>/
# so a later `rm -rf build` in setup.sh doesn't lose the coverage graph.
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

cat > /usr/local/bin/clang <<'CLANG_EOF'
#!/bin/bash
/usr/bin/clang "$@" --coverage -O0 -g -DNDEBUG
rc=$?
/usr/local/bin/_cov_snapshot_gcno "$@"
exit $rc
CLANG_EOF
chmod +x /usr/local/bin/clang

cat > /usr/local/bin/clang++ <<'CLANGXX_EOF'
#!/bin/bash
/usr/bin/clang++ "$@" --coverage -O0 -g -DNDEBUG
rc=$?
/usr/local/bin/_cov_snapshot_gcno "$@"
exit $rc
CLANGXX_EOF
chmod +x /usr/local/bin/clang++

# Force PATH so `clang` resolves to the shim even if the agent's setup.sh
# tried to sanitize its own PATH. /usr/local/bin is already first in Debian
# default PATH, but being explicit here avoids environment surprises.
export PATH=/usr/local/bin:$PATH

# Step 4: re-run agent setup.sh with shim compiler.
CC=/usr/local/bin/clang CXX=/usr/local/bin/clang++ \
CFLAGS="--coverage -O0 -g -DNDEBUG" \
CXXFLAGS="--coverage -O0 -g -DNDEBUG" \
LDFLAGS="--coverage" \
  bash /app/setup.sh
COV_SETUP_RC=$?
if [ $COV_SETUP_RC -ne 0 ]; then
    echo "[cov] instrumented setup.sh failed (rc=$COV_SETUP_RC) — skipping coverage summary"
    echo "=== end coverage pass (setup.sh failed) ==="
    exit 0
fi

# Step 5: rebuild the 19 test group binaries with the shim compiler.
# Uses the same clang line as the baseline compile_group, only with the
# shim intercepting the compile to add --coverage. Uses a separate build
# directory (/tmp/lauf_cov_build) so we don't stomp the baseline artifacts.
COV_BUILD=/tmp/lauf_cov_build
rm -rf "$COV_BUILD"
mkdir -p "$COV_BUILD"

echo "[cov] rebuilding 19 test group binaries with --coverage shim"
declare -A COV_COMPILE_RC
for g in "${TEST_GROUPS[@]}"; do
    src="/tests/test_${g}.c"
    bin="${COV_BUILD}/test_${g}"
    errlog="/tmp/cov_compile_${g}.err"
    if [ ! -f "$src" ]; then
        COV_COMPILE_RC[$g]=99
        continue
    fi
    cov_lauf_libs=$(ls /usr/local/lib/liblauf*.a 2>/dev/null)
    cov_lexy_libs=$(ls /usr/local/lib/liblexy*.a 2>/dev/null)
    if [ -z "$cov_lauf_libs" ]; then
        echo "[cov] no liblauf*.a found after instrumented setup — skipping group $g"
        COV_COMPILE_RC[$g]=98
        continue
    fi
    # -Wl,--export-dynamic: force libclang_rt.profile's __gcov_dump
    # (normally a static local T symbol) into the DYNAMIC symbol table so
    # the LD_PRELOAD hook below can dlsym(RTLD_DEFAULT, "__gcov_dump") and
    # actually flush counters before _exit in the fork-per-test harness.
    # Without this, dlsym returns NULL and every test-executed line
    # (which runs in a child that _exit()s) is dropped from .gcda.
    clang -std=c99 -D_GNU_SOURCE -O0 -g -Wno-implicit-function-declaration \
          -I/usr/local/include -I/tests \
          "$src" \
          -Wl,--start-group $cov_lauf_libs $cov_lexy_libs -Wl,--end-group \
          -lstdc++ -lm -lpthread \
          -Wl,--export-dynamic \
          -o "$bin" 2> "$errlog"
    COV_COMPILE_RC[$g]=$?
done

echo "[cov] compile summary:"
for g in "${TEST_GROUPS[@]}"; do
    rc="${COV_COMPILE_RC[$g]}"
    if [ "$rc" = "0" ]; then
        echo "  $g: OK"
    else
        echo "  $g: FAILED rc=$rc — first 10 lines of errlog:"
        head -10 "/tmp/cov_compile_${g}.err" 2>/dev/null | sed 's/^/    /'
    fi
done

# Step 6a: build an LD_PRELOAD hook that flushes gcov counters before
# `_exit()`. Every test in harness.h forks a child, runs one test, then
# calls `_exit(status)` for crash isolation. `_exit` bypasses atexit and
# libgcov's atexit-registered `__gcov_dump`, so without this hook the
# child-side counters (which is where all lib code actually runs) never
# flush and coverage.json reports ~0% on everything. The parent's atexit
# still fires, but the parent only runs the harness dispatch loop, not
# the lib functions the tests actually exercise.
cat > /tmp/cov_hook.c <<'HOOK_EOF'
/* LD_PRELOAD-loaded hook that flushes libgcov counters on _exit() /
 * _Exit(). harness.h forks per test and the child calls _exit() for
 * crash isolation; libgcov's atexit-registered dump handler never fires
 * on _exit(), so without this hook every child's counters are dropped
 * and the child-executed lib code shows as 0% covered. This hook
 * intercepts _exit / _Exit, calls __gcov_dump() to flush merged
 * counters, then chains to the real _exit / _Exit.
 *
 * __gcov_dump is resolved via dlsym(RTLD_DEFAULT, ...) rather than a
 * direct extern because libclang_rt.profile emits __gcov_dump as a
 * local T symbol; the test binary is rebuilt with `-Wl,--export-dynamic`
 * in test.sh to promote it into the dynamic symbol table so this dlsym
 * call succeeds. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stddef.h>

typedef void (*_exit_fn_t)(int);

static void _cov_dump(void)
{
    void (*dump)(void) = (void (*)(void))dlsym(RTLD_DEFAULT, "__gcov_dump");
    if (dump == NULL) {
        /* Legacy fallback for older libgcov naming. */
        dump = (void (*)(void))dlsym(RTLD_DEFAULT, "__gcov_flush");
    }
    if (dump != NULL) {
        dump();
    }
}

void _exit(int status)
{
    _cov_dump();
    static _exit_fn_t real__exit = NULL;
    if (real__exit == NULL) {
        real__exit = (_exit_fn_t)dlsym(RTLD_NEXT, "_exit");
    }
    real__exit(status);
    __builtin_unreachable();
}

/* Also hook _Exit (C11) which some glibc paths use as an alias. */
void _Exit(int status)
{
    _cov_dump();
    static _exit_fn_t real__Exit = NULL;
    if (real__Exit == NULL) {
        real__Exit = (_exit_fn_t)dlsym(RTLD_NEXT, "_Exit");
    }
    real__Exit(status);
    __builtin_unreachable();
}
HOOK_EOF
/usr/bin/clang -shared -fPIC -O0 -o /tmp/cov_hook.so /tmp/cov_hook.c -ldl 2>/tmp/cov_hook.build.err
COV_HOOK_RC=$?
if [ $COV_HOOK_RC -ne 0 ]; then
    echo "[cov] failed to build LD_PRELOAD hook (rc=$COV_HOOK_RC) — coverage will be zero for lib code"
    head -20 /tmp/cov_hook.build.err
fi

# Step 6b: run each instrumented binary under the LD_PRELOAD hook. .gcda
# emission is what drives coverage; the CTRF fragment written here (into
# /tmp/cov_frag_*) is thrown away — the pass-rate CTRF from the baseline
# pass is what counts.
GCOV_PREFIX=/tmp/gcov_runtime
mkdir -p "$GCOV_PREFIX"
echo "[cov] running instrumented binaries (GCOV_PREFIX=$GCOV_PREFIX, LD_PRELOAD=/tmp/cov_hook.so)"
declare -A COV_RUN_RC
for g in "${TEST_GROUPS[@]}"; do
    bin="${COV_BUILD}/test_${g}"
    if [ ! -x "$bin" ]; then
        COV_RUN_RC[$g]=97
        continue
    fi
    timeout --kill-after=10s 180s \
        env GCOV_PREFIX="$GCOV_PREFIX" GCOV_PREFIX_STRIP=0 \
            LD_PRELOAD=/tmp/cov_hook.so \
        "$bin" "/tmp/cov_frag_${g}.json" > /dev/null 2> "/tmp/cov_run_${g}.err"
    COV_RUN_RC[$g]=$?
done

echo "[cov] run summary (rc; 137=SIGKILL/timeout, 124=timeout-exit, 139=SIGSEGV, 97=missing bin):"
for g in "${TEST_GROUPS[@]}"; do
    echo "  $g: rc=${COV_RUN_RC[$g]}"
done

echo "[cov] .gcda inventory:"
echo "  under $COV_BUILD:"
find "$COV_BUILD" -name '*.gcda' -printf '    %p (%s bytes)\n' 2>/dev/null | head -30
echo "  under $GCOV_PREFIX:"
find "$GCOV_PREFIX" -name '*.gcda' -printf '    %p (%s bytes)\n' 2>/dev/null | head -30
echo "  under /app:"
find /app -name '*.gcda' -printf '    %p (%s bytes)\n' 2>/dev/null | head -30

# Step 7: restore snapshotted .gcno + relocate .gcda back to compile-time paths.
: > /tmp/gcov.log

SNAPSHOT_GCNO=$(find "$GCNO_SAFE" -name '*.gcno' 2>/dev/null)
if [ -n "$SNAPSHOT_GCNO" ]; then
    for s in $SNAPSHOT_GCNO; do
        orig="${s#$GCNO_SAFE}"
        orig_dir=$(dirname "$orig")
        mkdir -p "$orig_dir"
        cp -nf "$s" "$orig" 2>/dev/null
        echo "[cov] gcno snapshot $s -> $orig" >> /tmp/gcov.log
    done
fi

RELOCATED_GCDA=$(find "$GCOV_PREFIX" -name '*.gcda' 2>/dev/null)
if [ -n "$RELOCATED_GCDA" ]; then
    for d in $RELOCATED_GCDA; do
        orig="${d#$GCOV_PREFIX}"
        orig_dir=$(dirname "$orig")
        mkdir -p "$orig_dir"
        cp -f "$d" "$orig"
        echo "[cov] relocated $d -> $orig" >> /tmp/gcov.log
    done
fi

# Step 8: run gcov per-dir. `-p` mangles output filenames with the source
# path (so /app/src/lauf/lib/memory.cpp becomes
# #app#src#lauf#lib#memory.cpp.gcov), which avoids two `memory.cpp.gcov`
# files clobbering each other during the mv-to-aggregate-dir step.
COV_GCOV_DIR=/tmp/all_gcov
rm -rf "$COV_GCOV_DIR"
mkdir -p "$COV_GCOV_DIR"

run_gcov_in_dir() {
    local gcda_path="$1"
    local gcda_dir gcda_base
    gcda_dir=$(dirname "$gcda_path")
    gcda_base=$(basename "$gcda_path")
    echo "[cov] cd $gcda_dir && gcov -p $gcda_base" >> /tmp/gcov.log
    ( cd "$gcda_dir" && gcov -p "$gcda_base" >> /tmp/gcov.log 2>&1 ) || true
    find "$gcda_dir" -maxdepth 1 -name '*.gcov' -exec mv -f {} "$COV_GCOV_DIR/" \; 2>/dev/null
}

for d in $(find "$COV_BUILD" -name '*.gcda' 2>/dev/null); do
    run_gcov_in_dir "$d"
done
LIB_GCDA=$(find /app -name '*.gcda' 2>/dev/null)
if [ -n "$LIB_GCDA" ]; then
    for d in $LIB_GCDA; do
        run_gcov_in_dir "$d"
    done
fi

echo "[cov] .gcov files in $COV_GCOV_DIR (first 60):"
ls "$COV_GCOV_DIR" 2>/dev/null | head -60
echo "[cov] gcov.log (last 40 lines):"
tail -40 /tmp/gcov.log 2>/dev/null | sed 's/^/  /'

# Step 9: summarize into /logs/verifier/coverage.json. Path-qualify each
# source so lib/memory.cpp and runtime/memory.cpp are distinct targets.
# In-scope sources only (Phase-3 dropped runtime/stacktrace, lib/debug,
# lib/limits, lib/platform, lib/test from the task scope — those are still
# built by the library but not exercised by our tests, so we don't report
# on them here).
python3 /tests/coverage_summarize.py \
    --gcov-dir "$COV_GCOV_DIR" \
    --out /logs/verifier/coverage.json \
    --source lauf/config.cpp \
    --source lauf/reader.cpp \
    --source lauf/writer.cpp \
    --source lauf/vm.cpp \
    --source lauf/vm_execute.cpp \
    --source lauf/lib.cpp \
    --source lauf/asm/builder.cpp \
    --source lauf/asm/module.cpp \
    --source lauf/asm/program.cpp \
    --source lauf/asm/type.cpp \
    --source lauf/backend/dump.cpp \
    --source lauf/backend/qbe.cpp \
    --source lauf/frontend/text.cpp \
    --source lauf/lib/bits.cpp \
    --source lauf/lib/fiber.cpp \
    --source lauf/lib/heap.cpp \
    --source lauf/lib/int.cpp \
    --source lauf/lib/memory.cpp \
    --source lauf/runtime/memory.cpp \
    --source lauf/runtime/process.cpp \
    --source lauf/runtime/value.cpp \
    --source lauf/support/page_allocator.cpp \
  || echo "coverage_summarize failed (non-fatal)"

# Step 10: dump coverage.json so it lands in debug.log (grader only
# auto-downloads ctrf.json + reward.txt).
echo "=== coverage.json ==="
cat /logs/verifier/coverage.json 2>/dev/null || echo "(no coverage.json produced)"
echo "=== end coverage.json ==="

# Explicit exit 0 — coverage failure is never a grading failure.
exit 0
