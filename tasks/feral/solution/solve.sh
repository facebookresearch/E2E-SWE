#!/bin/bash
set -e

# Ground-truth solution for the Feral language task. Runs only during `--mode=evaluate_gt`, in
# Container A that keeps internet ON for this one clone. Places the reference Feral source under
# /app, prunes the std/ subdirectory down to the in-scope surface (io + assert + prelude), then
# writes a setup.sh that builds+installs Feral OFFLINE. Test.sh runs `source ./setup.sh` in a
# fresh grading container to reproduce the install and then invokes `/usr/local/bin/feral <script>`.
#
# In-scope std modules (what the agent is required to ship):
#   - std/io      (loadlib('std/IO') + a minimal io.fer re-exporting print/println/eprint/...)
#   - std/assert  (pure-Feral: eq/ne/gt/lt/ge/le, uses raise + prelude comparison operators)
# Every other lib/std/*.{fer,cpp} is deleted before build so the reference install matches the
# scope described in instruction.md; the upstream io.fer imports std/term which is out of scope,
# so we replace io.fer with a minimal `loadlib('std/IO');` re-export that matches what the
# agent is expected to produce.

git clone https://github.com/Feral-Lang/Feral.git /tmp/repo
cd /tmp/repo
git checkout 63a20a9e45846020887e6c19466febf62c41b28f  # 2026-07-05 HEAD (no upstream tag)

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# --- Prune std/ to the in-scope surface ---
# Keep only: io.fer (replaced below), assert.fer, IO.cpp. Delete everything else so the reference
# install ships the same modules the agent is asked to ship.
find /app/lib/std -mindepth 1 -maxdepth 1 \
    ! -name 'io.fer' ! -name 'assert.fer' ! -name 'IO.cpp' \
    -exec rm -rf {} +

# --- Replace io.fer with a minimal, in-scope version ---
# Upstream io.fer wraps colored/formatted print helpers that require std/term (out of scope).
# The agent's expected io.fer is a minimal `loadlib('std/IO')` that pulls in the C++ shim's
# print/println/eprint/eprintln (+ stdin/stdout/stderr) into the module namespace.
cat > /app/lib/std/io.fer <<'FEREOF'
loadlib('std/IO');
FEREOF

# Write the offline install script the grader will source. `--no-build-isolation` is a
# Python-installer term but analogous concern here: the image has no network, so cmake must not
# try to FetchContent anything. Feral's CMakeLists uses include(FetchContent) but does not invoke
# FetchContent_Declare/FetchContent_MakeAvailable for external deps -- everything it needs is
# vendored under cmake/ or in-tree. So a plain cmake configure + build + install works offline.
#
# PREFIX_DIR is Feral's own env-var override for CMAKE_INSTALL_PREFIX (see CMakeLists.txt); we
# point it at /usr/local so the binary lands at /usr/local/bin/feral, the shared library at
# /usr/local/lib/libferal.so, and the std/prelude modules at /usr/local/lib/feral/{std,prelude}.
# No set -e in setup.sh so a build failure surfaces via the CTRF (all tests fail) rather than
# aborting the test.sh harness.
cat > /app/setup.sh <<'EOF'
# Upstream CMakeLists demands cmake >= 3.31 aspirationally, but no 3.31-only features are actually
# used -- Debian 22.04 ships cmake 3.22.1 in cpp_base and configures/builds cleanly after lowering
# the min-version. Patch before invoking cmake so the offline grader doesn't need pip.
sed -i 's/cmake_minimum_required(VERSION 3\.[0-9]\+)/cmake_minimum_required(VERSION 3.22)/' /app/CMakeLists.txt
export PREFIX_DIR=/usr/local
cmake -B /app/build -S /app -DCMAKE_BUILD_TYPE=Release -DDISABLE_MARCH_NATIVE=true >/tmp/cmake_configure.log 2>&1
cmake --build /app/build -j"$(nproc)" --target install >/tmp/cmake_build.log 2>&1
ldconfig 2>/dev/null || true
EOF
chmod +x /app/setup.sh
