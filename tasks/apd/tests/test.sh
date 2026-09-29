#!/bin/bash
# Offline grading. The Go toolchain + python3 are pre-baked in the per-task image
# (environment/Dockerfile) and there is NO network — do not add apt-get / curl / go-get steps.
#
# Note: no `set -e` — the reward logic below relies on capturing the test runner's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

export GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-mod=mod GOCACHE="${GOCACHE:-/tmp/gocache}"

# Build the project. setup.sh was written by the agent (or by solve.sh for GT eval) and builds the
# module offline against the baked toolchain.
bash ./setup.sh

# Locate the Go module. It normally lives at the /app working directory, but the agent may have
# rooted its go.mod in a subdirectory; find it so grading is independent of that layout choice.
MODDIR=$(dirname "$(find /app -maxdepth 3 -name go.mod 2>/dev/null | head -1)")
if [ -z "$MODDIR" ] || [ "$MODDIR" = "." ]; then MODDIR=/app; fi

# Place the hidden suite into the module directory and run it there. The tests are an external
# `apd_test` package that imports the module via its public API; one `func TestXxx` ==
# one CTRF entry (no subtests). A compile failure yields zero tests -> reward 0.
#
# Drop any *_test.go the agent left in the module dir first. `go test .` compiles every
# *_test.go in the package directory, so the agent's own tests would otherwise be graded
# alongside the hidden suite: they inflate the CTRF count past test_case_count, and one that
# fails to compile (e.g. a mismatched `package` clause) or overruns the timeout collapses the
# whole run to a single BUILD failure. `-maxdepth 1` is the right scope because `go test .`
# builds only the package in $MODDIR, and `*_test.go` is exactly Go's own rule for test files.
find "$MODDIR" -maxdepth 1 -name '*_test.go' -delete
cp /tests/*_test.go "$MODDIR"/
cd "$MODDIR"
go test -json -timeout 120s . > /tmp/gotest.json 2>&1
test_exit=$?

# Convert `go test -json` -> CTRF for the grader, and mirror pass/fail into reward.txt.
mkdir -p /logs/verifier
python3 /tests/ctrf.py /tmp/gotest.json /logs/verifier/ctrf.json

if [ "$test_exit" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
