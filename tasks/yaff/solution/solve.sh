#!/bin/bash
set -e
# Ground-truth solver. Runs ONLY during `--mode=evaluate_gt`, in the GT clone
# container (the one place internet is allowed, for the git clone below). It
# populates /app with the reference implementation of the carve — the yaff
# header-only zero-copy runtime — laid out exactly as instruction.md requires
# (public headers under include/yaff/...).

# git is pre-baked in the per-task image. This clone is the ONLY network op in GT.
git clone https://github.com/yandex/yaff.git /tmp/repo
cd /tmp/repo
git checkout d6f74675374b587ce24112c284abd54a92090221   # pinned for reproducibility

# --- Carve out exactly the runtime header subsystem into /app ---
mkdir -p /app/include/yaff

# The zero-copy runtime (header-only). NEVER include the protoc plugin / compiler
# (src/) or the reflection/visitor/any_* headers — those are out of carve scope.
cp include/yaff/base.h       /app/include/yaff/
cp include/yaff/buffer.h     /app/include/yaff/
cp include/yaff/array.h      /app/include/yaff/
cp include/yaff/message.h    /app/include/yaff/
cp include/yaff/serializer.h /app/include/yaff/
cp include/yaff/util.h       /app/include/yaff/
cp include/yaff/yaff.h       /app/include/yaff/

cd /app
rm -rf /tmp/repo

# The held-out harness compiles /tests against /app/include directly (and supplies
# yaff/version.h itself), so no build/install step is needed. setup.sh is kept as a
# trivial no-op for symmetry with the WRG offline contract.
echo ': # yaff: header-only carve; tests compile against /app/include directly' > ./setup.sh
