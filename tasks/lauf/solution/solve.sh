#!/bin/bash
# Ground-truth setup for the lauf WRG task. Runs only under --mode=evaluate_gt.
# The GT `solve.sh` container has the network on so we can `git clone`; the
# grading container that runs setup.sh + test.sh is offline.
#
# lauf pins commit 58a09f434624344306cfa3e12a469623f54a8378 ("Update example").
# git rev-parse verified this is the full SHA of short 58a09f4 (memory:
# feedback-wrg-verify-git-hash — bootstrap workers have fabricated hashes).
set -e

git clone https://github.com/foonathan/lauf.git /tmp/repo
cd /tmp/repo
git checkout 58a09f434624344306cfa3e12a469623f54a8378

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh runs in the offline grading container. It:
#   * Builds lauf via CMake with clang (config.h #errors on non-clang), using
#     the pre-fetched lexy at /opt/lexy-src to skip FetchContent's network hit.
#   * Turns off the reference repo's own tests/benchmarks/tools — none of those
#     targets are needed and some pull in extra deps (doctest, tools/qbe.cpp
#     assumes qbe is on PATH). The QBE backend LIBRARY (liblauf_qbe.a) is
#     always built by src/CMakeLists.txt regardless of the tools flag, so
#     the grader can link against it transparently.
#   * Installs the public headers under /usr/local/include/lauf/ and copies
#     every static library produced by the build into /usr/local/lib/. The
#     grader links test drivers with `-llauf_core -llauf_text -llexy_file
#     -llexy_ext -llexy_unicode_database` against these installed artifacts.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
set -e

# Configure + build lauf_core + lauf_text + lauf_qbe (all built by
# src/CMakeLists.txt) against the baked lexy source. Turn off the reference
# repo's own doctest-based tests, benchmarks, and tools — none of those are
# needed by the grader and doctest / the qbe CLI are not baked in the image.
cmake -S /app -B /app/build -G Ninja \
    -DCMAKE_C_COMPILER=clang \
    -DCMAKE_CXX_COMPILER=clang++ \
    -DCMAKE_BUILD_TYPE=Release \
    -DFETCHCONTENT_SOURCE_DIR_LEXY=/opt/lexy-src \
    -DLAUF_BUILD_TESTS=OFF \
    -DLAUF_BUILD_TOOLS=OFF \
    -DLAUF_BUILD_BENCHMARKS=OFF

cmake --build /app/build

# Install headers under /usr/local/include/lauf/ so client code can write
# `#include <lauf/vm.h>` with no -I flag.
mkdir -p /usr/local/include/lauf
cp -r /app/include/lauf/. /usr/local/include/lauf/

# Copy every static library produced by the build (lauf's own + the lexy
# archives FetchContent built) into /usr/local/lib/ so `-llauf_core -llauf_text
# -llexy_file -llexy_ext -llexy_unicode_database` all resolve.
mkdir -p /usr/local/lib
find /app/build -name '*.a' -exec cp -v {} /usr/local/lib/ \;

# Refresh the loader cache in case anything ended up as a .so.
ldconfig 2>/dev/null || true
EOF
chmod +x /app/setup.sh
