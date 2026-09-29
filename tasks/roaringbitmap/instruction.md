# Chunkbits — a compressed integer-set library

Implement **chunkbits**, a Java library of compressed, immutable-friendly sets of integers. The
central idea: a set of 32-bit integers is partitioned into **chunks** of 2¹⁶ values (by the high 16
bits of each value), and each chunk is stored in whichever of three *container* representations is
smallest — a sorted array of the low 16 bits, an uncompressed 2¹⁶-bit bitmap, or a list of runs
(consecutive-value intervals). This yields excellent compression while keeping membership,
set-algebra, rank/select and iteration fast. On top of the 32-bit core the library also provides a
memory-mappable variant, two 64-bit variants, a range-query index, a `java.util.BitSet`-compatible
adapter, and an analysis helper.

Everything is **pure Java on the JDK (target Java 8), with no external runtime dependencies.** You
may organise internal helper classes and packages however you like; only the packages, class names,
method signatures and import paths described below are part of the observable contract that your
implementation must match.

Throughout, **integers are interpreted as UNSIGNED**. Java has no unsigned `int`/`long`, so values
are compared with unsigned semantics (`Integer.compareUnsigned` / `Long.compareUnsigned`). For 32-bit
values the ascending order is therefore:

```
0, 1, …, 2147483647 (0x7FFFFFFF), -2147483648 (0x80000000), …, -1 (0xFFFFFFFF)
```

i.e. all non-negative ints first (ascending), then all negative ints (ascending). When a value is
rendered as text (e.g. in `toString`), it is printed as its **unsigned** decimal (so the `int` `-1`
prints as `4294967295`, and `0x80000000` prints as `2147483648`). The same rule applies to 64-bit
`long` values with `Long.MAX_VALUE` (=9223372036854775807) followed by `Long.MIN_VALUE`
(=-9223372036854775808) … up to `-1`.

**Ranges are half-open `[start, end)`** everywhere a `(long start, long end)` pair appears.

---

## 1. `io.chunkbits.ChunkBitmap` — the 32-bit core

`public class ChunkBitmap` is the primary type: a mutable, compressed set of 32-bit unsigned
integers. It implements `Cloneable` and `Iterable<Integer>`.

### 1.1 Construction, membership, cardinality

- `ChunkBitmap()` — empty set.
- `static ChunkBitmap bitmapOf(int... values)` — a set of the given values (deduplicated, stored in
  unsigned order).
- `static ChunkBitmap bitmapOfUnordered(int... values)` — same result as `bitmapOf` for any input
  order.
- `static ChunkBitmap bitmapOfRange(long start, long end)` — the half-open range `[start, end)`;
  empty when `start >= end`.
- `void add(int x)` — add one value (idempotent).
- `void add(int... values)` — add several values.
- `void addN(int[] data, int offset, int n)` — add `data[offset .. offset+n)`. Throws
  `IllegalArgumentException` if `n < 0`, `offset < 0`, or `offset + n > data.length`; `n == 0` is a
  no-op.
- `void add(long start, long end)` — add the half-open range `[start, end)`.
- `void remove(int x)` — remove one value (no-op if absent).
- `void remove(long start, long end)` — remove the half-open range.
- `boolean contains(int x)` — membership.
- `boolean contains(long start, long end)` — true iff **every** value in `[start, end)` is present;
  false when `end <= start`.
- `boolean checkedAdd(int x)` — add; return `true` iff the value was newly added.
- `boolean checkedRemove(int x)` — remove; return `true` iff the value had been present.
- `void clear()` — remove everything.
- `boolean isEmpty()`.
- `int getCardinality()` / `long getLongCardinality()` — number of values.
- `boolean cardinalityExceeds(long threshold)` — true iff cardinality is strictly greater than
  `threshold`.

**Range bounds.** Every method taking a `(long start, long end)` range (`add`, `remove`, `contains`,
`bitmapOfRange`, `intersects`, `flip`, `orNot`, and the static range operations) validates the
bounds: it throws `IllegalArgumentException` unless `0 <= start` and `end <= 2^32` (and `start`,
`end` individually lie in `[0, 2^32]`). An in-range but empty range (`start >= end`) is accepted and
is a no-op for mutators.

### 1.2 Set algebra

