# Held-out grading harness for the rko_lio core. Compiles the agent's core implementation
# (sources + headers under <APP_DIR>/rko_lio/core) together with the held-out Catch2 test
# sources in this directory into a single `rko_lio_core_tests` executable.
#
# This is intentionally independent of the agent's own build system: it only requires that the
# core sources/headers exist at the documented paths and expose the documented public API. All
# dependencies (Eigen3, Sophus, TBB, tsl-robin-map, Catch2) are pre-baked in the per-task image
# and resolved via find_package — no network, no FetchContent.
#
# Results are emitted in CTRF JSON by a custom Catch2 reporter (ctrf_reporter.cpp) compiled into
# the binary, so grading is fully C++-native — no pytest layer. Run with:
#   ./rko_lio_core_tests --reporter ctrf --out /logs/verifier/ctrf.json
cmake_minimum_required(VERSION 3.22)
project(rko_lio_core_tests LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Root of the agent's generated repo (where rko_lio/core/* lives). Overridable via -DAPP_DIR=.
set(APP_DIR "/app" CACHE PATH "Path to the agent's generated repo root")

find_package(Eigen3 3.4 REQUIRED CONFIG)
find_package(Sophus REQUIRED CONFIG)
find_package(TBB REQUIRED CONFIG)
find_package(tsl-robin-map REQUIRED CONFIG)
find_package(Catch2 3 REQUIRED CONFIG)

# Agent's core implementation sources. May be empty for a header-only implementation (all logic
# inline in the .hpp under rko_lio/core); in that case the test TUs alone pull in the definitions,
# so we must NOT require any .cpp to exist.
file(GLOB CORE_SOURCES CONFIGURE_DEPENDS "${APP_DIR}/rko_lio/core/*.cpp")

# Held-out test sources (this directory) plus the CTRF reporter.
set(TEST_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/ctrf_reporter.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/test_interval_stats.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/test_voxel_down_sample.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/test_process_timestamps.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/test_preprocess_scan.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/test_imu_integration.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/test_register_scan.cpp)

add_executable(rko_lio_core_tests ${CORE_SOURCES} ${TEST_SOURCES})

# Test files include the core headers as "rko_lio/core/<h>.hpp" -> APP_DIR on the include path.
# Helper headers (eigen_approx.hpp, synthetic_clouds.hpp) live in this directory.
target_include_directories(rko_lio_core_tests PRIVATE "${APP_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}")

target_link_libraries(rko_lio_core_tests PRIVATE
    Eigen3::Eigen Sophus::Sophus TBB::tbb tsl::robin_map Catch2::Catch2WithMain)
