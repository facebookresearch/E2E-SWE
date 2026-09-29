import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics DETERMINISTIC SELECTORS (TruncationSelector, EliteSelector).
 *
 * Split out of the former monolithic SelectorHarness so a signature mismatch here only zeroes this
 * small cluster. Self-contained: its own imports + only the helpers these cases reference. Case
 * bodies are verbatim. Runner is shared.
 */
public class TruncationEliteHarness {
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

    static {
        // =========================================================================================
        // TRUNCATION — deterministic top-n / bottom-n by fitness (RNG-independent).
        //   "return first N" fails because it ignores fitness ordering.
        // =========================================================================================

        // TruncationSelector top-k (k=2 and k=3) + count==0 edge — three same-node deterministic
        // truncation cases bundled (MAXIMUM top-2 -> {24,15}; top-3 -> {24,15,9}; count 0 -> empty).
        // Truncation is RNG-independent, so a single seed covers all three. first-N (list order) fails
        // top-k. The distinct MINIMUM scenario is kept SEPARATE below.
        c("sel_truncation_topk", () -> {
            seed(1);
            var population = pop(
                phenoInt(1, 2, 3),   // 6
                phenoInt(4, 5, 6),   // 15
                phenoInt(1, 1, 1),   // 3
                phenoInt(8, 8, 8),   // 24
                phenoInt(3, 3, 3));  // 9
            var sel = new TruncationSelector<IntegerGene, Integer>();
            List<Integer> f2 = sel.select(population, 2, Optimize.MAXIMUM)
                    .stream().map(Phenotype::fitness).collect(Collectors.toList());
            Collections.sort(f2, Collections.reverseOrder());
            List<Integer> f3 = sel.select(population, 3, Optimize.MAXIMUM)
                    .stream().map(Phenotype::fitness).collect(Collectors.toList());
            Collections.sort(f3, Collections.reverseOrder());
            int zero = sel.select(pop(phenoInt(1, 1), phenoInt(2, 2)), 0, Optimize.MAXIMUM).length();
            return f2.toString() + "|" + f3.toString() + "|" + zero;     // [24, 15]|[24, 15, 9]|0
        });

        // TruncationSelector MINIMUM picks the bottom-2: {3,6}. first-N -> {6,15}.
        c("sel_truncation_minimize_bottom2", () -> {
            seed(3);
            var population = pop(
                phenoInt(1, 2, 3),   // 6
                phenoInt(4, 5, 6),   // 15
                phenoInt(1, 1, 1),   // 3
                phenoInt(8, 8, 8));  // 24
            var out = new TruncationSelector<IntegerGene, Integer>()
                    .select(population, 2, Optimize.MINIMUM);
            List<Integer> fits = out.stream().map(Phenotype::fitness).collect(Collectors.toList());
            Collections.sort(fits);
            return fits.toString();                                      // [3, 6]
        });

        // =========================================================================================
        // ELITE — the best individual is ALWAYS present (deterministic).
        //   "return first N" fails when the best is not among the first N.
        // =========================================================================================

        // EliteSelector: best-preservation regardless of list position — two same-node cases bundled.
        //   (1) Elite(1): best (fitness 24, last in list) is always present, count=2.
        //   (2) Elite(2): the two elites (24 and 15, placed near the end) both appear when count=2.
        // A first-N impl drops the best in both -> fails. All four sub-values preserved.
        c("sel_elite_keeps_top", () -> {
            seed(4);
            var pop1 = pop(
                phenoInt(1, 2, 3),   // 6
                phenoInt(4, 5, 6),   // 15
                phenoInt(3, 3, 3),   // 9
                phenoInt(8, 8, 8));  // 24  <- best, last in list
            var out1 = new EliteSelector<IntegerGene, Integer>(1)
                    .select(pop1, 2, Optimize.MAXIMUM);
            boolean hasBest = out1.stream().anyMatch(p -> p.fitness() == 24);

            var pop2 = pop(
                phenoFit(6),
                phenoFit(3),
                phenoFit(9),
                phenoFit(15),   // 2nd best, near end
                phenoFit(24));  // best, last
            var out2 = new EliteSelector<IntegerGene, Integer>(2)
                    .select(pop2, 2, Optimize.MAXIMUM);
            Set<Integer> fits = out2.stream().map(Phenotype::fitness).collect(Collectors.toSet());
            boolean topTwo = fits.contains(24) && fits.contains(15);

            return out1.length() + "|" + hasBest + "|" + out2.length() + "|" + topTwo;  // 2|true|2|true
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