Static forms return a **new** `ChunkBitmap` and never modify their inputs; in-place forms modify the
receiver.

- Static: `static ChunkBitmap and/or/xor/andNot(ChunkBitmap a, ChunkBitmap b)`.
- In-place: `void and(ChunkBitmap other)`, `void or(ChunkBitmap other)`, `void xor(ChunkBitmap
  other)`, `void andNot(ChunkBitmap other)`.
  - `x.and(x)` and `x.or(x)` leave `x` unchanged; `x.xor(x)` and `x.andNot(x)` empty it.
- Multi-way union: `static ChunkBitmap or(ChunkBitmap... bitmaps)` and `static ChunkBitmap
  or(Iterator<? extends ChunkBitmap> bitmaps)`.
- Cardinality-only (no result materialised): `static int andCardinality(a, b)`, `static int
  orCardinality(a, b)`, `static int xorCardinality(a, b)`, `static int andNotCardinality(a, b)`.
  These satisfy `orCardinality = |a| + |b| − andCardinality` and `xorCardinality = |a| + |b| −
  2·andCardinality`, `andNotCardinality = |a| − andCardinality`.
- Intersection tests: `static boolean intersects(a, b)`; instance `boolean intersects(long start,
  long end)` (true iff any present value lies in `[start, end)`; false when `end <= start`).
- Complemented union: `void orNot(ChunkBitmap other, long rangeEnd)` sets the receiver to `this ∪
  (complement of other within [0, rangeEnd))`. It throws `UnsupportedOperationException` if `other`
  is the same object as `this`. The static form is `static ChunkBitmap orNot(ChunkBitmap a,
  ChunkBitmap b, long rangeEnd)`.

`and`/`andNot`/`xor` never leave behind empty chunks (a chunk that becomes empty is dropped).

### 1.3 Rank, select, navigation, ranges

All positions use unsigned order; `rank` of the smallest present value is 1, and `select(0)` is the
smallest present value.

- `int rank(int x)` / `long rankLong(int x)` — number of present values `<= x` (unsigned).
- `int select(int j)` — the `j`-th smallest present value (0-based). Throws
  `IllegalArgumentException` if `j >= cardinality`.
- `int first()` / `int last()` — smallest / largest present value (unsigned). Throw
  `java.util.NoSuchElementException` when empty.
- `int firstSigned()` / `int lastSigned()` — smallest / largest by **signed** order. Throw
  `NoSuchElementException` when empty.
- `long nextValue(int from)` — smallest present value `>= from` (unsigned), or `-1` if none.
- `long previousValue(int from)` — largest present value `<= from` (unsigned), or `-1` if none.
- `long nextAbsentValue(int from)` — smallest **absent** value `>= from`. If every value from `from`
  up through the maximum unsigned value `0xFFFFFFFF` is present (so the next absent value would fall
  outside the 32-bit range), returns `-1`.
- `long previousAbsentValue(int from)` — largest **absent** value `<= from`.
  (These four return `long` so that the full unsigned value and the `-1` sentinel are representable.)
- `long rangeCardinality(long start, long end)` — number of present values in `[start, end)`; 0 when
  `start >= end`.
- `ChunkBitmap selectRange(long start, long end)` — a new bitmap containing exactly the present
  values in `[start, end)`; empty when `end <= start`.
- `ChunkBitmap limit(int maxcardinality)` — a new bitmap with the `maxcardinality` smallest present
  values (all of them if fewer).

### 1.4 Flip

- `void flip(int x)` — toggle a single value.
- `void flip(long start, long end)` — toggle every value in `[start, end)`.
- `static ChunkBitmap flip(ChunkBitmap bm, long start, long end)` — a new bitmap with `[start, end)`
  toggled; returns a clone of `bm` when `start >= end`.

### 1.5 Iteration and traversal

- `Iterator<Integer> iterator()` — boxed values in unsigned ascending order; its `remove()` throws
  `UnsupportedOperationException`.
- `int[] toArray()` — all values, unsigned ascending.
- `PeekableIntIterator getIntIterator()` — unsigned ascending.
- `PeekableIntIterator getReverseIntIterator()` — unsigned descending.
- `PeekableIntIterator getSignedIntIterator()` — **signed** ascending (so `Integer.MIN_VALUE` first).
- `BatchIterator getBatchIterator()` — bulk iteration (see §2).
- `void forEach(IntConsumer consumer)` — visit every value, unsigned ascending (see §2 for
  `IntConsumer`).
