# DNA Chisel

Build `dnachisel`, a Python library for optimizing DNA sequences with respect to constraints and objectives.

When designing synthetic genes for lab work, there are many constraints to juggle simultaneously — avoid certain enzyme sites so cloning works, keep GC content balanced so synthesis succeeds, optimize codons for the target organism so the protein expresses well. DNA Chisel automates this.

A user defines a problem by giving it a DNA sequence, a list of hard constraints (must be satisfied), and optional optimization objectives (nice to have, maximize their score). The library solves constraints first by finding and fixing every violation through targeted local mutations, then optimizes objectives by tweaking the sequence to maximize objective scores without breaking any constraints. It uses exhaustive search for small local mutation spaces and random guided search for larger ones.

The library comes with ~20 built-in specification classes covering the most common needs in gene design: avoiding restriction enzyme sites, controlling GC content, preserving protein translation, optimizing codon usage for different organisms, avoiding hairpin structures, ensuring sequence uniqueness, controlling melting temperature, and more. Any specification can serve as either a hard constraint or a soft objective. The library also supports circular DNA, GenBank I/O with specification annotations, and a command-line interface.

## Dependencies

The environment is **offline** — there is no network access, and all required dependencies are
**already installed**. Do **not** attempt to install anything (no `pip install`, no network
downloads); the project is built and installed for you by a `setup.sh` that runs fully offline.

The following Python packages are pre-installed and available for import: `numpy`, `biopython`,
`proglog`, `docopt`, `flametree`, `python_codon_tables`, `primer3-py`.

## Imports

All public classes and functions below are importable from the top-level `dnachisel` package unless stated otherwise. Example: `from dnachisel import DnaOptimizationProblem, AvoidPattern, translate`.

The function `gc_content` is importable from `dnachisel.biotools`.

## Core API

### DnaOptimizationProblem

The central class. Construct with:

```python
problem = DnaOptimizationProblem(
    sequence,            # string of ATGC (uppercase)
    constraints=None,    # list of Specification objects
    objectives=None,     # list of Specification objects
    logger="bar",        # "bar" for progress bar, None for silent
    mutation_space=None, # usually left as None (auto-computed)
)
```

Key methods:

- `resolve_constraints(final_check=True)` — Modify the sequence until all constraints pass. Raises `NoSolutionError` if any constraint cannot be satisfied (e.g., a breach in a frozen region). When `final_check=True`, verifies all constraints still pass after resolution (resolving one can sometimes undo another).
- `optimize()` — Maximize total objective score while keeping all constraints satisfied. Skips objectives that are passive or have zero boost.
- `all_constraints_pass(autopass=True)` — Returns `True` if every constraint's evaluation score is >= 0. When `autopass=True`, constraints enforced by nucleotide restrictions are assumed to pass.
- `constraints_evaluations(autopass=True)` — Returns an iterable of `SpecEvaluation` objects, one per constraint.
- `objectives_evaluations()` — Returns an iterable of `SpecEvaluation` objects, one per objective.
- `objective_scores_sum()` — Sum of all objective scores weighted by their boost.
- `constraints_text_summary()` — Human-readable text. Contains "SUCCESS" when all pass, "FAIL" for failures. Each evaluation is formatted with PASS/FAIL status and the specification label.
- `objectives_text_summary()` — Human-readable text. Contains "TOTAL OBJECTIVES SCORE" with the summed score.
- `number_of_edits()` — Count of nucleotide positions that differ between the current and original sequence.
- `sequence` — Current sequence (string, mutable during solve/optimize).
- `sequence_before` — The original sequence at problem creation.
- `constraints` — List of constraint Specification objects.
- `objectives` — List of objective Specification objects.
- `mutation_space` — The `MutationSpace` object. Has a `space_size` property (number of possible variants).

#### from_record (classmethod)

```python
problem = DnaOptimizationProblem.from_record(record, logger="bar")
```

