import io.chunkbits.*;

import java.io.*;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- serialization of ChunkBitmap: DataOutput and ByteBuffer round-trips (fully
 * in-memory), serializedSizeInBytes consistency, maximumSerializedSize bound, validate(), and the
 * bad-cookie deserialization error. Expected strings captured from the reference into expected.tsv.
 */
public class SerializationHarness {
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

  static byte[] toBytes(ChunkBitmap b) throws IOException {
    ByteArrayOutputStream bos = new ByteArrayOutputStream();
    b.serialize(new DataOutputStream(bos));
    return bos.toByteArray();
  }

  static ChunkBitmap fromBytes(byte[] bytes) throws IOException {
    ChunkBitmap b = new ChunkBitmap();
    b.deserialize(new DataInputStream(new ByteArrayInputStream(bytes)));
    return b;
  }

  static {
    // ---- DataOutput round-trip identity ----
    c("dataoutput_roundtrip", () -> {
      try {
        ChunkBitmap in = ChunkBitmap.bitmapOf(1, 2, 3, 1000, 70000, 200000);
        ChunkBitmap out = fromBytes(toBytes(in));
        return "equals=" + in.equals(out)
            + "|cardOut=" + out.getCardinality()
            + "|validate=" + out.validate();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- serializedSizeInBytes equals the number of bytes actually written ----
    c("serialized_size_matches", () -> {
      try {
        ChunkBitmap in = ChunkBitmap.bitmapOf(1, 2, 3, 1000, 70000);
        int declared = in.serializedSizeInBytes();
        int actual = toBytes(in).length;
        return "match=" + (declared == actual);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- ByteBuffer round-trip; buffer position advances by serializedSizeInBytes ----
    c("bytebuffer_roundtrip", () -> {
      try {
        ChunkBitmap in = ChunkBitmap.bitmapOf(5, 6, 7, 100000, 300000);
        int size = in.serializedSizeInBytes();
        ByteBuffer buf = ByteBuffer.allocate(size);
        in.serialize(buf);
        int posAfter = buf.position();
        buf.flip();
        ChunkBitmap out = new ChunkBitmap();
        out.deserialize(buf);
        return "equals=" + in.equals(out) + "|advanced=" + (posAfter == size);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- serialize(ByteBuffer) and serialize(DataOutput) produce identical bytes ----
    c("bytebuffer_dataoutput_identical", () -> {
      try {
        ChunkBitmap in = ChunkBitmap.bitmapOf(1, 50, 5000, 65540);
        byte[] viaStream = toBytes(in);
        ByteBuffer buf = ByteBuffer.allocate(in.serializedSizeInBytes());
        in.serialize(buf);
        byte[] viaBuffer = buf.array();
        return "identical=" + Arrays.equals(viaStream, viaBuffer);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- round-trip AFTER runOptimize (run containers serialize with a different cookie) ----
    c("roundtrip_runoptimized", () -> {
      try {
        ChunkBitmap in = new ChunkBitmap();
        in.add(0L, 1000L);
        in.runOptimize();
        ChunkBitmap out = fromBytes(toBytes(in));
        return "equals=" + in.equals(out) + "|cardOut=" + out.getCardinality();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- empty bitmap round-trips ----
    c("roundtrip_empty", () -> {
      try {
        ChunkBitmap in = new ChunkBitmap();
        ChunkBitmap out = fromBytes(toBytes(in));
        return "equals=" + in.equals(out) + "|isEmpty=" + out.isEmpty();
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- round-trip preserves unsigned wraparound values ----
    c("roundtrip_unsigned", () -> {
      try {
        ChunkBitmap in = ChunkBitmap.bitmapOf(0, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF);
        ChunkBitmap out = fromBytes(toBytes(in));
        return "equals=" + in.equals(out) + "|toArray=" + Arrays.toString(out.toArray());
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- validate() true for a well-formed bitmap ----
    c("validate_true", () -> {
      ChunkBitmap b = ChunkBitmap.bitmapOf(1, 2, 3, 100000);
      return "validate=" + b.validate();
    });

    // ---- maximumSerializedSize is a deterministic upper bound >= actual size ----
    c("maximum_serialized_size_bound", () -> {
      try {
        ChunkBitmap in = ChunkBitmap.bitmapOf(1, 2, 3, 1000, 70000, 200000);
        long max = ChunkBitmap.maximumSerializedSize(in.getLongCardinality(), 200001L);
        int actual = in.serializedSizeInBytes();
        return "bound=" + (max >= actual);
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });

    // ---- deserializing garbage (bad cookie) throws IOException ----
    c("bad_cookie", () -> {
      return "err="
          + thrown(
              () -> {
                byte[] garbage = new byte[] {0, 0, 0, 0, 0, 0, 0, 0};
                ChunkBitmap b = new ChunkBitmap();
                b.deserialize(new DataInputStream(new ByteArrayInputStream(garbage)));
              });
    });

    // ---- cross-instance: deserialize into a pre-populated bitmap overwrites it ----
    c("deserialize_overwrites", () -> {
      try {
        byte[] bytes = toBytes(ChunkBitmap.bitmapOf(7, 8, 9));
        ChunkBitmap target = ChunkBitmap.bitmapOf(1, 2, 3, 4, 5);
        target.deserialize(new DataInputStream(new ByteArrayInputStream(bytes)));
        return "toArray=" + Arrays.toString(target.toArray());
      } catch (Exception e) {
        return "EX:" + e.getClass().getSimpleName();
      }
    });
  }

  public static void main(String[] args) throws Exception {
    Runner.run(cases, args);
  }
}
