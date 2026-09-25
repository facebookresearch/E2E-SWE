#!/bin/bash
set -e

# WRG ground-truth setup for RBDyn (Phase-5 v5).
#
# solve.sh runs in an internet-on container under --mode=evaluate_gt (per
# D109253956), so `git clone` reaches github. Runtime deps and the RBDyn
# fixture libraries are pre-baked in the per-task image (rbdyn:v5); this
# script only needs to plant the reference-implementation .cpp files at
# the paths the agent would produce them at, then write setup.sh which
# will be re-source'd offline by test.sh at grade time.
#
# Phase-5 change (vs v4): agent scope shrunk from 6 -> 4 files. VisServo
# and ZMP moved from agent scope back into the fixture (libRBDyn_core.a)
# — both had 0 dedicated tests; unearned-pass per /review-task-wrg-v0
# quality review. GT only plants the 4 hard-math narrow RBDyn files now.

git clone https://github.com/jrl-umi3218/RBDyn.git /tmp/repo
cd /tmp/repo
git checkout a49b383e3fbc57168c7238fd93155c409b6046f5  # HEAD 2026-07-20, pre-commit-ci-update-config

# The reference repo tree layout expected by the task spec:
#   /app/src/RBDyn/{IDIM,Coriolis,Jacobian,NumericalIntegration}.cpp
# (Headers are already installed in the image at /usr/local/include/.)
mkdir -p /app/src/RBDyn
cp /tmp/repo/src/RBDyn/IDIM.cpp                 /app/src/RBDyn/IDIM.cpp
cp /tmp/repo/src/RBDyn/Coriolis.cpp             /app/src/RBDyn/Coriolis.cpp
cp /tmp/repo/src/RBDyn/Jacobian.cpp             /app/src/RBDyn/Jacobian.cpp
cp /tmp/repo/src/RBDyn/NumericalIntegration.cpp /app/src/RBDyn/NumericalIntegration.cpp

cd /app
rm -rf /tmp/repo

# Write setup.sh -- test.sh will source this OFFLINE at grade time to
# compile the agent's .cpp files into .o files that link against the
# pre-baked fixture library.
#
#   /app/build/rbdyn_narrow/*.o   -> the 4 narrow RBDyn algorithm files
#
# --coverage puts gcov instrumentation on the agent's compilation units
# so test.sh's gcov aggregation reports line-coverage of the agent's own
# code (the fixture lib was built without --coverage and contributes 0
# gcov data).
cat > /app/setup.sh <<'EOF'
#!/bin/bash
set -e

BUILD=/app/build
mkdir -p "$BUILD/rbdyn_narrow"

COMMON_FLAGS=(
    -std=c++17 -O0 -g --coverage -fPIC
    -I/usr/local/include
    -I/usr/include/eigen3
    -DEIGEN_MPL2_ONLY
)

for src in /app/src/RBDyn/IDIM.cpp \
           /app/src/RBDyn/Coriolis.cpp \
           /app/src/RBDyn/Jacobian.cpp \
           /app/src/RBDyn/NumericalIntegration.cpp; do
    obj="$BUILD/rbdyn_narrow/$(basename "${src%.cpp}").o"
    g++ "${COMMON_FLAGS[@]}" -Drbdyn_EXPORTS -c "$src" -o "$obj"
done
EOF
chmod +x /app/setup.sh
