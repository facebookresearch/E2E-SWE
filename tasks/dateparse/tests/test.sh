#!/bin/bash
# Offline grading for the `dateparse` Go task. There is NO network. Compilation happens inside
# `go test`; all toolchain + env (GOPROXY=off, GOFLAGS=-mod=mod) is baked into the image.
#
# No `set -e` — we always want to emit a CTRF report (even on build failure) and compute the
# reward from it, rather than aborting on a non-zero `go test` exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

# Locate the Go module root: the directory holding a go.mod that declares `module dateparse`. The
# implementation may live directly in the working dir or in a subdirectory; GT places it in /app.
# Prefer the shallowest matching go.mod; fall back to the shallowest go.mod, then to /app.
MODROOT=""
while IFS= read -r m; do
  if grep -qE '^module[[:space:]]+dateparse([[:space:]]|$)' "$m"; then
    MODROOT="$(dirname "$m")"
    break
  fi
done < <(find /app -name go.mod 2>/dev/null | awk '{print length, $0}' | sort -n | cut -d' ' -f2-)
if [ -z "$MODROOT" ]; then
  first="$(find /app -name go.mod 2>/dev/null | awk '{print length, $0}' | sort -n | cut -d' ' -f2- | head -1)"
  [ -n "$first" ] && MODROOT="$(dirname "$first")"
fi
[ -z "$MODROOT" ] && MODROOT=/app

# Build/prepare via setup.sh (written by the agent, or by solve.sh for GT). Best effort — Go
# actually compiles during `go test` below.
if [ -f "$MODROOT/setup.sh" ]; then
  ( cd "$MODROOT" && bash ./setup.sh ) >/dev/null 2>&1
elif [ -f /app/setup.sh ]; then
  ( cd /app && bash ./setup.sh ) >/dev/null 2>&1
fi

# Place the hidden Go test file(s) into the module root so they compile against the
# implementation. They are `package expr_test` and `import "expr"`, so dropping them next to the
# root package makes `go test .` build them as the package's external test. They are
# `package dateparse_test` and `import "dateparse"`.
#
# Drop any *_test.go the agent left in the module root first. `go test .` compiles every
# *_test.go in the package directory, so the agent's own tests would otherwise be graded
# alongside the hidden suite: they inflate the CTRF count past test_case_count, and one that
# fails to compile (e.g. a mismatched `package` clause) or overruns the timeout collapses the
# whole run to a single BUILD failure. `-maxdepth 1` is the right scope because `go test .`
# builds only the root package, and `*_test.go` is exactly Go's own rule for test files.
find "$MODROOT" -maxdepth 1 -name '*_test.go' -delete
cp /tests/*_test.go "$MODROOT/" 2>/dev/null

cd "$MODROOT"
go test -json -timeout 120s -run 'Test' . > /tmp/gotest.json 2>&1

# Convert `go test -json` output into the CTRF report the grader reads.
python3 /tests/go2ctrf.py < /tmp/gotest.json > /logs/verifier/ctrf.json

# Reward fallback. The grader scores authoritatively from ctrf.json + task.toml
# test_case_count; we also write reward.txt for compatibility with the template contract.
python3 - <<'PY'
import json

# Must match [verifier].test_case_count in task.toml.
CANONICAL_TOTAL = 56
try:
    s = json.load(open("/logs/verifier/ctrf.json"))["results"]["summary"]
    ok = (
        s["passed"] == CANONICAL_TOTAL
        and s["failed"] == 0
        and s.get("other", 0) == 0
        and s.get("skipped", 0) == 0
    )
except Exception:
    ok = False
open("/logs/verifier/reward.txt", "w").write("1" if ok else "0")
PY
