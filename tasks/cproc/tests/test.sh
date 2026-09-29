#!/bin/bash
# WRG verifier driver for the cproc task (offline).
# 1. Takes pristine copies of the pre-installed external tools (qbe, cpp, as,
#    ld) the compile pipeline is built on.
# 2. Sources the agent's ./setup.sh to build+install cproc + cproc-qbe.
# 3. Restores those tools — setup.sh must not be able to swap out the code
#    generator the pipeline-integrity test uses as its oracle — and then
#    withdraws the host C compilers' ability to translate C. instruction.md
#    allows them only for building the agent's own sources during setup.sh,
#    never for translating the programs under test. gcc's `cc1` keeps
#    answering preprocess-only (`-E`) invocations, which is how `cpp` runs,
#    and the gcc driver stays usable as an assembler/linker front end.
# 4. Runs pytest, which fans out per-test subprocesses that each write a
#    small C source, invoke `cproc source.c -o binary`, execute the binary,
#    and assert on exit code + stdout.
# No `set -e` — we need the reward logic below to capture pytest's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier

function emit_abort_ctrf {
  # Well-formed one-test CTRF for an abort that happens before pytest runs.
  echo "{\"results\":{\"tool\":{\"name\":\"pytest\"},\"summary\":{\"tests\":1,\"passed\":0,\"failed\":1,\"skipped\":0,\"pending\":0,\"other\":0,\"start\":0,\"stop\":0},\"tests\":[{\"name\":\"<setup>\",\"status\":\"failed\",\"message\":\"$1\"}]}}" \
    > /logs/verifier/ctrf.json
  echo 0 > /logs/verifier/reward.txt
}

# Copy the pre-installed toolchain aside. The digests stay in this shell's
# memory, so tampering with the copies themselves is detectable too.
VERIFIER_PRIV=$(mktemp -d /tmp/.cproc-verifier-XXXXXXXX)
chmod 700 "$VERIFIER_PRIV"
declare -A TOOL_PATH TOOL_SHA
for tool in qbe cpp as ld; do
  tool_path=$(command -v "$tool")
  [ -n "$tool_path" ] || continue
  TOOL_PATH[$tool]=$tool_path
  TOOL_SHA[$tool]=$(sha256sum < "$tool_path")
  cp -p "$tool_path" "$VERIFIER_PRIV/$tool"
done

# Build + install the agent's cproc binaries. setup.sh usually has its own
# `set -e`; that propagates via `source`, so an install/build failure here
# aborts BEFORE we can emit a well-formed CTRF. Disable -e after sourcing so
# we always reach the pytest run and CTRF emission below.
bash ./setup.sh
SETUP_EXIT=$?
set +e

if [ $SETUP_EXIT -ne 0 ]; then
  emit_abort_ctrf "setup.sh failed with exit code ${SETUP_EXIT}"
  exit 0
fi

for tool in "${!TOOL_PATH[@]}"; do
  if [ "$(sha256sum < "$VERIFIER_PRIV/$tool" 2>/dev/null)" != "${TOOL_SHA[$tool]}" ]; then
    emit_abort_ctrf "setup.sh tampered with the verifier's copy of the pre-installed ${tool}"
    exit 0
  fi
  if [ "$(sha256sum < "${TOOL_PATH[$tool]}" 2>/dev/null)" != "${TOOL_SHA[$tool]}" ]; then
    echo "verifier: ${TOOL_PATH[$tool]} was replaced during setup.sh; restoring the pre-installed ${tool}" >&2
    cp -p "$VERIFIER_PRIV/$tool" "${TOOL_PATH[$tool]}"
  fi
done
# The integrity tests drive the code generator through this copy, so no later
# PATH entry or in-place replacement can re-point them at a wrapper.
export CPROC_QBE_ORIG="$VERIFIER_PRIV/qbe"

# Withdraw C translation from the host compilers for the graded phase. A PATH
# shim would not do: a delegating implementation reaches /usr/bin/gcc by
# absolute path. gcc's compiler proper is wrapped so that only preprocessing
# survives, and clang — self-contained, no cc1 — loses its execute bits
# (execve needs at least one of them set, even for root).
cc1_count=0
for cc1 in /usr/lib/gcc/*/*/cc1 /usr/lib/gcc/*/*/cc1plus \
           /usr/libexec/gcc/*/*/cc1 /usr/libexec/gcc/*/*/cc1plus; do
  [ -x "$cc1" ] || continue
  [ "$(head -c 2 "$cc1")" = '#!' ] && continue
  cc1_count=$((cc1_count + 1))
  cc1_real="$VERIFIER_PRIV/cc1-$cc1_count"
  mv "$cc1" "$cc1_real"
  cat > "$cc1" <<EOF
#!/bin/sh
# Preprocessing only while the hidden tests run: a conforming cproc-qbe
# translates its own input.
for arg in "\$@"; do
  [ "\$arg" = "-E" ] && exec "$cc1_real" "\$@"
done
echo "cc1: compiling C is disabled during grading" >&2
exit 1
EOF
  chmod 755 "$cc1"
done
chmod a-x /usr/lib/llvm-*/bin/clang /usr/lib/llvm-*/bin/clang-[0-9]* \
          /usr/bin/tcc /usr/bin/tcc-* 2>/dev/null
unset CC CXX CPP CFLAGS CPPFLAGS CPATH C_INCLUDE_PATH

pytest --ctrf /logs/verifier/ctrf.json /tests/test_cproc.py -v --timeout=60 -rA
TEST_EXIT=$?

if [ $TEST_EXIT -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
