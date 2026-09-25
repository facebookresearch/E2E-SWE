import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- rank/select, navigation (next/previous value/absent value), first/last,
 * rangeCardinality, selectRange and limit on ChunkBitmap.
 *
 * Navigation methods return `long` (so -1L sentinel and full unsigned values like 4294967295L are
 * representable) -- assertions capture them as longs. Unsigned ordering is exercised at the sign
 * boundary. Expected strings captured from the reference into /tests/expected.tsv.
 */
public class RankSelectHarness {
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
    // ---- rank: count of values <= x (unsigned); rank(smallest)=1 ----
    c("rank_basic", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 1000);
      return "r0=" + b.rank(0)
          + "|r1=" + b.rank(1)
          + "|r2=" + b.rank(2)
          + "|r999=" + b.rank(999)
          + "|r1000=" + b.rank(1000)
          + "|rankLong1000=" + b.rankLong(1000);
    });

    // ---- select: j-th smallest (0-based); out-of-range throws IllegalArgumentException ----
    c("select_basic", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 1000);
      return "s0=" + b.select(0)
          + "|s3=" + b.select(3)
          + "|outOfRange=" + thrown(() -> ChunkBitmap.bitmapOf(1, 2, 3, 1000).select(4));
    });

    // ---- rank/select under unsigned ordering across the sign boundary ----
    c("rank_select_unsigned", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(1);
      b.add(Integer.MAX_VALUE); // 2147483647
      b.add(-234); // large unsigned (4294967062)
      return "sel0=" + b.select(0)
          + "|sel1=" + b.select(1)
          + "|sel2=" + b.select(2)
          + "|rankMax=" + b.rank(Integer.MAX_VALUE)
          + "|rankNeg234=" + b.rank(-234);
    });

    // ---- first/last/firstSigned/lastSigned; empty throws NoSuchElementException ----
    c("first_last", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(5);
      b.add(0x80000000); // signed-smallest, unsigned-large
      b.add(100);
      return "first=" + b.first()
          + "|last=" + b.last()
          + "|firstSigned=" + b.firstSigned()
          + "|lastSigned=" + b.lastSigned()
          + "|emptyFirst=" + thrown(() -> new ChunkBitmap().first())
          + "|emptyLast=" + thrown(() -> new ChunkBitmap().last());
    });

    // ---- nextValue: smallest present >= from, else -1L ----
    c("next_value", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(0, 1, 4);
      return "n2=" + b.nextValue(2)
          + "|n4=" + b.nextValue(4)
          + "|n5=" + b.nextValue(5)
          + "|n0=" + b.nextValue(0);
    });

    // ---- previousValue: largest present <= from, else -1L ----
    c("previous_value", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(0, 1, 4);
      return "p3=" + b.previousValue(3)
          + "|p0=" + b.previousValue(0)
          + "|pWrap=" + b.previousValue(-1) // -1 == 0xFFFFFFFF, largest unsigned
          + "|emptyPrev=" + new ChunkBitmap().previousValue(5);
    });

    // ---- nextAbsentValue: smallest absent >= from ----
    c("next_absent_value", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(0, 1, 2);
      return "na0=" + b.nextAbsentValue(0)
          + "|emptyAbsent=" + new ChunkBitmap().nextAbsentValue(5);
    });

    // ---- previousAbsentValue: largest absent <= from ----
    c("previous_absent_value", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2);
      return "pa2=" + b.previousAbsentValue(2) + "|pa5=" + b.previousAbsentValue(5);
    });

    // ---- rangeCardinality: count in [start,end); start>=end -> 0 ----
    c("range_cardinality", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 1000L); // dense [0,1000)
      return "rc_0_1000=" + b.rangeCardinality(0L, 1000L)
          + "|rc_100_200=" + b.rangeCardinality(100L, 200L)
          + "|rc_empty=" + b.rangeCardinality(500L, 500L)
          + "|rc_startGEend=" + b.rangeCardinality(500L, 100L);
    });

    // ---- selectRange: copy limited to [start,end) ----
    c("select_range", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 5, 10, 15, 20);
      ChunkBitmap sub = b.selectRange(5L, 16L); // 5,10,15
      ChunkBitmap empty = b.selectRange(16L, 5L);
      return "sub=" + Arrays.toString(sub.toArray()) + "|emptyCard=" + empty.getCardinality();
    });

    // ---- limit: at most maxcardinality smallest values ----
    c("limit", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 1000);
      return "limit2=" + Arrays.toString(b.limit(2).toArray())
          + "|limit0=" + b.limit(0).getCardinality()
          + "|limit100=" + b.limit(100).getCardinality();
    });

    // ---- nextAbsentValue at the very top of the unsigned range returns -1 (no absent value >= from) ----
    c("next_absent_top_of_range", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(0xFFFFFFFF);
      ChunkBitmap full = new ChunkBitmap();
      full.add(0xFFFF0000L, 0x100000000L); // top container completely full
      return "presentMax=" + b.nextAbsentValue(0xFFFFFFFF)
          + "|fullTop=" + full.nextAbsentValue(0xFFFF0000);
    });

    // ---- previousValue when from's chunk is empty but a lower chunk has values ----
    c("previous_value_empty_middle", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(5);
      b.add(3 * 65536 + 10);
      return "prevMidGap=" + b.previousValue(2 * 65536)
          + "|prevBelow=" + b.previousValue(4);
    });

    // ---- next/previous absent across a full chunk then a gap (multi-container) ----
    c("absent_across_full_chunk", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 65536L); // chunk 0 completely full
      b.add(3 * 65536); // a value in chunk 3
      return "nextAbsent0=" + b.nextAbsentValue(0)
          + "|nextVal0=" + b.nextValue(0)
          + "|prevAbsentInFull=" + b.previousAbsentValue(65535);
    });

    // ---- rangeCardinality / selectRange spanning the signed-boundary and multiple chunks ----
    c("range_ops_sign_boundary", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0x7FFFFFFF); // 2147483647
      b.add(0x80000000); // 2147483648 unsigned
      b.add(0x80000005); // 2147483653 unsigned
      long rc = b.rangeCardinality(0x7FFFFFFFL, 0x80000006L); // [2147483647, 2147483654)
      ChunkBitmap sel = b.selectRange(0x80000000L, 0x80000006L);
      return "rangeCard=" + rc + "|selCard=" + sel.getCardinality() + "|selFirst=" + sel.first();
    });

    // ---- rank/select on a bitmap spanning multiple containers ----
    c("rank_select_multicontainer", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(5);
      b.add(65536 + 7); // second container
      b.add(2 * 65536 + 3); // third container
      return "card=" + b.getCardinality()
          + "|sel0=" + b.select(0)
          + "|sel1=" + b.select(1)
          + "|sel2=" + b.select(2)
          + "|rankMid=" + b.rank(65536 + 7)
          + "|rankLast=" + b.rank(2 * 65536 + 3);
    });

    // ---- nextValue/previousValue crossing a container boundary ----
    c("navigation_boundary", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(65535); // last of container 0
      b.add(65536); // first of container 1
      return "next65535=" + b.nextValue(65535)
          + "|next65534=" + b.nextValue(65534)
          + "|prev65536=" + b.previousValue(65536)
          + "|nextAbsent65535=" + b.nextAbsentValue(65535);
    });

    // ---- large dense range: rank/select consistency at scale ----
    c("dense_rank_select", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 100000L); // {0..99999}
      return "card=" + b.getCardinality()
          + "|sel0=" + b.select(0)
          + "|sel99999=" + b.select(99999)
          + "|rank50000=" + b.rank(50000)
          + "|rangeCard=" + b.rangeCardinality(1000L, 2000L);
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
