#!/bin/bash
# Ground-truth setup for the b3d WRG task. Runs in the GT container (which
# has Internet); clones the reference repository, runs the reference's
# Python DSL codegen step (needed once, offline-friendly output baked into
# /app), and writes an OFFLINE setup.sh that the grader runs to build and
# install the reference library. The setup.sh itself must not need any
# network access.
set -e

# The reference's math backend is generated from a small in-tree DSL
# (src/math.dsl → src/math-gen.inc) via scripts/gen-math.py.
# math-toolkit.h #includes math-gen.inc unconditionally, so the include
# file must exist before src/b3d.c can compile. Install python3 up-front
# so solve.sh works whether or not the base image ships it.
apt-get update -qq
apt-get install -y --no-install-recommends python3

git clone https://github.com/jserv/b3d.git /tmp/repo
cd /tmp/repo
# Pin to the exact commit the task was authored against so the GT output is
# reproducible. Any tip revision that keeps the b3d.h/b3d-math.h/b3d-obj.h/
# b3d-voxel.h public API stable is compatible with the spec.
git checkout 8e3d31a2dff1b85344ba64bf7437d15dfa15ff6b
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo .git

# Bake the generated math backend into /app/src/math-gen.inc so setup.sh
# (which runs offline) does not need Python.
python3 scripts/gen-math.py --dsl src/math.dsl -o src/math-gen.inc

cat > setup.sh <<'SETUP'
#!/bin/bash
# Offline build+install for the b3d reference. No network. Compiles the two
# library translation units (src/b3d.c, src/b3d-voxel.c) into a static
# libb3d.a and installs public headers + library into /usr/local. Header-
# only modules (b3d-math.h, b3d-obj.h) are shipped as-is.
set -e

mkdir -p /app/build
gcc -std=c11 -O2 -Iinclude -Isrc -c src/b3d.c       -o /app/build/b3d.o
gcc -std=c11 -O2 -Iinclude -Isrc -c src/b3d-voxel.c -o /app/build/b3d-voxel.o
ar rcs /app/build/libb3d.a /app/build/b3d.o /app/build/b3d-voxel.o

install -Dm644 include/b3d.h       /usr/local/include/b3d.h
install -Dm644 include/b3d-math.h  /usr/local/include/b3d-math.h
install -Dm644 include/b3d-obj.h   /usr/local/include/b3d-obj.h
install -Dm644 include/b3d-voxel.h /usr/local/include/b3d-voxel.h
install -Dm644 /app/build/libb3d.a /usr/local/lib/libb3d.a
ldconfig
SETUP
chmod +x setup.sh
