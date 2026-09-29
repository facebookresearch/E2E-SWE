#!/bin/bash
# GROUND TRUTH for the binjgb WRG task.
# Runs only during GT eval (Container A, which has Internet for the clone); the
# agent never sees this file. Container B (grading) is offline.
set -e

git clone https://github.com/binji/binjgb.git /tmp/repo
cd /tmp/repo
git checkout c60e138da5a795ebb55e56b11b7e90024e41112c

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Build the headless tester binary offline. The tester needs only 6 C files
# from src/ (memory, common, options, emulator, joypad, tester); it links no
# external libraries beyond libc. This bypasses CMake's SDL2/OpenGL search
# entirely, so no imgui submodule is required.
cat > ./setup.sh <<'__BINJGB_SETUP_EOF__'
#!/bin/bash
set -e
mkdir -p bin
cc -O2 -Isrc \
   -Wno-unused-parameter -Wno-unused-function -Wno-unused-variable \
   -Wno-implicit-fallthrough \
   -o bin/binjgb-tester \
   src/memory.c src/common.c src/options.c src/emulator.c \
   src/joypad.c src/tester.c
__BINJGB_SETUP_EOF__
chmod +x ./setup.sh
