#!/bin/bash
# Offline grading for the dyn4j task.
#
# dyn4j has ZERO external deps, so there is NO baked-jar classpath -- the agent's compiled classes
# in /app/out are the only classpath. The agent implements dyn4j under /app/src and provides
# /app/setup.sh that compiles it into /app/out. This script builds the agent's code, then compiles
# + runs each Java test driver against it to produce per-test JSON, and converts that to CTRF.
# Uses only the JDK + python3 in the per-task image -- no pip, no network.
#
# No `set -e`: every stage must run so a CTRF report is always produced (a broken submission yields
# an all-fail report with the denominator preserved, i.e. reward 0, rather than a grader error).
#
# TODO(Phase 4-5): author the dyn4j drivers + regenerate expected.tsv (run a driver with CAPTURE=1).
# Planned split (one capability per driver so a compile failure in one does not zero the others):
#   GeometryHarness   -- org.dyn4j.geometry  (Vector2, shapes, Mass, AABB, Transform, hull/decompose/simplify)
#   CollisionHarness  -- org.dyn4j.collision (broadphase, SAT/GJK narrowphase, manifold, raycast, CCD)
#   DynamicsHarness   -- org.dyn4j.dynamics + org.dyn4j.world (bodies, joints, contacts, world.step)
# Adjust the DRIVER list below to whatever drivers you actually author.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier /tmp/h

# 1. Build the agent's dyn4j source (offline) via the setup.sh it wrote (or solve.sh for GT).
# /app/src is the artifact of record, so the rebuild must be hermetic: stash any build output left
# behind first, otherwise an orphan .class whose .java was deleted stays on the grading classpath
# and can wipe a whole driver (javac "reference to X is ambiguous"). setup.sh recreates /app/out.
# If the rebuild yields no classes at all, restore the stashed output so this stash never zeroes a
# submission on its own.
rm -rf /tmp/out.prev
[ -d /app/out ] && mv /app/out /tmp/out.prev
bash ./setup.sh 2>/logs/verifier/setup.log || true
if [ -z "$(find /app/out -name '*.class' 2>/dev/null | head -n 1)" ] && [ -d /tmp/out.prev ]; then
    rm -rf /app/out && mv /tmp/out.prev /app/out
fi

# 2-3. Compile + run each driver INDEPENDENTLY against the agent's classes (no external jars).
# Missing cases (a driver that failed to compile/run) are recorded as failed by make_ctrf,
# preserving the denominator.
: > /logs/verifier/dyn4j_results.jsonl
for DRIVER in GeometryHarness CollisionHarness DynamicsHarness HullHarness DecomposeHarness SimplifyHarness BroadphaseHarness StepListenerHarness CollisionListenerHarness ContactListenerHarness BoundsListenerHarness ListenerRegistryHarness WorldQueryHarness ExceptionHarness; do
    [ -f "/tests/$DRIVER.java" ] || continue
    rm -rf /tmp/h && mkdir -p /tmp/h
    if javac -cp "/app/out" -d /tmp/h /tests/Runner.java "/tests/$DRIVER.java" 2>"/logs/verifier/${DRIVER}_compile.log"; then
        EXPECTED_TSV=/tests/expected.tsv java -cp "/tmp/h:/app/out" "$DRIVER" \
            >> /logs/verifier/dyn4j_results.jsonl 2>"/logs/verifier/${DRIVER}_run.log" || true
    fi
done

# 4. Convert results to CTRF (canonical case list = names in /tests/expected.tsv; missing -> failed).
python3 /tests/make_ctrf.py /logs/verifier/dyn4j_results.jsonl /logs/verifier/ctrf.json /tests/expected.tsv \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: all-or-nothing. 1 iff every canonical case passed (passed == CANONICAL_TOTAL and
# failed == other == skipped == 0); anything else -- including a missing/unreadable ctrf.json -- is 0.
CANONICAL_TOTAL=186
REWARD=$(CANONICAL_TOTAL="$CANONICAL_TOTAL" python3 -c "
import json, os, sys
total = int(os.environ['CANONICAL_TOTAL'])
try:
    s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    ok = (int(s.get('passed', 0)) == total
          and int(s.get('failed', 0)) == 0
          and int(s.get('other', 0)) == 0
          and int(s.get('skipped', 0)) == 0
          and int(s.get('pending', 0)) == 0)
except Exception:
    ok = False
print(1 if ok else 0)
" 2>/dev/null || echo 0)
case "$REWARD" in
    1) echo 1 > /logs/verifier/reward.txt ;;
    *) echo 0 > /logs/verifier/reward.txt ;;
esac
