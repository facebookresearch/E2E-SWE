import io.evolab.*;
import io.evolab.engine.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Function;
import java.util.function.Supplier;

/**
 * WRG test harness — jenetics EvolutionStatistics bookkeeping (io.evolab.stat.EvolutionStatistics).
 *
 * Isolated into its own driver: EvolutionStatistics.ofComparable() / peek(stats) / stats.fitness()
 * .count() is a fragile surface, so a signature mismatch here must not compile-wipe the convergence,
 * invariant, or codec engine clusters. Self-contained: its own imports + only the helpers this case
 * references. Case body is verbatim (only the oneMax method reference is repointed to this class).
 * Runner is shared.
 */
public class EngineStatisticsHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final long SEED = 42L;
    static void seed() { RandomRegistry.random(new java.util.Random(SEED)); }

    // ---- fitness functions ----

    // OneMax: number of set bits in the single BitChromosome. Global optimum == chromosome length.
    static Integer oneMax(Genotype<BitGene> gt) {
        return ((BitChromosome) gt.chromosome()).bitCount();
    }

    static {
        // =====================================================================
        // EvolutionStatistics: after a fixed-generation run the fitness sample
        // count equals populationSize * generations (RNG-independent bookkeeping).
        // =====================================================================
        c("eng_statistics_count", () -> {
            seed();
            final int PS = 30, GENS = 10;
            EvolutionStatistics<Integer, io.evolab.stat.MinMax<Integer>> stats =
                EvolutionStatistics.ofComparable();
            Engine<BitGene, Integer> engine = Engine
                .builder(EngineStatisticsHarness::oneMax, Genotype.of(BitChromosome.of(15, 0.5)))
                .populationSize(PS)
                .build();
            engine.stream()
                .limit(Limits.byFixedGeneration(GENS))
                .peek(stats)
                .collect(EvolutionResult.toBestEvolutionResult());
            return String.valueOf(stats.fitness().count());                // 300
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
