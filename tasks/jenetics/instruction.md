# Implement `evolab`: a genetic-algorithm / evolutionary-computation library (Java)

## What you are building

You are implementing the core module of **evolab**, a genetic-algorithm (GA) library in Java. A GA
evolves a population of candidate solutions: each candidate is a **genotype** (made of chromosomes,
made of genes); an **engine** repeatedly selects the fittest, recombines and mutates them, and
converges toward an optimum. You must implement four things:

1. **The data model** — genes, chromosomes, and genotypes (the representation of a candidate).
2. **The operators** — mutators, crossovers, and selectors (how the population changes each generation).
3. **The evolution engine** — the fluent builder + stream that actually runs the GA to an optimum.
4. **Support** — statistics accumulators and sequence/range utilities.

Everything lives under the package root `io.evolab`. Implement the public behavior described below and standard
GA semantics; the tests exercise the **public API only**, so your public types, packages, and method
signatures must match the names below so the hidden test program compiles against your code.

**Determinism:** the engine and operators draw randomness from a global source,
`io.evolab.util.RandomRegistry` (`RandomRegistry.random(RandomGenerator)` sets it; `RandomRegistry.random()`
reads it). The tests seed it before stochastic cases and assert only **RNG-independent properties** —
convergence to a known optimum, invariants (population size, generation count, valid genotypes), and
deterministic configurations (mutation probability 0 or 1) — so a correct implementation is graded
fairly regardless of its internal random-number-consumption order. Numeric results are compared after
rounding to 6 decimals; integer/boolean results verbatim.

## Environment: where your code goes and how it is built

- Put your Java source under **`/app/src`**, package root `io/evolab/…`. Java **17** source
  (records, sealed types, etc. are fine).
- The core module has **no external dependencies** — implement everything in plain Java on the JDK.
  There is no internet.
- Create **`/app/setup.sh`** that compiles offline into `/app/out`:
  ```bash
  mkdir -p /app/out
  find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
  ```

**Generic parameters** — throughout, `G` is the gene type (`extends Gene<?, G>`) and `C` the fitness
type (`extends Comparable<? super C>`). Numeric-gene operators additionally bound `G extends
NumericGene<?, G>`; `MeanAlterer` bounds `G extends Gene<?, G> & Mean<G>`; and
`PartiallyMatchedCrossover<T, C>` uses `T` for the `EnumGene` allele type. Match these bounds exactly.

## Layer 1 — Genes, chromosomes, genotype (`io.evolab`)

The generic model is `Gene<A, G>` → `Chromosome<G extends Gene>` → `Genotype<G>`, where `A` is the
allele (value) type and `G` the gene type. Every `Chromosome<G>` is `Iterable<G>` over its genes, so
callers can enhanced-for a chromosome directly (`for (G gene : chromosome)`).

### Numeric genes — `IntegerGene`, `LongGene`, `DoubleGene`

Bounded numeric genes. Factories and instance methods:
```java
static IntegerGene of(int value, int min, int max)   static IntegerGene of(int min, int max)   // 2-arg = random allele in range
static IntegerGene of(int value, IntRange range)
// LongGene.of(...) mirrors IntegerGene;  DoubleGene.of(double value, double min, double max), DoubleGene.of(DoubleRange)
A       allele()   A min()   A max()   boolean isValid()      // isValid = allele within [min, max]
G       mean(G other)                                          // the gene midway — for INTEGER genes the FLOORED average
G       newInstance()   G newInstance(A allele)                // newInstance() = random gene
double  doubleValue()   int intValue()
```

### `BitGene` + `BitChromosome`

A bit string:
```java
static BitChromosome of(CharSequence bits)          // e.g. "1011"
static BitChromosome of(int length)   static BitChromosome of(int length, double onesProbability)   static BitChromosome of(BigInteger v)
int      length()   int bitCount()                  // bitCount = number of set bits
BitGene  get(int i)                                  // get(i).allele() is a Boolean
boolean  booleanValue(int i)
```
**Bit ordering** is least-significant-bit first: in `of(CharSequence)` the **rightmost** character is
bit index 0 (matching `of(BigInteger)`), and `get(i)` / `booleanValue(i)` index from the LSB. So for
`of("1011")` bit 0 is the trailing `1` (true), bit 1 is `1` (true), bit 2 is `0` (false), bit 3 is `1`.

### `IntegerChromosome` / `LongChromosome` / `DoubleChromosome`

