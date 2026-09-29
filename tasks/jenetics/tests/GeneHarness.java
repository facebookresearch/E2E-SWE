import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — jenetics genes / chromosomes / genotype (the data model). Uses EXPLICIT-allele
 * construction throughout (no RNG) so results are deterministic and free of random-consumption-order
 * fragility.
 *
 * Design: ONE bundled, multi-assertion case per gene / chromosome / genotype TYPE. Each case joins its
 * distinct behaviors with '|' so a single CTRF entry rewards one implementation node — exercising the
 * genuinely meaningful behavior (mean() averaging, bit counting/indexing, geneCount aggregation, validity
 * against bounds/char-sets) rather than re-checking trivial getters many times. Doubles via f().
 */
public class GeneHarness {
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
        // ---- IntegerGene: allele + bounds + validity(in/out of range) + mean() (floored average) ----
        c("gene_int", () -> {
            IntegerGene g = IntegerGene.of(5, 0, 10);
            // mean uses the average-of-integers bit trick: (4&8)+((4^8)>>1) = 6 (floored average)
            IntegerGene m = IntegerGene.of(4, 0, 10).mean(IntegerGene.of(9, 0, 10)); // (4&9)+((4^9)>>1)=0+6=6
            return "allele=" + g.allele()
                 + "|min=" + g.min() + "|max=" + g.max()
                 + "|validIn=" + g.isValid()
                 + "|validOut=" + IntegerGene.of(15, 0, 10).isValid()
                 + "|mean=" + m.allele();
        });

        // ---- LongGene: allele + bounds + validity + mean() (floored average) ----
        c("gene_long", () -> {
            LongGene g = LongGene.of(100L, 0L, 1000L);
            LongGene m = LongGene.of(3L, 0L, 1000L).mean(LongGene.of(9L, 0L, 1000L)); // (3&9)+((3^9)>>1)=1+5=6
            return "allele=" + g.allele()
                 + "|min=" + g.min() + "|max=" + g.max()
                 + "|validIn=" + g.isValid()
                 + "|validOut=" + LongGene.of(5000L, 0L, 1000L).isValid()
                 + "|mean=" + m.allele();
        });

        // ---- DoubleGene: allele + bounds + validity + mean() (midpoint) ----
        c("gene_double", () -> {
            DoubleGene g = DoubleGene.of(0.5, 0, 1);
            DoubleGene m = DoubleGene.of(0.2, 0, 1).mean(DoubleGene.of(0.6, 0, 1)); // midpoint 0.4
            return "allele=" + f(g.allele())
                 + "|min=" + f(g.min()) + "|max=" + f(g.max())
                 + "|validIn=" + g.isValid()
                 + "|validOut=" + DoubleGene.of(1.5, 0, 1).isValid()
                 + "|mean=" + f(m.allele());
        });

        // ---- CharacterGene: allele + validity against a valid-char set (in-set true, out-of-set false) ----
        c("gene_char", () -> {
            CharacterGene g = CharacterGene.of('a', new CharSeq("abc"));
            return "allele=" + g.allele()
                 + "|validIn=" + g.isValid()
                 + "|validOut=" + CharacterGene.of('x', new CharSeq("abc")).isValid();
        });

        // ---- AnyGene: deterministic supplier + allele + validity (custom validator) ----
        c("gene_any", () -> {
            AnyGene<String> g = AnyGene.of("X", () -> "X", (String a) -> a.length() == 1);
            return "allele=" + g.allele()
                 + "|validIn=" + g.isValid()
                 + "|validOut=" + AnyGene.of("XY", () -> "XY", (String a) -> a.length() == 1).isValid();
        });

        // ---- IntegerChromosome: length + gene access + validity (valid vs a member out of range) ----
        c("chrom_int", () -> {
            IntegerChromosome ch = IntegerChromosome.of(
                IntegerGene.of(7, 0, 9), IntegerGene.of(2, 0, 9), IntegerGene.of(3, 0, 9));
            return "length=" + ch.length()
                 + "|gene0=" + ch.get(0).allele()
                 + "|valid=" + ch.isValid()
                 + "|validBad=" + IntegerChromosome.of(
                        IntegerGene.of(15, 0, 9), IntegerGene.of(2, 0, 9)).isValid();
        });

