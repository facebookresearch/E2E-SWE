import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- the java.util.BitSet-compatible ChunkBitSet view and the BitSetUtil bridge
 * (ChunkBitmap<->BitSet/long[] conversions). ChunkBitSet is expected to mirror java.util.BitSet
 * semantics. Expected strings captured from the reference into /tests/expected.tsv.
 */
public class BitSetInteropHarness {
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

  static {
    // ---- ChunkBitSet: set single + set range; cardinality/length/size/get ----
    c("bitset_set_and_query", () -> {
      ChunkBitSet s = new ChunkBitSet();
      s.set(1);
      s.set(3, 7); // sets 3,4,5,6
      return "card=" + s.cardinality()
          + "|get1=" + s.get(1)
          + "|get2=" + s.get(2)
          + "|get7=" + s.get(7)
          + "|length=" + s.length()
          + "|size=" + s.size()
          + "|isEmpty=" + s.isEmpty();
    });

    // ---- ChunkBitSet: nextSetBit / nextClearBit ----
    c("bitset_next_bits", () -> {
      ChunkBitSet s = new ChunkBitSet();
      s.set(3, 7); // 3,4,5,6
      return "nextSet0=" + s.nextSetBit(0)
          + "|nextSet4=" + s.nextSetBit(4)
          + "|nextSetPastEnd=" + s.nextSetBit(7)
          + "|nextClear0=" + s.nextClearBit(0)
          + "|nextClear3=" + s.nextClearBit(3);
    });

    // ---- ChunkBitSet: empty invariants (mirror java.util.BitSet) ----
    c("bitset_empty", () -> {
      ChunkBitSet s = new ChunkBitSet();
      return "isEmpty=" + s.isEmpty()
          + "|length=" + s.length()
          + "|card=" + s.cardinality()
          + "|nextSet0=" + s.nextSetBit(0)
          + "|nextClear0=" + s.nextClearBit(0)
          + "|toString=" + s.toString();
    });

    // ---- ChunkBitSet: clear-to-empty ----
    c("bitset_clear_range", () -> {
      ChunkBitSet s = new ChunkBitSet();
      s.set(100);
      s.clear(3, 600); // clears 100
      return "isEmpty=" + s.isEmpty() + "|length=" + s.length();
    });

    // ---- ChunkBitSet: get(from,to) is a zero-based sub-view ----
    c("bitset_subview", () -> {
      ChunkBitSet s = new ChunkBitSet();
      s.set(2);
      s.set(5);
      java.util.BitSet sub = s.get(2, 6); // relative -> bits 0 and 3
      return "sub0=" + sub.get(0) + "|sub3=" + sub.get(3) + "|subCard=" + sub.cardinality();
    });

    // ---- ChunkBitSet: boolean ops match truth tables ----
    c("bitset_boolean_ops", () -> {
      ChunkBitSet a = new ChunkBitSet();
      a.set(2, 128); // 2..127
      ChunkBitSet b = new ChunkBitSet();
      b.set(2, 64); // 2..63
      a.and(b);
      ChunkBitSet x = new ChunkBitSet();
      x.set(2);
      x.set(64);
      x.set(127);
      ChunkBitSet y = new ChunkBitSet();
      y.set(64);
      y.set(127);
      x.xor(y);
      return "andCard=" + a.cardinality()
          + "|andFirst=" + a.nextSetBit(0)
          + "|andLast=" + (a.length() - 1)
          + "|xorResult=" + x.toString();
    });

    // ---- ChunkBitSet: flip round-trips ----
    c("bitset_flip", () -> {
      ChunkBitSet s = new ChunkBitSet();
      s.flip(7);
      boolean afterOne = s.get(7);
      s.flip(7);
      return "afterOne=" + afterOne + "|afterTwoEmpty=" + s.isEmpty();
    });

    // ---- BitSetUtil.bitmapOf(BitSet) round-trips ----
    c("bitsetutil_from_bitset", () -> {
      java.util.BitSet bs = new java.util.BitSet();
      bs.set(1);
      bs.set(1000);
      ChunkBitmap b = BitSetUtil.bitmapOf(bs);
      return "card=" + b.getCardinality() + "|toArray=" + Arrays.toString(b.toArray());
    });

    // ---- BitSetUtil.bitmapOf(long[]) little-endian word semantics ----
    c("bitsetutil_from_longs", () -> {
      ChunkBitmap b = BitSetUtil.bitmapOf(new long[] {0b1010L}); // bits 1 and 3
      return "toArray=" + Arrays.toString(b.toArray());
    });

    // ---- BitSetUtil.toLongArray round-trip: bitmapOf(toLongArray(b)) reconstructs b; empty -> len 0 ----
    c("bitsetutil_to_longs", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 3, 64, 130);
      long[] words = BitSetUtil.toLongArray(b);
      ChunkBitmap roundTrip = BitSetUtil.bitmapOf(words);
      long[] emptyWords = BitSetUtil.toLongArray(new ChunkBitmap());
      return "roundTrips=" + roundTrip.equals(b)
          + "|word0=" + words[0]
          + "|emptyLen=" + emptyWords.length;
    });

    // ---- BitSetUtil.bitsetOf + equals ----
    c("bitsetutil_bitset_of", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(2, 5, 9);
      java.util.BitSet bs = BitSetUtil.bitsetOf(b);
      return "bs2=" + bs.get(2)
          + "|bs5=" + bs.get(5)
          + "|bs3=" + bs.get(3)
          + "|equals=" + BitSetUtil.equals(bs, b);
    });

    // ---- BitSetUtil: negative bit set -> IllegalArgumentException on toLongArray ----
    c("bitsetutil_negative_error", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0xFFFFFFFF); // negative as signed int
      return "err=" + thrown(() -> BitSetUtil.toLongArray(b));
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
