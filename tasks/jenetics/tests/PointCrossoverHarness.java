import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics SINGLE-/MULTI-POINT CROSSOVER (SinglePointCrossover, MultiPointCrossover).
 *
 * Split out of the former monolithic AltererHarness so a signature mismatch here only zeroes this
 * small cluster. Self-contained: its own imports + only the helpers these cases reference. Case
 * bodies are verbatim. Runner is shared.
 */
public class PointCrossoverHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    /** Fix the global RNG so any residual randomness is reproducible across CAPTURE runs. */
    static void seed() { RandomRegistry.random(new java.util.Random(42)); }

    // ---- builders (copied from OperatorHarness) -------------------------------------------------

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

    /** Ordered (unsorted) alleles of the first chromosome. */
    static List<Integer> allelesOrdered(Genotype<IntegerGene> g) {
        List<Integer> out = new ArrayList<>();
        for (IntegerGene gene : g.chromosome()) out.add(gene.allele());
        return out;
    }

    static ISeq<Phenotype<IntegerGene, Integer>> pop(Phenotype<IntegerGene, Integer>... ps) {
        return ISeq.of(ps);
    }

    static {
        // =========================================================================================
        // CROSSOVERS — with two DIFFERENT parents & prob 1.0, offspring must be recombined:
        // at least one offspring differs from BOTH parents, union multiset preserved. No-op fails.
        // =========================================================================================

        // SinglePointCrossover p=1.0: union multiset preserved AND at least one offspring differs
        // from BOTH parents (recombination occurred). A no-op returns the parents unchanged: its
        // offspring each EQUAL a parent -> "recombined" flag false -> FAILS.
        c("alt_singlepoint_recombined", () -> {
            seed();
            List<Integer> pa = List.of(10, 20, 30, 40, 50, 60);
            List<Integer> pb = List.of(61, 71, 81, 91, 12, 13);
            SinglePointCrossover<IntegerGene, Integer> x = new SinglePointCrossover<>(1.0);
            var res = x.alter(pop(phenoInt(10, 20, 30, 40, 50, 60),
                                  phenoInt(61, 71, 81, 91, 12, 13)), 1L);
            List<Integer> o0 = allelesOrdered(res.population().get(0).genotype());
            List<Integer> o1 = allelesOrdered(res.population().get(1).genotype());
            // union multiset preserved
            List<Integer> union = new ArrayList<>(); union.addAll(o0); union.addAll(o1);
            Collections.sort(union);
            List<Integer> expUnion = new ArrayList<>(); expUnion.addAll(pa); expUnion.addAll(pb);
            Collections.sort(expUnion);
            boolean unionOk = union.equals(expUnion);
            // at least one offspring differs from BOTH parents
            boolean recomb = (!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb));
            return unionOk + "|" + recomb;               // true|true
        });

        // MultiPointCrossover (3 points) p=1.0: same discrimination — union preserved + recombined.
        c("alt_multipoint_recombined", () -> {
            seed();
            List<Integer> pa = List.of(11, 22, 33, 44, 55, 66, 77);
            List<Integer> pb = List.of(88, 99, 12, 13, 14, 15, 16);
            MultiPointCrossover<IntegerGene, Integer> x = new MultiPointCrossover<>(1.0, 3);
            var res = x.alter(pop(phenoInt(11, 22, 33, 44, 55, 66, 77),
                                  phenoInt(88, 99, 12, 13, 14, 15, 16)), 1L);
            List<Integer> o0 = allelesOrdered(res.population().get(0).genotype());
            List<Integer> o1 = allelesOrdered(res.population().get(1).genotype());
            List<Integer> union = new ArrayList<>(); union.addAll(o0); union.addAll(o1);
            Collections.sort(union);
            List<Integer> expUnion = new ArrayList<>(); expUnion.addAll(pa); expUnion.addAll(pb);
            Collections.sort(expUnion);
            boolean unionOk = union.equals(expUnion);
            boolean recomb = (!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb));
            return unionOk + "|" + recomb;               // true|true
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