- `void forEachInRange(int start, int length, IntConsumer consumer)` — visit present values in the
  window `[start, start+length)`.
- `void forAllInRange(int uStart, int length, RelativeRangeConsumer consumer)` — report **every**
  position in the window `[uStart, uStart+length)` as present or absent (see §2). Throws
  `IllegalArgumentException` if `length < 0` or if the window would read past `0xFFFFFFFF`; `length
  == 0` is a no-op.

### 1.6 Optimization, equality, structure

- `boolean runOptimize()` — convert chunks to run form where that is smaller; returns `true` iff the
  bitmap contains at least one run-encoded chunk **after** the call (equivalently, it agrees with
  `hasRunCompression()` evaluated afterward). A chunk already in run form from a prior range operation
  (e.g. `add(long, long)` or `bitmapOfRange`) counts, so `runOptimize()` on such a bitmap still returns
  `true`. Never changes the set of values.
- `boolean removeRunCompression()` — undo run encoding; returns `true` if any run chunk was
  converted away.
- `boolean hasRunCompression()` — true iff any chunk is currently run-encoded.
- `void trim()` — release unused capacity; never changes the set.
- `ChunkBitmap clone()` — deep, independent copy.
- `boolean equals(Object o)` — value-based: two `ChunkBitmap`s are equal iff they contain the same
  set, regardless of run-compression state.
- `boolean contains(ChunkBitmap other)` — true iff `other` is a subset (the empty set is a subset of
  everything).
- `boolean isHammingSimilar(ChunkBitmap other, int tolerance)` — true iff the two sets differ in at
  most `tolerance` values (symmetric-difference size `<= tolerance`).
- `String toString()` — e.g. `{1,2,3,1000}`, values in unsigned ascending order, printed unsigned.

**Run encoding from range operations (a compression contract).** A chunk whose values form one or a
few contiguous runs is stored in *run form* (a list of `[start, length]` intervals) rather than as a
sorted array or a 2^16-bit bitmap, because that is far smaller. This run encoding is produced
**directly** by the range-based operations — `bitmapOfRange`, `add(long, long)`, `flip(long, long)`,
`orNot`, and range `remove` — not only by an explicit `runOptimize()`. Concretely, after
`ChunkBitmap.bitmapOfRange(0, 100)` (or `new ChunkBitmap(); b.add(0L, 1000L)`, or `flip(0L, 300L)` on
an empty bitmap), `hasRunCompression()` returns `true` and the bitmap serialises to a tiny run-encoded
form. Run encoding is likewise **preserved** through operations whose result is still run-representable:
range `remove` that punches a hole in a run (leaving two runs), `andNot`/`xor` that split a run, and
`selectRange` over run-encoded chunks all keep `hasRunCompression() == true`. This is observable via
`hasRunCompression()`, `serializedSizeInBytes()` (a range chunk serialises to a handful of bytes,
versus thousands for an array/bitmap chunk of the same cardinality), and the insights run-container
count (§10). The set of values is of course identical regardless of representation.

### 1.7 Serialization

`ChunkBitmap` serialises to a compact **portable** binary format (little-endian; described in §9)
that is stable and independent of the JDK. The same format is shared with the buffer-package classes
(§7), so a blob written by one deserialises in the other.

- `void serialize(java.io.DataOutput out)`.
- `void serialize(java.nio.ByteBuffer buffer)` — writes the same bytes; advances the buffer position
  by exactly `serializedSizeInBytes()`.
- `void deserialize(java.io.DataInput in)` — replaces the receiver's contents. Throws
  `java.io.IOException` if the input does not begin with a valid format cookie (see §9).
- `void deserialize(java.nio.ByteBuffer buffer)`.
- `int serializedSizeInBytes()` — exact number of bytes `serialize` writes.
- `static long maximumSerializedSize(long cardinality, long universeSize)` — a deterministic upper
  bound on the serialized size of any bitmap with the given cardinality over `[0, universeSize)`.
- `Boolean validate()` — structural self-check; returns `true` for a well-formed bitmap.

`getSizeInBytes()` / `getLongSizeInBytes()` return an in-memory size estimate (not necessarily equal
to the serialized size).

