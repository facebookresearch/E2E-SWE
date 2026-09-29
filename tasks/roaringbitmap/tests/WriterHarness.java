import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- the ChunkBitmapWriter builder: incremental construction via add/addMany/flush,
 * the constantMemory + partial-radix-sort configuration, and the capacity sanity errors. Results are
 * asserted by set contents. Expected strings captured from the reference into /tests/expected.tsv.
 */
public class WriterHarness {
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
    // ---- basic writer: add + flush + getUnderlying ----
    c("writer_basic", () -> {
      ChunkBitmapWriter<ChunkBitmap> w = ChunkBitmapWriter.writer().get();
      w.add(1);
      w.add(2);
      w.add(3);
      w.flush();
      return Arrays.toString(w.getUnderlying().toArray());
    });

    // ---- addMany ----
    c("writer_add_many", () -> {
      ChunkBitmapWriter<ChunkBitmap> w = ChunkBitmapWriter.writer().get();
      w.addMany(10, 20, 30, 40);
      w.flush();
      return "card=" + w.getUnderlying().getCardinality()
          + "|toArray=" + Arrays.toString(w.getUnderlying().toArray());
    });

    // ---- add(long,long) range through the writer ----
    c("writer_range", () -> {
      ChunkBitmapWriter<ChunkBitmap> w = ChunkBitmapWriter.writer().get();
      w.add(100L, 105L);
      w.flush();
      return Arrays.toString(w.getUnderlying().toArray());
    });

    // ---- constantMemory + partial radix sort accepts unordered input, yields sorted set ----
    c("writer_constant_memory_unordered", () -> {
      ChunkBitmapWriter<ChunkBitmap> w =
          ChunkBitmapWriter.writer().constantMemory().doPartialRadixSort().get();
      w.add(1000);
      w.add(3);
      w.add(1);
      w.add(2);
      w.add(3); // duplicate
      w.flush();
      return "toArray=" + Arrays.toString(w.getUnderlying().toArray());
    });

    // ---- writer spanning several containers ----
    c("writer_multicontainer", () -> {
      ChunkBitmapWriter<ChunkBitmap> w = ChunkBitmapWriter.writer().get();
      w.add(5);
      w.add(65536 + 7);
      w.add(2 * 65536 + 9);
      ChunkBitmap b = w.get(); // flush + getUnderlying
      return "card=" + b.getCardinality() + "|first=" + b.first() + "|last=" + b.last();
    });

    // ---- capacity sanity: too-large or negative capacity throws IllegalArgumentException ----
    c("writer_capacity_errors", () -> {
      return "tooBig=" + thrown(() -> ChunkBitmapWriter.writer().initialCapacity(70000))
          + "|negative=" + thrown(() -> ChunkBitmapWriter.writer().expectedValuesPerContainer(-1));
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
