#!/bin/bash
# Ground-truth setup for the owl WRG task. Runs in the GT container (which
# has Internet); clones the reference repository, materializes it under
# /app, and writes an OFFLINE setup.sh that the grader runs to build the
# reference binary. The setup.sh itself must not need any network access.
set -e

git clone https://github.com/ianh/owl.git /tmp/repo
cd /tmp/repo
# Pin to the exact commit the task was authored against so the GT output is
# reproducible. If this commit ever disappears from the upstream, un-pin by
# removing the checkout line — any tip revision is compatible with the spec
# (grammar.owl locks the DSL format to owl.v4).
git checkout f9aba9d2842fe2b74f8a2bd4b7d5976bf41aa93e
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo .git

cat > setup.sh <<'SETUP'
#!/bin/bash
# Offline build for the owl reference. No network. The reference repo's
# plain top-level Makefile compiles src/*.c into ./owl with gcc + libc + -ldl.
set -e
make
SETUP
chmod +x setup.sh
