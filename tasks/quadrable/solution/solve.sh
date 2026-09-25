#!/bin/bash
set -e

# git + build-essential are pre-installed in the shared C++ base image;
# liblmdb-dev and libb2-dev are pre-installed in the per-task quadrable image
# (FROM the C++ base + apt-install liblmdb-dev libb2-dev). So no apt-get
# install needed at solve time. solve.sh still runs in an internet-on
# container, so the git clone + submodule init work.

git clone https://github.com/hoytech/quadrable.git /tmp/repo
cd /tmp/repo
git checkout 4f44437dc9b951a91986ad69e2856938387be614  # HEAD 2026-07-13 "header for std::optional"

# Init only the submodules needed by the library headers:
#   - external/lmdbxx      -> lmdb++.h    (C++ RAII wrapper over LMDB)
#   - external/hoytech-cpp -> hoytech/hex.h (used by include/quadrable/debug.h,
#     the only OPTIONAL debug renderer header; keeping it makes the debug
#     header self-consistent for any consumer that pulls it in).
# Explicitly SKIP external/docopt.cpp -- that's for the quadb CLI, which is
# out of scope for this task.
git submodule update --init external/lmdbxx external/hoytech-cpp

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# quadrable is header-only. The agent's setup.sh must install the public
# headers under /usr/local/include/ so the grader's
#   g++ -std=c++17 driver.cpp -llmdb -lb2 -lpthread
# (with no -I flag) can resolve `#include <quadrable.h>` and its transitive
# includes:
#   quadrable.h -> "lmdbxx/lmdb++.h" -> /usr/local/include/lmdbxx/lmdb++.h
#   quadrable.h -> "quadrable/Key.h" -> "blake2.h"
#     -> /usr/include/blake2.h  (system libb2-dev, already baked in image)
#   quadrable/debug.h (optional) -> "hoytech/hex.h"
#     -> /usr/local/include/hoytech/hex.h
cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
# System /usr/include/blake2.h + -lb2 (libb2-dev) supply the BLAKE2s API used
# in include/quadrable/Key.h; no need to install external/hoytech-cpp/blake2.h.
mkdir -p /usr/local/include/quadrable /usr/local/include/lmdbxx /usr/local/include/hoytech
cp /app/include/quadrable.h                        /usr/local/include/quadrable.h
cp -r /app/include/quadrable/.                     /usr/local/include/quadrable/
cp /app/external/lmdbxx/lmdb++.h                   /usr/local/include/lmdbxx/lmdb++.h
cp /app/external/hoytech-cpp/hoytech/hex.h         /usr/local/include/hoytech/hex.h
EOF
chmod +x ./setup.sh
