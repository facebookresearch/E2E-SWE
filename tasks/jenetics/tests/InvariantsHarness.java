import io.evolab.*;
import io.evolab.engine.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — jenetics engine INVARIANTS (config getters, generation counting, population-size
 * constancy, best-genotype validity/shape, Optimize relational behavior, best-so-far monotonicity).
 *
 * Split out of the former monolithic EngineHarness so the config-getter usage
 * (engine.populationSize()/optimize()) is isolated from the pure convergence and codec clusters — a
 * signature mismatch in those getters only zeroes these invariant cases. Self-contained: its own
 * imports + only the helpers these cases reference. Case bodies are verbatim (only the oneMax method
 * reference is repointed to this class). Runner is shared.
 */
public class InvariantsHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final long SEED = 42L;
    static void seed() { RandomRegistry.random(new java.util.Random(SEED)); }

    static String f(double v) {
        if (Double.isNaN(v)) return "NaN";
        if (Double.isInfinite(v)) return v > 0 ? "Inf" : "-Inf";
        double r = Math.round(v * 1e6) / 1e6;
        if (r == 0.0) r = 0.0;
        return String.format(Locale.ROOT, "%.6f", r);
    }

    // ---- fitness functions ----

    // OneMax: number of set bits in the single BitChromosome. Global optimum == chromosome length.
    static Integer oneMax(Genotype<BitGene> gt) {
        return ((BitChromosome) gt.chromosome()).bitCount();
    }

    static {
        // =====================================================================
        // OneMax convergence — best fitness converges to N regardless of RNG.
        // =====================================================================
        // Convergence run that ALSO folds in the config/invariant checks the old
        // shallow getter cases tested: the built Engine reports the configured
        // populationSize()/optimize(), and the converged result's population stays
        // at that fixed size. Emits best fitness (== N) with the invariants gated in.
        c("eng_onemax_n20", () -> {
            seed();
            final int N = 20, PS = 100;
            Engine<BitGene, Integer> engine = Engine
                .builder(InvariantsHarness::oneMax, Genotype.of(BitChromosome.of(N, 0.5)))
                .populationSize(PS)
                .optimize(Optimize.MAXIMUM)
                .build();
            EvolutionResult<BitGene, Integer> r = engine.stream()
                .limit(Limits.byFixedGeneration(300))
                .collect(EvolutionResult.toBestEvolutionResult());
            boolean cfg = engine.populationSize() == PS
                && engine.optimize() == Optimize.MAXIMUM
                && r.population().length() == PS;
            // Report best fitness only when the config/population invariants hold.
            return cfg ? String.valueOf(r.bestFitness()) : "invariant-violation";   // 20
        });

        // =====================================================================
        // Generation-count limit: the LAST stream element's generation() equals
        // byFixedGeneration(k). generation() is the generation at which a given
        // result was produced; reducing to the final element yields the k-th
        // (last) generation deterministically -> RNG-path-independent. (We read
        // the final element, NOT the best result: the best result's generation()
        // is the generation the optimum was first reached, which is RNG-dependent.)
        // =====================================================================
        // Bundled: the final element's generation() under byFixedGeneration(37) == 37, AND the number
        // of stream elements under byFixedGeneration(10) == 10 (two same-node generation-count checks).
        c("eng_generation_count", () -> {
            Engine<BitGene, Integer> engine = Engine
                .builder(InvariantsHarness::oneMax, Genotype.of(BitChromosome.of(15, 0.5)))
                .populationSize(50)
                .build();
            seed();
            EvolutionResult<BitGene, Integer> last = engine.stream()
                .limit(Limits.byFixedGeneration(37))
                .reduce((a, b) -> b)
                .orElseThrow();
            seed();
            long gens = engine.stream()
                .limit(Limits.byFixedGeneration(10))
                .count();
            return last.generation() + "|" + gens;                          // 37|10
        });

        // =====================================================================
        // Population-size invariant (single, strongest form): population size is
        // constant across EVERY generation of the run (RNG-independent).
        // =====================================================================
        c("eng_population_size_const", () -> {
            seed();
            final int PS = 40;
            Engine<BitGene, Integer> engine = Engine
                .builder(InvariantsHarness::oneMax, Genotype.of(BitChromosome.of(15, 0.5)))
                .populationSize(PS)
                .build();
            boolean allEqual = engine.stream()
                .limit(Limits.byFixedGeneration(25))
                .allMatch(res -> res.population().length() == PS);
            return String.valueOf(allEqual);                                // true
        });

        // =====================================================================
        // Best phenotype: after a MAXIMUM run over [0,100] the best phenotype reaches a
        // near-optimum fitness AND carries a structurally valid genotype. The fitness gate
        // makes this non-vacuous (a shape-only isValid() check is true for any in-range
        // genotype); asserting near-optimum via bestPhenotype() exercises that path.
        // =====================================================================
        c("eng_best_valid", () -> {
            seed();
            Engine<IntegerGene, Integer> engine = Engine
                .builder((Integer x) -> x, Codecs.ofScalar(IntRange.of(0, 100)))
                .populationSize(50)
                .optimize(Optimize.MAXIMUM)
                .build();
            EvolutionResult<IntegerGene, Integer> r = engine.stream()
                .limit(Limits.byFixedGeneration(50))
                .collect(EvolutionResult.toBestEvolutionResult());
            Phenotype<IntegerGene, Integer> best = r.bestPhenotype();
            return String.valueOf(best.fitness() >= 90 && best.genotype().isValid());  // true
        });

        // Best genotype length equals the chromosome count (RNG-independent shape).
        c("eng_best_genotype_shape", () -> {
            seed();
            Engine<BitGene, Integer> engine = Engine
                .builder(InvariantsHarness::oneMax, Genotype.of(BitChromosome.of(18, 0.5)))
                .populationSize(50)
                .build();
            EvolutionResult<BitGene, Integer> r = engine.stream()
                .limit(Limits.byFixedGeneration(30))
                .collect(EvolutionResult.toBestEvolutionResult());
            Genotype<BitGene> g = r.bestPhenotype().genotype();
            return g.length() + "," + g.chromosome().length();             // 1,18
        });

        // =====================================================================
        // Best-so-far progress: tracking the running best across the stream for a MAXIMUM
        // OneMax(25) objective, the accumulated best-so-far reaches a near-optimum threshold
        // by stream end (RNG-path-independent). Only a genuinely evolving engine gets there:
        // a random OneMax(25) population tops out around the mid-teens, so a non-optimizing
        // engine cannot clear the threshold. (The running MAX is used rather than the raw
        // per-generation best because the default engine is non-elitist, so a single
        // generation's best may dip; the meaningful signal is that evolution makes progress.)
        // =====================================================================
        c("eng_best_monotonic", () -> {
            seed();
            Engine<BitGene, Integer> engine = Engine
                .builder(InvariantsHarness::oneMax, Genotype.of(BitChromosome.of(25, 0.5)))
                .populationSize(80)
                .optimize(Optimize.MAXIMUM)
                .build();
            int[] running = { Integer.MIN_VALUE };
            engine.stream()
                .limit(Limits.byFixedGeneration(60))
                .map(EvolutionResult::bestFitness)
                .forEach(bf -> running[0] = Math.max(running[0], bf));
            return String.valueOf(running[0] >= 23);                       // true (optimum 25)
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
