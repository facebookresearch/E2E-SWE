import io.evolab.*;
import io.evolab.engine.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Function;
import java.util.function.Supplier;

/**
 * WRG test harness — jenetics engine CONVERGENCE cases (OneMax / numeric max / min / sphere).
 *
 * Split out of the former monolithic EngineHarness so a signature mismatch here only zeroes this
 * cluster of pure-convergence cases. The config-getter usage (engine.populationSize()/optimize())
 * lives in InvariantsHarness and the EvolutionStatistics case in EngineStatisticsHarness, so a
 * mismatch in those APIs cannot compile-wipe these convergence assertions. Self-contained: its own
 * imports + only the helpers these cases reference. Case bodies are verbatim (only the oneMax method
 * reference is repointed to this class). Runner is shared.
 */
public class ConvergenceHarness {
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
        // OneMax N=30: any correct engine drives best fitness to NEAR the optimum N. The EXACT optimum
        // (30) is not RNG-path-guaranteed even under a fixed seed (jenetics' internal parallel workers
        // consume RNG off the seeded thread-local), so assert a near-optimum threshold any correct
        // engine clears -> RNG-path-independent (a non-evolving/first-N impl tops out well below 28).
        c("eng_onemax_n30", () -> {
            seed();
            final int N = 30;
            Engine<BitGene, Integer> engine = Engine
                .builder(ConvergenceHarness::oneMax, Genotype.of(BitChromosome.of(N, 0.5)))
                .populationSize(150)
                .optimize(Optimize.MAXIMUM)
                .build();
            EvolutionResult<BitGene, Integer> r = engine.stream()
                .limit(Limits.byFixedGeneration(400))
                .collect(EvolutionResult.toBestEvolutionResult());
            return String.valueOf(r.bestFitness() >= 28);                   // true (optimum 30)
        });

        // OneMax best genotype at convergence: all bits set -> bitCount == N (RNG-independent).
        c("eng_onemax_best_allset", () -> {
            seed();
            final int N = 16;
            Engine<BitGene, Integer> engine = Engine
                .builder(ConvergenceHarness::oneMax, Genotype.of(BitChromosome.of(N, 0.5)))
                .populationSize(100)
                .optimize(Optimize.MAXIMUM)
                .build();
            EvolutionResult<BitGene, Integer> r = engine.stream()
                .limit(Limits.byFixedGeneration(300))
                .collect(EvolutionResult.toBestEvolutionResult());
            BitChromosome ch = (BitChromosome) r.bestPhenotype().genotype().chromosome();
            return String.valueOf(ch.bitCount());                           // 16
        });

        // =====================================================================
        // Integer / Double maximization to a known max.
        // =====================================================================
        // Maximize x in [0,100]. The exact boundary (100) is not reliably hit by any
        // particular RNG path, so assert a near-optimum threshold that ANY correct engine
        // clears after long evolution -> RNG-path-independent boolean.
        c("eng_int_max", () -> {
            seed();
            Engine<IntegerGene, Integer> engine = Engine
                .builder((Integer x) -> x, Codecs.ofScalar(IntRange.of(0, 100)))
                .populationSize(100)
                .optimize(Optimize.MAXIMUM)
                .build();
            EvolutionResult<IntegerGene, Integer> r = engine.stream()
                .limit(Limits.byFixedGeneration(200))
                .collect(EvolutionResult.toBestEvolutionResult());
            return String.valueOf(r.bestFitness() >= 90);                   // true
        });

