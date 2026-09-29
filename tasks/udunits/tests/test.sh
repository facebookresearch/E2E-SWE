#!/bin/bash
# Grading driver. Builds the implementation (agent's or ground-truth) via the
# setup.sh in the working directory, compiles the C-native test against the
# installed library, and runs it. The test writes the CTRF report to
# /logs/verifier/ctrf.json and exits 0 iff every test passes.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

bash ./setup.sh   # installs libudunits2 + udunits2.h/converter.h (offline)

mkdir -p /logs/verifier
cc /tests/test_udunits.c -I/usr/local/include -L/usr/local/lib -ludunits2 -lm -o /tmp/test_udunits
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
CTRF_PATH=/logs/verifier/ctrf.json /tmp/test_udunits

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
