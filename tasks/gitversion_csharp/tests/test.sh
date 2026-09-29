#!/bin/bash
# Offline C# grading for the GitVersion task. No network — the per-task image bakes the .NET 10 SDK,
# a local NuGet feed, git, and the pytest harness. Do not add apt-get / curl / download steps.
#
# Note: no `set -e` — the reward logic below relies on capturing pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

# Build the candidate's GitVersion CLI. setup.sh (written by the agent, or by solve.sh for GT eval)
# publishes a runnable CLI to /app/dist offline; the tests invoke it as `dotnet /app/dist/gitversion.dll`.
bash ./setup.sh

# Deterministic git identity + default branch for the fixture repos the tests build.
git config --global user.email "wrg@example.com"
git config --global user.name "WRG Grader"
git config --global init.defaultBranch main

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_gitversion.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
