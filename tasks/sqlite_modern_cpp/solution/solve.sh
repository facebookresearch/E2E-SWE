#!/bin/bash
set -e

# git + build-essential are pre-installed in the C++ base image; libsqlite3-dev
# is pre-installed in the per-task sqlite_modern_cpp:v1 image (FROM cpp_base
# + apt-install libsqlite3-dev). So no apt-get install needed at solve time.

git clone https://github.com/aminroosta/sqlite_modern_cpp.git /tmp/repo
cd /tmp/repo
git checkout 56af65d2c5085dd34a2c1a4ad20cf8b93ad1024f  # tag v3.2

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
# libsqlite3-dev is pre-installed in the per-task image; no apt-get needed.
# sqlite_modern_cpp is header-only; install the primary header + sub-headers.
cp /app/hdr/sqlite_modern_cpp.h /usr/local/include/sqlite_modern_cpp.h
cp -r /app/hdr/sqlite_modern_cpp /usr/local/include/sqlite_modern_cpp
EOF
chmod +x ./setup.sh