        // Maximize -(x-3)^2 over x in [-10,10] -> optimum at x=3, fitness 0.
        c("eng_double_max", () -> {
            seed();
            Function<Double, Double> ff = x -> -(x - 3.0) * (x - 3.0);
            Engine<DoubleGene, Double> engine = Engine
                .builder(ff, Codecs.ofScalar(DoubleRange.of(-10.0, 10.0)))
                .populationSize(200)
                .optimize(Optimize.MAXIMUM)
                .build();
            EvolutionResult<DoubleGene, Double> r = engine.stream()
                .limit(Limits.byFixedGeneration(500))
                .collect(EvolutionResult.toBestEvolutionResult());
            // Converges toward 0 from below; assert it reaches within a coarse tolerance
            // that ANY correct engine clears -> RNG-path-independent boolean.
            return String.valueOf(r.bestFitness() > -0.01);                 // true
        });

        // Harder convergence: minimize 2D sphere (x^2 + y^2), each var in [-5,5].
        // Known global optimum = 0 at (0,0). Assert a coarse tolerance any correct
        // engine clears after long evolution -> RNG-path-independent boolean.
        c("eng_vector_sphere_min", () -> {
            seed();
            InvertibleCodec<double[], DoubleGene> codec =
                Codecs.ofVector(DoubleRange.of(-5.0, 5.0), 2);
            Engine<DoubleGene, Double> engine = Engine
                .builder(v -> v[0] * v[0] + v[1] * v[1], codec)
                .populationSize(200)
                .optimize(Optimize.MINIMUM)
                .build();
            EvolutionResult<DoubleGene, Double> r = engine.stream()
                .limit(Limits.byFixedGeneration(500))
                .collect(EvolutionResult.toBestEvolutionResult());
            return String.valueOf(r.bestFitness() < 0.1);                   // true (optimum 0)
        });

        // =====================================================================
        // Optimize.MINIMUM converging to a known min.
        // =====================================================================
        // Minimize x in [0,100]. Assert a near-optimum threshold any correct engine clears
        // (the exact boundary 0 is not guaranteed by a particular RNG path).
        c("eng_int_min", () -> {
            seed();
            Engine<IntegerGene, Integer> engine = Engine
                .builder((Integer x) -> x, Codecs.ofScalar(IntRange.of(0, 100)))
                .populationSize(100)
                .optimize(Optimize.MINIMUM)
                .build();
            EvolutionResult<IntegerGene, Integer> r = engine.stream()
                .limit(Limits.byFixedGeneration(200))
                .collect(EvolutionResult.toBestEvolutionResult());
            return String.valueOf(r.bestFitness() <= 10);                   // true
        });

        // Minimize (x-2)^2 over x in [-10,10] -> optimum at x=2, fitness 0.
        c("eng_double_min", () -> {
            seed();
            Function<Double, Double> ff = x -> (x - 2.0) * (x - 2.0);
            Engine<DoubleGene, Double> engine = Engine
                .builder(ff, Codecs.ofScalar(DoubleRange.of(-10.0, 10.0)))
                .populationSize(200)
                .optimize(Optimize.MINIMUM)
                .build();
            EvolutionResult<DoubleGene, Double> r = engine.stream()
                .limit(Limits.byFixedGeneration(500))
                .collect(EvolutionResult.toBestEvolutionResult());
            return String.valueOf(r.bestFitness() < 0.01);                  // true
        });

        // =====================================================================
        // Limits.bySteadyFitness: stopping is an invariant — after the stream ends,
        // the best fitness stayed steady; for OneMax it also reaches the optimum.
        // =====================================================================
        c("eng_steady_fitness_optimum", () -> {
            seed();
            final int N = 20;
            Engine<BitGene, Integer> engine = Engine
                .builder(ConvergenceHarness::oneMax, Genotype.of(BitChromosome.of(N, 0.5)))
                .populationSize(120)
                .optimize(Optimize.MAXIMUM)
                .build();
            // Steady for 50 generations OR hard cap of 1000 — either way OneMax converges to N.
            EvolutionResult<BitGene, Integer> r = engine.stream()
                .limit(Limits.bySteadyFitness(50))
                .limit(Limits.byFixedGeneration(1000))
                .collect(EvolutionResult.toBestEvolutionResult());
            return String.valueOf(r.bestFitness());                        // 20
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
