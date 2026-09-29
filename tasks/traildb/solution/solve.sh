#!/bin/bash
# Ground-truth setup -- the ONLY container in the WRG flow with internet on.
# Clones the reference traildb repo at the pinned commit, then writes the
# offline `setup.sh` the grading container will source.
set -e

git clone https://github.com/traildb/traildb.git /tmp/repo
cd /tmp/repo
# Pinned 2019-11-01 HEAD-of-master (verified full 40-char SHA).
git checkout 053ed8e5d0301c792f3ee703cd9936c49ecf41a1

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

cat > ./setup.sh <<'EOF'
#!/bin/bash
# Offline build+install: uses gcc + autotools (autoreconf + configure + make),
# all pre-baked in the per-task image alongside libjudy-dev + libarchive-dev
# + pkg-config. NOTE we use autotools rather than the repo's default waf --
# waf's `waflib/Context.py` still does `import imp`, which was removed in
# Python 3.12, so waf breaks on any modern Python.
set -e

cd /app

# UPSTREAM DEFECT PATCH -- Makefile.am's libtraildb_la_SOURCES list is
# incomplete: it forgets both src/tdb_multi_cursor.c and its dependency
# src/pqueue/pqueue.c. The autotools build then produces a libtraildb.so
# missing the tdb_multi_cursor_* symbols (declared in the public traildb.h
# header) with `undefined reference to pqueue_pop` at link time. The waf
# path uses ant_glob("src/**/*.c") and pulls both in transparently. Add
# the two missing entries idempotently before the already-listed
# `src/tdb_queue.c` line.
if ! grep -q 'tdb_multi_cursor.c' Makefile.am; then
    sed -i 's|src/tdb_queue.c \\|src/tdb_multi_cursor.c \\\n  src/pqueue/pqueue.c \\\n  src/tdb_queue.c \\|' Makefile.am
fi

autoreconf -i
./configure --prefix=/usr/local
make -j"$(nproc)"
make install

# make install drops libtraildb.so + libtraildb.a into /usr/local/lib, public
# headers (traildb.h, tdb_types.h, tdb_error.h, tdb_limits.h) into
# /usr/local/include, and the tdb CLI + traildb_bench into /usr/local/bin.
# Refresh the linker cache so dlopen()/ld pick libtraildb.so up.
ldconfig
EOF
chmod +x ./setup.sh
