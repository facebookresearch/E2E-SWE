import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- multi-bitmap aggregation via FastAggregation (and/or/xor plus the
 * cardinality-only and intersects forms) and ParallelAggregation (or/xor). Results are asserted by
 * set/cardinality/boolean only (aggregation is free to choose any internal representation).
 * Expected strings captured from the reference into /tests/expected.tsv.
 */
public class AggregationHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static String arr(ChunkBitmap b) {
    return Arrays.toString(b.toArray());
  }

  static {
    // ---- FastAggregation.or over several bitmaps ----
    c("fast_or", () -> {
      ChunkBitmap r =
          FastAggregation.or(
              ChunkBitmap.bitmapOf(1, 2), ChunkBitmap.bitmapOf(2, 3), ChunkBitmap.bitmapOf(4));
      return "toArray=" + arr(r) + "|card=" + r.getCardinality();
    });

    // ---- FastAggregation.and over several bitmaps ----
    c("fast_and", () -> {
      ChunkBitmap r =
          FastAggregation.and(
              ChunkBitmap.bitmapOf(1, 2, 3), ChunkBitmap.bitmapOf(2, 3, 4), ChunkBitmap.bitmapOf(3, 4, 5));
      return arr(r);
    });

    // ---- FastAggregation.xor over several bitmaps ----
    c("fast_xor", () -> {
      ChunkBitmap r = FastAggregation.xor(ChunkBitmap.bitmapOf(1, 2), ChunkBitmap.bitmapOf(2, 3));
      return arr(r);
    });

    // ---- FastAggregation.naive_or matches or ----
    c("fast_naive_or", () -> {
      ChunkBitmap[] ops = {ChunkBitmap.bitmapOf(1, 5), ChunkBitmap.bitmapOf(5, 9), ChunkBitmap.bitmapOf(2)};
      ChunkBitmap a = FastAggregation.naive_or(ops);
      ChunkBitmap b = FastAggregation.or(ops);
      return "equal=" + a.equals(b) + "|toArray=" + arr(a);
    });

    // ---- FastAggregation.andCardinality / orCardinality ----
    c("fast_cardinalities", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3, 4);
      ChunkBitmap b = ChunkBitmap.bitmapOf(3, 4, 5, 6);
      return "andCard=" + FastAggregation.andCardinality(a, b)
          + "|orCard=" + FastAggregation.orCardinality(a, b);
    });

    // ---- FastAggregation.intersects ----
    c("fast_intersects", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      ChunkBitmap b = ChunkBitmap.bitmapOf(3, 4);
      ChunkBitmap c = ChunkBitmap.bitmapOf(10, 11);
      return "ab=" + FastAggregation.intersects(a, b) + "|ac=" + FastAggregation.intersects(a, c);
    });

    // ---- large multi-way or (exercises workshy/priority paths for many bitmaps) ----
    c("fast_or_many", () -> {
      ChunkBitmap[] ops = new ChunkBitmap[12];
      for (int i = 0; i < ops.length; i++) {
        ops[i] = ChunkBitmap.bitmapOf(i, i + 100, i + 100000);
      }
      ChunkBitmap r = FastAggregation.or(ops);
      return "card=" + r.getCardinality() + "|first=" + r.first() + "|last=" + r.last();
    });

    // ---- ParallelAggregation.or matches the sequential union ----
    c("parallel_or", () -> {
      ChunkBitmap[] ops = {
        ChunkBitmap.bitmapOf(1, 2, 3), ChunkBitmap.bitmapOf(3, 4, 5), ChunkBitmap.bitmapOf(100000, 100001)
      };
      ChunkBitmap par = ParallelAggregation.or(ops);
      ChunkBitmap seq = FastAggregation.or(ops);
      return "equal=" + par.equals(seq) + "|card=" + par.getCardinality();
    });

    // ---- ParallelAggregation.xor matches the sequential symmetric difference ----
    c("parallel_xor", () -> {
      ChunkBitmap[] ops = {ChunkBitmap.bitmapOf(1, 2, 3), ChunkBitmap.bitmapOf(2, 3, 4)};
      ChunkBitmap par = ParallelAggregation.xor(ops);
      ChunkBitmap seq = FastAggregation.xor(ops);
      return "equal=" + par.equals(seq) + "|toArray=" + arr(par);
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
