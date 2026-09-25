#!/bin/bash
# Offline grading. The test harness (pytest + pytest-django + plugins) and every dependency
# (Django 5.2, django-taggit) are pre-baked in the per-task image (see environment/Dockerfile),
# and PIP_NO_INDEX is set. There is NO network — no apt-get / curl / pip-from-index here.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline. setup.sh was written by the agent (or by solve.sh for GT eval)
# and runs `pip install -e . --no-build-isolation` against the pre-installed deps in this same
# environment. No system service is needed (the suite uses an in-memory SQLite database).
bash ./setup.sh

export PYTHONPATH=/tests:$PYTHONPATH
export DJANGO_SETTINGS_MODULE=test_settings

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_django_modelcluster.py -v --timeout=120 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
