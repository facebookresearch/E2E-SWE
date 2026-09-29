#!/bin/bash
# Grading driver. Builds the implementation via setup.sh, then compiles and runs each
# test group as an INDEPENDENT translation unit. A compile error in one group fails
# only that group's tests (reported as failed via the manifest); the other groups still
# compile, run, and score — so partial credit is preserved instead of an all-or-nothing
# zero. The merged CTRF goes to /logs/verifier/ctrf.json.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

bash ./setup.sh   # installs the ureact headers + umbrella to /usr/local/include (offline)

mkdir -p /logs/verifier
rm -f /tmp/frag_*.json

for grp in signals dynamic events; do
  if c++ -std=c++17 /tests/test_${grp}.cpp -I/usr/local/include -o /tmp/t_${grp} 2>/tmp/${grp}.cerr; then
    /tmp/t_${grp} /tmp/frag_${grp}.json
  else
    echo "group ${grp}: COMPILE FAILED"; sed -n '1,5p' /tmp/${grp}.cerr
    python3 - "$grp" /tmp/frag_${grp}.json <<'PY'
import sys, json
grp, out = sys.argv[1], sys.argv[2]
names = {}
for line in open('/tests/manifest.txt'):
    line = line.strip()
    if not line: continue
    g, ns = line.split(':', 1); names[g] = ns.split(',')
arr = [{"name": n, "status": "failed", "duration": 0, "message": "group failed to compile"} for n in names[grp]]
json.dump(arr, open(out, 'w'))
PY
  fi
done

python3 - <<'PY'
import json, glob
tests = []
for f in sorted(glob.glob('/tmp/frag_*.json')):
    tests += json.load(open(f))
CANONICAL_TOTAL = 23  # must equal [verifier].test_case_count in task.toml
passed = sum(1 for t in tests if t['status'] == 'passed'); n = len(tests)
skipped = sum(1 for t in tests if t['status'] == 'skipped')
failed = sum(1 for t in tests if t['status'] == 'failed')
other = n - passed - failed - skipped
ctrf = {"results": {"tool": {"name": "ureact-ctest", "version": "1"},
        "summary": {"tests": n, "passed": passed, "failed": failed,
                    "skipped": skipped, "pending": 0, "other": other, "start": 0, "stop": 0},
        "tests": tests}}
json.dump(ctrf, open('/logs/verifier/ctrf.json', 'w'))
ok = (passed == CANONICAL_TOTAL and failed == 0 and other == 0 and skipped == 0)
open('/logs/verifier/reward.txt', 'w').write('1' if ok else '0')
print(f"passed {passed}/{n} (canonical {CANONICAL_TOTAL})")
PY