---

## 2. Iterator and callback interfaces (package `io.chunkbits`)

- `interface IntConsumer { void accept(int value); }` — receiver for `forEach`/`forEachInRange`.
- `interface IntIterator { boolean hasNext(); int next(); IntIterator clone(); }`.
- `interface PeekableIntIterator extends IntIterator`, adding:
  - `int peekNext()` — the value `next()` would return, without advancing.
  - `void advanceIfNeeded(int minval)` — skip forward so the next value is `>= minval` (unsigned);
    for a reverse iterator, skip so the next value is `<= minval`.
  - `PeekableIntIterator clone()`.
- `interface BatchIterator { int nextBatch(int[] buffer); boolean hasNext(); BatchIterator clone();
  void advanceIfNeeded(int target); }` — `nextBatch` fills `buffer` with up to `buffer.length` values
  in ascending order and returns how many were written (0 when exhausted).
- `interface RelativeRangeConsumer` — used by `forAllInRange`; all positions are **relative to the
  window start**:
  - `void acceptPresent(int relativePos)`
  - `void acceptAbsent(int relativePos)`
  - `void acceptAllPresent(int relativeFrom, int relativeTo)` — positions `[relativeFrom,
    relativeTo)` are all present.
  - `void acceptAllAbsent(int relativeFrom, int relativeTo)` — positions `[relativeFrom, relativeTo)`
    are all absent.

---

## 3. Aggregation (package `io.chunkbits`)

`FastAggregation` — a final class of static helpers combining many bitmaps:

- `static ChunkBitmap and(ChunkBitmap... bitmaps)` / `and(Iterator<...>)`.
- `static ChunkBitmap or(ChunkBitmap... bitmaps)` / `or(Iterator<...>)`.
- `static ChunkBitmap xor(ChunkBitmap... bitmaps)` / `xor(Iterator<...>)`.
- `static ChunkBitmap naive_or(ChunkBitmap... bitmaps)` — a straightforward left fold (result equals
  `or`).
- `static int andCardinality(ChunkBitmap... bitmaps)` — 0 for no arguments; the single bitmap's
  cardinality for one argument.
- `static int orCardinality(ChunkBitmap... bitmaps)`.
- `static boolean intersects(ChunkBitmap... bitmaps)` — false for no arguments.

`ParallelAggregation` — a class of static helpers that compute the same results as `FastAggregation`
but may use multiple threads internally:

- `static ChunkBitmap or(ChunkBitmap... bitmaps)`.
- `static ChunkBitmap xor(ChunkBitmap... bitmaps)`.

---

## 4. `io.chunkbits.ChunkBitmapWriter` — incremental construction

`interface ChunkBitmapWriter<T> extends java.util.function.Supplier<T>` builds a bitmap efficiently
from a stream of values. Obtain one from a fluent builder ("wizard"):

- `static Wizard<..., ChunkBitmap> ChunkBitmapWriter.writer()` — the builder for a heap `ChunkBitmap`
  writer.
- The builder exposes fluent, self-returning configuration methods including
  `constantMemory()`, `doPartialRadixSort()`, `optimiseForArrays()`, `optimiseForRuns()`,
  `runCompress(boolean)`, `expectedValuesPerContainer(int)`, `expectedDensity(double)`,
  `expectedRange(long, long)`, `initialCapacity(int)`, and `fastRank()`; and a terminal `get()`
  returning the `ChunkBitmapWriter`.
- `expectedValuesPerContainer(int)` and `initialCapacity(int)` throw `IllegalArgumentException` for a
  value `< 0` or `>= 65536`.

Writer methods:

- `void add(int value)`.
- `void add(long start, long end)`.
- `void addMany(int... values)`.
- `void flush()`.
- `T getUnderlying()`.
- `T get()` — flush, then return the underlying bitmap.
- `void reset()`.

A `constantMemory().doPartialRadixSort()` writer accepts values in any order and still yields the
correct, deduplicated, unsigned-sorted set after `flush()`.

---

## 5. `java.util.BitSet` interoperation (package `io.chunkbits`)

