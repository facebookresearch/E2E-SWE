import io.chunkbits.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- run-length optimization, structural equality, cloning, subset containment and
 * Hamming similarity. Assertions focus on observable set/boolean/cardinality outcomes (never on
 * internal container representation or exact byte sizes, which are implementation-defined).
 * Expected strings captured from the reference into /tests/expected.tsv.
 */
public class OptimizeHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static {
    // ---- runOptimize keeps the SET identical while enabling run compression ----
    c("run_optimize_preserves_set", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 100L); // a contiguous run -> compressible
      long cardBefore = b.getLongCardinality();
      boolean optimized = b.runOptimize();
      boolean has = b.hasRunCompression();
      return "optimized=" + optimized
          + "|hasRun=" + has
          + "|cardSame=" + (b.getLongCardinality() == cardBefore)
          + "|contains50=" + b.contains(50)
          + "|contains100=" + b.contains(100);
    });

    // ---- removeRunCompression reverses it, set still identical ----
    c("remove_run_compression", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 100L);
      b.runOptimize();
      boolean removed = b.removeRunCompression();
      return "removed=" + removed
          + "|hasRunAfter=" + b.hasRunCompression()
          + "|card=" + b.getLongCardinality();
    });

    // ---- sparse data does not gain run compression ----
    c("run_optimize_sparse", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 100, 10000, 1000000);
      boolean optimized = b.runOptimize();
      return "optimized=" + optimized + "|hasRun=" + b.hasRunCompression();
    });

    // ---- clone produces an equal, independent copy ----
    c("clone_independent", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 1000);
      ChunkBitmap cl = b.clone();
      cl.add(9999); // mutate the clone only
      return "equalBeforeMutateReflected=" + b.equals(ChunkBitmap.bitmapOf(1, 2, 3, 1000))
          + "|cloneHas9999=" + cl.contains(9999)
          + "|origHas9999=" + b.contains(9999);
    });

    // ---- equals is value-based across independently-built bitmaps ----
    c("equals_value_based", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      ChunkBitmap b = new ChunkBitmap();
      b.add(3);
      b.add(1);
      b.add(2);
      ChunkBitmap c = ChunkBitmap.bitmapOf(1, 2, 4);
      return "ab=" + a.equals(b) + "|ac=" + a.equals(c);
    });

    // ---- equals holds across differing run-compression state (value-based) ----
    c("equals_across_runstate", () -> {
      ChunkBitmap a = new ChunkBitmap();
      a.add(0L, 50L);
      ChunkBitmap b = a.clone();
      b.runOptimize(); // b run-compressed, a not
      return "equal=" + a.equals(b) + "|cardSame=" + (a.getLongCardinality() == b.getLongCardinality());
    });

    // ---- contains(subset) ----
    c("contains_subset", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 4);
      return "sub23=" + b.contains(ChunkBitmap.bitmapOf(2, 3))
          + "|sub25=" + b.contains(ChunkBitmap.bitmapOf(2, 5))
          + "|emptySub=" + b.contains(new ChunkBitmap());
    });

    // ---- isHammingSimilar ----
    c("hamming_similar", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3);
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2); // differs by 1 bit
      return "tol1=" + a.isHammingSimilar(b, 1) + "|tol0=" + a.isHammingSimilar(b, 0);
    });

    // ---- trim does not change the set ----
    c("trim_preserves_set", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 1000, 100000);
      long card = b.getLongCardinality();
      b.trim();
      return "cardSame=" + (b.getLongCardinality() == card) + "|contains100000=" + b.contains(100000);
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
