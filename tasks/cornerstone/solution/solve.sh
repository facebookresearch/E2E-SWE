#!/bin/bash
# GROUND TRUTH for the cornerstone WRG task. Runs in an internet-enabled
# container, clones upstream at the pinned commit,
# initialises the ASIO submodule, and writes an offline setup.sh that the
# grader will `source` after this container ends.
#
# The base image ships gcc/g++/cmake/python3/git/build-essential/gtest and
# asio. Nothing else needed.
set -e

git clone https://github.com/datatechnology/cornerstone.git /tmp/repo
cd /tmp/repo
git checkout eb053fcff3ffa271be2c5f31d6a58c511b493f85
# ASIO is a git submodule; init it here (only script with Internet).
git submodule update --init --recursive

# ---------------------------------------------------------------------------
# Defensive null-guard for raft_server::request_append_entries(peer&).
#
# Upstream `create_append_entries_req` at src/raft_server.cxx:664-670 returns
# `ptr<req_msg>()` (a null shared_ptr) after calling `state_mgr->system_exit(-1)`
# when the leader's tracked `peer.next_log_idx` briefly exceeds its own
# `log_store->next_slot()` — a legitimate but rare race that opens during the
# snapshot install pipeline for a late-catching follower.
#
# The upstream code path assumes `system_exit(-1)` terminates the process,
# but upstream's OWN test state_mgrs (`in_memory_state_mgr` in
# tests/src/test_impls.cxx:216 and `simple_state_mgr` in
# tests/src/test_everything_together.cxx:91) are BOTH pure no-ops
# (`std::cout << ... << std::endl;`). So even under upstream's own tests,
# the process continues, the null `req` propagates into `peer::send_req`,
# and crashes on `req->get_commit_idx()` inside sstrfmt logging. Upstream
# tests never trigger this because they don't exercise the snapshot install
# pipeline.
#
# The patch adds a one-line defensive guard: if `create_append_entries_req`
# returned null, release the `busy_flag_` we just claimed (via `p.set_free()`,
# the exact counterpart of `p.make_busy()`) and return false so the natural
# heartbeat retry loop re-issues the append on the next tick.
#
# NON-ERROR PATH UNCHANGED: the guard fires only when msg is null, which is
# exactly the case where upstream would otherwise SIGSEGV.
# ---------------------------------------------------------------------------
git apply <<'PATCH_EOF'
--- a/src/raft_server.cxx
+++ b/src/raft_server.cxx
@@ -362,6 +362,7 @@ bool raft_server::request_append_entries(peer& p)
     if (p.make_busy())
     {
         ptr<req_msg> msg = create_append_entries_req(p);
+        if (!msg) { p.set_free(); return false; }
         p.send_req(msg, resp_handler_);
         return true;
     }
PATCH_EOF

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# The agent's setup.sh must install cornerstone's public headers and static
# library so the grader's g++ driver resolves `#include <cornerstone/cornerstone.hxx>`
# and links `-lcornerstone` without any -I / -L flags. Headers install to
# /usr/local/include/cornerstone/, static library to /usr/local/lib/libcornerstone.a.
#
# We build cornerstone as a static library from src/*.cxx against the vendored
# ASIO submodule at ./asio/asio/include (the system libasio-dev at
# /usr/include/asio.hpp is IDENTICAL 1.22.1, so either would work — we use the
# submodule to keep GT closer to upstream's build recipe).
cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e

BUILD_DIR="/tmp/cornerstone_build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Compile every src/*.cxx into position-independent objects and archive them.
# -DASIO_STANDALONE and -DASIO_HAS_STD_CHRONO match cornerstone's own
# add_definitions(). -I include/ for cornerstone's own headers, -I asio/asio/include
# for the ASIO submodule.
CXX_FLAGS="-std=c++17 -O2 -fPIC -Wall -Wextra -DASIO_STANDALONE -DASIO_HAS_STD_CHRONO"
INCLUDES="-I/app/include -I/app/asio/asio/include"

for src in /app/src/*.cxx; do
    obj="$BUILD_DIR/$(basename "$src" .cxx).o"
    g++ $CXX_FLAGS $INCLUDES -c "$src" -o "$obj"
done

ar rcs "$BUILD_DIR/libcornerstone.a" "$BUILD_DIR"/*.o

# Install: headers under /usr/local/include/cornerstone/, static lib under
# /usr/local/lib/. ldconfig is not needed for a .a static archive.
install -d /usr/local/include/cornerstone
install -m 644 /app/include/*.hxx /usr/local/include/cornerstone/
install -d /usr/local/lib
install -m 644 "$BUILD_DIR/libcornerstone.a" /usr/local/lib/libcornerstone.a
EOF
chmod +x ./setup.sh
