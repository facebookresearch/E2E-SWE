#!/bin/bash
# Offline grading. The test harness (pytest + pytest-django) and every runtime dependency
# (Django 5.2 line, typing_extensions, django-fast-update) are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — do not add a venv,
# uv, apt-get, curl, or any pip install of the harness/Django here.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline. setup.sh was written by the agent (or by solve.sh for GT eval)
# and runs `pip install -e . --no-build-isolation` against the pre-installed dependencies in this
# same environment (it pulls in the baked Django 5.2 line).
bash ./setup.sh

# The test app package and settings module live alongside the test files.
export PYTHONPATH=/tests:$PYTHONPATH
export DJANGO_SETTINGS_MODULE=test_settings

# --no-migrations: build the test DB via run-syncdb for every app instead of running migrations.
# The app exposes ComputedFieldsAdminModel / ContributingModelsModel as proxies of
# django.contrib.contenttypes' ContentType; resolving those proxy bases through the migration state
# requires the app to ship a migrations package, which is an implementation detail outside the spec.
# Syncdb creates the schema directly from the model registry and sidesteps that.
pytest --ctrf /logs/verifier/ctrf.json /tests/test_django_computedfields.py -v --no-migrations --timeout=120 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
