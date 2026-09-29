#!/bin/bash
set -e

# Ground-truth solution for the gtirb task. Runs only during `--mode=evaluate_gt`
# in Container A (internet ON for this one clone). Clones gtirb at the pinned
# v2.3.2 commit, copies the C++-relevant subset into /app, and writes a setup.sh
# that builds the library OFFLINE via CMake (all deps are baked in the per-task
# image: libprotobuf-dev, protobuf-compiler, libboost-all-dev, cmake, g++).
#
# We cherry-pick the C++ tree (include/, src/, proto/, CMakeLists.txt + support
# .cmake files, version.txt, gtirbConfig.cmake.in, CMakeLists.googletest) and
# skip everything the C++ build doesn't need: python/, java/, cl/, doc/,
# resources/, cpack-config.cmake, PROTOBUF.md, AuxData.md, FAQ.md, CHANGELOG.md,
# CONTRIBUTING.md, CODE_OF_CONDUCT.md, GrammaTech-CLA-GTIRB.pdf, conanfile.py,
# and the src/test/ subdirectory (gtirb's own tests — we run our own hidden
# tests via /tests/test_gtirb.cpp).
#
# Legacy proto/v0/ is included in the clone but disabled at build time via
# -DGTIRB_ENABLE_TESTS=OFF (which also disables everything under proto/v0's
# CMake integration).

git clone https://github.com/GrammaTech/gtirb.git /tmp/repo
cd /tmp/repo
git checkout eb6a7af1bb9754de004147f292dc1c7728f62e56  # tag v2.3.2

mkdir -p /app
# Copy the whole tree (gtirb's top-level CMakeLists.txt references random
# files from the root — README.md, LICENSE.md, cpack-config.cmake — that we
# don't want to hunt down one by one). Then strip only the paths we're sure
# the C++ build doesn't need.
cp -a /tmp/repo/. /app/
# The C++ build path takes -DGTIRB_PY_API=OFF etc. and skips these
# subtrees at configure time; deleting them from disk keeps the workspace
# leaner but is not strictly required.
rm -rf /app/python /app/java /app/cl /app/doc
# gtirb's own ctest suite (uses gtest that CMake tries to fetch); we run
# our own hidden tests via /tests/test_gtirb.cpp, so this subtree isn't
# needed even if -DGTIRB_ENABLE_TESTS were ON.
rm -rf /app/src/test
# Legacy proto/v0 (backward-compat with pre-2.0 format; not exposed by the
# public API in v2.x).
rm -rf /app/proto/v0
# CMakeLists.txt references README.md via CPack. gtirb ships LICENSE.txt but
# CMakeLists.txt asks for LICENSE.md — symlink so CPack doesn't fail.
if [ -f /app/LICENSE.txt ] && [ ! -e /app/LICENSE.md ]; then
    ln -sf LICENSE.txt /app/LICENSE.md
fi

cd /app
rm -rf /tmp/repo

# Write setup.sh that builds gtirb OFFLINE. All deps (libprotobuf-dev, boost,
# cmake, g++) are pre-installed in the per-task image. No `set -e` so a build
# failure can't abort the (no-set-e) test.sh that sources it.
#
# Build options:
#   -DGTIRB_PY_API=OFF / -DGTIRB_CL_API=OFF / -DGTIRB_JAVA_API=OFF
#       C++ API only. Skip Python/CommonLisp/Java paths.
#   -DGTIRB_DOCUMENTATION=OFF
#       No doxygen build.
#   -DGTIRB_ENABLE_TESTS=OFF
#       Skip gtirb's ctest suite (we run our own /tests/test_gtirb.cpp).
#       Also skips the googletest download (offline; can't download anyway).
#   -DGTIRB_RUN_CLANG_TIDY=OFF
#       Skip clang-tidy (not installed, would fail the config).
#   -DCMAKE_CXX_FLAGS="-Wno-error"
#       gtirb sets -Werror; newer g++ may emit new warnings that would
#       otherwise turn into fatal build errors. Defuse defensively.
#   -DGTIRB_BUILD_SHARED_LIBS=ON
#       Build libgtirb.so + libgtirb_proto.so (dynamic linking, gtirb's
#       default; shared is easier to install and .so is smaller than .a).
#   -DCMAKE_INSTALL_PREFIX=/usr/local
#       Standard install prefix; ldconfig picks up /usr/local/lib.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/build && cd /app/build && \
  cmake .. \
    -DGTIRB_PY_API=OFF \
    -DGTIRB_CL_API=OFF \
    -DGTIRB_JAVA_API=OFF \
    -DGTIRB_DOCUMENTATION=OFF \
    -DGTIRB_ENABLE_TESTS=OFF \
    -DGTIRB_RUN_CLANG_TIDY=OFF \
    -DGTIRB_BUILD_SHARED_LIBS=ON \
    -DCMAKE_CXX_FLAGS="-Wno-error" \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DCMAKE_BUILD_TYPE=Release \
    -Wno-dev >/tmp/cmake.log 2>&1 && \
  make -j"$(nproc)" install >/tmp/make.log 2>&1 && \
  ldconfig
EOF
chmod +x /app/setup.sh
