#!/bin/bash
# Offline grading for the jenetics task.
#
# jenetics core has ZERO external deps, so there is NO baked-jar classpath -- the agent's compiled
# classes in /app/out are the only classpath. The agent implements the library under /app/src and
# provides /app/setup.sh that compiles it into /app/out. This script builds the agent's code, then
# compiles + runs each Java test driver against it to produce per-test JSON, and converts that to
# CTRF. Uses only the JDK + python3 in the per-task image -- no pip, no network.
#
# No `set -e`: every stage must run so a CTRF report is always produced (a broken submission yields
# an all-fail report with the denominator preserved, i.e. reward 0, rather than a grader error).
#
# Independently-compiled drivers, split into SMALL self-contained per-capability files so a compile
# failure (one off-signature symbol) only zeroes its own small cluster instead of a whole subsystem:
#   GeneHarness                 -- genes + chromosomes + genotype (IntegerGene/DoubleGene/BitChromosome/...)
#   -- alterers (split by operator family) --
#   MutatorHarness              -- Mutator / SwapMutator / GaussianMutator
#   PointCrossoverHarness       -- SinglePointCrossover / MultiPointCrossover
#   UniformPmxHarness           -- UniformCrossover / PartiallyMatchedCrossover
#   NumericRecombinatorHarness  -- MeanAlterer / LineCrossover / IntermediateCrossover / CombineAlterer
#   CompositeAltererHarness     -- Alterer.of(...) composite / PartialAlterer.of(...)
#   -- selectors (split by selector family) --
#   TournamentRouletteHarness   -- Tournament / RouletteWheel / StochasticUniversal / MonteCarlo
#   TruncationEliteHarness      -- Truncation / Elite (deterministic)
#   RankSelectorHarness         -- LinearRank / ExponentialRank / Boltzmann
#   -- engine (split so config-getters + statistics are isolated) --
#   ConvergenceHarness          -- OneMax / numeric max / min / sphere convergence
#   InvariantsHarness           -- config getters + generation/population/valid/monotonic invariants
#   CodecHarness                -- Codecs.ofScalar / ofVector round-trips
#   EngineStatisticsHarness     -- EvolutionStatistics bookkeeping (isolated fragile surface)
#   -- stat + util --
#   MomentStatHarness           -- io.evolab.stat moments + MinMax/Quantile/Summary + ranges
#   SeqHarness                  -- io.evolab.util ISeq/MSeq/Seq (fragile toString(String)/toISeq idioms)

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

mkdir -p /logs/verifier /tmp/h

# 1. Build the agent's jenetics source (offline) via the setup.sh it wrote (or solve.sh for GT).
# /app/out is wiped first so the graded classpath reflects ONLY the delivered /app/src: a class left
# over from the agent's dev loop whose source no longer exists (e.g. a renamed/relocated public type)
# would otherwise stay on the classpath and can make a simple name ambiguous, compile-wiping drivers.
rm -rf /app/out
bash ./setup.sh 2>/logs/verifier/setup.log || true

# 2-3. Compile + run each driver INDEPENDENTLY against the agent's classes (no external jars).
: > /logs/verifier/jen_results.jsonl
for DRIVER in GeneHarness \
    MutatorHarness PointCrossoverHarness UniformPmxHarness NumericRecombinatorHarness CompositeAltererHarness \
    TournamentRouletteHarness TruncationEliteHarness RankSelectorHarness \
    ConvergenceHarness InvariantsHarness CodecHarness EngineStatisticsHarness \
    MomentStatHarness SeqHarness; do
    [ -f "/tests/$DRIVER.java" ] || continue
    rm -rf /tmp/h && mkdir -p /tmp/h
    if javac -cp "/app/out" -d /tmp/h /tests/Runner.java "/tests/$DRIVER.java" 2>"/logs/verifier/${DRIVER}_compile.log"; then
        EXPECTED_TSV=/tests/expected.tsv java -cp "/tmp/h:/app/out" "$DRIVER" \
            >> /logs/verifier/jen_results.jsonl 2>"/logs/verifier/${DRIVER}_run.log" || true
    fi
done

# 4. Convert results to CTRF (canonical case list = names in /tests/expected.tsv; missing -> failed).
python3 /tests/make_ctrf.py /logs/verifier/jen_results.jsonl /logs/verifier/ctrf.json /tests/expected.tsv \
    >/logs/verifier/ctrf.log 2>&1 || true

# 5. Reward: 1 IFF every canonical case passed (no failures, no skips, no other), else 0.
CANONICAL_TOTAL=79
python3 - "$CANONICAL_TOTAL" <<'PY' > /logs/verifier/reward.txt 2>/dev/null || echo 0 > /logs/verifier/reward.txt
import json, sys
total = int(sys.argv[1])
try:
    s = json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    ok = (int(s.get('passed', 0)) == total and int(s.get('failed', 0)) == 0
          and int(s.get('other', 0)) == 0 and int(s.get('skipped', 0)) == 0
          and int(s.get('pending', 0)) == 0)
except Exception:
    ok = False
print(1 if ok else 0)
PY