Creates a problem from a Biopython `SeqRecord` or a path to a GenBank file. Parses features of type `misc_feature` whose label qualifier starts with `@` (constraint) or `~` (objective). The label format is `@SpecName(arg1, key=value)` or `~SpecName(arg1)`. The feature's genomic location becomes the specification's location.

Specifications are looked up by class name or `shorthand_name` in a default dict. Multiple specifications on a single feature can be joined with `&`.

#### to_record

```python
record = problem.to_record(
    filepath=None,              # if given, writes GenBank file
    with_sequence_edits=False,  # annotate each nucleotide change as a feature
    with_constraints=True,      # include constraint annotations
    with_objectives=True,       # include objective annotations
)
```

Returns a Biopython `SeqRecord` of the current sequence, optionally annotated with constraints, objectives, and edit locations. If `filepath` is provided, writes the record as GenBank instead of returning it.

### CircularDnaOptimizationProblem

Same interface as `DnaOptimizationProblem` but handles circular DNA. Constraints that span the origin (position 0 wrapping to the end) are correctly handled. The resulting `sequence` has the same length as the input.

### NoSolutionError

Exception raised when `resolve_constraints()` cannot find a solution — typically because a constraint breach is in a region with no mutable positions, or random search exhausted its iteration limit. Carries `location`, `message`, and `problem` attributes.

## Specifications

All specifications can be used as either constraints or objectives. Each has a `boost` parameter (default 1.0) for weighting in objective scoring, and a `location` parameter (tuple `(start, end)` or `Location` object, default covers full sequence).

Base class methods available on all specifications:
- `as_passive_objective()` — Returns a copy with `optimize_passively=True`. A passive objective is not actively optimized in its own pass, but its score is considered when optimizing other objectives.
- `copy_with_changes(**kwargs)` — Returns a shallow copy with the given attributes overridden (e.g., `spec.copy_with_changes(boost=10)`).

A specification's `evaluate(problem)` method returns a `SpecEvaluation` with:
- `score` — float, >= 0 means passing
- `passes` — bool (`score >= 0`)
- `locations` — list of breach/suboptimal `Location` objects
- `message` — human-readable string

### AvoidPattern

```python
AvoidPattern(pattern, location=None, strand="from_location", boost=1.0)
```

Prevents a sequence pattern from appearing. The `pattern` argument is a string parsed by `SequencePattern.from_string()` — it can be an enzyme name (`"BsaI_site"`), a DNA/IUPAC sequence (`"ATTGCC"`), a homopolymer (`"7xA"`), a repeated k-mer (`"3x3mer"`), or a regex. Checks both strands by default; the `strand` argument selects which strand(s) are checked, using the `Location` strand convention (`1` the forward strand only, `-1` the reverse strand only, `0` both).

Shorthand name: `"no"`

### AvoidHairpins

```python
AvoidHairpins(stem_size=20, hairpin_window=200, location=None, boost=1.0)
```

Avoids hairpin structures — regions where a subsequence of length `stem_size` has its reverse complement within `hairpin_window` nucleotides.

### AvoidStopCodons

```python
AvoidStopCodons(genetic_table="Standard", location=None, boost=1.0)
```

Prevents any in-frame stop codon (TAA, TAG, TGA for Standard table) within the specified codon-aligned location. The location length must be a multiple of 3.

### AvoidChanges

```python
AvoidChanges(max_edits=0, location=None, indices=None, boost=1.0)
```

Preserves the original sequence at the specified location or at specific `indices`. With `max_edits=0`, the region is completely frozen — no changes are possible there.

Shorthand name: `"keep"`

### EnforceGCContent

```python
EnforceGCContent(mini=0, maxi=1.0, target=None, window=None, location=None, boost=1.0)
```

Enforces GC content (proportion of G+C nucleotides) within `[mini, maxi]`. If `window` is set, every sliding window of that size must satisfy the bounds. If `target` is set (and mini/maxi are defaults), optimizes toward the target GC.

