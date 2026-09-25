#!/bin/bash
# Ground-truth setup — the ONLY container in the WRG flow with internet on.
# Clones the reference bolt repo, then writes the offline `setup.sh` the
# grading container will source.
set -e

git clone https://github.com/Beariish/bolt.git /tmp/repo
cd /tmp/repo
git checkout 0b9e293612974f0af09142920713c100e3ad9418  # main HEAD, pinned

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

cat > ./setup.sh <<'EOF'
#!/bin/bash
# Offline build+install: uses cmake + gcc, both pre-baked in cpp_base.
set -e

# Bolt ships CMakeLists but NO install() rules, so we do a manual install
# of every public header + the built libbolt.a.
cmake -B /app/build -S /app -DCMAKE_BUILD_TYPE=Release
cmake --build /app/build -j"$(nproc)"

# Install the static library.
install -d /usr/local/lib
install -m 644 /app/build/bolt/libbolt.a /usr/local/lib/

# Install headers with the exact source-tree layout so
#   #include "bolt.h"
#   #include "boltstd/boltstd.h"
# both resolve without extra -I flags, and every transitive #include
# ("bt_context.h", "boltstd_core.h", "../bolt.h" from inside boltstd/,
# etc.) finds its neighbor.
install -d /usr/local/include
install -d /usr/local/include/boltstd
install -m 644 /app/bolt/bolt.h /usr/local/include/
install -m 644 /app/bolt/bt_buffer.h /usr/local/include/
install -m 644 /app/bolt/bt_compiler.h /usr/local/include/
install -m 644 /app/bolt/bt_config.h /usr/local/include/
install -m 644 /app/bolt/bt_context.h /usr/local/include/
install -m 644 /app/bolt/bt_debug.h /usr/local/include/
install -m 644 /app/bolt/bt_embedding.h /usr/local/include/
install -m 644 /app/bolt/bt_gc.h /usr/local/include/
install -m 644 /app/bolt/bt_object.h /usr/local/include/
install -m 644 /app/bolt/bt_op.h /usr/local/include/
install -m 644 /app/bolt/bt_parser.h /usr/local/include/
install -m 644 /app/bolt/bt_prelude.h /usr/local/include/
install -m 644 /app/bolt/bt_tokenizer.h /usr/local/include/
install -m 644 /app/bolt/bt_type.h /usr/local/include/
install -m 644 /app/bolt/bt_userdata.h /usr/local/include/
install -m 644 /app/bolt/bt_value.h /usr/local/include/
install -m 644 /app/bolt/boltstd/boltstd.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_arrays.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_core.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_io.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_math.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_meta.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_regex.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_strings.h /usr/local/include/boltstd/
install -m 644 /app/bolt/boltstd/boltstd_tables.h /usr/local/include/boltstd/

ldconfig
EOF
chmod +x ./setup.sh
