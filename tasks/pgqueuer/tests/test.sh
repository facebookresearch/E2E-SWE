#!/bin/bash
# Offline grading. The test harness, pgqueuer's runtime deps, and the postgresql service are all
# pre-baked in the per-task image (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO
# network — do not add apt-get / curl / download steps.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Start the pre-baked PostgreSQL service and provision the test role + database the suite uses.
# The apt postinst's initdb leaves the cluster's data/config/log/run dirs root-owned, and PostgreSQL
# refuses to run the server as root — so hand them to the postgres user at runtime before starting
# (SSL is already disabled in the baked postgresql.conf so the server needs no readable key). Bound
# the readiness wait so a failed start can never hang the grader.
mkdir -p /var/run/postgresql
chown -R postgres:postgres /etc/postgresql /var/lib/postgresql /var/log/postgresql /var/run/postgresql
pg_ctlcluster $(pg_lsclusters -h | awk '{print $1}') main start || true
for _ in $(seq 1 60); do pg_isready -q && break; sleep 1; done
su - postgres -c "psql -v ON_ERROR_STOP=1 -c \"CREATE USER testuser WITH PASSWORD 'testpass' SUPERUSER;\""
su - postgres -c "psql -v ON_ERROR_STOP=1 -c \"CREATE DATABASE testdb OWNER testuser;\""

# Standard libpq env vars; pgqueuer reads these for every connection.
export PGHOST=localhost
export PGPORT=5432
export PGUSER=testuser
export PGPASSWORD=testpass
export PGDATABASE=testdb

# Install/build the project offline. setup.sh was written by the agent (or by solve.sh for GT eval)
# and runs against the pre-installed dependencies in this same environment.
bash ./setup.sh

# Re-assert the harness's libpq env AFTER sourcing setup.sh: a setup.sh that (against the spec)
# provisions its own role/DB or re-exports PG* must NOT be able to clobber the grading connection.
export PGHOST=localhost
export PGPORT=5432
export PGUSER=testuser
export PGPASSWORD=testpass
export PGDATABASE=testdb

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_pgqueuer.py -v --timeout=60 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