Has a `string_to_parameters(string)` classmethod that parses annotation strings and returns the 4-tuple `(mini, maxi, target, window)`. `mini`, `maxi`, and `target` are proportions in `[0, 1]` (the percentage divided by 100), or `None` when that bound/target is absent. `window` is the integer base-pair count, or `None` when no window is given. A range string of the form `"<lo>-<hi>%"` sets `mini`/`maxi` and leaves `target` as `None`; a single-value string `"<v>%"` is parsed as a `target` (with `mini`/`maxi` left `None`); an optional `/<n>bp` suffix sets `window`.

Shorthand name: `"gc"`

### EnforceTranslation

```python
EnforceTranslation(genetic_table="default", location=None, boost=1.0)
```

Preserves the amino-acid translation of a coding region. The location must be codon-aligned (length divisible by 3); the length is validated eagerly, so a non-codon-aligned location raises `ValueError` no later than `DnaOptimizationProblem` construction — never deferred to `resolve_constraints()`. Only synonymous codon changes are allowed. Supports reverse-strand locations (`Location(start, end, strand=-1)`), in which case the reverse complement of the subsequence is translated.

Shorthand name: `"cds"`

### EnforcePatternOccurence

```python
EnforcePatternOccurence(pattern=None, occurences=1, location=None, strand="from_location", boost=1.0)
```

Enforces exactly `occurences` instances of a pattern. Can insert a pattern (if 0 exist and 1 is required) or remove extras.

Shorthand name: `"insert"`

### EnforceSequence

```python
EnforceSequence(sequence=None, location=None, boost=1.0)
```

Fixes specific nucleotides at a location. The `sequence` can use IUPAC notation.

Shorthand name: `"sequence"`

### EnforceChoice

```python
EnforceChoice(choices=None, location=None, boost=1.0)
```

Restricts the sequence at a location to one of several provided alternative strings.

Shorthand name: `"choice"`

### EnforceChanges

```python
EnforceChanges(minimum=None, location=None, boost=1.0)
```

Requires at least `minimum` nucleotide changes from the original sequence within the location.

Shorthand name: `"change"`

### EnforceMeltingTemperature

```python
EnforceMeltingTemperature(mini=None, maxi=None, target=None, location=None, boost=1.0)
```

Enforces that the melting temperature (Tm) of the subsequence falls within `[mini, maxi]`. Uses `primer3.calc_tm()` for Tm calculation. Typically used on primer-length regions (20-30 bp).

Shorthand name: `"tm"`

### EnforceRegionsCompatibility

```python
EnforceRegionsCompatibility(locations, compatibility_condition, condition_label="", boost=1.0)
```

Ensures that all pairs of specified regions satisfy a compatibility condition. The `locations` is a list of `(start, end)` tuples. The `compatibility_condition` is a callable `(location1, location2, problem) -> bool` where `location1` and `location2` are `Location` objects — use `location.extract_sequence(problem.sequence)` to get the actual subsequences for comparison.

### EnforceTerminalGCContent

```python
EnforceTerminalGCContent(window_size, mini=0, maxi=1, boost=1.0)
```

Enforces GC content bounds at both the left-terminal and right-terminal windows of the sequence.

### SequenceLengthBounds

```python
SequenceLengthBounds(min_length=0, max_length=None, boost=1.0)
```

Validates that the sequence length falls within the given bounds. Evaluation only — does not modify the sequence.

### UniquifyAllKmers

```python
UniquifyAllKmers(k, location=None, include_reverse_complement=True, boost=1.0)
```

As a constraint, ensures all k-mers of length `k` within the location are unique (no duplicates). As an objective, maximizes the number of unique k-mers. Checks reverse complements by default.

Shorthand name: `"all_unique_kmers"`

### AllowPrimer

```python
AllowPrimer(location=None, tmin=50, tmax=70, boost=1.0)
```

Composite specification (a `SpecificationSet`) that bundles multiple requirements to make a region primer-compatible: unique k-mers for specificity, melting temperature within `[tmin, tmax]`, and avoidance of repeated short patterns.

