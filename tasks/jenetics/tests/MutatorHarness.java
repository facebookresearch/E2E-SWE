import io.evolab.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * WRG test harness — jenetics MUTATORS (Mutator / SwapMutator / GaussianMutator).
 *
 * Split out of the former monolithic AltererHarness so a signature mismatch in one operator family
 * only zeroes its own small cluster instead of compile-wiping every alterer case. Self-contained:
 * its own imports + only the helpers these cases reference. Case bodies are verbatim. Runner is shared.
 */
public class MutatorHarness {
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

    /** Single-chromosome IntegerGene genotype from explicit allele values (range 0..99). */
    static Genotype<IntegerGene> genoInt(int... alleles) {
        IntegerGene[] genes = new IntegerGene[alleles.length];
        for (int i = 0; i < alleles.length; i++) genes[i] = IntegerGene.of(alleles[i], 0, 99);
        return Genotype.of(IntegerChromosome.of(genes));
    }

    /** DoubleGene genotype from explicit allele values (range 0..1). */
    static Genotype<DoubleGene> genoDouble(double... alleles) {
        DoubleGene[] genes = new DoubleGene[alleles.length];
        for (int i = 0; i < alleles.length; i++) genes[i] = DoubleGene.of(alleles[i], 0.0, 1.0);
        return Genotype.of(DoubleChromosome.of(genes));
    }

    /** Phenotype whose fitness == sum of the (single-chromosome) integer alleles. */
    static Phenotype<IntegerGene, Integer> phenoInt(int... alleles) {
        Genotype<IntegerGene> g = genoInt(alleles);
        int sum = 0; for (int a : alleles) sum += a;
        return Phenotype.of(g, 1L, sum);
    }

