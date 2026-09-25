import io.chunkbits.*;

import java.nio.ByteBuffer;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- RangeIndex, the succinct range-query structure. Values are appended at
 * incrementing row indices; predicate queries (lt/lte/gt/gte/eq/neq/between) return a ChunkBitmap of
 * the row indices whose stored value satisfies the predicate. Unsigned order throughout. Also covers
 * the in-memory serialize->map round-trip. Expected strings captured into /tests/expected.tsv.
 */
public class RangeIndexHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static String arr(ChunkBitmap b) {
    return Arrays.toString(b.toArray());
  }

  static String thrown(Runnable r) {
    try {
      r.run();
      return "none";
    } catch (Throwable e) {
      return e.getClass().getSimpleName();
    }
  }

  /** Build a RangeIndex from the given values (rows 0..n-1). */
  static RangeIndex of(long maxValue, long... values) {
    RangeIndex.Appender app = RangeIndex.appender(maxValue);
    for (long v : values) {
      app.add(v);
    }
    return app.build();
  }

  static {
    // ---- canonical README example ----
    c("canonical", () -> {
      RangeIndex r = of(1_000_000L, 1L, 1L, 100_000L); // rows 0,1,2
      return "lt5=" + arr(r.lt(5))
          + "|gte1=" + arr(r.gte(1))
          + "|gt1=" + arr(r.gt(1))
          + "|eq1=" + arr(r.eq(1))
          + "|neq1=" + arr(r.neq(1))
          + "|lte1=" + arr(r.lte(1));
    });

    // ---- lt / lte boundaries ----
    c("lt_lte", () -> {
      RangeIndex r = of(100L, 10L, 20L, 30L, 40L);
      return "lt0=" + arr(r.lt(0))
          + "|lt25=" + arr(r.lt(25))
          + "|lte30=" + arr(r.lte(30))
          + "|lt10=" + arr(r.lt(10));
    });

    // ---- gt / gte boundaries ----
    c("gt_gte", () -> {
      RangeIndex r = of(100L, 10L, 20L, 30L, 40L);
      return "gt20=" + arr(r.gt(20))
          + "|gte20=" + arr(r.gte(20))
          + "|gte0=" + arr(r.gte(0))
          + "|gt40=" + arr(r.gt(40));
    });

    // ---- eq / neq point queries with duplicates ----
    c("eq_neq", () -> {
      RangeIndex r = of(100L, 5L, 5L, 7L, 5L); // three rows equal 5
      return "eq5=" + arr(r.eq(5))
          + "|eq7=" + arr(r.eq(7))
          + "|eq6=" + arr(r.eq(6))
          + "|neq5=" + arr(r.neq(5));
    });

    // ---- between is inclusive on both ends ----
    c("between", () -> {
      RangeIndex r = of(10L, 0L, 1L, 2L, 3L, 4L, 5L, 6L, 7L, 8L, 9L); // value==row
      return "b0_10=" + arr(r.between(0, 10))
          + "|b2_8=" + arr(r.between(2, 8))
          + "|b3_7=" + arr(r.between(3, 7))
          + "|b5_5=" + arr(r.between(5, 5));
    });

    // ---- complements: gte|lt == all, lte|gt == all ----
    c("complements", () -> {
      RangeIndex r = of(1000L, 100L, 200L, 300L, 400L, 500L);
      ChunkBitmap union1 = ChunkBitmap.or(r.gte(300), r.lt(300));
      ChunkBitmap union2 = ChunkBitmap.or(r.lte(300), r.gt(300));
      return "gteLt=" + arr(union1) + "|lteGt=" + arr(union2);
    });

    // ---- cardinality variants match the set sizes ----
    c("cardinality_variants", () -> {
      RangeIndex r = of(100L, 10L, 20L, 30L, 40L, 50L);
      return "ltCard30=" + r.ltCardinality(30)
          + "|gteCard30=" + r.gteCardinality(30)
          + "|eqCard20=" + r.eqCardinality(20)
          + "|betweenCard20_40=" + r.betweenCardinality(20, 40);
    });

    // ---- context overload intersects the result with a provided ChunkBitmap ----
    c("context_overload", () -> {
      RangeIndex r = of(100L, 10L, 20L, 30L, 40L, 50L); // rows 0..4
      ChunkBitmap context = ChunkBitmap.bitmapOf(0, 1, 2); // restrict to first three rows
      return "ltCtx=" + arr(r.lt(35, context)) + "|gteCtx=" + arr(r.gte(20, context));
    });

    // ---- unsigned extremes: 0, MIN, -1 in unsigned order ----
    c("unsigned_extremes", () -> {
      RangeIndex r = of(-1L, 0L, Long.MIN_VALUE, -1L); // rows 0,1,2
      return "gtNeg1=" + arr(r.gt(-1L))
          + "|gteNeg1=" + arr(r.gte(-1L))
          + "|lteNeg1=" + arr(r.lte(-1L))
          + "|ltMin=" + arr(r.lt(Long.MIN_VALUE))
          + "|gtMin=" + arr(r.gt(Long.MIN_VALUE))
          + "|eqMin=" + arr(r.eq(Long.MIN_VALUE));
    });

    // ---- contiguous fill: predicates map onto exact index ranges ----
    c("contiguous_fill", () -> {
      long size = 5000L;
      RangeIndex.Appender app = RangeIndex.appender(size);
      for (long i = 0; i < size; i++) {
        app.add(i);
      }
      RangeIndex r = app.build();
      return "lt10Card=" + r.ltCardinality(10)
          + "|gte4990Card=" + r.gteCardinality(4990)
          + "|eq2500=" + arr(r.eq(2500))
          + "|between100_102=" + arr(r.between(100, 102));
    });

    // ---- values crossing the 65536 container boundary in the RESULT bitmap ----
    c("result_boundary", () -> {
      long n = 0x1000AL;
      RangeIndex.Appender app = RangeIndex.appender(n);
      for (long i = 0; i < n; i++) {
        app.add(i);
      }
      RangeIndex r = app.build();
      // between over the boundary; result indices span two containers
      return "betweenCard=" + r.betweenCardinality(0x10000 - 5, 0x10000 + 5)
          + "|gteCard=" + r.gteCardinality(0x10000);
    });

    // ---- single value ----
    c("single_value", () -> {
      RangeIndex r = of(64L, 32L);
      return "gte=" + r.gteCardinality(32)
          + "|lte=" + r.lteCardinality(32)
          + "|eq=" + arr(r.eq(32))
          + "|between=" + arr(r.between(32, 32));
    });

    // ---- over-range thresholds SATURATE (not wrap): threshold above maxValue ----
    c("over_range_saturation", () -> {
      RangeIndex r = of(255L, 5L, 44L, 100L); // rows 0,1,2
      return "lte300=" + arr(r.lte(300))
          + "|gt300=" + arr(r.gt(300))
          + "|eq300=" + arr(r.eq(300))
          + "|neq300=" + arr(r.neq(300))
          + "|lt300=" + arr(r.lt(300))
          + "|gte300=" + arr(r.gte(300));
    });

    // ---- between with an over-range max degrades to gte(min); in-range inverted bounds -> empty ----
    c("between_over_range_and_inverted", () -> {
      RangeIndex r = of(255L, 5L, 44L, 100L); // rows 0,1,2
      return "over=" + arr(r.between(40, 500))
          + "|overCard=" + r.betweenCardinality(40, 500)
          + "|inverted=" + arr(r.between(100, 50))
          + "|invertedCard=" + r.betweenCardinality(100, 50);
    });

    // ---- over-range eq/neq cardinality forms ----
    c("over_range_cardinality", () -> {
      RangeIndex r = of(255L, 5L, 44L, 100L, 44L); // two rows equal 44
      return "eqCard300=" + r.eqCardinality(300)
          + "|neqCard300=" + r.neqCardinality(300)
          + "|lteCard300=" + r.lteCardinality(300)
          + "|gtCard300=" + r.gtCardinality(300);
    });

    // ---- empty structure: all queries empty ----
    c("rangeidx_empty", () -> {
      RangeIndex r = RangeIndex.appender(10_000_000L).build();
      return "ltCard=" + r.ltCardinality(500)
          + "|gteCard=" + r.gteCardinality(0)
          + "|eq=" + arr(r.eq(5));
    });

    // ---- in-memory serialize -> map round-trip answers identically ----
    c("serialize_map_roundtrip", () -> {
      RangeIndex.Appender app = RangeIndex.appender(1_000_000L);
      app.add(1L);
      app.add(1L);
      app.add(100_000L);
      ByteBuffer buf = ByteBuffer.allocate(app.serializedSizeInBytes());
      app.serialize(buf);
      buf.flip();
      RangeIndex mapped = RangeIndex.map(buf);
      return "lt5=" + arr(mapped.lt(5))
          + "|gte1=" + arr(mapped.gte(1))
          + "|eq100000=" + arr(mapped.eq(100_000));
    });

    // ---- build() vs map(serialized) equivalence ----
    c("build_vs_map", () -> {
      RangeIndex.Appender app = RangeIndex.appender(100L);
      for (long v : new long[] {10, 20, 30, 40, 50}) {
        app.add(v);
      }
      RangeIndex built = app.build();
      RangeIndex.Appender app2 = RangeIndex.appender(100L);
      for (long v : new long[] {10, 20, 30, 40, 50}) {
        app2.add(v);
      }
      ByteBuffer buf = ByteBuffer.allocate(app2.serializedSizeInBytes());
      app2.serialize(buf);
      buf.flip();
      RangeIndex mapped = RangeIndex.map(buf);
      return "sameLt35=" + built.lt(35).equals(mapped.lt(35))
          + "|sameBetween=" + built.between(20, 40).equals(mapped.between(20, 40));
    });

    // ---- over-range add: a value with a higher-order bit set throws IllegalArgumentException ----
    c("over_range_error", () -> {
      return "err=" + thrown(() -> {
        RangeIndex.Appender app = RangeIndex.appender(10L); // mask covers bits up to 0xF
        app.add(1_000_000L); // far higher bit set
      });
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