Shorthand name: `"primer"`

### Codon Optimization

#### CodonOptimize (factory function)

```python
CodonOptimize(species=None, method="use_best_codon", location=None,
              codon_usage_table=None, boost=1.0)
```

Returns a codon optimization specification. The `species` names a codon usage table from the `python_codon_tables` package (e.g., `"e_coli"`, `"h_sapiens"`). The `method` selects the strategy:

- `"use_best_codon"` — Replace each codon with the most frequent synonymous codon (maximizes Codon Adaptation Index).
- `"match_codon_usage"` — Adjust codon frequencies to match the target species' overall codon usage profile.
- `"harmonize_rca"` — Harmonize Relative Codon Adaptiveness between original and target species. Requires `original_species` parameter (e.g., `CodonOptimize(species="e_coli", method="harmonize_rca", original_species="h_sapiens")`). Each codon is replaced so its relative frequency in the target species matches its relative frequency in the original species.

Used as an objective, the score represents how close the current codons are to optimal; it is `<= 0`. For `"use_best_codon"` the score is exactly `0` only when every codon is already the most-frequent synonymous codon, so optimizing a coding sequence under that method (with a matching `EnforceTranslation` constraint and no competing constraints) drives `objective_scores_sum()` to `0`. The `"match_codon_usage"` optimum is a (negative) best-effort match to the usage profile rather than `0`. Can also be used as a constraint.

#### AvoidRareCodons

```python
AvoidRareCodons(min_frequency, species=None, location=None, boost=1.0)
```

Avoids codons whose usage frequency falls below `min_frequency` (e.g., 0.1 = 10%). A milder form of codon optimization.

Shorthand name: `"no_rare_codons"`

## Sequence Patterns

Patterns represent motifs to search for in DNA sequences. All pattern classes support `find_matches(sequence, location=None)` (returns `Location` objects) and `find_matches_in_string(sequence)` (returns `(start, end, strand)` tuples).

### SequencePattern

Base class for all patterns. Has a `from_string(string)` classmethod that parses a string and returns the appropriate subclass:

- `"BsaI_site"` → `EnzymeSitePattern("BsaI")`
- `"7xA"` → `HomopolymerPattern("A", 7)`
- `"3x3mer"` → `RepeatedKmerPattern(3, 3)`
- `"ATTGCC"` → `DnaNotationPattern("ATTGCC")`

### DnaNotationPattern

Pattern for DNA/IUPAC sequences. Searches both strands.

### EnzymeSitePattern

Pattern for restriction enzyme recognition sites. Constructed with the enzyme name (e.g., `"BsaI"`).

### HomopolymerPattern

Pattern for runs of a single nucleotide. `HomopolymerPattern("A", 7)` matches `AAAAAAA`. Parsed from strings like `"7xA"`.

### RepeatedKmerPattern

Pattern for tandem repeats of short k-mers. `RepeatedKmerPattern(3, 3)` matches any 3-mer repeated 3 times (e.g., `ATGATGATG`). Parsed from strings like `"3x3mer"`.

### MotifPssmPattern

Position-Specific Scoring Matrix pattern for probabilistic motif matching.

```python
MotifPssmPattern.from_sequences(sequences, name="unnamed",
                                 pseudocounts=None, threshold=None)
```

Creates a PSSM from a list of aligned DNA sequences of equal length. The `threshold` sets the minimum PSSM score for a match.

## Biotools

Utility functions for DNA sequence manipulation.

### Sequence operations

- `translate(dna_sequence, table="Standard")` — Translate DNA to amino acids. Returns a string like `"MKV"`.
- `reverse_complement(sequence)` — Return the reverse complement (`"ATGC"` → `"GCAT"`).
- `complement(dna_sequence)` — Return the complement (`"ATGC"` → `"TACG"`).
- `reverse_translate(protein_sequence, table="Standard")` — Return a DNA sequence encoding the given protein.
- `gc_content(sequence, window_size=None)` — Compute GC proportion (0.0 to 1.0). Importable from `dnachisel.biotools`.

