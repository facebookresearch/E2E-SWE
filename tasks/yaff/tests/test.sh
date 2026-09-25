#!/bin/bash
# Grader entry point for the yaff C++ task. Runs fully OFFLINE — cmake, a C++20
# compiler, doctest (bundled in /tests), and python3 (base image) are all pre-baked in
# the per-task image (environment/Dockerfile). No network, no apt-get, NO pytest.
#
# Testing is C++-native: each held-out component (tests/cpp/test_<component>.cpp) is
# compiled into its own doctest binary and run with the bundled 'ctrf' reporter
# (tests/cpp/ctrf_reporter.cpp), which emits a per-binary CTRF JSON. tests/merge_ctrf.py
# then merges the partials into /logs/verifier/ctrf.json — the language-agnostic report the
# WRG grader reads. One doctest TEST_CASE == one CTRF entry == one [verifier] test_case_count.
#
# No `set -e`: we must always reach the merge step so a CTRF report is produced even when a
# component fails to compile. Per-component binaries + `cmake --build -- -k` (keep-going) mean
# one component's compile failure only zeroes that component's cases (real partial credit): its
# binary is absent, so its cases never appear in the merged CTRF. The grader's denominator is
# task.toml [verifier] test_case_count (fixed at 34), not the merged entry count, so an absent
# component simply lowers the pass percentage — no synthesized 'failed' entries are needed.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

BUILD_DIR=/tmp/yaff_build
BUILD_LOG=/tmp/yaff_build.log
PARTIALS_DIR=/tmp/yaff_ctrf
export YAFF_BUILD_DIR="${BUILD_DIR}"
export YAFF_BUILD_LOG="${BUILD_LOG}"
rm -rf "${PARTIALS_DIR}"
mkdir -p "${PARTIALS_DIR}"

# Locate the include root robustly: the carve's headers live under <root>/yaff/, but the agent
# may put <root> at /app/include or nest it (e.g. /app/repo/include). Find yaff/base.h and use
# its grandparent as the include root; fall back to /app/include.
BASE_H="$(find /app -type f -path '*/yaff/base.h' 2>/dev/null | head -1)"
if [ -n "${BASE_H}" ]; then
    APP_INCLUDE="$(dirname "$(dirname "${BASE_H}")")"
else
    APP_INCLUDE="/app/include"
fi
echo "using APP_INCLUDE=${APP_INCLUDE}" >"${BUILD_LOG}"

# Compile the held-out tests (/tests/cpp) against the agent's carved headers. The carve is
# header-only, so nothing under /app/src is needed. Each component is its own binary; build with
# keep-going so one component's compile failure does not block the others (real partial credit).
echo "=== configuring ===" >>"${BUILD_LOG}"
cmake -S /tests -B "${BUILD_DIR}" -G "Unix Makefiles" -DAPP_DIR=/app -DAPP_INCLUDE="${APP_INCLUDE}" -DCMAKE_BUILD_TYPE=Release >>"${BUILD_LOG}" 2>&1
echo "=== building (keep-going) ===" >>"${BUILD_LOG}"
cmake --build "${BUILD_DIR}" --parallel "$(nproc)" -- -k >>"${BUILD_LOG}" 2>&1
echo "build exit: $?" >>"${BUILD_LOG}"
echo "=== built binaries ===" >>"${BUILD_LOG}"
ls -1 "${BUILD_DIR}"/test_* 2>/dev/null >>"${BUILD_LOG}"

# Run each built component binary with the CTRF reporter → one partial JSON per binary.
# A binary that failed to compile is simply absent (its cases won't appear in the merge).
echo "=== running component binaries (C++-native CTRF) ===" >>"${BUILD_LOG}"
for bin in "${BUILD_DIR}"/test_*; do
    [ -x "${bin}" ] || continue
    stem="$(basename "${bin}")"
    echo "--- ${stem} ---" >>"${BUILD_LOG}"
    # --no-skip: honor no skip decorators; per-case timeout is enforced by the outer
    # verifier timeout. Reporter writes valid JSON even on all-pass / on failures.
    YAFF_CTRF_OUT="${PARTIALS_DIR}/${stem}.ctrf.json" \
        timeout 120 "${bin}" --reporters=ctrf --no-skip --force-colors=off \
        >>"${BUILD_LOG}" 2>&1
    echo "${stem} exit: $?" >>"${BUILD_LOG}"
done

# Merge per-binary partials into the single CTRF the grader reads. Always produces a valid
# file (empty results if every component failed to build).
python3 /tests/merge_ctrf.py "${PARTIALS_DIR}" /logs/verifier/ctrf.json >>"${BUILD_LOG}" 2>&1
echo "merge exit: $?" >>"${BUILD_LOG}"

# Reward gate: binary 1/0. Write 1 IFF every declared case ran and passed, i.e.
# passed == task.toml [verifier] test_case_count and failed == other == skipped == 0.
# A component that failed to compile contributes no cases, so passed < TOTAL -> 0.
python3 - <<'PY'
import json

CANONICAL_TOTAL = 34  # must equal task.toml [verifier] test_case_count

try:
    with open("/logs/verifier/ctrf.json") as fh:
        s = json.load(fh)["results"]["summary"]
    ok = (
        int(s.get("passed", 0)) == CANONICAL_TOTAL
        and int(s.get("failed", 1)) == 0
        and int(s.get("other", 1)) == 0
        and int(s.get("skipped", 1)) == 0
    )
except Exception:
    ok = False
with open("/logs/verifier/reward.txt", "w") as fh:
    fh.write("1" if ok else "0")
PY
