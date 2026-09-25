import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics FITNESS-PROPORTIONATE + UNIFORM SELECTORS (TournamentSelector,
 * RouletteWheelSelector, StochasticUniversalSelector, MonteCarloSelector), with selection-pressure
 * assertions.
 *
 * Split out of the former monolithic SelectorHarness so a signature mismatch in one selector family
 * only zeroes its own small cluster. Self-contained: its own imports + only the helpers these cases
 * reference. Case bodies are verbatim. Runner is shared.
 */
public class TournamentRouletteHarness {
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

    /** Phenotype whose fitness == sum of the (single-chromosome) integer alleles. */
    static Phenotype<IntegerGene, Integer> phenoInt(int... alleles) {
        Genotype<IntegerGene> g = genoInt(alleles);
        int sum = 0; for (int a : alleles) sum += a;
        return Phenotype.of(g, 1L, sum);
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
        // =========================================================================================
        // FITNESS-PROPORTIONATE / RANK PRESSURE SELECTORS
        //   Primary assertion: over a large seeded sample the MEAN selected fitness is clearly ABOVE
        //   the population mean. A "return first N (ignore fitness)" impl FAILS every one of these.
        // =========================================================================================

        // TournamentSelector(3): tournament of 3 strongly favours high fitness.
        // pop mean = 31.875; a correct impl yields a selected mean far above pop mean + 20.
        c("sel_tournament_pressure", () -> {
            var population = spreadPop();
            boolean above = pressureAbove(101, new TournamentSelector<>(3), population, 2000, 20.0);
            return String.valueOf(above);                                // true
        });

        // RouletteWheelSelector: fitness-proportionate. All fitnesses positive (required). Selected
        // mean above pop mean. (Roulette weights by fitness value, so the >mean gap is robust.)
        c("sel_roulette_pressure", () -> {
            var population = spreadPop();
            boolean above = pressureAbove(303, new RouletteWheelSelector<>(), population, 2000, 20.0);
            return String.valueOf(above);                                // true
        });

        // StochasticUniversalSelector: low-variance fitness-proportionate sampling -> selected mean
        // above pop mean (observed lift ~+11 for this seed; +5 margin defeats first-N/uniform).
        c("sel_sus_pressure", () -> {
            var population = spreadPop();
            boolean above = pressureAbove(404, new StochasticUniversalSelector<>(),
                                          population, 2000, 5.0);
            return String.valueOf(above);                                // true
        });

        // =========================================================================================
        // UNIFORM SELECTOR — assert the OPPOSITE of pressure (mean ≈ population mean).
        //   Distinguishes MonteCarlo from every pressure selector AND from first-N.
        // =========================================================================================

        // MonteCarloSelector: uniform random. Over a large seeded sample the selected mean should be
        // CLOSE to the population mean (no selection pressure). A first-N impl would peg near the
        // leading elements' fitness (far below pop mean) and FAIL this "within tolerance" check.
        c("sel_montecarlo_no_pressure", () -> {
            seed(808);
            var population = spreadPop();
            var out = new MonteCarloSelector<IntegerGene, Integer>()
                    .select(population, 2000, Optimize.MAXIMUM);
            double diff = Math.abs(selMean(out) - popMean(population));
            return String.valueOf(diff < 3.0);                           // true (pop mean 31.875)
        });

        // (Removed: sel_tournament_count_membership — a count/membership-only sanity case that a
        // first-N impl also passes; the *_pressure cases above are the real tournament discriminators.)
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
