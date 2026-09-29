import io.chunkbits.buffer.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- BufferFastAggregation, the multi-bitmap aggregation entry point for the buffer
 * package (and/or/xor over ImmutableChunkBitmap operands, returning MutableChunkBitmap). Results are
 * asserted by set/cardinality only. Expected strings captured from the reference into expected.tsv.
 */
public class BufferAggregationHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static String arr(int[] a) {
    return Arrays.toString(a);
  }

  static {
    // ---- BufferFastAggregation.or ----
    c("buffer_or", () -> {
      MutableChunkBitmap r =
          BufferFastAggregation.or(
              MutableChunkBitmap.bitmapOf(1, 2),
              MutableChunkBitmap.bitmapOf(2, 3),
              MutableChunkBitmap.bitmapOf(4));
      return "toArray=" + arr(r.toArray()) + "|card=" + r.getCardinality();
    });

    // ---- BufferFastAggregation.and ----
    c("buffer_and", () -> {
      MutableChunkBitmap r =
          BufferFastAggregation.and(
              MutableChunkBitmap.bitmapOf(1, 2, 3),
              MutableChunkBitmap.bitmapOf(2, 3, 4),
              MutableChunkBitmap.bitmapOf(3, 4, 5));
      return arr(r.toArray());
    });

    // ---- BufferFastAggregation.xor ----
    c("buffer_xor", () -> {
      MutableChunkBitmap r =
          BufferFastAggregation.xor(
              MutableChunkBitmap.bitmapOf(1, 2), MutableChunkBitmap.bitmapOf(2, 3));
      return arr(r.toArray());
    });

    // ---- large multi-way or spanning containers ----
    c("buffer_or_many", () -> {
      MutableChunkBitmap[] ops = new MutableChunkBitmap[12];
      for (int i = 0; i < ops.length; i++) {
        ops[i] = MutableChunkBitmap.bitmapOf(i, i + 100, i + 100000);
      }
      MutableChunkBitmap r = BufferFastAggregation.or(ops);
      return "card=" + r.getCardinality() + "|first=" + r.first() + "|last=" + r.last();
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
