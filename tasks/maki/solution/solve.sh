#!/bin/bash
set -e

# git + build-essential are pre-installed in the C++ base image, so no
# apt-get install needed at solve time. solve.sh runs in an internet-on
# container, so the git clone works.

git clone https://github.com/fgoujeon/maki.git /tmp/repo
cd /tmp/repo
git checkout b269a6c4c21a2207d73464bbb701cc1d9425ff7c  # tag v2.0.1

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# maki is header-only. The agent's setup.sh must install the public headers
# under /usr/local/include/ so the grader's `g++ -std=c++17 driver.cpp` (with
# no -I flag) can resolve `#include <maki.hpp>` and `#include <maki/*.hpp>`.
cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
cp /app/include/maki.hpp /usr/local/include/maki.hpp
cp -r /app/include/maki /usr/local/include/maki
EOF
chmod +x ./setup.sh