        // ---- LongChromosome: length + gene access + validity ----
        c("chrom_long", () -> {
            LongChromosome ch = LongChromosome.of(
                LongGene.of(7L, 0L, 9L), LongGene.of(2L, 0L, 9L), LongGene.of(3L, 0L, 9L));
            return "length=" + ch.length()
                 + "|gene0=" + ch.get(0).allele()
                 + "|valid=" + ch.isValid()
                 + "|validBad=" + LongChromosome.of(LongGene.of(15L, 0L, 9L)).isValid();
        });

        // ---- DoubleChromosome: length + gene access + validity ----
        c("chrom_double", () -> {
            DoubleChromosome ch = DoubleChromosome.of(
                DoubleGene.of(0.25, 0, 1), DoubleGene.of(0.5, 0, 1));
            return "length=" + ch.length()
                 + "|gene0=" + f(ch.get(0).allele())
                 + "|valid=" + ch.isValid()
                 + "|validBad=" + DoubleChromosome.of(DoubleGene.of(1.5, 0, 1)).isValid();
        });

        // ---- CharacterChromosome: length + gene access + validity (valid vs char out of set) ----
        c("chrom_char", () -> {
            CharacterChromosome ch = CharacterChromosome.of("hello");
            return "length=" + ch.length()
                 + "|gene2=" + ch.get(2).allele()
                 + "|valid=" + ch.isValid()
                 + "|validBad=" + CharacterChromosome.of("ax", new CharSeq("abc")).isValid();
        });

        // ---- AnyChromosome: deterministic supplier + length + gene access + validity ----
        c("chrom_any", () -> {
            AnyChromosome<String> ch = AnyChromosome.of(() -> "X", (String a) -> a.equals("X"), 3);
            return "length=" + ch.length()
                 + "|gene0=" + ch.get(0).allele()
                 + "|valid=" + ch.isValid()
                 + "|validBad=" + AnyChromosome.of(() -> "X", (String a) -> a.equals("Z"), 2).isValid();
        });

        // ---- Genotype (single-type): length(#chromosomes) + geneCount(total genes) + validity ----
        c("genotype_single", () -> {
            Genotype<IntegerGene> gt = Genotype.of(
                IntegerChromosome.of(IntegerGene.of(1, 0, 9), IntegerGene.of(2, 0, 9)),
                IntegerChromosome.of(IntegerGene.of(3, 0, 9)));
            return "length=" + gt.length()
                 + "|geneCount=" + gt.geneCount()
                 + "|valid=" + gt.isValid();
        });

        // ---- Genotype (multi-chromosome, mixed-length): geneCount aggregation across a structured genotype ----
        // Genotype requires a single gene type; use several DoubleChromosomes of differing lengths so
        // geneCount = 3 + 1 + 2 = 6 exercises cross-chromosome aggregation (real structural behavior).
        c("genotype_multi", () -> {
            Genotype<DoubleGene> gt = Genotype.of(
                DoubleChromosome.of(DoubleGene.of(0.1, 0, 1), DoubleGene.of(0.2, 0, 1), DoubleGene.of(0.3, 0, 1)),
                DoubleChromosome.of(DoubleGene.of(0.4, 0, 1)),
                DoubleChromosome.of(DoubleGene.of(0.5, 0, 1), DoubleGene.of(0.6, 0, 1)));
            return "length=" + gt.length()
                 + "|geneCount=" + gt.geneCount()
                 + "|valid=" + gt.isValid()
                 + "|chrom0len=" + gt.get(0).length();
        });

