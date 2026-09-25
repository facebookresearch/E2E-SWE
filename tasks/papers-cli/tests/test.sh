#!/bin/bash
# Offline grading. The test harness (pytest + plugins + pytest-httpserver) and every dependency are
# pre-baked in the per-task image (see environment/Dockerfile), and PIP_NO_INDEX is set. There is
# NO network — do not add apt-get / curl / download steps. The crossref-mock fixture spins up an
# in-container HTTP server; the test helper that launches the CLI drops any inherited *_proxy vars
# and sets no_proxy for localhost itself, so the tests reach it directly with no proxy handling here.
#
# Note: no `set -e` — the reward logic below relies on capturing pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project. setup.sh was written by the agent (or by solve.sh for GT eval) and
# runs offline against the pre-installed dependencies in this same environment.
bash ./setup.sh

# Git identity for the tests that exercise the `--git` install (backup repo commits). The tests
# also set GIT_AUTHOR_*/GIT_COMMITTER_* via monkeypatch, but configure a global fallback too.
git config --global user.email "papers-test@example.com"
git config --global user.name "Papers Test"
git config --global init.defaultBranch main

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_papers.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
