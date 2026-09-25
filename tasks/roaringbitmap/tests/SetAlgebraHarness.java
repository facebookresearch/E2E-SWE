import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- set algebra (and/or/xor/andNot, their cardinality-only forms, intersects,
 * orNot) on ChunkBitmap, both the static (immutable) and in-place variants.
 *
 * Each case builds concrete operands and asserts the exact resulting set (via toArray/toString) or
 * the exact cardinality/boolean, joined with '|'. Values are deterministic and offline; expected
 * strings captured from the reference into /tests/expected.tsv. Imports only public io.chunkbits API.
 */
public class SetAlgebraHarness {
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

  static String arr(ChunkBitmap b) {
    return Arrays.toString(b.toArray());
  }

  static {
    // ---- static and/or/xor/andNot on overlapping operands ----
    c("static_ops", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      ChunkBitmap b = ChunkBitmap.bitmapOf(2, 3, 4);
      return "and=" + arr(ChunkBitmap.and(a, b))
          + "|or=" + arr(ChunkBitmap.or(a, b))
          + "|xor=" + arr(ChunkBitmap.xor(a, b))
          + "|andNot=" + arr(ChunkBitmap.andNot(a, b))
          // inputs must be unchanged by static ops
          + "|aUnchanged=" + arr(a)
          + "|bUnchanged=" + arr(b);
    });

    // ---- in-place and ----
    c("inplace_and", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3, 4, 5);
      a.and(ChunkBitmap.bitmapOf(2, 4, 6));
      return arr(a);
    });

    // ---- in-place or ----
    c("inplace_or", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      a.or(ChunkBitmap.bitmapOf(3, 4, 5));
      return arr(a);
    });

    // ---- in-place xor ----
    c("inplace_xor", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      a.xor(ChunkBitmap.bitmapOf(2, 3, 4));
      return arr(a);
    });

    // ---- in-place andNot ----
    c("inplace_andnot", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3, 4);
      a.andNot(ChunkBitmap.bitmapOf(2, 4));
      return arr(a);
    });

    // ---- self-operations: xor/andNot with self clear; and/or with self no-op ----
    c("self_ops", () -> {
      ChunkBitmap x1 = ChunkBitmap.bitmapOf(1, 2, 3);
      x1.xor(x1);
      ChunkBitmap x2 = ChunkBitmap.bitmapOf(1, 2, 3);
      x2.andNot(x2);
      ChunkBitmap x3 = ChunkBitmap.bitmapOf(1, 2, 3);
      x3.and(x3);
      ChunkBitmap x4 = ChunkBitmap.bitmapOf(1, 2, 3);
      x4.or(x4);
      return "xorSelf=" + x1.getCardinality()
          + "|andNotSelf=" + x2.getCardinality()
          + "|andSelf=" + arr(x3)
          + "|orSelf=" + arr(x4);
    });

    // ---- cardinality-only forms (no result materialization) ----
    c("cardinality_forms", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      ChunkBitmap b = ChunkBitmap.bitmapOf(2, 3, 4);
      return "and=" + ChunkBitmap.andCardinality(a, b)
          + "|or=" + ChunkBitmap.orCardinality(a, b)
          + "|xor=" + ChunkBitmap.xorCardinality(a, b)
          + "|andNot=" + ChunkBitmap.andNotCardinality(a, b);
    });

    // ---- disjoint operands: empty intersection, additive union ----
    c("disjoint_ops", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      ChunkBitmap b = ChunkBitmap.bitmapOf(100, 200, 300);
      return "andCard=" + ChunkBitmap.andCardinality(a, b)
          + "|orCard=" + ChunkBitmap.orCardinality(a, b)
          + "|intersects=" + ChunkBitmap.intersects(a, b);
    });

    // ---- intersects (static) and intersects(long,long) range ----
    c("intersects", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      ChunkBitmap b = ChunkBitmap.bitmapOf(3, 4, 5);
      ChunkBitmap c = ChunkBitmap.bitmapOf(4);
      return "ab=" + ChunkBitmap.intersects(a, b)
          + "|ac=" + ChunkBitmap.intersects(a, c)
          + "|rangeIn=" + c.intersects(2L, 6L)
          + "|rangeOut=" + c.intersects(5L, 10L)
          + "|supLEmin=" + c.intersects(5L, 5L);
    });

    // ---- multi-arg or(...) equals pairwise fold ----
    c("multi_or", () -> {
      ChunkBitmap r =
          ChunkBitmap.or(
              ChunkBitmap.bitmapOf(1, 2), ChunkBitmap.bitmapOf(2, 3), ChunkBitmap.bitmapOf(4));
      return "card=" + r.getCardinality() + "|toArray=" + arr(r);
    });

    // ---- or(Iterator) form ----
    c("or_iterator", () -> {
      List<ChunkBitmap> list =
          Arrays.asList(ChunkBitmap.bitmapOf(1), ChunkBitmap.bitmapOf(2, 3), ChunkBitmap.bitmapOf(3, 4));
      ChunkBitmap r = ChunkBitmap.or(list.iterator());
      return arr(r);
    });

    // ---- unsigned operands: ops respect unsigned ordering across the sign boundary ----
    c("unsigned_ops", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(0x7FFFFFFF, 0x80000000, 0xFFFFFFFF);
      ChunkBitmap b = ChunkBitmap.bitmapOf(0x80000000, 5);
      return "or=" + arr(ChunkBitmap.or(a, b))
          + "|and=" + arr(ChunkBitmap.and(a, b))
          + "|andNot=" + arr(ChunkBitmap.andNot(a, b));
    });

    // ---- orNot: complement of other within [0,rangeEnd) OR'd with this; self -> UnsupportedOp ----
    c("or_not", () -> {
      ChunkBitmap x1 = ChunkBitmap.bitmapOf(0);
      ChunkBitmap x2 = ChunkBitmap.bitmapOf(2, 3);
      ChunkBitmap x1copy = x1.clone();
      x1copy.orNot(x2, 5L); // complement of {2,3} in [0,5) = {0,1,4}, OR {0} -> {0,1,4}
      String selfErr = thrown(() -> ChunkBitmap.bitmapOf(1, 2).orNot(ChunkBitmap.bitmapOf(1, 2), 5L));
      // NB: orNot(this) throws; use two distinct bitmaps otherwise.
      ChunkBitmap sameContent = ChunkBitmap.bitmapOf(1, 2);
      return "inplace=" + arr(x1copy) + "|selfErr=" + selfErr + "|sc=" + sameContent.getCardinality();
    });

    // ---- static orNot ----
    c("static_or_not", () -> {
      ChunkBitmap x1 = ChunkBitmap.bitmapOf(0);
      ChunkBitmap x2 = ChunkBitmap.bitmapOf(2, 3);
      ChunkBitmap r = ChunkBitmap.orNot(x1, x2, 5L);
      return "toArray=" + arr(r) + "|x1Unchanged=" + arr(x1);
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
