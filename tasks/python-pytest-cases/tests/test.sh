#!/bin/bash
# Offline grading. The test harness (pytest==8.4.1 + pytest-json-ctrf + pytest-timeout) and every
# dependency are pre-baked in the per-task image (see environment/Dockerfile), and PIP_NO_INDEX is
# set. There is NO network — no venv/uv, no pip install, no apt-get / curl / download steps. The
# image bakes the harness + deps into the SYSTEM python and `bash ./setup.sh` installs the project
# there, so pytest runs on the system python directly.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project. setup.sh was written by the agent (model eval) or by
# solution/solve.sh (GT eval) and runs offline against the pre-installed dependencies here.
bash ./setup.sh

# -p pytester enables the bundled `pytester` fixture used by the suite to launch inner pytest
# sessions that exercise the plugin's collection/parametrization. pytest is pinned to 8.4.1 in the
# image: pytest-cases-style plugins deeply monkeypatch pytest internals and pytest >=9 changed
# internal signatures.
pytest --ctrf /logs/verifier/ctrf.json /tests/test_python_pytest_cases.py -p pytester -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
