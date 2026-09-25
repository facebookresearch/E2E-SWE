#!/bin/bash
# Ground-truth setup — the ONLY container in the WRG flow with internet on.
# Clones the reference packcc repo, then writes the offline `setup.sh` the
# grading container will source.
set -e

git clone https://github.com/arithy/packcc.git /tmp/repo
cd /tmp/repo
git checkout 78e65e69784a9696f065ed7a9c453a66f8685409  # pinned commit — see .task-journal.json

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

cat > ./setup.sh <<'EOF'
#!/bin/bash
# Offline build+install: packcc is a single .c file compiled with gcc.
# Its imports directory ships bundled reusable grammar fragments; we install
# them at packcc's compiled-in IMPORT_DIR_SYSTEM (/usr/share/packcc/import)
# so `%import "char/ascii_character_group.peg"` works with no -I flag or
# PCC_IMPORT_PATH env-var.
set -e

# Build packcc itself. Upstream default flags include the whole strict-C90
# --with-sanitizer set; here we use a plain -O2 build so the binary is fast
# and doesn't drag in libasan/libubsan (which would need runtime libs on
# every child invocation).
# `-D_POSIX_C_SOURCE=200809L` exposes POSIX declarations (strnlen, fileno)
# the source relies on but does not declare itself. `-std=c99` accepts the
# source's occasional mixed declarations-and-code (which strict C90 rejects
# under -pedantic).
gcc -O2 -std=c99 -D_POSIX_C_SOURCE=200809L \
    -o /usr/local/bin/packcc /app/src/packcc.c

# Install the bundled import files at the compiled-in system path so
# %import resolves without any -I flag.
install -d /usr/share/packcc/import
cp -a /app/import/. /usr/share/packcc/import/
EOF
chmod +x ./setup.sh
