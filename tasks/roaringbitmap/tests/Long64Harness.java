import io.chunkbits.longlong.*;

import java.io.*;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- Chunk64Bitmap, the 64-bit (ART-backed) variant. Longs are ALWAYS treated as
 * unsigned: order is 0,1,...,Long.MAX_VALUE, Long.MIN_VALUE,...,-1. Covers add/addRange, rank/select
 * across the sign boundary, iterators, flip range, set algebra, and an in-memory serialize round
 * trip. Expected strings captured from the reference into /tests/expected.tsv.
 */
public class Long64Harness {
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

  static String longs(Chunk64Bitmap b) {
    return Arrays.toString(b.toArray());
  }

  static {
    // ---- basic add/contains/cardinality ----
    c("l64_basic", () -> {
      Chunk64Bitmap b = Chunk64Bitmap.bitmapOf(1L, 2L, 100L, 1000L);
      b.addLong(1234L);
      return "card=" + b.getLongCardinality()
          + "|c1=" + b.contains(1L)
          + "|c3=" + b.contains(3L)
          + "|c1234=" + b.contains(1234L);
    });

    // ---- unsigned ordering: toArray / select over the sign boundary ----
    c("l64_unsigned_order", () -> {
      Chunk64Bitmap b = Chunk64Bitmap.bitmapOf(Long.MIN_VALUE, 0L, 1L, Long.MAX_VALUE);
      return "toArray=" + longs(b)
          + "|sel0=" + b.select(0)
          + "|sel1=" + b.select(1)
          + "|sel2=" + b.select(2)
          + "|sel3=" + b.select(3);
    });

    // ---- rank across the sign boundary ----
    c("l64_rank_unsigned", () -> {
      Chunk64Bitmap b = Chunk64Bitmap.bitmapOf(Long.MIN_VALUE, 0L, 1L, Long.MAX_VALUE);
      return "r0=" + b.rankLong(0L)
          + "|r1=" + b.rankLong(1L)
          + "|rMax=" + b.rankLong(Long.MAX_VALUE)
          + "|rNeg1=" + b.rankLong(-1L)
          + "|rMin=" + b.rankLong(Long.MIN_VALUE);
    });

    // ---- addLong(1); addLong(-1) unsigned: -1 is the largest ----
    c("l64_add_negative_unsigned", () -> {
      Chunk64Bitmap b = new Chunk64Bitmap();
      b.addLong(1L);
      b.addLong(-1L);
      return "sel0=" + b.select(0) + "|sel1=" + b.select(1) + "|rankNeg1=" + b.rankLong(-1L);
    });

    // ---- addRange half-open ----
    c("l64_add_range", () -> {
      Chunk64Bitmap b = new Chunk64Bitmap();
      b.addRange(5L, 12L);
      return "card=" + b.getLongCardinality() + "|sel0=" + b.select(0) + "|sel6=" + b.select(6);
    });

    // ---- addRange crossing the sign boundary (unsigned) ----
    c("l64_add_range_signspan", () -> {
      Chunk64Bitmap b = new Chunk64Bitmap();
      b.addRange(Long.MAX_VALUE - 1, Long.MAX_VALUE + 3); // MAX-1, MAX, MIN, MIN+1
      return "card=" + b.getLongCardinality() + "|toArray=" + longs(b);
    });

    // ---- addRange invalid ranges throw IllegalArgumentException ----
    c("l64_add_range_errors", () -> {
      return "eq=" + thrown(() -> new Chunk64Bitmap().addRange(5L, 5L))
          + "|rev=" + thrown(() -> new Chunk64Bitmap().addRange(10L, 3L))
          + "|zero=" + thrown(() -> new Chunk64Bitmap().addRange(0L, 0L));
    });

    // ---- first / last (unsigned); empty throws NoSuchElementException ----
    c("l64_first_last", () -> {
      Chunk64Bitmap b = Chunk64Bitmap.bitmapOf(2L, 4L, 8L, -128L, -64L, -32L);
      return "first=" + b.first()
          + "|last=" + b.last()
          + "|emptyFirst=" + thrown(() -> new Chunk64Bitmap().first());
    });

    // ---- select out of range throws IllegalArgumentException ----
    c("l64_select_error", () -> {
      return "err=" + thrown(() -> Chunk64Bitmap.bitmapOf(1L, 2L, 3L).select(3))
          + "|emptyErr=" + thrown(() -> new Chunk64Bitmap().select(0));
    });

    // ---- long iterator ascending unsigned ----
    c("l64_iterator", () -> {
      Chunk64Bitmap b = Chunk64Bitmap.bitmapOf(Long.MIN_VALUE, 0L, 1L, Long.MAX_VALUE);
      LongIterator it = b.getLongIterator();
      StringBuilder sb = new StringBuilder();
      while (it.hasNext()) {
        sb.append(it.next()).append(",");
      }
      return sb.toString();
    });

    // ---- reverse iterator ----
    c("l64_reverse_iterator", () -> {
      Chunk64Bitmap b = Chunk64Bitmap.bitmapOf(1L, 5L, 100L);
      LongIterator it = b.getReverseLongIterator();
      StringBuilder sb = new StringBuilder();
      while (it.hasNext()) {
        sb.append(it.next()).append(",");
      }
      return sb.toString();
    });

    // ---- peekable advanceIfNeeded across the sign boundary ----
    c("l64_peekable_advance", () -> {
      Chunk64Bitmap b = new Chunk64Bitmap();
      b.addRange(Long.MAX_VALUE, Long.MIN_VALUE + 3); // MAX, MIN, MIN+1, MIN+2
      PeekableLongIterator it = b.getLongIterator();
      it.advanceIfNeeded(Long.MAX_VALUE);
      long p1 = it.peekNext();
      it.advanceIfNeeded(Long.MIN_VALUE + 1);
      long p2 = it.peekNext();
      return "p1=" + p1 + "|p2=" + p2;
    });

    // ---- set algebra: same and differing high buckets ----
    c("l64_set_algebra", () -> {
      Chunk64Bitmap a = Chunk64Bitmap.bitmapOf(123L, 234L);
      Chunk64Bitmap b = Chunk64Bitmap.bitmapOf(234L, 345L);
      Chunk64Bitmap x = a.clone();
      x.xor(b);
      Chunk64Bitmap an = a.clone();
      an.and(b);
      Chunk64Bitmap anot = a.clone();
      anot.andNot(b);
      return "xor=" + longs(x) + "|and=" + longs(an) + "|andNot=" + longs(anot);
    });

    // ---- self ops: xor/andNot -> empty; or/and -> unchanged ----
    c("l64_self_ops", () -> {
      Chunk64Bitmap x = Chunk64Bitmap.bitmapOf(1L, 2L, 3L);
      x.xor(x);
      Chunk64Bitmap y = Chunk64Bitmap.bitmapOf(1L, 2L, 3L);
      y.or(y);
      return "xorSelfCard=" + x.getLongCardinality() + "|orSelfCard=" + y.getLongCardinality();
    });

    // ---- flip range (Chunk64Bitmap has a range flip) ----
    c("l64_flip_range", () -> {
      Chunk64Bitmap b = new Chunk64Bitmap();
      b.addLong(0L);
      b.flip(1L, 2L); // add 1
      Chunk64Bitmap b2 = new Chunk64Bitmap();
      b2.addLong(0L);
      b2.flip(0xFFFFL, 0x10002L); // across a 16-bit container edge
      return "flip1Card=" + b.getLongCardinality()
          + "|flip1Sel1=" + b.select(1)
          + "|edgeCard=" + b2.getLongCardinality()
          + "|edgeSel3=" + b2.select(3);
    });

    // ---- serialize(DataOutput) and serialize(ByteBuffer) emit the SAME bytes; cross round-trip ----
    c("l64_serialize_overloads_agree", () -> {
      try {
        Chunk64Bitmap in = Chunk64Bitmap.bitmapOf(1L, (1L << 40) + 7L, (1L << 40) + 9L, -3L);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        in.serialize(new DataOutputStream(bos));
        byte[] viaStream = bos.toByteArray();
        java.nio.ByteBuffer buf = java.nio.ByteBuffer.allocate((int) in.serializedSizeInBytes());
        in.serialize(buf);
        byte[] viaBuffer = buf.array();
        // cross round-trip: DataOutput bytes read back via ByteBuffer
        Chunk64Bitmap out = new Chunk64Bitmap();
        out.deserialize(java.nio.ByteBuffer.wrap(viaStream));
        return "identical=" + Arrays.equals(viaStream, viaBuffer)
            + "|crossEquals=" + in.equals(out)
            + "|crossCard=" + out.getLongCardinality();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- serialize -> deserialize round-trip (in-memory) with high-bit-spanning values ----
    c("l64_serialize_roundtrip", () -> {
      try {
        Chunk64Bitmap in = Chunk64Bitmap.bitmapOf(-123L, 123L, Long.MAX_VALUE);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        in.serialize(new DataOutputStream(bos));
        Chunk64Bitmap out = new Chunk64Bitmap();
        out.deserialize(new DataInputStream(new ByteArrayInputStream(bos.toByteArray())));
        return "card=" + out.getLongCardinality()
            + "|sel0=" + out.select(0)
            + "|sel1=" + out.select(1)
            + "|sel2=" + out.select(2)
            + "|equals=" + in.equals(out);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
