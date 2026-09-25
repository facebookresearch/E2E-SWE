import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- flip (single-value toggle, half-open range complement, and the static form).
 * Deterministic; expected strings captured from the reference into /tests/expected.tsv.
 */
public class FlipHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static String arr(ChunkBitmap b) {
    return Arrays.toString(b.toArray());
  }

  static {
    // ---- flip(int): toggle a single value both ways ----
    c("flip_scalar", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(5);
      b.flip(5); // remove
      b.flip(6); // add
      return "afterRemoveAdd=" + arr(b) + "|card=" + b.getCardinality();
    });

    // ---- flip(long,long): complement of [start,end) on empty, then flip back ----
    c("flip_range_roundtrip", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.flip(0L, 3L); // -> {0,1,2}
      String after = arr(b);
      b.flip(0L, 3L); // back to empty
      return "after=" + after + "|backCard=" + b.getCardinality();
    });

    // ---- flip(long,long): partial overlap toggles present off and absent on ----
    c("flip_range_partial", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3);
      b.flip(2L, 6L); // 2,3 removed; 4,5 added -> {1,4,5}
      return arr(b);
    });

    // ---- static flip(bm, start, end): returns new bitmap, input unchanged ----
    c("flip_static", () -> {
      ChunkBitmap in = ChunkBitmap.bitmapOf(0, 1, 2);
      ChunkBitmap out = ChunkBitmap.flip(in, 1L, 4L); // toggle [1,4): 1,2 off, 3 on -> {0,3}
      return "out=" + arr(out) + "|inUnchanged=" + arr(in);
    });

    // ---- static flip empty range returns a clone of the input ----
    c("flip_static_empty_range", () -> {
      ChunkBitmap in = ChunkBitmap.bitmapOf(7, 8);
      ChunkBitmap out = ChunkBitmap.flip(in, 5L, 5L);
      return "out=" + arr(out) + "|equalsIn=" + out.equals(in);
    });

    // ---- flip(long,long) crossing a container boundary ----
    c("flip_range_boundary", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(65535);
      b.flip(65534L, 65538L); // toggle 65534,65535,65536,65537: 65535 off, others on
      return "toArray=" + arr(b) + "|card=" + b.getCardinality();
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
