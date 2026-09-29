#!/bin/bash
set -e

# Ground-truth solution for the chunkbits task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE RoaringBitmap core-module source as the agent's deliverable, ALIASED so the agent
# never sees the origin library name, and writes the offline build script.
#
# Pinned to the 1.6.14 release tag (Java 8 source -> compiles on the JDK 17 base in classpath mode).
# The core `roaringbitmap` module has ZERO external runtime dependencies (pure Java on the JDK); the
# JUnit/guava/kryo/jackson/assertj deps are test-only and are NOT part of the deliverable.

git clone https://github.com/RoaringBitmap/RoaringBitmap.git /tmp/repo
cd /tmp/repo
git checkout 1.6.14

# The agent's deliverable = the whole core `roaringbitmap` module (all packages under
# org/roaringbitmap/**: root 32-bit core, .buffer mmap variant, .longlong 64-bit variant + .art
# radix tree, .insights). The other repo modules (bsi, examples, jmh, fuzz-tests, ...) are out of
# scope: they are separate Gradle artifacts.
mkdir -p /app/src
cp -a /tmp/repo/roaringbitmap/src/main/java/. /app/src/
# Compile in classpath mode: drop module-info so a PARTIAL agent submission still compiles.
find /app/src -name 'module-info.java' -delete
# package-info.java files are javadoc-only; keep them (they carry the aliased package decl) but they
# are harmless. There is a self-contained Java-8 ArraysShim in main/java; the java11 multi-release
# variant is NOT copied (it lives under src/java11, outside main/java), so the build is pure Java 8.

# ---- Anti-contamination alias (package + class names) -----------------------------------------
# RoaringBitmap is an extremely well-known OSS library, so a model could reproduce it from memory by
# name. Defeat this by renaming BOTH the package and the giveaway class names, keeping behaviour
# identical (only identifiers change). The hidden tests import io.chunkbits.* with the aliased class
# names and compile against this; instruction.md uses only the aliased names and never mentions the
# origin (RoaringBitmap / Roaring / Lemire / CRoaring).
#   package  org.roaringbitmap        -> io.chunkbits
#   class    RoaringBitmap            -> ChunkBitmap        (blanket Roaring->Chunk covers all:
#            Roaring64Bitmap          -> Chunk64Bitmap       Mutable/ImmutableRoaringBitmap,
#            Roaring64NavigableMap    -> Chunk64NavigableMap RoaringArray, RoaringBitmapWriter,
#            RoaringBitSet            -> ChunkBitSet         InvalidRoaringFormat, RoaringIntPacking,
#            RangeBitmap              -> RangeIndex          FastRankRoaringBitmap, ...)
# 'Chunk' and 'RangeIndex' are verified absent from the source, so no identifier collisions.

# 1. Dotted package references (package/import/qualified names) + the RoaringFormatSpec URL token.
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's/org\.roaringbitmap/io.chunkbits/g'
# 2. Rename the RangeBitmap type (do this BEFORE the blanket Roaring->Chunk so it is unambiguous).
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's/\bRangeBitmap\b/RangeIndex/g'
# 3. Blanket class-name / identifier / string-literal rename: every 'Roaring' -> 'Chunk'.
find /app/src -name '*.java' -print0 | xargs -0 sed -i 's/Roaring/Chunk/g'
# 4. Scrub residual origin-revealing URLs left in javadoc comments (defence in depth; GT source only).
find /app/src -name '*.java' -print0 | xargs -0 sed -i \
    -e 's#https://github.com/[A-Za-z0-9_]*Chunk[A-Za-z0-9_/]*#https://example.invalid/chunkbits/spec#g' \
    -e 's#https://github.com/lemire/[A-Za-z0-9_]*#https://example.invalid/fastpfor#g'

# 5. Move package directories to match the aliased package: org/roaringbitmap -> io/chunkbits, and
#    rename every source FILE whose name contains Roaring/RangeBitmap to its aliased class name.
mkdir -p /app/src/io
mv /app/src/org/roaringbitmap /app/src/io/chunkbits
rmdir /app/src/org 2>/dev/null || true
# RangeBitmap.java -> RangeIndex.java
find /app/src -name 'RangeBitmap.java' -exec bash -c 'mv "$0" "${0%/RangeBitmap.java}/RangeIndex.java"' {} \;
# every *Roaring*.java -> *Chunk*.java
find /app/src -name '*Roaring*.java' | while read -r f; do
    mv "$f" "$(dirname "$f")/$(basename "$f" | sed 's/Roaring/Chunk/g')"
done

cd /app
rm -rf /tmp/repo

# setup.sh builds the whole module OFFLINE with plain javac -- the core has ZERO external deps and
# the (aliased) reference source targets Java 8, compiling cleanly on the JDK 17 base at the default
# source level. No `set -e` here so a compile failure cannot abort the (no-set-e) test.sh that
# sources it.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
EOF