`ChunkBitSet extends java.util.BitSet` is a drop-in whose behaviour matches `java.util.BitSet`,
backed by a `ChunkBitmap`. It has a no-arg constructor `ChunkBitSet()` (an empty set) and overrides
at least: `set(int)`, `set(int, boolean)`, `set(int, int)`,
`set(int, int, boolean)`, `clear(int)`, `clear(int, int)`, `clear()`, `get(int)`, `get(int, int)`
(returns a new zero-based `ChunkBitSet` over the sub-range `[from, to)`), `nextSetBit(int)`,
`nextClearBit(int)`, `previousSetBit(int)`, `previousClearBit(int)`, `length()`, `size()`,
`isEmpty()`, `cardinality()`, `intersects(BitSet)`, `and/or/xor/andNot(BitSet)`, `flip(int)`,
`flip(int, int)`, `equals`, `hashCode`, `clone`, `stream`, `toString`, `toLongArray`, `toByteArray`.

Semantics follow `java.util.BitSet`: `length()` is `0` for an empty set else `(highest set bit) + 1`;
`size()` is `length()` rounded up to a multiple of 64 (and `0` only when empty); `nextSetBit` returns
`-1` when there is no higher set bit; `toString()` of the empty set is `{}`. `get(from, to)` returns
the bits of `[from, to)` shifted down so that bit `from` becomes bit 0. Boolean operations against
another `BitSet` follow the usual truth tables.

`BitSetUtil` — a final class of static conversions:

- `static ChunkBitmap bitmapOf(java.util.BitSet bitSet)`.
- `static ChunkBitmap bitmapOf(long[] words)` — words are interpreted little-endian, exactly as
  `java.util.BitSet.toLongArray()` produces them (bit `i` is word `i/64`, bit `i%64`).
- `static java.util.BitSet bitsetOf(ChunkBitmap bitmap)`.
- `static java.util.BitSet bitsetOfWithoutCopy(ChunkBitmap bitmap)`.
- `static long[] toLongArray(ChunkBitmap bitmap)` — empty bitmap → a zero-length array.
- `static byte[] toByteArray(ChunkBitmap bitmap)` — little-endian.
- `static boolean equals(java.util.BitSet bitset, ChunkBitmap bitmap)` — true iff they represent the
  same set of integers.
- `toLongArray`, `bitsetOf` and `bitsetOfWithoutCopy` throw `IllegalArgumentException` if the bitmap
  contains a value whose signed-`int` interpretation is negative (i.e. `last()` is negative).

---

## 6. `io.chunkbits.RangeIndex` — succinct range queries

`RangeIndex` is an immutable, succinct structure supporting range predicates over a sequence of
appended unsigned-`long` values. Each `add(value)` associates the value with the next **row index**
(starting at 0); a query returns a `ChunkBitmap` of the row indices whose stored value satisfies the
predicate. Duplicate values are stored independently (they occupy distinct rows).

Build:

- `static RangeIndex.Appender appender(long maxValue)` — start building; `maxValue` sizes the value
  slices.
- On `Appender`:
  - `void add(long value)` — append a value at the next row. Throws `IllegalArgumentException`
    (message ends `too large`) if the value has a set bit above the highest bit of `maxValue`.
  - `RangeIndex build()`.
  - `int serializedSizeInBytes()`.
  - `void serialize(java.nio.ByteBuffer buffer)` — little-endian.
- `static RangeIndex map(java.nio.ByteBuffer buffer)` — reconstruct a `RangeIndex` from a serialized
  buffer. A `build()` result and a `map(serialized)` result answer all queries identically. The
  round-trip is fully in-memory (`ByteBuffer.allocate` / `flip` / `map`).

Queries (unsigned comparisons; each returns a `ChunkBitmap` of matching row indices):

- `ChunkBitmap`-returning: `lt(long)`, `lte(long)`, `gt(long)`, `gte(long)`, `eq(long)`,
  `neq(long)`, `between(long min, long max)` — `between` is **inclusive** on both ends.
- Each predicate also has a `(long threshold, ChunkBitmap context)` overload that additionally
  intersects the result with `context` (result ⊆ context; `context` is not modified).
- Cardinality variants return `long`: `ltCardinality`, `lteCardinality`, `gtCardinality`,
  `gteCardinality`, `eqCardinality`, `neqCardinality`, `betweenCardinality`, each with the same plain
  and `(…, ChunkBitmap context)` overloads.

