#!/bin/bash
# Ground-truth setup. Runs with Internet (the clone is the only network operation); writes a
# setup.sh that builds OFFLINE but does not run it — test.sh runs `source ./setup.sh` in the
# offline grading container.
#
# The reference sources use a `Zopfli`/`ZOPFLI` symbol prefix; the task's public API uses a neutral
# `Deflopt`/`DEFLOPT` prefix (to describe the goal without cueing the upstream project). We apply a
# consistent identifier rename to the clone before building — a pure rename, functionally identical.
# Scope: the core library (src/zopfli/) + the CLI; the PNG optimizer (src/zopflipng/) is not built.
# Zero third-party deps (libc + libm only), so setup.sh compiles directly with gcc — no network.
set -e

git clone https://github.com/google/zopfli.git /tmp/repo
cd /tmp/repo
git checkout ccf9f0588d4a4509cb1040310ec122243e670ee6

# Consistent public-symbol rename across the core sources (Zopfli -> Deflopt, ZOPFLI -> DEFLOPT).
sed -i 's/Zopfli/Deflopt/g; s/ZOPFLI/DEFLOPT/g' src/zopfli/*.c src/zopfli/*.h

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh builds the two artifacts the tests use, OFFLINE, from the (renamed) core sources only:
#   /app/deflopt        - the CLI binary (all core sources, incl. the one that defines main())
#   /app/libdeflopt.so  - the shared library (core sources without the CLI's main) for ctypes
cat > setup.sh <<'SETUP'
#!/bin/bash
set -e
cd /app
gcc src/zopfli/*.c -O2 -W -Wall -Wextra -Wno-unused-function -lm -o deflopt
gcc -shared -fPIC \
    src/zopfli/blocksplitter.c src/zopfli/cache.c src/zopfli/deflate.c \
    src/zopfli/gzip_container.c src/zopfli/hash.c src/zopfli/katajainen.c \
    src/zopfli/lz77.c src/zopfli/squeeze.c src/zopfli/tree.c src/zopfli/util.c \
    src/zopfli/zlib_container.c src/zopfli/zopfli_lib.c \
    -lm -o libdeflopt.so
SETUP
chmod +x setup.sh