```java
static IntegerChromosome of(Gene... genes)   of(min, max)   of(min, max, int length)   of(IntRange range, int length)
int              length()   G get(int i)   // (or gene(i))
boolean          isValid()   Chromosome<G> newInstance()
```
`of(min, max)` builds a length-1 chromosome; `of(min, max, length)` a random one of that length.

### `CharacterGene` + `CharacterChromosome`

Character genes over a valid-character set (`io.evolab.util.CharSeq`, default alphanumerics):
```java
static CharacterGene       of(char c)   of(char c, CharSeq valid)
Character allele()   char charValue()   boolean isValid()   CharacterGene newInstance(Character c)
static CharacterChromosome of(String s)   of(String s, CharSeq valid)
int length()   CharacterGene get(int i)   char charAt(int i)   boolean isValid()
```

### `AnyGene<A>` + `AnyChromosome<A>`

Genes over an arbitrary allele type, using a supplier + validator:
```java
static <A> AnyGene<A>       of(A allele, Supplier<? extends A> supplier, Predicate<? super A> validator)
A allele()   boolean isValid()   AnyGene<A> newInstance(A a)
static <A> AnyChromosome<A> of(Supplier<? extends A> supplier, Predicate<? super A> validator, int length)
int length()   AnyGene<A> get(int i)   boolean isValid()
```

### `EnumGene<A>` + `PermutationChromosome<A>`

A permutation of a set of alleles (used by `PartiallyMatchedCrossover`):
```java
static <A> PermutationChromosome<A> of(ISeq<A> alleles)
static     PermutationChromosome<Integer> ofInteger(int length)     // a permutation of 0..length-1
int length()   EnumGene<A> get(int i)                               // get(i).allele() is the element
```

### `Genotype<G>`

```java
static <G> Genotype<G> of(Chromosome<G>... chromosomes)
static <G> Genotype<G> of(Iterable<? extends Chromosome<G>> chromosomes)     // e.g. a List
int          length()        // number of chromosomes
int          geneCount()     // total genes across all chromosomes
Chromosome<G> get(int i)     Chromosome<G> chromosome()   // chromosome() = the first
boolean      isValid()       Genotype<G> newInstance()
```
`Genotype<G>` **implements `Factory<Genotype<G>>`** — `newInstance()` is the factory method (produces a
new random genotype of the same structure). So a `Genotype` can be passed directly wherever a
`Factory<Genotype<G>>` is expected, e.g. `Engine.builder(fitness, someGenotype)`.

### `Phenotype<G, C extends Comparable<C>>` and `Optimize`

A phenotype is a genotype plus its evaluated fitness:
```java
static <G,C> Phenotype<G,C> of(Genotype<G> gt, long generation)              // unevaluated
static <G,C> Phenotype<G,C> of(Genotype<G> gt, long generation, C fitness)   // evaluated (fitness set directly)
Phenotype<G,C> withFitness(C fitness)
Genotype<G> genotype()   C fitness()   long generation()
enum Optimize { MAXIMUM, MINIMUM }   // Optimize.best(a, b) picks the better fitness accordingly
```

## Layer 2 — Genetic operators (`io.evolab`)

**Alterers** mutate/recombine a population. Each `implements Alterer<G, C>`:
```java
AltererResult<G,C> alter(Seq<Phenotype<G,C>> population, long generation)   // result: population(), int alterations()
```
`alterations()` reports the total number of individual gene-level alterations the operator applied
across the whole population — `0` for a no-op. Since `p=1` alters every gene, at `p=1` it equals the
aggregate number of genes the operator processed.

Provide these (crossovers recombine pairs, preserving chromosome length):
```java
Mutator(double p) | ()          SwapMutator(double p) | ()      GaussianMutator(double p) | ()   // mutate genes (p=0 none, p=1 every gene)
SinglePointCrossover(double p) | ()
MultiPointCrossover(double p, int n) | (double p) | (int n) | ()             // n = number of crossover points
UniformCrossover(double crossoverProbability, double swapProbability) | (double) | ()
PartiallyMatchedCrossover(double p)                                          // PMX, for permutation chromosomes
LineCrossover(double p, double p2) | (double) | ()                           // numeric-gene recombinators (G extends NumericGene)
IntermediateCrossover(double p, double p2) | (double) | ()
MeanAlterer(double p) | ()                                                   // G extends Gene & Mean<G> (Double/Integer/LongGene implement Mean)
CombineAlterer(BinaryOperator<G> combiner, double p) | (BinaryOperator<G>)
static Alterer<G,C> Alterer.of(Alterer<G,C>... alterers)                     // chains alterers -> a CompositeAlterer
static Alterer<G,C> PartialAlterer.of(Alterer<G,C> a, int... chromosomeIndices)   // applies a to only those chromosome indices
```

