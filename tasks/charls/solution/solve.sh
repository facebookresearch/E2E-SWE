#!/bin/bash
set -e

# git + build-essential + cmake are pre-installed in the C++ base image. solve.sh runs in
# the internet-on GT container (--mode=evaluate_gt / Container A only), so the git clone
# works.

git clone https://github.com/team-charls/charls.git /tmp/repo
cd /tmp/repo
git checkout 9930a2a2fa75f516c4a08708180c9907fa501a97  # tag 2.4.4 (2026-06-08)

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# charls is a full compiled C++17 library. The agent's setup.sh must build charls as a
# shared library (libcharls.so) and install both the shared library + public C headers so
# the grader's per-module g++ commands
#
#     g++ -std=c++17 driver.cpp -lcharls -lgtest -lgtest_main -lpthread
#     (with no -I flag)
#
# can resolve `#include <charls/charls.h>` and link the C API entry points.
#
# Public C API headers land under /usr/local/include/charls/ (matches upstream layout);
# the shared lib lands under /usr/local/lib/libcharls.so; ldconfig picks it up.
cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
cmake -B /app/build -S /app -DCMAKE_BUILD_TYPE=Release -DCHARLS_BUILD_TESTS=OFF -DCHARLS_BUILD_SAMPLES=OFF -DCHARLS_BUILD_FUZZ_TEST=OFF -DBUILD_SHARED_LIBS=ON
cmake --build /app/build -j"$(nproc)"
cmake --install /app/build --prefix /usr/local
ldconfig
EOF
chmod +x ./setup.sh
