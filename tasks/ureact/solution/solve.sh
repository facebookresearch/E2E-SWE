#!/bin/bash
# Ground-truth setup. Runs with Internet (clone allowed); writes /app/setup.sh (which
# runs offline at grade time) installing the reactive-core headers so the test compiles
# against -I/usr/local/include with the umbrella header <ureact/ureact.hpp>.
set -e

git clone https://github.com/YarikTH/ureact.git /tmp/repo
cd /tmp/repo
git checkout 6639e6860b21e2a3e4ae3f67e9e6afb4c5681251

mkdir -p /app/repo
cp -r /tmp/repo/include /app/repo/include

cat > /app/setup.sh <<'SETUP'
#!/bin/bash
# Installs the header-only reactive library to /usr/local/include (offline).
set -e
mkdir -p /usr/local/include
cp -r /app/repo/include/ureact /usr/local/include/ureact

# Umbrella header the test includes as <ureact/ureact.hpp>.
cat > /usr/local/include/ureact/ureact.hpp <<'UMBRELLA'
#ifndef UREACT_UMBRELLA_HPP
#define UREACT_UMBRELLA_HPP
#include <ureact/signal.hpp>
#include <ureact/events.hpp>
#include <ureact/transaction.hpp>
#include <ureact/observer.hpp>
#include <ureact/adaptor/lift.hpp>
#include <ureact/adaptor/observe.hpp>
#include <ureact/adaptor/flatten.hpp>
#include <ureact/adaptor/fold.hpp>
#include <ureact/adaptor/merge.hpp>
#include <ureact/adaptor/hold.hpp>
#include <ureact/adaptor/filter.hpp>
#include <ureact/adaptor/transform.hpp>
#include <ureact/adaptor/snapshot.hpp>
#include <ureact/adaptor/count.hpp>
#endif
UMBRELLA
SETUP
chmod +x /app/setup.sh