**Selectors** choose individuals for the next generation. Each `implements Selector<G, C>`:
```java
ISeq<Phenotype<G,C>> select(Seq<Phenotype<G,C>> population, int count, Optimize opt)   // returns exactly `count` individuals
```
Provide these:
```java
TournamentSelector(int sampleSize)      // samples with replacement
RouletteWheelSelector()   StochasticUniversalSelector()   MonteCarloSelector()   // fitness-proportional / SUS / uniform-random
TruncationSelector()                    // top `count` by fitness
EliteSelector(int eliteCount) | ()      // keeps the best
BoltzmannSelector(double b)   LinearRankSelector(double nminus)   ExponentialRankSelector(double c)   // rank/temperature-scaled — bias toward FITTER individuals (contracts below)
```

The last three are **rank- / temperature-scaled** selectors. Like the other non-uniform selectors they
bias selection toward **fitter** individuals (contrast `MonteCarloSelector`, which is uniform-random with
no pressure); each one's parameter tunes how sharp that pressure is:

- `LinearRankSelector(double nminus)` — probability is linear in fitness **rank** (not raw fitness);
  a smaller `nminus` means stronger preference for the fittest.
- `ExponentialRankSelector(double c)` — probability is exponential in fitness rank, with `c` in the
  range `[0, 1)`. Ranking individuals worst-to-best as `r = 0 .. N-1`, individual `r` is selected with
  probability proportional to `c^(N-1-r)`, so the fittest receive the highest probability. A **smaller**
  `c` gives a sharper preference for the fittest — **stronger** selection pressure than linear ranking —
  while `c` near 1 flattens toward uniform selection.
- `BoltzmannSelector(double b)` — temperature-scaled on raw fitness; a larger (positive) `b` sharpens
  the preference for higher fitness.

## Layer 3 — Evolution engine (`io.evolab.engine`)

**`Engine<G, C>`** is built with a fluent builder, then run as a stream:
```java
static Engine.Builder<G,C>   Engine.builder(Function<Genotype<G>, C> fitness, Factory<Genotype<G>> genotypeFactory)
static Engine.Builder<T,G,C> Engine.builder(Function<T, C> fitness, Codec<T, G> codec)   // Builder is generic
// builder setters (chainable), then build():
.populationSize(int)  .optimize(Optimize)  .selector(...)  .survivorsSelector(...)  .offspringSelector(...)  .alterers(Alterer...)  .build()
int      populationSize()   Optimize optimize()      // the BUILT Engine also exposes these config accessors
EvolutionStream<G,C> stream()                        // a Stream<EvolutionResult<G,C>>
```
Bound the stream with `.limit(...)` using **`Limits`**, and collect with an `EvolutionResult` collector:
```java
EvolutionStream<G,C> limit(Predicate<? super EvolutionResult<G,C>> proceed)   // ON EvolutionStream (besides the inherited limit(long)); stops when `proceed` returns false — the Limits.* predicates plug in here
static Predicate<...> Limits.byFixedGeneration(long n)      // runs exactly n generations
static Predicate<...> Limits.bySteadyFitness(int n)
// collectors:
EvolutionResult.toBestEvolutionResult()   EvolutionResult.toBestPhenotype()   EvolutionResult.toBestGenotype()
```

**`EvolutionResult<G, C>`** — the result of a run (or generation):
```java
C bestFitness()   Phenotype<G,C> bestPhenotype()   Genotype<G> bestGenotype()
long generation()   long totalGenerations()
ISeq<Phenotype<G,C>> population()   int populationCount()      // populationCount stays fixed across generations
```
Generation numbering is **1-based**: the first `EvolutionResult` yielded by `stream()` has
`generation() == 1`, so under `Limits.byFixedGeneration(n)` the stream yields exactly `n` results and
the final one's `generation() == n`. `totalGenerations()` is the cumulative number of generations
executed up to that result.

