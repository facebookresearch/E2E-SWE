#!/bin/bash
set -e

# Ground-truth solution for the rxdisasm task. The GT wraps the real reference decoder
# (yaxpeax-x86) as a LIBRARY and exposes exactly the CLI contract the agent must reproduce:
# read hex bytes (one instruction per line) from stdin, decode one x86-64 (long mode)
# instruction, print its yaxpeax textual disassembly.
#
# git + the Rust toolchain are pre-baked in the image. This GT solve runs in Container A
# (internet ON); the grading Container B is offline and builds from the vendor/ dir shipped
# to /app. The agent, using only the Rust standard library, writes its own std-only decoder.

# 1. Clone the reference decoder at the pinned commit.
git clone https://github.com/iximeow/yaxpeax-x86 /tmp/yaxpeax-x86
cd /tmp/yaxpeax-x86
git checkout 43a6554770d6bfd74c05d37af772e0a65ef54ab1

# 2. Build a thin CLI wrapper crate that path-depends on the library and prints Display.
mkdir -p /tmp/wrap/src
cat > /tmp/wrap/Cargo.toml <<'CARGO'
[package]
name = "rxdisasm"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "rxdisasm"
path = "src/main.rs"

[dependencies]
yaxpeax-x86 = { path = "/tmp/yaxpeax-x86", default-features = false, features = ["std", "fmt"] }

[profile.release]
opt-level = 3
CARGO

cat > /tmp/wrap/src/main.rs <<'RUST'
use std::io::{self, BufRead, Write};
use yaxpeax_x86::long_mode::InstDecoder;

fn hex_to_bytes(s: &str) -> Result<Vec<u8>, String> {
    let cleaned: String = s.chars().filter(|c| !c.is_whitespace()).collect();
    if cleaned.len() % 2 != 0 { return Err("odd hex length".into()); }
    let b = cleaned.as_bytes();
    let mut out = Vec::with_capacity(b.len() / 2);
    let mut i = 0;
    while i < b.len() {
        let hi = (b[i] as char).to_digit(16).ok_or("bad hex")?;
        let lo = (b[i + 1] as char).to_digit(16).ok_or("bad hex")?;
        out.push((hi * 16 + lo) as u8);
        i += 2;
    }
    Ok(out)
}

fn main() {
    let decoder = InstDecoder::default();
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line.unwrap();
        let line = line.trim();
        if line.is_empty() { continue; }
        match hex_to_bytes(line) {
            Ok(bytes) => match decoder.decode_slice(&bytes) {
                Ok(inst) => { writeln!(out, "{}", inst).unwrap(); }
                Err(e) => { writeln!(out, "ERR: {}", e).unwrap(); }
            },
            Err(e) => { writeln!(out, "ERR: {}", e).unwrap(); }
        }
    }
}
RUST

# 3. Vendor third-party crates over Container A's network and point cargo at them.
cd /tmp/wrap
cargo vendor vendor > /tmp/cargo-vendor-config
mkdir -p .cargo
cat >> .cargo/config.toml <<'CARGOCFG'
[source.crates-io]
replace-with = "vendored-sources"
[source.vendored-sources]
directory = "vendor"
CARGOCFG

# 4. Ship the wrapper crate (incl. the path-dep repo, vendor/ and .cargo/) under /app/src so the
#    built binary path /app/rxdisasm does not collide with any repo dir of the same name.
mkdir -p /app/src/yaxpeax-x86
cp -a /tmp/wrap/. /app/src/
cp -a /tmp/yaxpeax-x86/. /app/src/yaxpeax-x86/
# Rewrite the path dep to the shipped copy so the offline build resolves it.
sed -i 's#path = "/tmp/yaxpeax-x86"#path = "yaxpeax-x86"#' /app/src/Cargo.toml
rm -rf /tmp/wrap /tmp/yaxpeax-x86

# 5. Offline build from the shipped vendor/ dir. Produces /app/rxdisasm — exactly the artifact
#    the agent must produce (the agent writes its own std-only build).
cat > /app/setup.sh <<'SETUP'
cd /app/src && cargo build --release --offline
cp /app/src/target/release/rxdisasm /app/rxdisasm
SETUP
