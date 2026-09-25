import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics NUMERIC RECOMBINATORS (MeanAlterer, LineCrossover, IntermediateCrossover,
 * CombineAlterer).
 *
 * Split out of the former monolithic AltererHarness so a signature mismatch here only zeroes this
 * small cluster. Self-contained: its own imports + only the helpers these cases reference. Case
 * bodies are verbatim. Runner is shared.
 */
public class NumericRecombinatorHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String f(double v) {
        if (Double.isNaN(v)) return "NaN";
        if (Double.isInfinite(v)) return v > 0 ? "Inf" : "-Inf";
        double r = Math.round(v * 1e6) / 1e6;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%.6f", r);
    }

    /** Fix the global RNG so any residual randomness is reproducible across CAPTURE runs. */
    static void seed() { RandomRegistry.random(new java.util.Random(42)); }

    // ---- builders (copied from OperatorHarness) -------------------------------------------------

    /** DoubleGene genotype from explicit allele values (range 0..1). */
    static Genotype<DoubleGene> genoDouble(double... alleles) {
        DoubleGene[] genes = new DoubleGene[alleles.length];
        for (int i = 0; i < alleles.length; i++) genes[i] = DoubleGene.of(alleles[i], 0.0, 1.0);
        return Genotype.of(DoubleChromosome.of(genes));
    }

    /** Phenotype whose fitness == sum of the (single-chromosome) double alleles. */
    static Phenotype<DoubleGene, Double> phenoDouble(double... alleles) {
        Genotype<DoubleGene> g = genoDouble(alleles);
        double sum = 0; for (double a : alleles) sum += a;
        return Phenotype.of(g, 1L, sum);
    }

    static ISeq<Phenotype<DoubleGene, Double>> popD(Phenotype<DoubleGene, Double>... ps) {
        return ISeq.of(ps);
    }

    /** Ordered double alleles of the first chromosome (rounded via f). */
    static List<String> allelesD(Genotype<DoubleGene> g) {
        List<String> out = new ArrayList<>();
        for (DoubleGene gene : g.chromosome()) out.add(f(gene.allele()));
        return out;
    }

    static {
        // =========================================================================================
        // NUMERIC RECOMBINATORS — values moved (distinct parents) / unchanged (identical parents).
        // =========================================================================================

        // MeanAlterer p=1.0 on two DISTINCT parents: the altered offspring's chromosome moves toward
        // the element-wise mean, so its alleles DIFFER from the original at >0 positions while size /
        // length / validity are preserved. A no-op leaves the alleles equal -> changed==0 -> FAILS.
        c("alt_mean_distinct_changed", () -> {
            seed();
            List<String> pa = List.of(f(0.20), f(0.40), f(0.60), f(0.80));
            List<String> pb = List.of(f(0.10), f(0.30), f(0.50), f(0.70));
            MeanAlterer<DoubleGene, Double> m = new MeanAlterer<>(1.0);
            var res = m.alter(popD(
                phenoDouble(0.20, 0.40, 0.60, 0.80),
                phenoDouble(0.10, 0.30, 0.50, 0.70)), 1L);
            List<String> o0 = allelesD(res.population().get(0).genotype());
            List<String> o1 = allelesD(res.population().get(1).genotype());
            // At least one offspring differs from its aligned parent at >0 positions.
            int c0 = 0, c1 = 0;
            for (int i = 0; i < 4; i++) {
                if (!o0.get(i).equals(pa.get(i))) c0++;
                if (!o1.get(i).equals(pb.get(i))) c1++;
            }
            boolean changed = (c0 + c1) > 0;
            boolean valid = res.population().stream().allMatch(p -> p.genotype().isValid());
            int len = res.population().get(0).genotype().chromosome().length();
            return changed + "|" + res.population().length() + "|" + len + "|" + valid;
        });

        // MeanAlterer p=1.0 on two IDENTICAL parents: the mean of a value with itself is the value,
        // so the alleles are UNCHANGED regardless of RNG order — an exact RNG-independent check that
        // still preserves size / length. (Complements the "distinct -> changed" case above.)
        c("alt_mean_identical_unchanged", () -> {
            seed();
            MeanAlterer<DoubleGene, Double> m = new MeanAlterer<>(1.0);
            var res = m.alter(popD(
                phenoDouble(0.25, 0.5, 0.75),
                phenoDouble(0.25, 0.5, 0.75)), 1L);
            List<String> a0 = allelesD(res.population().get(0).genotype());
            List<String> a1 = allelesD(res.population().get(1).genotype());
            boolean same = a0.equals(List.of(f(0.25), f(0.5), f(0.75)))
                        && a1.equals(List.of(f(0.25), f(0.5), f(0.75)));
            return same + "|" + res.population().length();   // true|2
        });

        // LineCrossover p=1.0 on DISTINCT parents: an offspring's alleles are shifted along the line
        // between the parents -> at least one offspring differs from both parents at >0 positions,
        // size / length / validity preserved. No-op -> unchanged -> FAILS.
        c("alt_linecrossover_changed_valid", () -> {
            seed();
            List<String> pa = List.of(f(0.2), f(0.4), f(0.6));
            List<String> pb = List.of(f(0.7), f(0.5), f(0.3));
            LineCrossover<DoubleGene, Double> x = new LineCrossover<>(1.0);
            var res = x.alter(popD(
                phenoDouble(0.2, 0.4, 0.6),
                phenoDouble(0.7, 0.5, 0.3)), 1L);
            List<String> o0 = allelesD(res.population().get(0).genotype());
            List<String> o1 = allelesD(res.population().get(1).genotype());
            boolean changed = !o0.equals(pa) || !o1.equals(pb) || !o0.equals(pb) || !o1.equals(pa);
            // stricter: at least one offspring differs from BOTH parents
            boolean recomb = (!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb));
            boolean valid = res.population().stream().allMatch(p -> p.genotype().isValid());
            int l0 = res.population().get(0).genotype().chromosome().length();
            return recomb + "|" + res.population().length() + "|" + l0 + "|" + valid;
        });

        // IntermediateCrossover p=1.0 on DISTINCT parents: offspring interpolated between parents ->
        // recombined (at least one offspring differs from both), size / length / validity preserved.
        c("alt_intermediate_changed_valid", () -> {
            seed();
            List<String> pa = List.of(f(0.2), f(0.4), f(0.6), f(0.8));
            List<String> pb = List.of(f(0.7), f(0.5), f(0.3), f(0.1));
            IntermediateCrossover<DoubleGene, Double> x = new IntermediateCrossover<>(1.0);
            var res = x.alter(popD(
                phenoDouble(0.2, 0.4, 0.6, 0.8),
                phenoDouble(0.7, 0.5, 0.3, 0.1)), 1L);
            List<String> o0 = allelesD(res.population().get(0).genotype());
            List<String> o1 = allelesD(res.population().get(1).genotype());
            boolean recomb = (!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb));
            boolean valid = res.population().stream().allMatch(p -> p.genotype().isValid());
            int l0 = res.population().get(0).genotype().chromosome().length();
            return recomb + "|" + res.population().length() + "|" + l0 + "|" + valid;
        });

        // CombineAlterer p=1.0 with an averaging combiner on DISTINCT parents: the combined gene is
        // the average of the two parents' genes at that locus, so the altered offspring differs from
        // both parents at >0 positions; a clamping combiner keeps it valid. No-op -> unchanged.
        c("alt_combine_changed_valid", () -> {
            seed();
            List<String> pa = List.of(f(0.2), f(0.4), f(0.6));
            List<String> pb = List.of(f(0.8), f(0.6), f(0.4));
            CombineAlterer<DoubleGene, Double> m = new CombineAlterer<>(
                (a, b) -> DoubleGene.of(Math.min(1.0, (a.allele() + b.allele()) / 2.0), 0.0, 1.0),
                1.0);
            var res = m.alter(popD(
                phenoDouble(0.2, 0.4, 0.6),
                phenoDouble(0.8, 0.6, 0.4)), 1L);
            List<String> o0 = allelesD(res.population().get(0).genotype());
            List<String> o1 = allelesD(res.population().get(1).genotype());
            boolean recomb = (!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb));
            boolean valid = res.population().stream().allMatch(p -> p.genotype().isValid());
            int len = res.population().get(0).genotype().chromosome().length();
            return recomb + "|" + res.population().length() + "|" + len + "|" + valid;
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