Semantics to respect: `lt(0)` is empty; `gte(0)` is all rows; `lt` and `gte` at the same threshold
are complements over the row set, as are `lte`/`gt`. Unsigned order means `-1L` is the largest
possible value, `Long.MIN_VALUE` sits just above `Long.MAX_VALUE`.

**Over-range thresholds saturate (they do not wrap).** A threshold larger than any storable value —
i.e. one with a set bit above the highest bit of `maxValue` — is treated as "bigger than everything",
not reduced modulo the value width. So for a `RangeIndex` built with `appender(255)` over rows whose
values are all `<= 255`: `lte(300)` and `lt(300)` return **all** rows, `gte(300)` and `gt(300)` return
**none**, `eq(300)` returns none, and `neq(300)` returns all rows. `between(min, max)` with an
over-range `max` degrades to `gte(min)`; with `min == 0` it degrades to `lte(max)`. An in-range but
inverted range (`min > max`, both storable) returns the empty set.

---

## 7. Memory-mappable variant (package `io.chunkbits.buffer`)

Two classes mirror the core API but allow a bitmap to be read directly out of a `ByteBuffer`
(including a memory-mapped one) without copying:

- `ImmutableChunkBitmap` — a read-only view. Constructor `ImmutableChunkBitmap(java.nio.ByteBuffer
  buffer)` reads a serialized bitmap starting at the buffer's current position **without** disturbing
  the caller's buffer position/limit. It exposes the full read API (`contains`, `getCardinality`,
  `rank`, `select`, `first`, `last`, `getIntIterator`, `getReverseIntIterator`, `toArray`, `equals`,
  `validate`, `serializedSizeInBytes`, the static `and/or/xor/andNot(ImmutableChunkBitmap,
  ImmutableChunkBitmap)` returning a `MutableChunkBitmap`, etc.). `static MutableChunkBitmap
  flip(ImmutableChunkBitmap bm, long start, long end)` throws a `RuntimeException` when `start >=
  end`.
- `MutableChunkBitmap extends ImmutableChunkBitmap` — the read/write, heap-resident form. It has a
  no-arg constructor `MutableChunkBitmap()` (an empty set) and mirrors
  `ChunkBitmap`'s mutating API: `bitmapOf(int...)`, `bitmapOfRange(long,long)`, `add`, `addN`,
  `remove`, `contains`, `flip`, `checkedAdd`, `checkedRemove`, `getCardinality`, `rank`, `select`,
  `first`, `last`, `toArray`, in-place and static `and/or/xor/andNot`, `runOptimize`, `clone`,
  `serialize(DataOutput)`, `serialize(ByteBuffer)`, `deserialize(DataInput)`, `deserialize(ByteBuffer)`,
  `serializedSizeInBytes`. `static MutableChunkBitmap flip(MutableChunkBitmap bm, long start, long
  end)` returns a clone when `start >= end` (it does **not** throw — this is the deliberate difference
  from `ImmutableChunkBitmap.flip`). `select(j)` with `j >= cardinality` throws
  `IllegalArgumentException`; `first()`/`last()` on empty throw `NoSuchElementException`.

The buffer package uses the **same serialization format** as the core (§9). Consequences the
implementation must honour: `MutableChunkBitmap` and `ChunkBitmap` built from the same values
serialize to **byte-identical** output (before and after `runOptimize`); a blob written by
`ChunkBitmap.serialize` can be read by `MutableChunkBitmap.deserialize` and by `new
ImmutableChunkBitmap(buffer)`, and vice-versa. Two bitmaps written back-to-back into one stream can be
read sequentially: `new ImmutableChunkBitmap(bb)` then `bb.position(bb.position() +
first.serializedSizeInBytes())` then `new ImmutableChunkBitmap(bb)` for the second.

`BufferFastAggregation` — static aggregation over `ImmutableChunkBitmap` operands, returning
`MutableChunkBitmap`: `and(ImmutableChunkBitmap...)`, `or(ImmutableChunkBitmap...)`,
`xor(ImmutableChunkBitmap...)` (and `Iterator` overloads).

---

## 8. 64-bit variants (package `io.chunkbits.longlong`)

Two classes extend the idea to 64-bit unsigned `long` keys. Both always order values unsigned by
default and share these iteration/consumer interfaces in this package:

