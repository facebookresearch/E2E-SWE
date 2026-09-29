import io.evolab.*;
import io.evolab.engine.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Function;
import java.util.function.Supplier;

/**
 * WRG test harness — jenetics CODEC round-trips (Codecs.ofScalar / Codecs.ofVector encode/decode).
 *
 * Split out of the former monolithic EngineHarness so a signature mismatch in the codec API only
 * zeroes these fully-deterministic (no evolution / RNG) round-trip cases. Self-contained: its own
 * imports + only the helpers these cases reference. Case bodies are verbatim. Runner is shared.
 */
public class CodecHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String f(double v) {
        if (Double.isNaN(v)) return "NaN";
        if (Double.isInfinite(v)) return v > 0 ? "Inf" : "-Inf";
        double r = Math.round(v * 1e6) / 1e6;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%.6f", r);
    }

    static {
        // =====================================================================
        // Codec round-trips (fully deterministic — no evolution / RNG).
        // =====================================================================
        // Scalar round-trips (int/double/long) — three trivial same-node encode/decode cases bundled
        // into one multi-assertion case (each type's decoded value preserved).
        c("eng_codec_scalar_roundtrip", () -> {
            InvertibleCodec<Integer, IntegerGene> ci = Codecs.ofScalar(IntRange.of(0, 50));
            InvertibleCodec<Double, DoubleGene> cd = Codecs.ofScalar(DoubleRange.of(0.0, 10.0));
            InvertibleCodec<Long, LongGene> cl = Codecs.ofScalar(LongRange.of(0L, 1_000L));
            return ci.decode(ci.encode(37))
                 + "|" + f(cd.decode(cd.encode(4.25)))
                 + "|" + cl.decode(cl.encode(777L));                        // 37|4.250000|777
        });

        // Vector round-trips (int array / double array / encoded length) — three trivial same-node
        // cases bundled (int array back, double array back, and the encoded genotype's length).
        c("eng_codec_vector_roundtrip", () -> {
            InvertibleCodec<int[], IntegerGene> ci = Codecs.ofVector(IntRange.of(0, 100), 4);
            int[] backi = ci.decode(ci.encode(new int[]{ 3, 14, 15, 92 }));
            InvertibleCodec<double[], DoubleGene> cd = Codecs.ofVector(DoubleRange.of(0.0, 1.0), 3);
            double[] backd = cd.decode(cd.encode(new double[]{ 0.1, 0.5, 0.9 }));
            InvertibleCodec<int[], IntegerGene> cl = Codecs.ofVector(IntRange.of(0, 100), 5);
            Genotype<IntegerGene> gt = cl.encode(new int[]{ 1, 2, 3, 4, 5 });
            return Arrays.toString(backi)
                 + "|" + f(backd[0]) + "," + f(backd[1]) + "," + f(backd[2])
                 + "|" + gt.chromosome().length();          // [3, 14, 15, 92]|0.100000,0.500000,0.900000|5
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
