import io.chunkbits.ChunkBitmap;
import io.chunkbits.buffer.*;

import java.io.*;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- the buffer package (MutableChunkBitmap / ImmutableChunkBitmap), which mirrors
 * the core API but supports zero-copy reads over a ByteBuffer. All round-trips are in-memory
 * (ByteBuffer.allocate/wrap; no files/mmap). Also verifies cross-package byte-level interop with the
 * core ChunkBitmap. Expected strings captured from the reference into /tests/expected.tsv.
 */
public class BufferHarness {
  static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();

  static void c(String name, Supplier<String> p) {
    cases.put(name, p);
  }

  static String thrown(ThrowingRunnable r) {
    try {
      r.run();
      return "none";
    } catch (Throwable e) {
      return e.getClass().getSimpleName();
    }
  }

  interface ThrowingRunnable {
    void run() throws Exception;
  }

  static String arr(int[] a) {
    return Arrays.toString(a);
  }

  static {
    // ---- MutableChunkBitmap basic ops mirror the core API ----
    c("mutable_basic", () -> {
      MutableChunkBitmap b = MutableChunkBitmap.bitmapOf(1, 2, 3, 1000);
      return "card=" + b.getCardinality()
          + "|toArray=" + arr(b.toArray())
          + "|first=" + b.first()
          + "|last=" + b.last()
          + "|rank1000=" + b.rank(1000)
          + "|select3=" + b.select(3);
    });

    // ---- MutableChunkBitmap set algebra ----
    c("mutable_set_algebra", () -> {
      MutableChunkBitmap a = MutableChunkBitmap.bitmapOf(1, 2, 3);
      MutableChunkBitmap b = MutableChunkBitmap.bitmapOf(2, 3, 4);
      return "and=" + arr(MutableChunkBitmap.and(a, b).toArray())
          + "|or=" + arr(MutableChunkBitmap.or(a, b).toArray())
          + "|xor=" + arr(MutableChunkBitmap.xor(a, b).toArray())
          + "|andNot=" + arr(MutableChunkBitmap.andNot(a, b).toArray());
    });

    // ---- serialize -> wrap in ByteBuffer -> ImmutableChunkBitmap read-back (zero-copy pattern) ----
    c("immutable_from_bytebuffer", () -> {
      try {
        MutableChunkBitmap in = MutableChunkBitmap.bitmapOf(5, 6, 7, 100000, 300000);
        ByteBuffer buf = ByteBuffer.allocate(in.serializedSizeInBytes());
        in.serialize(buf);
        buf.flip();
        ImmutableChunkBitmap back = new ImmutableChunkBitmap(buf);
        return "equals=" + back.equals(in)
            + "|card=" + back.getCardinality()
            + "|validate=" + back.validate()
            + "|sizeMatch=" + (back.serializedSizeInBytes() == in.serializedSizeInBytes());
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- DataOutput/DataInput round-trip for MutableChunkBitmap ----
    c("mutable_dataoutput_roundtrip", () -> {
      try {
        MutableChunkBitmap in = MutableChunkBitmap.bitmapOf(1, 2, 3, 70000, 200000);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        in.serialize(new DataOutputStream(bos));
        MutableChunkBitmap out = new MutableChunkBitmap();
        out.deserialize(new DataInputStream(new ByteArrayInputStream(bos.toByteArray())));
        return "equals=" + in.equals(out) + "|card=" + out.getCardinality();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- reading two bitmaps sequentially from one ByteBuffer (position advance contract) ----
    c("immutable_sequential_read", () -> {
      try {
        MutableChunkBitmap r1 = MutableChunkBitmap.bitmapOf(1, 2, 3, 1000);
        MutableChunkBitmap r2 = MutableChunkBitmap.bitmapOf(2, 3, 1010);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(bos);
        r1.serialize(dos);
        r2.serialize(dos);
        dos.close();
        ByteBuffer bb = ByteBuffer.wrap(bos.toByteArray());
        ImmutableChunkBitmap back1 = new ImmutableChunkBitmap(bb);
        bb.position(bb.position() + back1.serializedSizeInBytes());
        ImmutableChunkBitmap back2 = new ImmutableChunkBitmap(bb);
        return "b1=" + back1.equals(r1) + "|b2=" + back2.equals(r2);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- cross-package interop: core ChunkBitmap and MutableChunkBitmap serialize identically ----
    c("cross_package_bytes_identical", () -> {
      try {
        int[] vals = {1, 2, 3, 1000, 65540, 200000};
        MutableChunkBitmap mrb = MutableChunkBitmap.bitmapOf(vals);
        ChunkBitmap rb = ChunkBitmap.bitmapOf(vals);
        ByteArrayOutputStream b1 = new ByteArrayOutputStream();
        mrb.serialize(new DataOutputStream(b1));
        ByteArrayOutputStream b2 = new ByteArrayOutputStream();
        rb.serialize(new DataOutputStream(b2));
        return "identical=" + Arrays.equals(b1.toByteArray(), b2.toByteArray());
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- cross-package: core-serialized bytes deserialize into a buffer bitmap ----
    c("cross_package_core_to_buffer", () -> {
      try {
        ChunkBitmap rb = ChunkBitmap.bitmapOf(10, 20, 30, 100000);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        rb.serialize(new DataOutputStream(bos));
        MutableChunkBitmap mrb = new MutableChunkBitmap();
        mrb.deserialize(new DataInputStream(new ByteArrayInputStream(bos.toByteArray())));
        return "card=" + mrb.getCardinality() + "|toArray=" + arr(mrb.toArray());
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- in-place ops on MutableChunkBitmap ----
    c("mutable_inplace", () -> {
      MutableChunkBitmap a = MutableChunkBitmap.bitmapOf(1, 2, 3, 4, 5);
      a.and(MutableChunkBitmap.bitmapOf(2, 4, 6));
      MutableChunkBitmap b = MutableChunkBitmap.bitmapOf(1, 2, 3);
      b.or(MutableChunkBitmap.bitmapOf(3, 4));
      return "and=" + arr(a.toArray()) + "|or=" + arr(b.toArray());
    });

    // ---- flip divergence: Immutable static flip on empty range throws; Mutable static clones ----
    c("flip_divergence", () -> {
      MutableChunkBitmap bm = MutableChunkBitmap.bitmapOf(7, 8);
      String immErr = thrown(() -> ImmutableChunkBitmap.flip(bm, 5L, 5L));
      MutableChunkBitmap mut = MutableChunkBitmap.flip(bm, 5L, 5L); // returns clone (no throw)
      return "immErr=" + immErr + "|mutClone=" + arr(mut.toArray());
    });

    // ---- checkedAdd / checkedRemove ----
    c("mutable_checked", () -> {
      MutableChunkBitmap b = new MutableChunkBitmap();
      return "add1=" + b.checkedAdd(5)
          + "|add2=" + b.checkedAdd(5)
          + "|rem1=" + b.checkedRemove(5)
          + "|rem2=" + b.checkedRemove(5);
    });

    // ---- select out of range throws IllegalArgumentException; empty first NoSuchElement ----
    c("mutable_errors", () -> {
      return "select=" + thrown(() -> MutableChunkBitmap.bitmapOf(1, 2, 3, 1000).select(4))
          + "|emptyFirst=" + thrown(() -> new MutableChunkBitmap().first());
    });

    // ---- runOptimize round-trip stays byte-interoperable across packages ----
    c("runoptimized_interop", () -> {
      try {
        int[] vals = new int[1000];
        for (int i = 0; i < vals.length; i++) {
          vals[i] = i; // contiguous run
        }
        MutableChunkBitmap mrb = MutableChunkBitmap.bitmapOf(vals);
        mrb.runOptimize();
        ChunkBitmap rb = ChunkBitmap.bitmapOf(vals);
        rb.runOptimize();
        ByteArrayOutputStream b1 = new ByteArrayOutputStream();
        mrb.serialize(new DataOutputStream(b1));
        ByteArrayOutputStream b2 = new ByteArrayOutputStream();
        rb.serialize(new DataOutputStream(b2));
        return "identical=" + Arrays.equals(b1.toByteArray(), b2.toByteArray())
            + "|card=" + mrb.getCardinality();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- unsigned round-trip through the buffer package ----
    c("mutable_unsigned_roundtrip", () -> {
      try {
        MutableChunkBitmap in = MutableChunkBitmap.bitmapOf(0, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF);
        ByteBuffer buf = ByteBuffer.allocate(in.serializedSizeInBytes());
        in.serialize(buf);
        buf.flip();
        ImmutableChunkBitmap back = new ImmutableChunkBitmap(buf);
        return "equals=" + back.equals(in) + "|toArray=" + arr(back.toArray());
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