### Random sequences

- `random_dna_sequence(length, seed=None)` — Generate a random ATGC string.
- `random_protein_sequence(length, seed=None)` — Generate a random protein sequence of exactly `length` characters, starting with M, ending with *, and with `length - 2` random amino acids in between.
- `random_compatible_dna_sequence(sequence_length, constraints, seed=None, logger="bar")` — Generate a random sequence that satisfies the given constraints.

### Sequence comparison

- `sequences_differences(seq1, seq2)` — Count of positions where two same-length sequences differ.
- `sequences_differences_segments(seq1, seq2)` — List of `(start, end)` tuples marking contiguous differing regions.

### Restriction enzymes

- `list_common_enzymes(site_length=(6,))` — Return names of restriction enzymes matching the given site length and other filters. Uses BioPython's `Restriction` module.

### GenBank I/O and record manipulation

- `load_record(filepath, linear=True, file_format="auto")` — Load a FASTA/GenBank file as a BioPython `SeqRecord`.
- `write_record(record, target, file_format="genbank")` — Write a `SeqRecord` to a file.
- `sequence_to_biopython_record(sequence, id="<unknown id>")` — Create a `SeqRecord` from a plain sequence string.
- `change_biopython_record_sequence(record, new_seq)` — Return a copy of the record with its sequence replaced by `new_seq`.
- `annotate_record(seqrecord, location="full", feature_type="misc_feature", **qualifiers)` — Add a feature annotation to a record in place.
- `annotate_differences(record, reference)` — Return a new record annotated with features at each position where `record` differs from `reference`.
- `annotate_pattern_occurrences(record, pattern)` — Return a new record annotated with features at each occurrence of a `SequencePattern`.

## Location

```python
Location(start, end, strand=0)
```

Represents a genomic interval. Uses Python slicing convention: `Location(5, 10)` covers positions 5-9. Strand is 1 (sense), -1 (antisense), or 0 (unspecified).

Key methods:
- `overlap_region(other)` — Returns a `Location` of the overlap, or `None`.
- `extended(extension_length, lower_limit=0, upper_limit=None)` — Extend both sides.
- `extract_sequence(sequence)` — Extract the subsequence; reverse-complements if strand is -1.
- `to_tuple()` — Returns `(start, end, strand)`.
- `merge_overlapping_locations(locations)` (static) — Merge a sorted list of overlapping locations.
- `from_data(location_data)` (static) — Convert tuple, BioPython `FeatureLocation`, or `Location` to a `Location`.
- Supports `+`, `-` (shift), `len()`, comparison, and hashing.

## CLI

The package installs a `dnachisel` command:

```
dnachisel <source> <target> [--circular] [--mute]
```

Where `source` is a GenBank file with specification annotations and `target` is an output GenBank file (`.gb`) or a report directory/zip. The `--mute` flag suppresses console output. Uses `docopt` for argument parsing.

## MutationSpace

The `MutationSpace` represents the set of allowed mutations at each position, built automatically during `DnaOptimizationProblem` initialization from the constraints. Accessible via `problem.mutation_space`. Has a `space_size` property giving the total number of possible sequence variants.

## SpecEvaluation

The result of evaluating a specification. Has `score` (float), `passes` (bool, `score >= 0`), `is_optimal` (bool), `locations` (list of `Location`), `message` (string), and `specification` (the spec that was evaluated).

## Setup

The package must be installable via `pip install -e .` with a `pyproject.toml` that declares the dependencies listed above and registers the `dnachisel` CLI entry point under `[project.scripts]`. Use the standard `setuptools` build backend (`build-backend = "setuptools.build_meta"`) with a static `version`.

The environment is offline, so the install must succeed without any network access — the build backend and all runtime dependencies are pre-installed. Create a `setup.sh` file containing: `pip install -e . --no-build-isolation`