- `interface LongConsumer { void accept(long value); }`
- `interface LongIterator { boolean hasNext(); long next(); LongIterator clone(); }`
- `interface PeekableLongIterator extends LongIterator` with `long peekNext()` and `void
  advanceIfNeeded(long minval)`.

### 8.1 `Chunk64Bitmap`

An always-unsigned 64-bit set (the high 48 bits select a chunk; the low 16 bits index a container).

- `Chunk64Bitmap()`, `static Chunk64Bitmap bitmapOf(long... values)`, `Chunk64Bitmap clone()`.
- `void addLong(long x)`, `void addInt(int x)` (adds the unsigned value of `x`), `void add(long...
  values)`.
- `void addRange(long start, long end)` — half-open; throws `IllegalArgumentException` if `end == 0`
  or `Long.compareUnsigned(start, end) >= 0`.
- `void removeLong(long x)`, `boolean contains(long x)`.
- `long getLongCardinality()`, `int getIntCardinality()` (throws `UnsupportedOperationException` if
  the cardinality exceeds `Integer.MAX_VALUE`), `boolean isEmpty()`, `void clear()`.
- `long rankLong(long x)`, `long select(long j)` (throws `IllegalArgumentException` if `j >=
  cardinality`), `long first()` / `long last()` (throw `NoSuchElementException` when empty).
- `PeekableLongIterator getLongIterator()` / `getReverseLongIterator()`; `long[] toArray()`;
  `Iterator<Long> iterator()` (its `remove()` throws `UnsupportedOperationException`); `void
  forEach(LongConsumer)`.
- `void flip(long x)` and `void flip(long start, long end)` (half-open range toggle).
- In-place `void and/or/xor/andNot(Chunk64Bitmap other)`; static `and/or/xor/andNot`; `static boolean
  intersects`; `static long andCardinality`. Self-ops behave as in §1.2.
- `boolean equals(Object)`, `int hashCode()`, `boolean runOptimize()`, `void trim()`.
- Serialization: `void serialize(DataOutput)` / `serialize(ByteBuffer)`; `void deserialize(DataInput)`
  / `deserialize(ByteBuffer)`; `long serializedSizeInBytes()`. This class uses its own compact
  format; a serialize→deserialize round-trip must reproduce the set exactly, including values that
  span the unsigned sign boundary. The two `serialize` overloads emit the **same bytes** (little-endian),
  so a blob written with `serialize(DataOutput)` reads back correctly via `deserialize(ByteBuffer)` and
  vice-versa, and `serialize(ByteBuffer)` advances the buffer position by exactly
  `serializedSizeInBytes()`.

### 8.2 `Chunk64NavigableMap`

A 64-bit set backed by a navigable map keyed on the high 32 bits, supporting both unsigned and signed
ordering and two serialization formats.

- Constructors: `Chunk64NavigableMap()` (unsigned), `Chunk64NavigableMap(boolean signedLongs)`, and
  overloads additionally taking `boolean cacheCardinalities`. When `signedLongs` is true, iteration /
  `select` / `rank` follow signed order (`-1 < 0`); when false (default), unsigned order.
