#!/bin/bash
set -e

# Assemble the groundtruth /app from the reference implementation:
# github.com/cberner/raptorq (pinned release tag v2.0.1 == crate 2.0.1). The clone is the ONLY
# network operation in the GT flow — GT eval keeps internet on in Container A for it; the grading
# container is offline.
PIN=v2.0.1
git clone https://github.com/cberner/raptorq.git /tmp/repo
cd /tmp/repo
git checkout "$PIN"

# The task surface is the pure-Rust library crate (`src/`). Copy it into /app and drop everything
# else upstream (benches/, examples/, the PyO3 bindings + maturin packaging, CI config, the
# upstream Cargo.toml). The crate's own `#[cfg(test)]` unit tests are NOT compiled when running a
# single integration-test target, so they need no dev-dependencies. The hidden suite replaces all
# upstream testing.
mkdir -p /app/src
cp /tmp/repo/src/*.rs /app/src/

# Minimal manifest: a `raptorq` lib crate, default = ["std"], ZERO dependencies. The no-op feature
# declarations match the cfg names used in the source so compilation is warning-clean; none of them
# pull a crate, and only `std` is enabled by default.
cat > /app/Cargo.toml <<'EOF'
[package]
name = "raptorq"
version = "2.0.1"
edition = "2024"

[lib]
crate-type = ["lib"]

[features]
default = ["std"]
std = []
serde_support = []
benchmarking = ["std"]
python = []
EOF

cd /app
rm -rf /tmp/repo

# setup.sh is SOURCED (not executed) by the grading harness — it must not call `exit`. It performs
# the OFFLINE build of the crate. The image bakes the toolchain and forces CARGO_NET_OFFLINE, and
# the crate has zero third-party deps, so this needs no network. This mirrors what the agent is
# expected to produce.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
export CARGO_NET_OFFLINE=true
export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/target}"
cargo build --offline --lib || return 1
EOF
chmod +x /app/setup.sh
