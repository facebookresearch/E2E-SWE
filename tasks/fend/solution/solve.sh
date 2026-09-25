#!/bin/bash
set -e

# git is pre-baked in the per-task image. This clone is the ONLY network operation in the GT flow
# (GT eval keeps internet on in Container A for it; the grading container is offline).
git clone https://github.com/printfn/fend.git /tmp/repo
cd /tmp/repo
git checkout 74f325f8df9d3188c1e691dc830c1e9093783530

# Assemble the groundtruth /app: the real fend-core engine (lives at core/ in the repo) plus a
# thin CLI wrapper that implements the task's binary contract:
#   fend "<expression>"  ->  prints get_main_result() to stdout (+ newline), exit 0
#   on evaluation error   ->  prints the error message to stderr, exit 1
mkdir -p /app/fend-core /app/src
cp -a /tmp/repo/core/. /app/fend-core/
rm -rf /tmp/repo

# fend-core's manifest inherits 8 fields from the fend repo's workspace root (which we did not
# copy). Make /app the workspace root and supply those inherited fields via [workspace.package].
cat > /app/Cargo.toml <<'EOF'
[workspace]
members = ["fend-core"]
resolver = "2"

[workspace.package]
version = "1.5.8"
description = "fend-core"
edition = "2024"
repository = "https://github.com/printfn/fend"
homepage = "https://github.com/printfn/fend"
keywords = ["calculator"]
categories = ["mathematics"]
license = "MIT"

[package]
name = "fendcli"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "fend"
path = "src/main.rs"

[dependencies]
fend-core = { path = "fend-core" }
EOF

cat > /app/src/main.rs <<'EOF'
use std::env;
use std::process::exit;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!("usage: fend <expression>");
        exit(2);
    }
    let mut ctx = fend_core::Context::new();
    match fend_core::evaluate(&args[1], &mut ctx) {
        Ok(res) => {
            println!("{}", res.get_main_result());
        }
        Err(e) => {
            eprintln!("{e}");
            exit(1);
        }
    }
}
EOF

cd /app

# setup.sh installs/builds the project offline in the (no-network) grading container. The image
# bakes the Rust toolchain and sets CARGO_NET_OFFLINE=true; the engine + wrapper are std-only so
# the build resolves entirely locally. Installs the `fend` binary onto PATH for the tests.
cat > ./setup.sh <<'EOF'
#!/bin/bash
set -e
cargo build --release --offline
cp target/release/fend /usr/local/bin/fend
EOF
chmod +x ./setup.sh
