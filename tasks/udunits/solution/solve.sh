#!/bin/bash
# Ground-truth setup. Runs with Internet (clone allowed); writes setup.sh (which
# must build OFFLINE) but does not run it. The tested surface is the core unit
# algebra + converter engine, so setup.sh compiles just those sources (XML loader
# and grammar are out of scope) — no expat/bison/flex needed.
set -e

git clone https://github.com/Unidata/UDUNITS-2.git /tmp/repo
cd /tmp/repo
git checkout v2.2.28
cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

cat > setup.sh <<'SETUP'
#!/bin/bash
set -e
mkdir -p /usr/local/include /usr/local/lib

# Minimal config.h so the core sources compile standalone (the autotools/cmake
# config.h is not needed for the tested core; XML/parser sources are excluded).
cat > lib/config.h <<'CFG'
#ifndef UDUNITS_CONFIG_H
#define UDUNITS_CONFIG_H
#define _GNU_SOURCE 1
#define _DEFAULT_SOURCE 1
#define HAVE_STRDUP 1
#define HAVE_STRCASECMP 1
#define HAVE_UNISTD_H 1
#define STDC_HEADERS 1
#endif
CFG

cd lib
cc -O2 -fPIC -shared -I. \
    converter.c error.c formatter.c idToUnitMap.c prefix.c status.c \
    systemMap.c unitAndId.c unitcore.c unitToIdMap.c ut_free_system.c \
    -lm -o /usr/local/lib/libudunits2.so
cp udunits2.h converter.h /usr/local/include/
ldconfig
SETUP
chmod +x setup.sh
