import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics RANK / TEMPERATURE-SCALED SELECTORS (LinearRankSelector,
 * ExponentialRankSelector, BoltzmannSelector), with selection-pressure assertions.
 *
 * Split out of the former monolithic SelectorHarness so a signature mismatch here only zeroes this
 * small cluster. Self-contained: its own imports + only the helpers these cases reference. Case
 * bodies are verbatim. Runner is shared.
 */
public class RankSelectorHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    /** Seed the global RNG so every stochastic draw is reproducible across CAPTURE runs. */
    static void seed(long s) { RandomRegistry.random(new java.util.Random(s)); }

    // ---- builders (copied from OperatorHarness) ------------------------------------------------

    /** Single-chromosome IntegerGene genotype from explicit allele values (range 0..99). */
    static Genotype<IntegerGene> genoInt(int... alleles) {
        IntegerGene[] genes = new IntegerGene[alleles.length];
        for (int i = 0; i < alleles.length; i++) genes[i] = IntegerGene.of(alleles[i], 0, 99);
        return Genotype.of(IntegerChromosome.of(genes));
    }

    /** Phenotype with an explicit fitness value (decoupled from allele sum). */
    static Phenotype<IntegerGene, Integer> phenoFit(int fitness) {
        return Phenotype.of(genoInt(fitness % 100), 1L, fitness);
    }

    @SafeVarargs
    static ISeq<Phenotype<IntegerGene, Integer>> pop(Phenotype<IntegerGene, Integer>... ps) {
        return ISeq.of(ps);
    }

    // ---- selection-pressure helpers ------------------------------------------------------------

    /** Population mean fitness. */
    static double popMean(Seq<Phenotype<IntegerGene, Integer>> population) {
        double s = 0; for (var p : population) s += p.fitness();
        return s / population.length();
    }

    /** Mean fitness of a selected sample. */
    static double selMean(ISeq<Phenotype<IntegerGene, Integer>> out) {
        double s = 0; for (var p : out) s += p.fitness();
        return s / out.length();
    }

    /**
     * Run a large seeded draw and return whether the selected mean is meaningfully ABOVE the
     * population mean by at least `margin`. Deterministic given the seed. A "return first N" or a
     * uniform selector cannot clear a robust margin; a real pressure selector does.
     */
    static boolean pressureAbove(long s, Selector<IntegerGene, Integer> sel,
                                 ISeq<Phenotype<IntegerGene, Integer>> population,
                                 int sample, double margin) {
        seed(s);
        var out = sel.select(population, sample, Optimize.MAXIMUM);
        return selMean(out) > popMean(population) + margin;
    }

    /**
     * Standard spread population for MAXIMUM pressure tests: fitnesses {1,2,4,8,16,32,64,128}.
     * Population mean = 255/8 = 31.875. A pressure selector pushes the selected mean well above this;
     * first-N (mean of first-N of a 2000-draw is just the population's leading elements repeated,
     * i.e. ~ the fitness of element 0 = 1) and uniform (~31.875) both stay below the +margin.
     */
    static ISeq<Phenotype<IntegerGene, Integer>> spreadPop() {
        return pop(phenoFit(1), phenoFit(2), phenoFit(4), phenoFit(8),
                   phenoFit(16), phenoFit(32), phenoFit(64), phenoFit(128));
    }

    static {
        // LinearRankSelector: rank-based pressure. Uses rank (not raw fitness) so the mean lift is
        // more modest — assert a smaller but still first-N-defeating margin (+5 over pop mean 31.875).
        c("sel_linearrank_pressure", () -> {
            var population = spreadPop();
            boolean above = pressureAbove(505, new LinearRankSelector<>(0.5), population, 2000, 5.0);
            return String.valueOf(above);                                // true
        });

        // ExponentialRankSelector: rank-based with exponential weighting -> stronger than linear rank.
        c("sel_exponentialrank_pressure", () -> {
            var population = spreadPop();
            boolean above = pressureAbove(606, new ExponentialRankSelector<>(0.7),
                                          population, 2000, 10.0);
            return String.valueOf(above);                                // true
        });

        // BoltzmannSelector: temperature-scaled fitness pressure. Larger b -> sharper preference for
        // high fitness (observed lift ~+8.5 at b=0.5 for this seed; +4 margin defeats first-N/uniform).
        c("sel_boltzmann_pressure", () -> {
            var population = spreadPop();
            boolean above = pressureAbove(707, new BoltzmannSelector<>(0.5), population, 2000, 4.0);
            return String.valueOf(above);                                // true
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