    /** Sorted list of the alleles of the first chromosome of a genotype (for multiset checks). */
    static List<Integer> alleles(Genotype<IntegerGene> g) {
        List<Integer> out = new ArrayList<>();
        for (IntegerGene gene : g.chromosome()) out.add(gene.allele());
        Collections.sort(out);
        return out;
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

    /** Ordered double alleles of the first chromosome (rounded via f). */
    static List<String> allelesD(Genotype<DoubleGene> g) {
        List<String> out = new ArrayList<>();
        for (DoubleGene gene : g.chromosome()) out.add(f(gene.allele()));
        return out;
    }

    /** Count positions where two equal-length int lists differ. */
    static int diffCount(List<Integer> a, List<Integer> b) {
        int d = 0;
        for (int i = 0; i < a.size(); i++) if (!a.get(i).equals(b.get(i))) d++;
        return d;
    }

    static {
        // =========================================================================================
        // MUTATOR — must prove the offspring actually differs from the parent (no-op fails).
        // =========================================================================================

        // Mutator p=1.0: EVERY gene of an IntegerChromosome is re-drawn from range [0,99]. Assert the
        // offspring genotype ACTUALLY DIFFERS from the parent at >0 positions (a fresh uniform draw
        // over 100 values almost surely differs; over seed 42 this is deterministic), remains valid,
        // and reports geneCount alterations. A no-op mutator (returns parent, 0 changes, 0 alterations)
        // FAILS every field: changed=false, alterations=0.
        c("alt_mutator_p1_changed", () -> {
            seed();
            List<Integer> parent = List.of(0, 0, 0, 0, 0, 0);
            Mutator<IntegerGene, Integer> m = new Mutator<>(1.0);
            var res = m.alter(pop(phenoInt(0, 0, 0, 0, 0, 0)), 1L);
            List<Integer> child = allelesOrdered(res.population().get(0).genotype());
            boolean changed = diffCount(parent, child) > 0;
            boolean valid = res.population().get(0).genotype().isValid();
            return changed + "|" + valid + "|" + res.alterations();   // true|true|6
        });

        // Mutator p=0.0: unchanged — exact equality to the parent + 0 alterations. This pins the
        // no-op boundary (a "no-op" IS correct here, but p=1 above catches a global no-op).
        c("alt_mutator_p0_unchanged", () -> {
            seed();
            Mutator<IntegerGene, Integer> m = new Mutator<>(0.0);
            var res = m.alter(pop(phenoInt(5, 6, 7)), 1L);
            List<Integer> after = allelesOrdered(res.population().get(0).genotype());
            boolean same = after.equals(List.of(5, 6, 7));
            return same + "|" + res.alterations();       // true|0
        });

        // Mutator p=1.0 over a 2-individual population: the aggregate number of changed alleles across
        // BOTH offspring is > 0 (both individuals mutate), population size preserved, alterations == 6.
        // A no-op yields 0 changes / 0 alterations -> FAILS.
        c("alt_mutator_p1_pop2_changed", () -> {
            seed();
            List<Integer> p0 = List.of(0, 0, 0);
            List<Integer> p1 = List.of(0, 0, 0);
            Mutator<IntegerGene, Integer> m = new Mutator<>(1.0);
            var res = m.alter(pop(phenoInt(0, 0, 0), phenoInt(0, 0, 0)), 1L);
            int d0 = diffCount(p0, allelesOrdered(res.population().get(0).genotype()));
            int d1 = diffCount(p1, allelesOrdered(res.population().get(1).genotype()));
            boolean changed = (d0 + d1) > 0;
            return changed + "|" + res.population().length() + "|" + res.alterations();
        });

        // =========================================================================================
        // SWAP MUTATOR — multiset preserved + alteration count == geneCount (no-op reporting 0 fails).
        //
        // NOTE: SwapMutator only ever PERMUTES the genes, so no allele value/multiset test can
        // distinguish it from an identity on a single chromosome (a full permutation preserves the
        // sorted multiset). The load-bearing discriminator against a no-op is therefore the reported
        // alteration count: with p=1.0 the mutator visits every one of the `geneCount` indices, so a
        // correct impl reports exactly geneCount alterations, whereas a no-op that returns the parent
        // reports 0. We assert BOTH the multiset invariant AND alterations == geneCount.
        // =========================================================================================
        c("alt_swap_p1_multiset_and_count", () -> {
            seed();
            SwapMutator<IntegerGene, Integer> m = new SwapMutator<>(1.0);
            var res = m.alter(pop(phenoInt(5, 4, 3, 2, 1)), 1L);
            List<Integer> sorted = alleles(res.population().get(0).genotype());  // sorted multiset
            boolean multisetOk = sorted.equals(List.of(1, 2, 3, 4, 5));
            return multisetOk + "|" + res.alterations();  // true|5
        });

        // SwapMutator p=0.0: exact unchanged order + 0 alterations.
        c("alt_swap_p0_unchanged", () -> {
            seed();
            SwapMutator<IntegerGene, Integer> m = new SwapMutator<>(0.0);
            var res = m.alter(pop(phenoInt(3, 1, 2)), 1L);
            boolean same = allelesOrdered(res.population().get(0).genotype()).equals(List.of(3, 1, 2));
            return same + "|" + res.alterations();       // true|0
        });

        // =========================================================================================
        // GAUSSIAN MUTATOR — values changed + still valid (in bounds). No-op fails the "changed".
        // =========================================================================================

        // GaussianMutator p=1.0 on DoubleGenes: every gene is perturbed -> the ROUNDED allele list
        // differs from the parent at >0 positions, and all values remain within [0,1] (valid). A
        // no-op leaves all values equal -> changed==0 -> FAILS.
        c("alt_gaussian_p1_changed_valid", () -> {
            seed();
            List<String> parent = List.of(f(0.25), f(0.5), f(0.75), f(0.1));
            GaussianMutator<DoubleGene, Double> m = new GaussianMutator<>(1.0);
            Genotype<DoubleGene> g = genoDouble(0.25, 0.5, 0.75, 0.1);
            Phenotype<DoubleGene, Double> ph = Phenotype.of(g, 1L, 1.6);
            var res = m.alter(ISeq.of(ph), 1L);
            List<String> child = allelesD(res.population().get(0).genotype());
            int changed = 0;
            for (int i = 0; i < parent.size(); i++) if (!parent.get(i).equals(child.get(i))) changed++;
            boolean anyChanged = changed > 0;
            boolean valid = res.population().get(0).genotype().isValid();
            return anyChanged + "|" + valid + "|" + res.alterations();   // true|true|4
        });

        // GaussianMutator p=0.0: unchanged double genotype + 0 alterations.
        c("alt_gaussian_p0_unchanged", () -> {
            seed();
            GaussianMutator<DoubleGene, Double> m = new GaussianMutator<>(0.0);
            Genotype<DoubleGene> g = genoDouble(0.25, 0.5, 0.75);
            Phenotype<DoubleGene, Double> ph = Phenotype.of(g, 1L, 1.5);
            var res = m.alter(ISeq.of(ph), 1L);
            boolean same = allelesD(res.population().get(0).genotype())
                    .equals(List.of(f(0.25), f(0.5), f(0.75)));
            return same + "|" + res.alterations();       // true|0
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
