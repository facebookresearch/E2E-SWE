import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- iteration surfaces of ChunkBitmap: boxed Iterator, primitive int iterators
 * (ascending / reverse / signed), the peekable advance API, the batch iterator, forEach /
 * forEachInRange, and toArray. Expected strings captured from the reference into expected.tsv.
 */
public class IteratorHarness {
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
    // ---- toArray: sorted unsigned ----
    c("to_array", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1000, 3, 1, 2);
      return Arrays.toString(b.toArray());
    });

    // ---- boxed iterator yields unsigned-ascending; remove() unsupported ----
    c("boxed_iterator", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(3, 1, 2);
      StringBuilder sb = new StringBuilder();
      for (Integer i : b) {
        sb.append(i).append(",");
      }
      String removeErr = thrown(() -> {
        Iterator<Integer> it = ChunkBitmap.bitmapOf(1).iterator();
        it.next();
        it.remove();
      });
      return "seq=" + sb + "|removeErr=" + removeErr;
    });

    // ---- primitive int iterator (ascending) over the sign boundary ----
    c("int_iterator_unsigned", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(5, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF);
      IntIterator it = b.getIntIterator();
      StringBuilder sb = new StringBuilder();
      while (it.hasNext()) {
        sb.append(it.next()).append(",");
      }
      return sb.toString();
    });

    // ---- reverse iterator ----
    c("reverse_iterator", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 1000);
      IntIterator it = b.getReverseIntIterator();
      StringBuilder sb = new StringBuilder();
      while (it.hasNext()) {
        sb.append(it.next()).append(",");
      }
      return sb.toString();
    });

    // ---- signed iterator orders by signed value (MIN first) ----
    c("signed_iterator", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(5, 0x80000000, 0xFFFFFFFF, 1);
      IntIterator it = b.getSignedIntIterator();
      StringBuilder sb = new StringBuilder();
      while (it.hasNext()) {
        sb.append(it.next()).append(",");
      }
      return sb.toString();
    });

    // ---- peekable advanceIfNeeded + peekNext ----
    c("peekable_advance", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 4, 5, 9);
      PeekableIntIterator it = b.getIntIterator();
      it.advanceIfNeeded(4);
      int peek1 = it.peekNext();
      int next1 = it.next(); // 4
      it.advanceIfNeeded(9);
      int peek2 = it.peekNext();
      return "peek1=" + peek1 + "|next1=" + next1 + "|peek2=" + peek2;
    });

    // ---- batch iterator fills a buffer; sum of batch counts == cardinality ----
    c("batch_iterator", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 5000L); // 5000 values across containers
      BatchIterator bit = b.getBatchIterator();
      int[] buf = new int[256];
      long total = 0;
      int firstVal = -1;
      boolean first = true;
      while (bit.hasNext()) {
        int n = bit.nextBatch(buf);
        if (first && n > 0) {
          firstVal = buf[0];
          first = false;
        }
        total += n;
      }
      return "total=" + total + "|firstVal=" + firstVal;
    });

    // ---- empty batch iterator ----
    c("batch_iterator_empty", () -> {
      ChunkBitmap b = new ChunkBitmap();
      BatchIterator bit = b.getBatchIterator();
      int[] buf = new int[16];
      return "hasNext=" + bit.hasNext() + "|nextBatch=" + bit.nextBatch(buf);
    });

    // ---- forEach visits all in unsigned order ----
    c("for_each", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(10, 20, 30);
      StringBuilder sb = new StringBuilder();
      b.forEach((IntConsumer) v -> sb.append(v).append(","));
      return sb.toString();
    });

    // ---- forEachInRange: only present values in [start,start+length) ----
    c("for_each_in_range", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 5, 8, 12, 20);
      StringBuilder sb = new StringBuilder();
      b.forEachInRange(5, 10, (IntConsumer) v -> sb.append(v).append(",")); // [5,15): 5,8,12
      return sb.toString();
    });

    // ---- reverse iterator on empty ----
    c("iterator_empty", () -> {
      ChunkBitmap b = new ChunkBitmap();
      return "intHasNext=" + b.getIntIterator().hasNext()
          + "|revHasNext=" + b.getReverseIntIterator().hasNext()
          + "|boxedHasNext=" + b.iterator().hasNext();
    });

    // ---- iterator clone is independent ----
    c("iterator_clone", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3);
      PeekableIntIterator it = b.getIntIterator();
      it.next(); // consume 1
      PeekableIntIterator clone = it.clone();
      int origNext = it.next(); // 2
      int cloneNext = clone.next(); // 2 (independent position)
      return "origNext=" + origNext + "|cloneNext=" + cloneNext;
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
