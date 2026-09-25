# Held-out test harness for the yaff WRG task. NOT shipped to the agent.
#
# yaff's carve is HEADER-ONLY (the zero-copy runtime under include/yaff/), so the held-out
# tests #include the agent's headers directly. Grading depends only on the include layout fixed
# by instruction.md (public headers under include/yaff/...), not on the agent's build files.
#
# Each component test file is compiled into its OWN binary (component_test.cpp + the doctest
# main). This isolates compilation: a template/signature mismatch that only one component
# instantiates fails only that component's binary, so the remaining components still grade and
# yield real partial credit — instead of one error zeroing the whole suite.
cmake_minimum_required(VERSION 3.14)
project(yaff_tests LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

if(NOT DEFINED APP_DIR)
    set(APP_DIR "/app")
endif()
# Include root holding the carve's headers (its child is yaff/). test.sh locates it robustly
# (the agent may nest it, e.g. /app/repo/include) and passes APP_INCLUDE; fall back to /app/include.
if(NOT DEFINED APP_INCLUDE)
    set(APP_INCLUDE "${APP_DIR}/include")
endif()
message(STATUS "yaff_tests: using include root ${APP_INCLUDE}")

set(MAIN_SRC "${CMAKE_CURRENT_SOURCE_DIR}/cpp/test_main.cpp")
# Custom doctest reporter that emits CTRF JSON directly (replaces the old pytest wrapper).
# Linked into every component binary; registered via DOCTEST_REGISTER_REPORTER("ctrf", ...).
set(CTRF_SRC "${CMAKE_CURRENT_SOURCE_DIR}/cpp/ctrf_reporter.cpp")

# One binary per component test file (named after its stem, e.g. test_flat).
file(GLOB COMPONENT_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/cpp/test_*.cpp")
list(REMOVE_ITEM COMPONENT_SOURCES "${MAIN_SRC}")

foreach(src ${COMPONENT_SOURCES})
    get_filename_component(stem "${src}" NAME_WE)   # e.g. test_flat
    add_executable(${stem} "${src}" "${MAIN_SRC}" "${CTRF_SRC}")
    target_include_directories(${stem} PRIVATE
        "${APP_INCLUDE}"                         # the carve's public headers (yaff/...)
        "${CMAKE_CURRENT_SOURCE_DIR}/compat"     # fallback yaff/version.h (build trivia)
        "${CMAKE_CURRENT_SOURCE_DIR}"            # bundled doctest.h
    )
endforeach()