- `static Chunk64NavigableMap bitmapOf(long... values)`.
- The mutation/query API mirrors §8.1: `addLong`, `addInt`, `add(long...)`, `addRange(long, long)`
  (same exception rule, evaluated with the map's ordering), `removeLong`, `contains`,
  `getLongCardinality`, `getIntCardinality`, `isEmpty`, `clear`, `rankLong`, `select` (out-of-range →
  `IllegalArgumentException`), `first` / `last` (empty → `NoSuchElementException`), `flip(long)` (no
  range-flip overload here), in-place and static `and/or/xor/andNot`, `LongIterator
  getLongIterator()` / `getReverseLongIterator()`, `toArray`, `equals`, `hashCode`.
- Serialization is controlled by a mutable static field:
  - `static final int SERIALIZATION_MODE_LEGACY = 0;`
  - `static final int SERIALIZATION_MODE_PORTABLE = 1;`
  - `static int SERIALIZATION_MODE = SERIALIZATION_MODE_LEGACY;` (default).
  - `void serialize(DataOutput)` / `void deserialize(DataInput)` dispatch on the current
    `SERIALIZATION_MODE`; `long serializedSizeInBytes()` reflects it.
  - **Legacy** mode: header `writeBoolean(signedLongs)`, `writeInt(numberOfHighParts)`, then for each
    high part `writeInt(high)` followed by the 32-bit bitmap (§9) of the low parts. Because the
    signedness flag is stored in the header, `deserialize` **restores it**: deserialising a
    legacy-serialised signed map into a freshly-constructed (default, unsigned) map re-establishes
    signed ordering (e.g. a signed map of `{-1, 1}` round-trips so that `select(0) == -1`,
    `select(1) == 1`).
  - **Portable** mode: cross-implementation format — header `writeLong(numberOfHighParts)` in
    **little-endian** (`Long.reverseBytes`), then for each high part `writeInt(high)` in little-endian
    (`Integer.reverseBytes`) followed by the standard 32-bit bitmap (§9). Deserialising in portable
    mode always yields an unsigned-ordered map. The portable format is byte-compatible with other
    implementations of this data structure.

---

## 9. The 32-bit serialization format (portable)

Both the core and buffer 32-bit bitmaps, and the per-high-part bitmaps inside the 64-bit portable
format, use this little-endian layout. A bitmap is a sequence of **chunks** ordered by ascending
unsigned 16-bit key; each chunk stores the low 16 bits of its values as either an array, a bitmap, or
a run list.

- If **no chunk is run-encoded**, the stream is:
  1. cookie `int` = `12346`;
  2. `int` chunk count `n`;
  3. for each chunk: `short` key, `short` (cardinality − 1) — the "keycard" pairs, all `n` of them;
  4. an offset header: `n` `int`s giving the byte offset of each chunk's data;
  5. each chunk's data: an **array** chunk (cardinality ≤ 4096) is `cardinality` `short`s (the sorted
     low 16 bits); a **bitmap** chunk (cardinality > 4096) is 1024 `long`s (8192 bytes, a 2¹⁶-bit
     bitmap).
- If **any chunk is run-encoded**, the stream is:
  1. cookie: the low 16 bits are `12347` and the high 16 bits are `(n − 1)`, written as one `int`;
  2. a run-flag bitset of `ceil(n / 8)` bytes (bit *i* set ⇒ chunk *i* is run-encoded);
  3. the `n` keycard pairs (`short` key, `short` cardinality − 1);
  4. an offset header of `n` `int`s **only when** `n >= 4` (omitted for `n < 4`);
  5. each chunk's data: array and bitmap chunks as above; a **run** chunk is a `short` run-count
     followed by that many `(short start, short length−1)` pairs (each pair encodes the run of values
     `[start, start+length]`).

All multi-byte integers are little-endian. `serialize(ByteBuffer)` writes the identical byte sequence
regardless of the buffer's byte order. `deserialize` throws `IOException` (wrapping an
invalid-format condition) if the leading cookie is neither `12346` nor a value whose low 16 bits are
`12347`.

`maximumSerializedSize(cardinality, universeSize)` returns the standard closed-form bound: roughly
`8 + 9 * ((universeSize + 65535) / 65536) + 2 * cardinality` bytes.

---

## 10. `io.chunkbits.insights` — representation analysis

`BitmapAnalyser` inspects the internal chunk-type breakdown of a bitmap:

- `static BitmapStatistics analyse(ChunkBitmap bitmap)`.
- `static BitmapStatistics analyse(java.util.Collection<? extends ChunkBitmap> bitmaps)` — the
  element-wise sum of the individual analyses.

`BitmapStatistics` reports:

- `long containerCount()` — total number of chunks.
- `long getBitmapContainerCount()` — number of bitmap-form chunks.
- `long getRunContainerCount()` — number of run-form chunks.
- `long getBitmapsCount()` — number of bitmaps analysed (1 for the single-bitmap overload).
- `ArrayContainersStats getArrayContainersStats()` — with `long getContainersCount()` (number of
  array-form chunks), `long getCardinalitySum()` (total values held in array-form chunks), and `long
  averageCardinality()`.

Because chunk type follows the smallest-representation rule, a small sparse set analyses to a single
array chunk; a run-optimised contiguous range to a single run chunk; and a dense (> 4096 values in one
2¹⁶ window) non-contiguous set to a single bitmap chunk.
