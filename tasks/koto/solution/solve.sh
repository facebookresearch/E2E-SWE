#!/bin/bash
set -e

# =============================================================================
# GROUND-TRUTH assembly for the koto WRG task.
#
# Reimplements koto-lang/koto (embeddable scripting language, Rust) pinned to
# tag v0.16.1 == SHA 0de8f08762a8643215d7aa8eb7c89ceef4765117.
#
# This runs in the GT-eval Container A, which HAS network. It clones koto, trims the
# workspace to the in-scope crates, and `cargo vendor`s the dependencies into
# /app/vendor (+ /app/.cargo/config.toml). Grading then runs in a SEPARATE OFFLINE
# container against this /app, so setup.sh builds `--offline` against the vendored
# sources that travel with /app. (The agent's own solution is std-only, so it needs
# no vendored deps — this vendoring is only for the GT build of real koto.)
#
# The grading contract is BLACK-BOX on script output: the deliverable is a cargo
# package named `koto` exposing `Koto::default().compile_and_run(&str)` plus the
# @display / value_to_string rendering protocol. The hidden test
# (tests/koto_grading.rs) drives ONLY that public API.
# =============================================================================

PIN=0de8f08762a8643215d7aa8eb7c89ceef4765117
git clone https://github.com/koto-lang/koto.git /tmp/repo
cd /tmp/repo
git checkout "$PIN"

# -----------------------------------------------------------------------------
# Trim the 11-crate workspace to the IN-SCOPE core-language subset. Grading is
# black-box, so we keep only what the real `koto` facade needs to build + run
# scripts, and drop tooling / host-integration / embedding libs.
#
#   IN : lexer, parser, bytecode, runtime, koto (facade), memory, derive
#        (derive is a build-time necessity: runtime uses #[koto_method] ~53x and
#        will not compile without it. It is NOT in GRADING scope — the agent may
#        build core-lib without macros — but the GT source needs it to build.)
#   OUT: cli, format, serde, test_utils, libs/* (8 embedding libs), examples
# -----------------------------------------------------------------------------
rm -rf /tmp/repo/crates/cli \
       /tmp/repo/crates/format \
       /tmp/repo/crates/serde \
       /tmp/repo/crates/test_utils \
       /tmp/repo/libs \
       /tmp/repo/crates/koto/examples

# Rewrite the [workspace] members (and default-members, if present) to the
# explicit in-scope list, dropping the `crates/koto/examples/*` and `libs/*`
# globs that now point at removed dirs; AND strip every in-scope member's
# [dev-dependencies] table. The dev-deps reference removed crates (e.g.
# crates/koto dev-deps on koto_test_utils + koto_geometry, which live under the
# removed test_utils/ and libs/ dirs) — and cargo resolves ALL workspace dev-deps
# even when only one integration test runs, so leaving them breaks resolution.
# The hidden grader (koto_grading.rs) uses ONLY the public `koto` crate, so no
# member needs dev-deps at grading time. Regex edits (tomllib is read-only in
# 3.11, and a toml writer may not be installed in the base image).
python3 - <<'PYEOF'
import re, pathlib
IN_SCOPE = ["lexer", "parser", "bytecode", "runtime", "koto", "memory", "derive"]

root = pathlib.Path("/tmp/repo/Cargo.toml")
s = root.read_text()
members = (
    '[\n'
    '    "crates/lexer",\n'
    '    "crates/parser",\n'
    '    "crates/bytecode",\n'
    '    "crates/runtime",\n'
    '    "crates/koto",\n'
    '    "crates/memory",\n'
    '    "crates/derive",\n'
    ']'
)
s, n = re.subn(r'members\s*=\s*\[.*?\]', 'members = ' + members, s, count=1, flags=re.DOTALL)
assert n == 1, "did not find [workspace] members array to trim"
s = re.sub(r'default-members\s*=\s*\[.*?\]', 'default-members = ' + members, s, count=1, flags=re.DOTALL)
root.write_text(s)
print("trimmed workspace members to in-scope crates")

# Strip the [dev-dependencies] table from each in-scope member manifest: delete
# from the "[dev-dependencies]" header up to the next TABLE header (a line starting
# with "[") or EOF. Must NOT stop at a "[" inside a value (e.g. features = ["x"]),
# so the stop is a line-initial "[" via the (?m)^\[ lookahead.
dev_re = re.compile(r'(?ms)^\[dev-dependencies\].*?(?=^\[|\Z)')
bench_re = re.compile(r'(?ms)^\[\[bench\]\].*?(?=^\[|\Z)')
for name in IN_SCOPE:
    mp = pathlib.Path(f"/tmp/repo/crates/{name}/Cargo.toml")
    if not mp.exists():
        continue
    ms = mp.read_text()
    ms, k = dev_re.subn("", ms)
    if k:
        print(f"stripped [dev-dependencies] from crates/{name}/Cargo.toml")
    # Strip [[bench]] targets — they need the (removed) criterion dev-dep.
    ms, kb = bench_re.subn("", ms)
    if kb:
        print(f"stripped [[bench]] from crates/{name}/Cargo.toml")
    mp.write_text(ms)

# crates/koto has an OPTIONAL koto_serde dep (path ../serde, removed) gated behind
# the `serde` default feature. Drop the dep, the feature, and serde from defaults so
# the manifest resolves without crates/serde. Grading never uses serde.
kp = pathlib.Path("/tmp/repo/crates/koto/Cargo.toml")
ks = kp.read_text()
ks = re.sub(r'(?m)^koto_serde\s*=.*\n', '', ks)          # optional dependency line
ks = re.sub(r'(?m)^serde\s*=\s*\[[^\]]*\]\s*\n', '', ks)  # `serde = ["koto_serde"]` feature
ks = re.sub(r'default\s*=\s*\[[^\]]*\]',
            'default = ["rc"]', ks, count=1)              # drop "serde" from defaults
kp.write_text(ks)
print("removed koto_serde dep + serde feature from crates/koto/Cargo.toml")
PYEOF

# Assemble /app from the trimmed workspace.
mkdir -p /app
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo /app/.git

# Vendor all dependencies NOW, while this container still has network. Grading
# runs in a SEPARATE offline container against this /app, so the vendored sources
# must travel with it. `cargo vendor` writes the source-replacement config to
# /app/.cargo/config.toml so subsequent `cargo build --offline` needs no network.
mkdir -p /app/.cargo
cargo vendor /app/vendor > /app/.cargo/config.toml

# setup.sh is SOURCED (not executed) by tests/test.sh — it must NOT call `exit`.
# It builds the `koto` package OFFLINE against the vendored deps produced above
# (/app/vendor + /app/.cargo/config.toml). The grading container has no network.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
export CARGO_NET_OFFLINE=true
export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/target}"
# Build only the facade package + its dependency crates (lexer/parser/bytecode/
# runtime/memory/derive), fully offline via the vendored sources.
cargo build --offline -p koto --lib || return 1
EOF
chmod +x /app/setup.sh
