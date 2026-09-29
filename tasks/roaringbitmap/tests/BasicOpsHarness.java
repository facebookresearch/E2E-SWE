import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- construction and basic membership/cardinality operations on ChunkBitmap.
 *
 * Each case is a realistic small workflow (build a bitmap, mutate it, query it) and returns a single
 * '|'-joined string encoding several related assertions, so one CTRF entry rewards one implementation
 * node. All values are deterministic and offline; expected strings are captured from the reference
 * implementation into /tests/expected.tsv. Imports only the PUBLIC io.chunkbits API.
 *
 * Unsigned semantics: values are ordered 0,1,...,0x7FFFFFFF, 0x80000000,...,0xFFFFFFFF. toString()
 * prints values as unsigned decimals (0xFFFFFFFF -> "4294967295").
 */
public class BasicOpsHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  /** Run body; return the thrown exception's simple class name, or "none". */
  static String thrown(Runnable r) {
    try {
      r.run();
      return "none";
    } catch (Throwable e) {
      return e.getClass().getSimpleName();
    }
  }

  static {
    // ---- empty bitmap invariants ----
    c("empty", () -> {
      ChunkBitmap b = new ChunkBitmap();
      return "card=" + b.getCardinality()
          + "|longCard=" + b.getLongCardinality()
          + "|isEmpty=" + b.isEmpty()
          + "|contains0=" + b.contains(0)
          + "|toString=" + b.toString();
    });

    // ---- bitmapOf: dedup + unsigned-sorted contents ----
    c("bitmapOf_basic", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 1000);
      return "card=" + b.getCardinality()
          + "|contains1000=" + b.contains(1000)
          + "|contains7=" + b.contains(7)
          + "|toArray=" + Arrays.toString(b.toArray())
          + "|toString=" + b.toString();
    });

    // ---- bitmapOf dedups repeated values ----
    c("bitmapOf_dedup", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(5, 5, 5, 1, 1, 9);
      return "card=" + b.getCardinality() + "|toArray=" + Arrays.toString(b.toArray());
    });

    // ---- bitmapOfUnordered: same set as bitmapOf regardless of input order ----
    c("bitmapOf_unordered", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOfUnordered(1000, 3, 1, 2, 3);
      return "card=" + b.getCardinality() + "|toArray=" + Arrays.toString(b.toArray());
    });

    // ---- add(int) idempotent + add(int...) varargs ----
    c("add_scalar_and_varargs", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(5);
      b.add(5); // idempotent
      b.add(1, 2, 3);
      return "card=" + b.getCardinality() + "|toArray=" + Arrays.toString(b.toArray());
    });

    // ---- addN(int[], offset, n): add a slice; and its bounds errors ----
    c("addN_slice", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.addN(new int[] {1, 2, 3, 4, 5}, 1, 3); // -> {2,3,4}
      return "toString=" + b.toString()
          + "|negN=" + thrown(() -> new ChunkBitmap().addN(new int[] {1, 2}, 0, -1))
          + "|tooBig=" + thrown(() -> new ChunkBitmap().addN(new int[] {1, 2}, 1, 5));
    });

    // ---- add(long,long) half-open range ----
    c("add_range", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(100000L, 200000L); // [100000,200000) -> 100000 values
      ChunkBitmap empty = new ChunkBitmap();
      empty.add(50L, 50L); // empty range -> no-op
      return "rangeCard=" + b.getCardinality()
          + "|first=" + b.first()
          + "|last=" + b.last()
          + "|emptyRangeCard=" + empty.getCardinality();
    });

    // ---- add(long,long) range spanning a container boundary (multiple of 65536) ----
    c("add_range_boundary", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(65530L, 65540L); // crosses the 65536 boundary
      return "card=" + b.getCardinality()
          + "|contains65535=" + b.contains(65535)
          + "|contains65536=" + b.contains(65536)
          + "|contains65540=" + b.contains(65540)
          + "|toArray=" + Arrays.toString(b.toArray());
    });

    // ---- remove(int) + remove(long,long) range ----
    c("remove_scalar_and_range", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 4, 5, 6, 7, 8, 9, 10);
      b.remove(5);
      b.remove(2L, 5L); // remove [2,5) -> removes 2,3,4
      return "card=" + b.getCardinality() + "|toArray=" + Arrays.toString(b.toArray());
    });

    // ---- contains(long,long): true iff ALL of [min,sup) present ----
    c("contains_range", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(10L, 20L); // [10,20)
      return "allIn=" + b.contains(10L, 20L)
          + "|partialOut=" + b.contains(15L, 25L)
          + "|supLEmin=" + b.contains(20L, 10L);
    });

    // ---- checkedAdd / checkedRemove return whether state changed ----
    c("checked_add_remove", () -> {
      ChunkBitmap b = new ChunkBitmap();
      boolean a1 = b.checkedAdd(5); // true (new)
      boolean a2 = b.checkedAdd(5); // false (already there)
      boolean r1 = b.checkedRemove(5); // true (was present)
      boolean r2 = b.checkedRemove(5); // false (absent)
      return "a1=" + a1 + "|a2=" + a2 + "|r1=" + r1 + "|r2=" + r2 + "|card=" + b.getCardinality();
    });

    // ---- clear() resets ----
    c("clear", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3);
      b.clear();
      return "card=" + b.getCardinality() + "|isEmpty=" + b.isEmpty();
    });

    // ---- cardinalityExceeds is strict > ----
    c("cardinality_exceeds", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3);
      return "exceeds2=" + b.cardinalityExceeds(2)
          + "|exceeds3=" + b.cardinalityExceeds(3)
          + "|exceeds4=" + b.cardinalityExceeds(4);
    });

    // ---- unsigned wraparound: values at/above 0x80000000 print unsigned and sort last ----
    c("unsigned_wraparound", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(1);
      b.add(0x7FFFFFFF); // 2147483647
      b.add(0x80000000); // -2147483648 signed, largest-but-one unsigned
      b.add(0xFFFFFFFF); // -1 signed, 4294967295 unsigned, the largest
      return "card=" + b.getCardinality()
          + "|toArray=" + Arrays.toString(b.toArray())
          + "|toString=" + b.toString();
    });

    // ---- bitmapOfRange: [min,max) as a range; empty when min>=max ----
    c("bitmap_of_range", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOfRange(4000L, 4255L);
      ChunkBitmap empty = ChunkBitmap.bitmapOfRange(10L, 10L);
      return "card=" + b.getCardinality()
          + "|first=" + b.first()
          + "|last=" + b.last()
          + "|emptyCard=" + empty.getCardinality();
    });

    // ---- range sanity errors: out-of-[0,2^32] bounds throw IllegalArgumentException ----
    c("range_sanity_errors", () -> {
      return "negStart=" + thrown(() -> new ChunkBitmap().add(-1L, 5L))
          + "|endTooBig=" + thrown(() -> new ChunkBitmap().add(0L, (1L << 32) + 1))
          + "|okFull=" + thrown(() -> new ChunkBitmap().add(0L, 1L << 32));
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
