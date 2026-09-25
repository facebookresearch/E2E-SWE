#!/bin/bash
set -e

# git + build-essential + cmake are pre-installed in the C++ base image, so no
# apt-get install needed at solve time. The git clone runs in the
# network-enabled solve container.

git clone https://github.com/leethomason/tinyxml2.git /tmp/repo
cd /tmp/repo
git checkout 9148bdf719e997d1f474be6bcc7943881046dba1  # tag 11.0.0

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
cmake -B /app/build -S /app -DCMAKE_BUILD_TYPE=Release -Dtinyxml2_BUILD_TESTING=OFF
cmake --build /app/build -j"$(nproc)"
cmake --install /app/build
ldconfig
EOF
chmod +x ./setup.sh
