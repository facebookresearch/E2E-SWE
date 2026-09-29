#!/bin/bash
set -e

# git is pre-baked in the per-task image (environment/Dockerfile). This clone is the ONLY network
# operation in the GT flow (GT eval keeps internet on for it; the grading container is offline).
git clone https://github.com/PRBonn/rko_lio.git /tmp/repo
cd /tmp/repo
git checkout 41f4f502dc4bbae437ba8d01ef0a44a3dfe4618e

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh builds the C++ core library OFFLINE against the pre-baked dependencies
# (Eigen3, Sophus, TBB, tsl-robin-map are installed in the image; RKO_LIO_FETCH_CONTENT_DEPS=OFF
# so CMake uses find_package instead of fetching). ROS and the C++ test target are disabled — the
# grader compiles the held-out Catch2 tests against /app/rko_lio/core separately (see tests/test.sh).
cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
cmake -S /app -B /app/build \
    -DCMAKE_BUILD_TYPE=Release \
    -DRKO_LIO_BUILD_ROS=OFF \
    -DRKO_LIO_BUILD_TESTS=OFF \
    -DRKO_LIO_FETCH_CONTENT_DEPS=OFF
cmake --build /app/build -j --target rko_lio.core
EOF
