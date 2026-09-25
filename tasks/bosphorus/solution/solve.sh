#!/bin/bash
set -e

# GROUND TRUTH for the bosphorus WRG task. Runs only during GT eval (never seen by the agent).
# git + cmake + build-essential are pre-baked in the per-task image (environment/Dockerfile).
# solve.sh runs in an internet-on container during GT eval, so the
# clone works; test.sh then runs OFFLINE and links against the pre-baked bosphorus deps
# (Boost / zlib / libpng / m4ri / BRiAl / cryptominisat5).

git clone https://github.com/meelgroup/bosphorus.git /tmp/repo
cd /tmp/repo
# Pin commit HEAD-of-master resolved via `git rev-parse HEAD` on the local clone (2026-07-15).
git checkout 5390b6ea1e4fc3ebe6846cecad9be9e60733d323

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh builds the bosphorus library + CLI OFFLINE against the pre-baked deps and installs to
# /usr/local/{bin,lib,include}. `-DENABLE_TESTING=OFF` avoids pulling upstream test infra
# (they use lit + OutputCheck via Python), which we replace with our own pytest+subprocess suite.
cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
cmake -B /app/build -S /app \
    -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_TESTING=OFF \
    -DSTATICCOMPILE=OFF
cmake --build /app/build -j"$(nproc)"
cmake --install /app/build
ldconfig
EOF
chmod +x ./setup.sh
