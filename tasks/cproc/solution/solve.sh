#!/bin/bash
# Ground-truth setup — the ONLY container in the WRG flow with internet on.
# Clones the reference cproc repo, then writes the offline `setup.sh` the
# grading container will source.
set -e

git clone https://github.com/michaelforney/cproc.git /tmp/repo
cd /tmp/repo
# Pinned to master HEAD as of the task brief. Subject: "qbe: Use extern for
# globals with external linkage". Requires a QBE that recognises the `extern`
# prefix in QBE IL — QBE v1.3 (baked in the image at SHA c0818978ac,
# dated 2026-05-13) already supports it.
git checkout d1c53ddf56571573a7025324c8dd5c6d547a4d1f

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

cat > ./setup.sh <<'EOF'
#!/bin/bash
# Offline build+install: uses gcc + POSIX make + configure, all pre-baked in
# cpp_base. External runtime deps (qbe, cpp, as, ld) are installed in the
# per-task image; cproc's own driver invokes them.
set -e

# Generate config.h + config.mk for the host system. cproc's configure is a
# small POSIX shell script that emits string arrays of the toolchain paths
# (preprocesscmd, codegencmd, assemblecmd, linkcmd) into config.h.
./configure

# Build the driver (cproc) and the frontend (cproc-qbe).
make -j"$(nproc)"

# Install to /usr/local/bin/. Tests invoke `cproc source.c -o binary` from
# a temp dir, so both binaries must be on PATH.
install -d /usr/local/bin
install -m 755 ./cproc     /usr/local/bin/
install -m 755 ./cproc-qbe /usr/local/bin/
EOF
chmod +x ./setup.sh
