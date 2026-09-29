#!/bin/bash
# Offline grading. The test harness and every dependency are pre-baked in the per-task image
# (see environment/Dockerfile), and PIP_NO_INDEX is set. There is NO network — no apt-get / curl /
# pip-from-index here.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Start the baked system services the tests need.
redis-server --daemonize yes --save "" --appendonly no

# PostgreSQL: the grading container surfaces the cluster's directories as root-owned (the
# OCI layer / user-namespace mapping drops the postgres-user ownership baked at image-build time),
# which makes `pg_ctlcluster` refuse to start ("Data directory ... must not be owned by root") and
# also breaks the log dir and the snakeoil SSL key the default config reads. Restore ownership of
# the postgres dirs, start with SSL disabled (the tests connect to plain localhost), and wait until
# the server actually accepts connections before running pytest (PostgresBucket connects to :5432).
PG_VER=$(pg_lsclusters -h | awk '{print $1}')
chown -R postgres:postgres /var/lib/postgresql /etc/postgresql /var/log/postgresql /var/run/postgresql 2>/dev/null || true
pg_ctlcluster "$PG_VER" main start -o '-c ssl=off' || true
for _ in $(seq 1 30); do
  pg_isready -h localhost -p 5432 -q && break
  sleep 1
done
su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres';\"" 2>/dev/null || true

# Install/build the project offline (runtime deps + hatchling build backend are pre-installed;
# the image sets PIP_NO_INDEX, so setup.sh uses --no-build-isolation).
bash ./setup.sh

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/ -v --timeout=30 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