**`EvolutionStatistics<C extends Comparable<? super C>, FitnessStatistics>`** — TWO type parameters;
accumulates run statistics, consumed via `stream.peek(statistics)`. The factory fixes the second type:
```java
static ... EvolutionStatistics.ofComparable()   // -> EvolutionStatistics<C, MinMax<C>>
static ... EvolutionStatistics.ofNumber()       // -> EvolutionStatistics<C, DoubleMomentStatistics>
FitnessStatistics fitness()                     // the accumulated fitness statistics (MinMax<C> / DoubleMomentStatistics)
```
The accumulator accepts **every** phenotype's fitness once per generation, so after a fixed-generation
run `fitness().count()` equals `populationSize × generations`.

**`Codec<T,G>` / `Codecs` / `InvertibleCodec<T,G>` / `Problem`** — encode a problem type into
genotypes and decode back:
```java
Factory<Genotype<G>> encoding()   Function<Genotype<G>,T> decoder()          // on a Codec
static InvertibleCodec<...> Codecs.ofScalar(IntRange | DoubleRange | LongRange)
static InvertibleCodec<...> Codecs.ofVector(range, int length)
Genotype<G> encode(T value)   T decode(Genotype<G> gt)                        // InvertibleCodec adds BOTH (codec.decode(codec.encode(v)) round-trips to v)
```
`Codecs.*` return an `InvertibleCodec<T,G>` (which extends `Codec`). `Problem` rounds out the API.

**Semantics to reproduce:** a solvable problem (e.g. maximizing the number of set bits in a
`BitChromosome`) converges to its optimum given enough generations; `Optimize.MAXIMUM`/`MINIMUM` pick
the higher/lower fitness.

## Layer 4 — Statistics & utilities (`io.evolab.stat`, `io.evolab.util`)

### `io.evolab.stat`

```java
// Moment accumulators: accept values, then read moments.
class DoubleMomentStatistics / IntMomentStatistics / LongMomentStatistics {
  void accept(value)
  long count()   min()   max()   sum()   double mean()   variance()   skewness()   kurtosis()
  // variance = SAMPLE (÷ n-1); skewness = bias-corrected SAMPLE skewness (G1, adjusted Fisher-Pearson);
  // kurtosis = bias-corrected SAMPLE EXCESS kurtosis (G2 — zero for a normal distribution)
  DoubleMoments toDoubleMoments()    // (IntMoments toIntMoments(), LongMoments toLongMoments())
}
// Immutable record forms, same accessors: DoubleMoments / IntMoments / LongMoments
// Static array summarizers (records):
DoubleSummary.min(double[]) / max / sum / mean(double[])  -> double
IntSummary.min(int[]) / max -> int    IntSummary.sum(int[]) -> long    IntSummary.mean(int[]) -> double
class MinMax {  static MinMax of()   static MinMax of(Comparator)   void accept(value)   min()   max()   long count()  }
class Quantile { Quantile(double p)   void accept(double)   long count()   double quantile()   double value() }   // online P^2 estimator; quantile()=p, count()=#accepted; value()=estimate of the p-quantile (so at p=1.0 it is the maximum of the accepted values)
```

### `io.evolab.util`

```java
// Ranges:
DoubleRange / IntRange / LongRange:  static of(a, b)   min()   max()   IntRange.size()   // size() = max - min (half-open width)
// CharSeq: an immutable, ordered set of valid characters (allele alphabet):
new CharSeq(CharSequence chars)   char get(int i)   int length()
// Immutable sequences Seq / ISeq / MSeq (each is Iterable<T> and streams directly):
ISeq.of(...)   MSeq.of(...)   int length()   get(int i)   map(f)   contains(x)   indexOf(x)   reverse()   List asList()
Stream<T> stream()                                 // Seq/ISeq/MSeq implement Iterable<T> (enhanced-for) AND expose stream()
MSeq.set(int i, v)   MSeq.sort()
String toString(String separator)                 // every Seq: joins elements with the separator, NO surrounding brackets
ISeq<T> MSeq.toISeq()                              // INSTANCE method: immutable snapshot of an MSeq
static <T> Collector<T,?,ISeq<T>> ISeq.toISeq()   // STATIC collector: stream.collect(ISeq.toISeq())  -- distinct from the instance method
// RandomRegistry: the global RNG source (see Determinism above)
RandomRegistry.random(RandomGenerator g)   RandomGenerator RandomRegistry.random()
```

## Scope

Implement the **complete core `evolab` module** — the gene/chromosome/genotype model, all the
operators, the evolution engine and its stream/limits/codecs/statistics, and the `stat`/`util`
support packages. The `evolab.ext`, `evolab.prog`, `evolab.xml`, … modules are out
of scope. You may organize internal/helper classes freely — only the public types, packages, and
signatures named above are relied upon by the tests.
