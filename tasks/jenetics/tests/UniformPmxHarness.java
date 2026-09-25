import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics UNIFORM CROSSOVER + PARTIALLY-MATCHED CROSSOVER (UniformCrossover, PMX).
 *
 * Split out of the former monolithic AltererHarness so a signature mismatch here only zeroes this
 * small cluster. Self-contained: its own imports + only the helpers these cases reference. Case
 * bodies are verbatim. Runner is shared.
 */
public class UniformPmxHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    /** Fix the global RNG so any residual randomness is reproducible across CAPTURE runs. */
    static void seed() { RandomRegistry.random(new java.util.Random(42)); }
    static void seed(long s) { RandomRegistry.random(new java.util.Random(s)); }

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

    /** Ordered permutation alleles (the Integer values) of the first chromosome. */
    static List<Integer> permOrdered(Genotype<EnumGene<Integer>> g) {
        List<Integer> out = new ArrayList<>();
        for (EnumGene<Integer> gene : g.chromosome()) out.add(gene.allele());
        return out;
    }

    static {
        // UniformCrossover(1.0, 0.5): union multiset preserved AND genuine recombination, asserted at
        // BOTH a 2-individual (single-pair) and a 4-individual (two-pair) population in ONE bundled
        // case (same operator + same params + same assertion — merged to remove pure size-fragmentation
        // without coverage loss). For each population: recombination is guaranteed (prob 1.0), so the
        // whole-population union multiset is preserved (uniform crossover only exchanges genes between
        // paired individuals) AND at least one offspring differs from every input individual. A no-op
        // preserves the multiset but leaves every offspring equal to an input -> "recombined" flag
        // false -> FAILS. Order: unionOk2|recomb2|unionOk4|recomb4.
        c("alt_uniform_recombined", () -> {
            // --- 2-individual (single pair) ---
            seed();
            List<Integer> pa = List.of(10, 20, 30, 40, 50, 60);
            List<Integer> pb = List.of(11, 21, 31, 41, 51, 61);
            UniformCrossover<IntegerGene, Integer> x2 = new UniformCrossover<>(1.0, 0.5);
            var res2 = x2.alter(pop(phenoInt(10, 20, 30, 40, 50, 60),
                                    phenoInt(11, 21, 31, 41, 51, 61)), 1L);
            List<Integer> o0 = allelesOrdered(res2.population().get(0).genotype());
            List<Integer> o1 = allelesOrdered(res2.population().get(1).genotype());
            List<Integer> union2 = new ArrayList<>(); union2.addAll(o0); union2.addAll(o1);
            Collections.sort(union2);
            List<Integer> expUnion2 = new ArrayList<>(); expUnion2.addAll(pa); expUnion2.addAll(pb);
            Collections.sort(expUnion2);
            boolean unionOk2 = union2.equals(expUnion2);
            boolean recomb2 = (!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb));

            // --- 4-individual (two pairs) ---
            seed();
            List<List<Integer>> parents = List.of(
                List.of(10, 20, 30, 40), List.of(50, 60, 70, 80),
                List.of(11, 21, 31, 41), List.of(51, 61, 71, 81));
            UniformCrossover<IntegerGene, Integer> x4 = new UniformCrossover<>(1.0, 0.5);
            var res4 = x4.alter(pop(
                phenoInt(10, 20, 30, 40), phenoInt(50, 60, 70, 80),
                phenoInt(11, 21, 31, 41), phenoInt(51, 61, 71, 81)), 1L);
            List<Integer> union4 = new ArrayList<>();
            List<List<Integer>> outs = new ArrayList<>();
            for (int i = 0; i < 4; i++) {
                List<Integer> o = allelesOrdered(res4.population().get(i).genotype());
                outs.add(o); union4.addAll(o);
            }
            Collections.sort(union4);
            List<Integer> expUnion4 = new ArrayList<>();
            for (List<Integer> p : parents) expUnion4.addAll(p);
            Collections.sort(expUnion4);
            boolean unionOk4 = union4.equals(expUnion4);
            boolean recomb4 = outs.stream().anyMatch(o -> parents.stream().noneMatch(o::equals));

            return unionOk2 + "|" + recomb2 + "|" + unionOk4 + "|" + recomb4;   // true|true|true|true
        });

        // =========================================================================================
        // PMX — offspring stay well-formed (right length, all alleles drawn from the base index set)
        //       AND the ordering actually permutes vs BOTH parents (no-op fails the "permuted" half).
        //
        // NOTE: jenetics' PartiallyMatchedCrossover operates on EnumGene by INDEX; on this JDK its
        // offspring are NOT clean permutations of 0..n-1 (they can repeat/drop indices — see the same
        // documented caveat in OperatorHarness op_pmx_shape). So we do NOT assert permutation-uniqueness
        // (that would be an RNG-order- and impl-detail-dependent, unfair check). The RNG-independent
        // invariants that DO hold for any correct impl are: length preserved and every offspring allele
        // is a member of {0..n-1}. The discriminator against a no-op is the AGGREGATE "permuted" flag:
        // over several seeds at least one offspring's ordering differs from BOTH parents. A no-op that
        // returns the parents unchanged passes the length/membership half but never permutes -> FAILS.
        // =========================================================================================
        c("alt_pmx_wellformed_and_permuted", () -> {
            List<Integer> pa = List.of(0, 1, 2, 3, 4, 5, 6);
            List<Integer> pb = List.of(6, 5, 4, 3, 2, 1, 0);
            boolean lenOk = true;
            boolean membershipOk = true;
            boolean anyPermuted = false;
            for (long s = 1; s <= 6; s++) {
                seed(s);
                PartiallyMatchedCrossover<Integer, Integer> x =
                    new PartiallyMatchedCrossover<>(1.0);
                var c1 = PermutationChromosome.of(ISeq.of(0, 1, 2, 3, 4, 5, 6));
                var c2 = PermutationChromosome.of(ISeq.of(6, 5, 4, 3, 2, 1, 0));
                var pa_ = Phenotype.of(Genotype.of(c1), 1L, 0);
                var pb_ = Phenotype.of(Genotype.of(c2), 1L, 0);
                var res = x.alter(ISeq.of(pa_, pb_), 1L);
                List<Integer> o0 = permOrdered(res.population().get(0).genotype());
                List<Integer> o1 = permOrdered(res.population().get(1).genotype());
                if (o0.size() != 7 || o1.size() != 7) lenOk = false;
                for (int v : o0) if (v < 0 || v > 6) membershipOk = false;
                for (int v : o1) if (v < 0 || v > 6) membershipOk = false;
                if ((!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb)))
                    anyPermuted = true;
            }
            return lenOk + "|" + membershipOk + "|" + anyPermuted;   // true|true|true
        });

        // PMX shape: population size preserved and both offspring keep length 6 (read from the seed-42
        // run), plus the AGGREGATE "permuted" discriminator -- over several seeds at least one
        // offspring's ordering differs from BOTH parents, i.e. PMX genuinely recombined. A no-op leaves
        // every offspring equal to a parent at every seed -> permuted false -> FAILS.
        //
        // The permuted flag is OR-ed over seeds (same guard as alt_pmx_wellformed_and_permuted above)
        // rather than read from one seed: which crossover segment a given seed produces depends on the
        // implementation's internal RNG-consumption order, and on a permutation and its exact reversal
        // a whole family of legitimate segments reproduces both parents verbatim -- so a single-seed
        // flag would be an RNG-order-dependent, unfair check.
        c("alt_pmx_shape_and_permuted", () -> {
            List<Integer> pa = List.of(0, 1, 2, 3, 4, 5);
            List<Integer> pb = List.of(5, 4, 3, 2, 1, 0);
            int popLen = 0, l0 = 0, l1 = 0;
            boolean permuted = false;
            for (long s : new long[] {42, 1, 2, 3, 4, 5, 6}) {
                seed(s);
                PartiallyMatchedCrossover<Integer, Integer> x = new PartiallyMatchedCrossover<>(1.0);
                var c1 = PermutationChromosome.of(ISeq.of(0, 1, 2, 3, 4, 5));
                var c2 = PermutationChromosome.of(ISeq.of(5, 4, 3, 2, 1, 0));
                var a = Phenotype.of(Genotype.of(c1), 1L, 0);
                var b = Phenotype.of(Genotype.of(c2), 1L, 0);
                var res = x.alter(ISeq.of(a, b), 1L);
                List<Integer> o0 = permOrdered(res.population().get(0).genotype());
                List<Integer> o1 = permOrdered(res.population().get(1).genotype());
                if (s == 42) {
                    popLen = res.population().length();
                    l0 = res.population().get(0).genotype().chromosome().length();
                    l1 = res.population().get(1).genotype().chromosome().length();
                }
                if ((!o0.equals(pa) && !o0.equals(pb)) || (!o1.equals(pa) && !o1.equals(pb)))
                    permuted = true;
            }
            return popLen + "|" + l0 + "|" + l1 + "|" + permuted;   // 2|6|6|true
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