        // ---- IntegerGene.mean(): FLOORED average edge cases (negatives / odd sums round toward -inf) ----
        // The bit-trick floored average differs from naive (a+b)/2 (which truncates toward 0 in Java) for
        // negative or odd-sum pairs. Wide bounds keep every gene valid; each mean() allele oracle-captured.
        c("gene_int_mean_floor", () -> {
            int[][] pairs = {{-3, -8}, {-7, 2}, {5, 2}, {7, 8}, {-1, -1}};
            StringBuilder sb = new StringBuilder();
            for (int[] p : pairs) {
                int mv = IntegerGene.of(p[0], -100, 100).mean(IntegerGene.of(p[1], -100, 100)).allele();
                if (sb.length() > 0) sb.append("|");
                sb.append(mv);
            }
            return sb.toString();   // oracle-captured (floored averages)
        });

        // ---- LongGene.mean(): FLOORED average edge cases (same trick, long width) ----
        c("gene_long_mean_floor", () -> {
            long[][] pairs = {{-3L, -8L}, {-7L, 2L}, {5L, 2L}, {7L, 8L}, {-1L, -1L}};
            StringBuilder sb = new StringBuilder();
            for (long[] p : pairs) {
                long mv = LongGene.of(p[0], -100L, 100L).mean(LongGene.of(p[1], -100L, 100L)).allele();
                if (sb.length() > 0) sb.append("|");
                sb.append(mv);
            }
            return sb.toString();   // oracle-captured (floored averages)
        });

        // ---- BitChromosome: bitCount + booleanValue at several indices over a fixed pattern ----
        // String is interpreted big-endian (rightmost char = bit 0); tests set-bit counting AND per-index
        // booleanValue() (indexing/endianness the model often mis-implements). Values oracle-captured.
        c("chrom_bit_pattern", () -> {
            BitChromosome ch = BitChromosome.of("110100101");
            return "bitCount=" + ch.bitCount()
                 + "|length=" + ch.length()
                 + "|b0=" + ch.booleanValue(0)
                 + "|b3=" + ch.booleanValue(3)
                 + "|b8=" + ch.booleanValue(8);
        });

        // ---- PermutationChromosome.ofInteger(n): RNG-INDEPENDENT validity invariants ----
        // A permutation of 0..n-1: length=n, isValid()=true, alleles sum to n(n-1)/2, and the SORTED
        // alleles equal 0..n-1 exactly (each appears once) -- all invariant of which permutation is drawn.
        c("chrom_perm_valid", () -> {
            int n = 6;
            PermutationChromosome<Integer> ch = PermutationChromosome.ofInteger(n);
            int sum = 0;
            int[] alleles = new int[n];
            for (int i = 0; i < n; i++) { int a = ch.get(i).allele(); alleles[i] = a; sum += a; }
            java.util.Arrays.sort(alleles);
            boolean sorted = true;
            for (int i = 0; i < n; i++) if (alleles[i] != i) sorted = false;
            return "length=" + ch.length()
                 + "|valid=" + ch.isValid()
                 + "|sum=" + sum
                 + "|sortedIota=" + sorted;
        });

        // ---- BitChromosome ENDIANNESS via get(i).allele(): single high bit near the MSB end ----
        // "10010000": the two set chars are near the left (high) end; get(i).allele() (a Boolean) must
        // map index 0 to the RIGHTMOST char. Catches a reversed-bit-order implementation.
        c("chrom_bit_endian", () -> {
            BitChromosome ch = BitChromosome.of("10010000");
            return "bitCount=" + ch.bitCount()
                 + "|length=" + ch.length()
                 + "|bit0=" + ch.get(0).allele()
                 + "|bit4=" + ch.get(4).allele()
                 + "|bit7=" + ch.get(7).allele();
        });

        // ---- BitChromosome EXTREMES: all-ones vs all-zeros (bitCount boundary behavior) ----
        // bitCount == length for all-set and 0 for all-clear; booleanValue(0) at each extreme.
        c("chrom_bit_extremes", () -> {
            BitChromosome all = BitChromosome.of("1111111");
            BitChromosome none = BitChromosome.of("0000");
            return "allCount=" + all.bitCount()
                 + "|allLen=" + all.length()
                 + "|noneCount=" + none.bitCount()
                 + "|noneLen=" + none.length()
                 + "|allb0=" + all.booleanValue(0)
                 + "|noneb0=" + none.booleanValue(0);
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
