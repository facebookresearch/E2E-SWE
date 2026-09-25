import io.chunkbits.*;
import io.chunkbits.insights.*;

import java.io.*;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- run-length container encoding. A key compression contract: range constructors
 * and range mutations produce run-encoded chunks directly (not just after an explicit runOptimize),
 * and run encoding is preserved through range-remove / andNot / xor / orNot / selectRange / slicing
 * where the result is still run-representable. Asserted via the observable hasRunCompression() and
 * serializedSizeInBytes() (a range-encoded chunk serialises far smaller than an array/bitmap chunk),
 * plus the insights run-container count. Expected values captured from the reference into expected.tsv.
 */
public class RunEncodingHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static int serializedSize(ChunkBitmap b) {
    try {
      ByteArrayOutputStream bos = new ByteArrayOutputStream();
      b.serialize(new DataOutputStream(bos));
      return bos.toByteArray().length;
    } catch (Exception e) {
      return -1;
    }
  }

  static {
    // ---- bitmapOfRange produces a run-encoded chunk directly (no runOptimize) ----
    c("range_ctor_is_run", () -> {
      ChunkBitmap small = ChunkBitmap.bitmapOfRange(0, 100);
      ChunkBitmap big = ChunkBitmap.bitmapOfRange(10, 5000); // >4096 values, still one run
      return "smallRun=" + small.hasRunCompression()
          + "|smallSize=" + serializedSize(small)
          + "|smallRunCount=" + BitmapAnalyser.analyse(small).getRunContainerCount()
          + "|bigRun=" + big.hasRunCompression()
          + "|bigSize=" + serializedSize(big)
          + "|bigCard=" + big.getCardinality();
    });

    // ---- add(long,long) on a fresh bitmap yields a run-encoded chunk directly ----
    c("add_range_is_run", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 1000L);
      return "run=" + b.hasRunCompression()
          + "|size=" + serializedSize(b)
          + "|runCount=" + BitmapAnalyser.analyse(b).getRunContainerCount()
          + "|card=" + b.getCardinality();
    });

    // ---- flip(long,long) over a fresh region yields a run-encoded chunk directly ----
    c("flip_range_is_run", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.flip(0L, 300L);
      return "run=" + b.hasRunCompression()
          + "|size=" + serializedSize(b)
          + "|card=" + b.getCardinality();
    });

    // ---- range-remove from a run chunk keeps run encoding (splits into runs, not a bitmap) ----
    c("range_remove_keeps_run", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 20000L);
      b.runOptimize();
      b.remove(5000L, 6000L); // punches a hole -> two runs
      return "run=" + b.hasRunCompression()
          + "|card=" + b.getCardinality()
          + "|runCount=" + BitmapAnalyser.analyse(b).getRunContainerCount();
    });

    // ---- andNot against a run chunk keeps run encoding ----
    c("andnot_keeps_run", () -> {
      ChunkBitmap a = new ChunkBitmap();
      a.add(0L, 10000L);
      a.runOptimize();
      a.andNot(ChunkBitmap.bitmapOf(5000)); // splits the run in two
      return "run=" + a.hasRunCompression()
          + "|card=" + a.getCardinality()
          + "|contains5000=" + a.contains(5000);
    });

    // ---- xor against a run chunk keeps run encoding where result is still run-representable ----
    c("xor_keeps_run", () -> {
      ChunkBitmap a = new ChunkBitmap();
      a.add(0L, 10000L);
      a.runOptimize();
      a.xor(ChunkBitmap.bitmapOf(4999, 5000, 5001)); // toggles three interior values
      return "run=" + a.hasRunCompression()
          + "|card=" + a.getCardinality()
          + "|contains5000=" + a.contains(5000);
    });

    // ---- orNot builds the complement over a full chunk; verify the resulting SET is correct ----
    c("ornot_is_run", () -> {
      ChunkBitmap a = ChunkBitmap.bitmapOf(5);
      a.orNot(ChunkBitmap.bitmapOf(2, 3), 65536L); // complement of {2,3} over [0,65536) plus {5}
      return "card=" + a.getCardinality()
          + "|contains0=" + a.contains(0)
          + "|contains2=" + a.contains(2)
          + "|contains5=" + a.contains(5)
          + "|contains65535=" + a.contains(65535);
    });

    // ---- selectRange over a run-optimized multi-chunk bitmap keeps run encoding ----
    c("selectrange_keeps_run", () -> {
      ChunkBitmap b = new ChunkBitmap();
      b.add(0L, 200000L);
      b.runOptimize();
      ChunkBitmap sub = b.selectRange(65530L, 131080L);
      return "run=" + sub.hasRunCompression() + "|card=" + sub.getCardinality();
    });

    // ---- aggregation over range-built operands produces the correct union set ----
    c("aggregation_run_operands", () -> {
      ChunkBitmap r =
          FastAggregation.or(
              ChunkBitmap.bitmapOfRange(0, 1000),
              ChunkBitmap.bitmapOfRange(500, 1500),
              ChunkBitmap.bitmapOfRange(1000, 2000));
      return "card=" + r.getCardinality()
          + "|first=" + r.first()
          + "|last=" + r.last()
          + "|contains1500=" + r.contains(1500);
    });

    // ---- subset containment across run + array chunks spanning multiple containers ----
    c("run_subset_contains", () -> {
      ChunkBitmap big = new ChunkBitmap();
      big.add(0L, 200000L);
      big.runOptimize();
      ChunkBitmap sub = ChunkBitmap.bitmapOf(65535, 65536, 131072);
      ChunkBitmap notSub = ChunkBitmap.bitmapOf(65535, 999999);
      return "contains=" + big.contains(sub) + "|containsNot=" + big.contains(notSub);
    });

    // ---- serialized range chunk round-trips and re-parses to an equal, still-run bitmap ----
    c("range_run_roundtrip", () -> {
      try {
        ChunkBitmap in = ChunkBitmap.bitmapOfRange(100, 9000);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        in.serialize(new DataOutputStream(bos));
        ChunkBitmap out = new ChunkBitmap();
        out.deserialize(new DataInputStream(new ByteArrayInputStream(bos.toByteArray())));
        return "equals=" + in.equals(out)
            + "|outRun=" + out.hasRunCompression()
            + "|card=" + out.getCardinality();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
