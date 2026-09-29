#!/bin/bash
set -e

# Ground-truth solution for the commons-compress replication task. Runs only during
# `--mode=evaluate_gt`, in the Container A that keeps internet ON. The reference (Apache
# commons-compress) is the "answer", so it is NOT baked into the image; this script fetches it +
# its deps into /app/gt-lib and provides a thin Archives that wraps it. The agent flow never runs
# this script, so the agent never has commons-compress on its classpath.

mkdir -p /app/gt-lib
fetch() { # <group-path> <artifact> <version>
    local rel="$1/$2/$3/$2-$3.jar" out="/app/gt-lib/$2-$3.jar"
    for base in \
        "https://maven-central.storage-download.googleapis.com/maven2" \
        "https://repo1.maven.org/maven2" \
    ; do
        curl -fSL --connect-timeout 10 --retry 8 --retry-delay 6 --retry-all-errors -o "$out" "$base/$rel" && [ -s "$out" ] && return 0
    done
    return 1
}
fetch org/apache/commons commons-compress 1.27.1
fetch commons-io commons-io 2.16.1
fetch org/apache/commons commons-lang3 3.14.0
fetch commons-codec commons-codec 1.17.0
fetch org/tukaani xz 1.9
test -s /app/gt-lib/commons-compress-1.27.1.jar

# The reference Archives: wraps commons-compress. Exactly the contract the agent implements from
# scratch (list/write/decompress/compress/detect over the canonical listing + spec formats).
mkdir -p /app/src/com/wrg/compress
cat > /app/src/com/wrg/compress/Archives.java <<'JAVA'
package com.wrg.compress;

import org.apache.commons.compress.archivers.*;
import org.apache.commons.compress.archivers.tar.*;
import org.apache.commons.compress.archivers.zip.*;
import org.apache.commons.compress.archivers.cpio.*;
import org.apache.commons.compress.archivers.ar.*;
import org.apache.commons.compress.compressors.*;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;

public class Archives {

    public String list(String format, byte[] archive) throws Exception {
        StringBuilder sb = new StringBuilder(); boolean first = true;
        try (ArchiveInputStream ais = new ArchiveStreamFactory()
                .createArchiveInputStream(format, new ByteArrayInputStream(archive))) {
            ArchiveEntry e;
            while ((e = ais.getNextEntry()) != null) {
                String type = e.isDirectory() ? "d" : (isSymlink(e) ? "l" : "f");
                byte[] content = (type.equals("f") && ais.canReadEntryData(e)) ? readAll(ais) : new byte[0];
                if (!first) sb.append('\n'); first = false;
                sb.append(e.getName()).append('\t').append(type).append('\t')
                  .append(e.getSize() < 0 ? content.length : e.getSize()).append('\t').append(sha256(content));
            }
        }
        return sb.toString();
    }

    public byte[] write(String format, String spec) throws Exception {
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        try (ArchiveOutputStream aos = new ArchiveStreamFactory().createArchiveOutputStream(format, bo)) {
            if (aos instanceof TarArchiveOutputStream) {
                ((TarArchiveOutputStream) aos).setLongFileMode(TarArchiveOutputStream.LONGFILE_GNU);
                ((TarArchiveOutputStream) aos).setBigNumberMode(TarArchiveOutputStream.BIGNUMBER_STAR);
            }
            for (String line : spec.split("\n", -1)) {
                if (line.isEmpty()) continue;
                String[] p = line.split("\t", -1);
                String name = p[0]; String type = p[1]; int mode = Integer.parseInt(p[2], 8);
                byte[] content = p.length > 3 && !p[3].isEmpty() ? Base64.getDecoder().decode(p[3]) : new byte[0];
                boolean dir = type.equals("d");
                aos.putArchiveEntry(mkEntry(format, name, dir, content.length, mode));
                if (!dir) aos.write(content);
                aos.closeArchiveEntry();
            }
            aos.finish();
        }
        return bo.toByteArray();
    }

    private ArchiveEntry mkEntry(String fmt, String name, boolean dir, int size, int mode) {
        switch (fmt) {
            case "tar": { TarArchiveEntry e = new TarArchiveEntry(dir && !name.endsWith("/") ? name + "/" : name);
                e.setSize(dir ? 0 : size); e.setMode(mode); return e; }
            case "zip": case "jar": { ZipArchiveEntry e = new ZipArchiveEntry(dir && !name.endsWith("/") ? name + "/" : name);
                e.setUnixMode(mode); return e; }
            case "cpio": { CpioArchiveEntry e = new CpioArchiveEntry(CpioConstants.FORMAT_NEW,
                    dir && !name.endsWith("/") ? name + "/" : name, dir ? 0 : size);
                e.setMode(dir ? CpioConstants.C_ISDIR | (mode & 0777) : CpioConstants.C_ISREG | (mode & 0777)); return e; }
            case "ar": return new ArArchiveEntry(name, size, 0, 0, mode, 0);
            default: throw new IllegalArgumentException("write unsupported for " + fmt);
        }
    }

    public byte[] decompress(String codec, byte[] data) throws Exception {
        try (CompressorInputStream cis = new CompressorStreamFactory(true)
                .createCompressorInputStream(codec, new ByteArrayInputStream(data))) {
            return readAll(cis);
        }
    }

    public byte[] compress(String codec, byte[] data) throws Exception {
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        try (CompressorOutputStream cos = new CompressorStreamFactory().createCompressorOutputStream(codec, bo)) {
            cos.write(data);
        }
        return bo.toByteArray();
    }

    public String detect(byte[] data) {
        InputStream in = new BufferedInputStream(new ByteArrayInputStream(data));
        try { return ArchiveStreamFactory.detect(in); } catch (Exception ignore) {}
        try { return CompressorStreamFactory.detect(in); } catch (Exception ignore) {}
        return "";
    }

    private static boolean isSymlink(ArchiveEntry e) {
        if (e instanceof TarArchiveEntry) return ((TarArchiveEntry) e).isSymbolicLink();
        return false;
    }
    static byte[] readAll(InputStream in) throws IOException {
        ByteArrayOutputStream bo = new ByteArrayOutputStream(); byte[] b = new byte[8192]; int n;
        while ((n = in.read(b)) > 0) bo.write(b, 0, n);
        return bo.toByteArray();
    }
    static String sha256(byte[] b) throws Exception {
        byte[] h = MessageDigest.getInstance("SHA-256").digest(b);
        StringBuilder s = new StringBuilder();
        for (byte x : h) s.append(String.format("%02x", x));
        return s.toString();
    }
}
JAVA

cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -encoding UTF-8 -cp "/app/gt-lib/*" -d /app/out
EOF
