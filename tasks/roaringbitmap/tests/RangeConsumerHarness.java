import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- forAllInRange with a RelativeRangeConsumer, which reports BOTH present and
 * absent positions (relative to the window start) over a range, plus its error paths. Expected
 * strings captured from the reference into /tests/expected.tsv.
 */
public class RangeConsumerHarness {
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

  /** Records P (present) / A (absent) per relative position into a fixed-size char[]. */
  static final class Recorder implements RelativeRangeConsumer {
    final char[] marks;

    Recorder(int length) {
      marks = new char[length];
      Arrays.fill(marks, '?');
    }

    @Override
    public void acceptPresent(int relativePos) {
      marks[relativePos] = 'P';
    }

    @Override
    public void acceptAbsent(int relativePos) {
      marks[relativePos] = 'A';
    }

    @Override
    public void acceptAllPresent(int relativeFrom, int relativeTo) {
      for (int i = relativeFrom; i < relativeTo; i++) {
        marks[i] = 'P';
      }
    }

    @Override
    public void acceptAllAbsent(int relativeFrom, int relativeTo) {
      for (int i = relativeFrom; i < relativeTo; i++) {
        marks[i] = 'A';
      }
    }

    String result() {
      return new String(marks);
    }
  }

  static {
    // ---- mixed present/absent window: 2 absent then 3 present ----
    c("mixed_window", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(100L, 110L); // present [100,110)
      Recorder rec = new Recorder(5);
      b.forAllInRange(98, 5, rec); // positions 98..102 -> A,A,P,P,P
      return rec.result();
    });

    // ---- fully present window ----
    c("all_present", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(100L, 10000L);
      Recorder rec = new Recorder(50);
      b.forAllInRange(200, 50, rec);
      return rec.result();
    });

    // ---- fully absent window ----
    c("all_absent", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(100L, 110L);
      Recorder rec = new Recorder(20);
      b.forAllInRange(200, 20, rec);
      return rec.result();
    });

    // ---- window crossing a container boundary ----
    c("window_boundary", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(65534);
      b.add(65536);
      Recorder rec = new Recorder(5);
      b.forAllInRange(65534, 5, rec); // 65534..65538 -> P,A,P,A,A
      return rec.result();
    });

    // ---- reading up to the very end of the unsigned range is allowed ----
    c("read_to_end", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0xFFFFFFFE);
      b.add(0xFFFFFFFF);
      Recorder rec = new Recorder(2);
      b.forAllInRange(0xFFFFFFFE, 2, rec); // both present
      return rec.result();
    });

    // ---- error paths: negative length and reading past the unsigned end ----
    c("errors", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0xFFFFFFFF);
      return "negLen=" + thrown(() -> new ChunkBitmap().forAllInRange(0, -1, new Recorder(1)))
          + "|pastEnd=" + thrown(() -> b.forAllInRange(0xFFFFFFFE, 3, new Recorder(3)));
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
