import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics ALTERER COMPOSITION (Alterer.of(...) composite + PartialAlterer.of(...)).
 *
 * Split out of the former monolithic AltererHarness so a signature mismatch here only zeroes this
 * small cluster. Self-contained: its own imports + only the helpers these cases reference. Case
 * bodies are verbatim. Runner is shared.
 */
public class CompositeAltererHarness {
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

    /** Multi-chromosome DoubleGene genotype: each row is one chromosome (range 0..1). */
    static Genotype<DoubleGene> genoDoubleMulti(double[]... rows) {
        DoubleChromosome[] chs = new DoubleChromosome[rows.length];
        for (int r = 0; r < rows.length; r++) {
            DoubleGene[] genes = new DoubleGene[rows[r].length];
            for (int i = 0; i < rows[r].length; i++) genes[i] = DoubleGene.of(rows[r][i], 0.0, 1.0);
            chs[r] = DoubleChromosome.of(genes);
        }
        return Genotype.of(Arrays.asList(chs));
    }

    /** Ordered double alleles of the first chromosome (rounded via f). */
    static List<String> allelesD(Genotype<DoubleGene> g) {
        List<String> out = new ArrayList<>();
        for (DoubleGene gene : g.chromosome()) out.add(f(gene.allele()));
        return out;
    }

    /** Ordered double alleles of chromosome `idx` (rounded via f). */
    static List<String> allelesDAt(Genotype<DoubleGene> g, int idx) {
        List<String> out = new ArrayList<>();
        for (DoubleGene gene : g.get(idx)) out.add(f(gene.allele()));
        return out;
    }

    static {
        // =========================================================================================
        // COMPOSITION — Alterer.of(...) composite and PartialAlterer.of(...).
        // =========================================================================================

        // Composite via Alterer.of(GaussianMutator(1.0), MeanAlterer(1.0)): the chain necessarily
        // mutates every gene, so BOTH offspring differ from their parents at >0 positions, while
        // size / length / validity are preserved. A no-op chain leaves them equal -> changed==0.
        c("alt_composite_changed_valid", () -> {
            seed();
            List<String> pa = List.of(f(0.2), f(0.4), f(0.6), f(0.8));
            List<String> pb = List.of(f(0.1), f(0.3), f(0.5), f(0.7));
            Alterer<DoubleGene, Double> chain = Alterer.<DoubleGene, Double>of(
                new GaussianMutator<DoubleGene, Double>(1.0),
                new MeanAlterer<DoubleGene, Double>(1.0));
            var res = chain.alter(popD(
                phenoDouble(0.2, 0.4, 0.6, 0.8),
                phenoDouble(0.1, 0.3, 0.5, 0.7)), 1L);
            List<String> o0 = allelesD(res.population().get(0).genotype());
            List<String> o1 = allelesD(res.population().get(1).genotype());
            boolean changed = !o0.equals(pa) && !o1.equals(pb);
            boolean valid = res.population().stream().allMatch(p -> p.genotype().isValid());
            int len = res.population().get(0).genotype().chromosome().length();
            return changed + "|" + res.population().length() + "|" + len + "|" + valid;
        });

        // PartialAlterer.of(GaussianMutator(1.0), 0): restricts the mutator to chromosome index 0.
        // On a 3-chromosome genotype: chromosome 0 (targeted) must CHANGE, while chromosomes 1 & 2
        // (untouched) must be EXACTLY unchanged. A no-op leaves chromosome 0 unchanged too -> the
        // "targeted changed" flag is false -> FAILS. (Also catches an over-broad alterer that
        // touches all chromosomes: chromosome 1/2 would then change -> untouched flag false.)
        c("alt_partial_targeted_and_untouched", () -> {
            seed();
            var g1 = genoDoubleMulti(
                new double[]{0.10, 0.20},
                new double[]{0.30, 0.40},
                new double[]{0.50, 0.60});
            var g2 = genoDoubleMulti(
                new double[]{0.15, 0.25},
                new double[]{0.35, 0.45},
                new double[]{0.55, 0.65});
            var a = Phenotype.of(g1, 1L, 0.0);
            var b = Phenotype.of(g2, 1L, 0.0);
            Alterer<DoubleGene, Double> alt =
                PartialAlterer.of(new GaussianMutator<DoubleGene, Double>(1.0), 0);
            var res = alt.alter(ISeq.of(a, b), 1L);
            Genotype<DoubleGene> out0 = res.population().get(0).genotype();
            Genotype<DoubleGene> out1 = res.population().get(1).genotype();
            // targeted chromosome 0 changed for at least one individual
            boolean targetedChanged =
                    !allelesDAt(out0, 0).equals(List.of(f(0.10), f(0.20)))
                 || !allelesDAt(out1, 0).equals(List.of(f(0.15), f(0.25)));
            // untouched chromosomes 1 & 2 exactly unchanged for BOTH individuals
            boolean untouched =
                    allelesDAt(out0, 1).equals(List.of(f(0.30), f(0.40)))
                 && allelesDAt(out0, 2).equals(List.of(f(0.50), f(0.60)))
                 && allelesDAt(out1, 1).equals(List.of(f(0.35), f(0.45)))
                 && allelesDAt(out1, 2).equals(List.of(f(0.55), f(0.65)));
            boolean valid = res.population().stream().allMatch(p -> p.genotype().isValid());
            int nch = out0.length();
            return targetedChanged + "|" + untouched + "|" + nch + "|" + valid;
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
