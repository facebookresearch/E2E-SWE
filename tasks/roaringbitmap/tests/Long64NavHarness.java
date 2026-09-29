import io.chunkbits.longlong.*;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- Chunk64NavigableMap, the 64-bit variant backed by a navigable map keyed on the
 * high 32 bits. Unlike Chunk64Bitmap it supports a SIGNED ordering mode (constructor flag) and two
 * serialization formats selected by the mutable static SERIALIZATION_MODE (legacy vs portable). The
 * portable format is cross-language-interoperable; four portable fixtures under /tests/testdata are
 * used to validate portable deserialization. Expected strings captured into /tests/expected.tsv.
 */
public class Long64NavHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static String thrown(Runnable r) {
    try {
      r.run();
      return "none";
    } catch (Throwable e) {
      return e.getClass().getSimpleName();
    }
  }

  static String testdataDir() {
    String d = System.getenv("TESTDATA_DIR");
    return d != null ? d : "/tests/testdata";
  }

  static Chunk64NavigableMap loadPortable(String resource) throws IOException {
    byte[] bytes = Files.readAllBytes(Paths.get(testdataDir(), resource));
    int prev = Chunk64NavigableMap.SERIALIZATION_MODE;
    Chunk64NavigableMap.SERIALIZATION_MODE = Chunk64NavigableMap.SERIALIZATION_MODE_PORTABLE;
    try {
      Chunk64NavigableMap m = new Chunk64NavigableMap();
      m.deserialize(new DataInputStream(new ByteArrayInputStream(bytes)));
      return m;
    } finally {
      Chunk64NavigableMap.SERIALIZATION_MODE = prev;
    }
  }

  static {
    // ---- unsigned (default) ordering ----
    c("l64nav_unsigned_order", () -> {
      Chunk64NavigableMap m = new Chunk64NavigableMap(); // unsigned by default
      m.addLong(1L);
      m.addLong(-1L);
      return "sel0=" + m.select(0) + "|sel1=" + m.select(1) + "|rankNeg1=" + m.rankLong(-1L);
    });

    // ---- signed ordering (constructor flag): -1 precedes 0 ----
    c("l64nav_signed_order", () -> {
      Chunk64NavigableMap m = new Chunk64NavigableMap(true); // signed
      m.addLong(1L);
      m.addLong(-1L);
      return "sel0=" + m.select(0) + "|sel1=" + m.select(1) + "|rankNeg1=" + m.rankLong(-1L);
    });

    // ---- signed vs unsigned select over {MIN,0,1,MAX} ----
    c("l64nav_signed_vs_unsigned_extremes", () -> {
      long[] vals = {Long.MIN_VALUE, 0L, 1L, Long.MAX_VALUE};
      Chunk64NavigableMap u = new Chunk64NavigableMap(false);
      Chunk64NavigableMap s = new Chunk64NavigableMap(true);
      for (long v : vals) {
        u.addLong(v);
        s.addLong(v);
      }
      return "uSel0=" + u.select(0)
          + "|uSel3=" + u.select(3)
          + "|sSel0=" + s.select(0)
          + "|sSel3=" + s.select(3);
    });

    // ---- basic ops + addRange ----
    c("l64nav_basic_ops", () -> {
      Chunk64NavigableMap m = Chunk64NavigableMap.bitmapOf(1L, 2L, 100L, 1000L);
      m.addLong(1234L);
      m.addRange(2000L, 2004L);
      return "card=" + m.getLongCardinality()
          + "|c1234=" + m.contains(1234L)
          + "|c2003=" + m.contains(2003L)
          + "|c2004=" + m.contains(2004L);
    });

    // ---- addRange spanning multiple 32-bit high buckets ----
    c("l64nav_add_range_buckets", () -> {
      Chunk64NavigableMap m = new Chunk64NavigableMap();
      long start = 2L * Integer.MAX_VALUE;
      m.addRange(start, start + 4);
      return "card=" + m.getLongCardinality() + "|first=" + m.first() + "|last=" + m.last();
    });

    // ---- set algebra ----
    c("l64nav_set_algebra", () -> {
      Chunk64NavigableMap a = Chunk64NavigableMap.bitmapOf(1L, 2L, 3L, 100000000000L);
      Chunk64NavigableMap b = Chunk64NavigableMap.bitmapOf(2L, 3L, 4L, 100000000000L);
      Chunk64NavigableMap x = Chunk64NavigableMap.bitmapOf(1L, 2L, 3L, 100000000000L);
      x.and(b);
      Chunk64NavigableMap o = Chunk64NavigableMap.bitmapOf(1L, 2L, 3L);
      o.or(Chunk64NavigableMap.bitmapOf(3L, 4L));
      return "andCard=" + x.getLongCardinality()
          + "|andArr=" + Arrays.toString(x.toArray())
          + "|orArr=" + Arrays.toString(o.toArray());
    });

    // ---- rank/select multi-bucket ----
    c("l64nav_rank_select_multibucket", () -> {
      Chunk64NavigableMap m = new Chunk64NavigableMap();
      for (int i = 1; i <= 5; i++) {
        m.addLong((long) i * Integer.MAX_VALUE + 1);
      }
      return "card=" + m.getLongCardinality()
          + "|sel0=" + m.select(0)
          + "|sel4=" + m.select(4)
          + "|rankLast=" + m.rankLong(5L * Integer.MAX_VALUE + 1);
    });

    // ---- legacy serialization round-trip (default mode) ----
    c("l64nav_legacy_roundtrip", () -> {
      int prev = Chunk64NavigableMap.SERIALIZATION_MODE;
      Chunk64NavigableMap.SERIALIZATION_MODE = Chunk64NavigableMap.SERIALIZATION_MODE_LEGACY;
      try {
        Chunk64NavigableMap in = Chunk64NavigableMap.bitmapOf(-123L, 123L, Long.MAX_VALUE);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        in.serialize(new DataOutputStream(bos));
        Chunk64NavigableMap out = new Chunk64NavigableMap();
        out.deserialize(new DataInputStream(new ByteArrayInputStream(bos.toByteArray())));
        return "card=" + out.getLongCardinality()
            + "|sel0=" + out.select(0)
            + "|sel2=" + out.select(2);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      } finally {
        Chunk64NavigableMap.SERIALIZATION_MODE = prev;
      }
    });

    // ---- portable serialization round-trip ----
    c("l64nav_portable_roundtrip", () -> {
      int prev = Chunk64NavigableMap.SERIALIZATION_MODE;
      Chunk64NavigableMap.SERIALIZATION_MODE = Chunk64NavigableMap.SERIALIZATION_MODE_PORTABLE;
      try {
        Chunk64NavigableMap in = Chunk64NavigableMap.bitmapOf(0L, 9L, (9L << 32) + 5L);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        in.serialize(new DataOutputStream(bos));
        Chunk64NavigableMap out = new Chunk64NavigableMap();
        out.deserialize(new DataInputStream(new ByteArrayInputStream(bos.toByteArray())));
        return "card=" + out.getLongCardinality()
            + "|sel0=" + out.select(0)
            + "|sel2=" + out.select(2);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      } finally {
        Chunk64NavigableMap.SERIALIZATION_MODE = prev;
      }
    });

    // ---- legacy deserialize RESTORES the stored signedness flag (order follows the serialized map) ----
    c("l64nav_legacy_restores_signedness", () -> {
      int prev = Chunk64NavigableMap.SERIALIZATION_MODE;
      Chunk64NavigableMap.SERIALIZATION_MODE = Chunk64NavigableMap.SERIALIZATION_MODE_LEGACY;
      try {
        Chunk64NavigableMap signed = new Chunk64NavigableMap(true);
        signed.addLong(-1L);
        signed.addLong(1L);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        signed.serialize(new DataOutputStream(bos));
        // deserialize into a DEFAULT (unsigned) map: the stored flag must restore signed order
        Chunk64NavigableMap out = new Chunk64NavigableMap();
        out.deserialize(new DataInputStream(new ByteArrayInputStream(bos.toByteArray())));
        return "sel0=" + out.select(0) + "|sel1=" + out.select(1) + "|card=" + out.getLongCardinality();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      } finally {
        Chunk64NavigableMap.SERIALIZATION_MODE = prev;
      }
    });

    // ---- portable fixture: 32bitvals (10 values 0..9 in one high bucket) ----
    c("l64nav_fixture_32bitvals", () -> {
      try {
        Chunk64NavigableMap m = loadPortable("64map32bitvals.bin");
        return "card=" + m.getLongCardinality() + "|sel0=" + m.select(0) + "|sel9=" + m.select(9);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- portable fixture: spreadvals (100 values across 10 buckets) ----
    c("l64nav_fixture_spreadvals", () -> {
      try {
        Chunk64NavigableMap m = loadPortable("64mapspreadvals.bin");
        return "card=" + m.getLongCardinality()
            + "|sel0=" + m.select(0)
            + "|sel90=" + m.select(90)
            + "|sel99=" + m.select(99);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- portable fixtures: empty + highvals (values near the unsigned 32-bit max in high+low) ----
    c("l64nav_fixture_empty_and_highvals", () -> {
      try {
        Chunk64NavigableMap empty = loadPortable("64mapempty.bin");
        Chunk64NavigableMap high = loadPortable("64maphighvals.bin");
        long maxInt = 0xFFFFFFFFL;
        return "emptyCard=" + empty.getLongCardinality()
            + "|highCard=" + high.getLongCardinality()
            + "|highSel0=" + high.select(0)
            + "|highSel120=" + high.select(120)
            + "|expectedSel120=" + ((maxInt << 32) + maxInt);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
