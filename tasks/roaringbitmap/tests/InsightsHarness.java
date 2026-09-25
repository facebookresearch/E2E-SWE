import io.chunkbits.*;
import io.chunkbits.insights.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- the insights analyser, which reports the internal container-type breakdown of
 * a ChunkBitmap (array / bitmap / run container counts + array cardinality stats). Inputs are chosen
 * so the resulting container type is deterministic: a tiny sparse set -> one array container; a
 * run-optimized contiguous range -> one run container; a >4096-cardinality single-chunk block -> one
 * bitmap container. Expected strings captured from the reference into /tests/expected.tsv.
 */
public class InsightsHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static {
    // ---- a small sparse bitmap is one array container ----
    c("array_container", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 5, 9, 100);
      BitmapStatistics s = BitmapAnalyser.analyse(b);
      return "containerCount=" + s.containerCount()
          + "|arrayCount=" + s.getArrayContainersStats().getContainersCount()
          + "|bitmapCount=" + s.getBitmapContainerCount()
          + "|runCount=" + s.getRunContainerCount()
          + "|arrCardSum=" + s.getArrayContainersStats().getCardinalitySum();
    });

    // ---- a run-optimized contiguous range is one run container ----
    c("run_container", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 1000L);
      b.runOptimize();
      BitmapStatistics s = BitmapAnalyser.analyse(b);
      return "containerCount=" + s.containerCount()
          + "|runCount=" + s.getRunContainerCount()
          + "|arrayCount=" + s.getArrayContainersStats().getContainersCount()
          + "|bitmapCount=" + s.getBitmapContainerCount();
    });

    // ---- a dense (>4096) single-chunk block is one bitmap container ----
    c("bitmap_container", () -> {
      ChunkBitmap b = new ChunkBitmap();
      for (int i = 0; i < 5000; i++) {
        b.add(i * 2); // 5000 non-contiguous values in chunk 0 -> bitmap container
      }
      BitmapStatistics s = BitmapAnalyser.analyse(b);
      return "containerCount=" + s.containerCount()
          + "|bitmapCount=" + s.getBitmapContainerCount()
          + "|runCount=" + s.getRunContainerCount();
    });

    // ---- analysing a collection sums the per-bitmap stats; empty stats sentinel ----
    c("collection_and_empty", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(1, 2, 3); // array container
      ChunkBitmap b = ChunkBitmap.bitmapOf(100, 200); // array container
      BitmapStatistics s = BitmapAnalyser.analyse(Arrays.asList(a, b));
      BitmapStatistics empty = BitmapAnalyser.analyse(new ChunkBitmap());
      return "bitmapsCount=" + s.getBitmapsCount()
          + "|arrayCount=" + s.getArrayContainersStats().getContainersCount()
          + "|arrCardSum=" + s.getArrayContainersStats().getCardinalitySum()
          + "|emptyContainerCount=" + empty.containerCount();
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
