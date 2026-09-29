"""Tests for the dnachisel DNA sequence optimization library.

Each test exercises a user-facing workflow through the public API,
verifying the library correctly optimizes DNA sequences under
constraints and objectives.
"""

import os
import tempfile
import subprocess
import numpy
import python_codon_tables
from itertools import combinations

import pytest
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation

from dnachisel import (
    DnaOptimizationProblem,
    CircularDnaOptimizationProblem,
    NoSolutionError,
    Location,
    AvoidPattern,
    AvoidChanges,
    AvoidHairpins,
    AvoidStopCodons,
    AvoidRareCodons,
    AllowPrimer,
    UniquifyAllKmers,
    EnforceGCContent,
    EnforceTranslation,
    EnforcePatternOccurence,
    EnforceSequence,
    EnforceChoice,
    EnforceChanges,
    EnforceMeltingTemperature,
    EnforceRegionsCompatibility,
    EnforceTerminalGCContent,
    SequenceLengthBounds,
    CodonOptimize,
    SequencePattern,
    DnaNotationPattern,
    EnzymeSitePattern,
    HomopolymerPattern,
    RepeatedKmerPattern,
    MotifPssmPattern,
    random_dna_sequence,
    random_protein_sequence,
    translate,
    reverse_complement,
    reverse_translate,
    complement,
    sequences_differences,
    sequences_differences_segments,
    list_common_enzymes,
    load_record,
    write_record,
    sequence_to_biopython_record,
    annotate_record,
    annotate_differences,
    annotate_pattern_occurrences,
    change_biopython_record_sequence,
    random_compatible_dna_sequence,
)
from dnachisel.biotools import gc_content


# ============================================================================
# Group 1: Core Optimization Engine
# ============================================================================


def test_multi_constraint_resolution():
    """User removes enzyme sites, enforces GC content, and preserves protein
    translation in a single optimization pass on a 2000bp sequence."""
    numpy.random.seed(42)

    protein = "MKVLLKASGRFYWELD"
    cds = reverse_translate(protein)
    prefix = random_dna_sequence(900, seed=42)
    suffix = random_dna_sequence(900, seed=43)
    sequence = prefix + "GGTCTC" + cds + "GGTCTC" + suffix
    cds_start = len(prefix) + 6
    cds_end = cds_start + len(cds)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            AvoidPattern("BsaI_site"),
            EnforceGCContent(mini=0.3, maxi=0.7, window=50),
            EnforceTranslation(location=(cds_start, cds_end)),
        ],
        logger=None,
    )

    evals_before = problem.constraints_evaluations()
    failing_before = [e for e in evals_before if not e.passes]
    assert len(failing_before) > 0
    for e in failing_before:
        assert e.locations is not None
        assert len(e.locations) > 0

    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    evals_after = problem.constraints_evaluations()
    assert len(list(evals_after)) == 3
    for e in evals_after:
        assert e.passes
        assert e.score >= 0

    assert "GGTCTC" not in problem.sequence
    assert "GAGACC" not in problem.sequence

    result_protein = translate(problem.sequence[cds_start:cds_end])
    assert result_protein.rstrip("*") == protein

    seq = problem.sequence
    for i in range(0, len(seq) - 50 + 1):
        wgc = gc_content(seq[i : i + 50])
        assert 0.3 <= wgc <= 0.7, f"GC={wgc:.3f} at position {i}"


def test_constraint_and_objective_optimization():
    """User resolves constraints then maximizes codon usage as an objective,
    verifying score improvement and translation preservation."""
    numpy.random.seed(100)

    protein = "MKWVTFISLLLLFSSAYS"
    cds = reverse_translate(protein)
    sequence = random_dna_sequence(200, seed=100) + cds + random_dna_sequence(200, seed=101)
    cds_start = 200
    cds_end = 200 + len(cds)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceTranslation(location=(cds_start, cds_end)),
            EnforceGCContent(mini=0.3, maxi=0.7, window=50),
        ],
        objectives=[
            CodonOptimize(species="e_coli", location=(cds_start, cds_end)),
        ],
        logger=None,
    )

    score_before = problem.objective_scores_sum()
    problem.resolve_constraints()
    problem.optimize()
    score_after = problem.objective_scores_sum()

    assert problem.all_constraints_pass()
    assert score_after >= score_before
    result_protein = translate(problem.sequence[cds_start:cds_end])
    assert result_protein.rstrip("*") == protein
    assert problem.number_of_edits() > 0


def test_no_solution_error_modes():
    """User encounters NoSolutionError when constraints are unsolvable due to
    frozen regions or contradictory requirements."""
    numpy.random.seed(200)

    with pytest.raises(NoSolutionError):
        problem = DnaOptimizationProblem(
            sequence="GGTCTC" + random_dna_sequence(100, seed=200),
            constraints=[
                AvoidPattern("BsaI_site"),
                AvoidChanges(location=(0, 6)),
            ],
            logger=None,
        )
        problem.resolve_constraints()

    with pytest.raises(NoSolutionError):
        problem = DnaOptimizationProblem(
            sequence="AAAAAATTTTTT" + random_dna_sequence(100, seed=201),
            constraints=[
                EnforceGCContent(mini=0.9, maxi=1.0, location=(0, 12)),
                AvoidChanges(location=(0, 12)),
            ],
            logger=None,
        )
        problem.resolve_constraints()


# ============================================================================
# Group 2: Pattern Avoidance
# ============================================================================


def test_avoid_pattern_all_types():
    """User avoids enzyme sites, IUPAC patterns, homopolymer runs, and repeated
    k-mers, verifying zero occurrences of each pattern type remain."""
    numpy.random.seed(123)
    sequence = random_dna_sequence(5000, seed=123)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[AvoidPattern("BsaI_site")],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()
    assert "GGTCTC" not in problem.sequence
    assert "GAGACC" not in problem.sequence

    numpy.random.seed(124)
    seq2 = "ATTGCC" + random_dna_sequence(500, seed=124)
    problem2 = DnaOptimizationProblem(
        sequence=seq2,
        constraints=[AvoidPattern("ATTGCC")],
        logger=None,
    )
    problem2.resolve_constraints()
    assert problem2.all_constraints_pass()
    pattern = DnaNotationPattern("ATTGCC")
    assert len(pattern.find_matches_in_string(problem2.sequence)) == 0

    numpy.random.seed(125)
    seq3 = random_dna_sequence(200, seed=125) + "AAAAAAA" + random_dna_sequence(200, seed=126)
    problem3 = DnaOptimizationProblem(
        sequence=seq3,
        constraints=[AvoidPattern("7xA")],
        logger=None,
    )
    assert not problem3.all_constraints_pass()
    problem3.resolve_constraints()
    assert problem3.all_constraints_pass()
    assert "AAAAAAA" not in problem3.sequence

    numpy.random.seed(127)
    seq4 = random_dna_sequence(200, seed=127) + "ATGATGATG" + random_dna_sequence(200, seed=128)
    problem4 = DnaOptimizationProblem(
        sequence=seq4,
        constraints=[AvoidPattern("3x3mer")],
        logger=None,
    )
    problem4.resolve_constraints()
    assert problem4.all_constraints_pass()
    rk_pattern = RepeatedKmerPattern(3, 3)
    assert len(rk_pattern.find_matches_in_string(problem4.sequence)) == 0


def test_avoid_hairpins():
    """User eliminates hairpin-forming sequences where a segment and its
    reverse complement appear near each other."""
    numpy.random.seed(130)
    stem = "ATGCTAGCGATCGATCGATC"
    spacer = random_dna_sequence(30, seed=130)
    rc_stem = reverse_complement(stem)
    sequence = (
        random_dna_sequence(200, seed=131)
        + stem
        + spacer
        + rc_stem
        + random_dna_sequence(200, seed=132)
    )

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[AvoidHairpins(stem_size=20, hairpin_window=200)],
        logger=None,
    )
    assert not problem.all_constraints_pass()
    problem.resolve_constraints()
    assert problem.all_constraints_pass()


def test_avoid_stop_codons():
    """User removes in-frame stop codons from a reading frame while allowing
    synonymous mutations."""
    numpy.random.seed(135)
    part1 = reverse_translate("MKVLL")
    part2 = reverse_translate("KASGRFY")
    cds_with_stop = part1 + "TAA" + part2
    full_seq = random_dna_sequence(99, seed=135) + cds_with_stop + random_dna_sequence(99, seed=136)
    cds_start = 99
    cds_end = 99 + len(cds_with_stop)

    problem = DnaOptimizationProblem(
        sequence=full_seq,
        constraints=[AvoidStopCodons(location=(cds_start, cds_end))],
        logger=None,
    )
    assert not problem.all_constraints_pass()
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    result_cds = problem.sequence[cds_start:cds_end]
    for i in range(0, len(result_cds) - 2, 3):
        codon = result_cds[i : i + 3]
        assert codon not in ("TAA", "TAG", "TGA"), f"Stop codon {codon} at codon {i // 3}"


# ============================================================================
# Group 3: Sequence Enforcement
# ============================================================================


def test_enforce_gc_content():
    """User enforces GC content within bounds per sliding window on a 3000bp
    sequence and verifies the string-parameter parser."""
    numpy.random.seed(140)
    sequence = random_dna_sequence(3000, seed=140)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[EnforceGCContent(mini=0.4, maxi=0.6, window=50)],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    seq = problem.sequence
    for i in range(0, len(seq) - 50 + 1):
        wgc = gc_content(seq[i : i + 50])
        assert 0.4 <= wgc <= 0.6, f"GC={wgc:.3f} at position {i}"

    # Parser returns (mini, maxi, target, window) — check the exact parsed values,
    # not just that 0.35 appears somewhere in the tuple.
    assert EnforceGCContent.string_to_parameters("35-65%/50bp") == (0.35, 0.65, None, 50)


def test_enforce_translation():
    """User preserves amino-acid translation on forward and reverse strands,
    and gets an error for non-codon-aligned locations."""
    numpy.random.seed(145)
    protein = "MKVLLKASGRFY"
    cds = reverse_translate(protein)

    sequence = random_dna_sequence(1000, seed=145) + cds + random_dna_sequence(1000, seed=146)
    cds_start = 1000
    cds_end = 1000 + len(cds)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceTranslation(location=(cds_start, cds_end)),
            AvoidPattern("BsaI_site"),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()
    assert translate(problem.sequence[cds_start:cds_end]).rstrip("*") == protein

    numpy.random.seed(147)
    cds_rc = reverse_complement(reverse_translate("MWVTF"))
    seq2 = random_dna_sequence(90, seed=147) + cds_rc + random_dna_sequence(90, seed=148)
    rc_start = 90
    rc_end = 90 + len(cds_rc)
    problem2 = DnaOptimizationProblem(
        sequence=seq2,
        constraints=[
            EnforceTranslation(location=Location(rc_start, rc_end, strand=-1)),
            AvoidPattern("BsaI_site"),
        ],
        logger=None,
    )
    problem2.resolve_constraints()
    assert problem2.all_constraints_pass()
    rc_result = reverse_complement(problem2.sequence[rc_start:rc_end])
    assert translate(rc_result).rstrip("*") == "MWVTF"

    with pytest.raises(ValueError):
        DnaOptimizationProblem(
            sequence=random_dna_sequence(50, seed=149),
            constraints=[EnforceTranslation(location=(0, 16))],
            logger=None,
        )


def test_enforce_pattern_occurence():
    """User inserts a specific pattern into a sequence that lacks it,
    verifying exact occurrence count after resolution."""
    numpy.random.seed(148)
    sequence = random_compatible_dna_sequence(
        300,
        constraints=[
            EnforceGCContent(mini=0.4, maxi=0.6, window=50),
            AvoidPattern("BsmBI_site"),
        ],
        logger=None,
        seed=148,
    )

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforcePatternOccurence(pattern="BsmBI_site", occurences=1),
            EnforceGCContent(mini=0.3, maxi=0.7, window=50),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    bsmbi_pattern = EnzymeSitePattern("BsmBI")
    matches = bsmbi_pattern.find_matches(problem.sequence)
    assert len(matches) == 1


def test_enforce_sequence_and_choice():
    """User fixes specific nucleotides at one location, restricts another to
    one of several alternatives, and validates sequence length bounds."""
    numpy.random.seed(150)
    sequence = random_dna_sequence(300, seed=150)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceSequence(sequence="GCGCGC", location=(50, 56)),
            EnforceChoice(choices=["AATTCC", "GGCCAA", "TTGGAA"], location=(100, 106)),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()
    assert problem.sequence[50:56] == "GCGCGC"
    assert problem.sequence[100:106] in ["AATTCC", "GGCCAA", "TTGGAA"]

    problem2 = DnaOptimizationProblem(
        sequence=random_dna_sequence(200, seed=151),
        constraints=[SequenceLengthBounds(min_length=100, max_length=300)],
        logger=None,
    )
    assert problem2.all_constraints_pass()

    problem3 = DnaOptimizationProblem(
        sequence=random_dna_sequence(50, seed=152),
        constraints=[SequenceLengthBounds(min_length=100)],
        logger=None,
    )
    assert not problem3.all_constraints_pass()


def test_enforce_changes_and_avoid_changes():
    """User forces a minimum number of mutations in one region while preserving
    another, verifying edit counts after optimization."""
    numpy.random.seed(152)
    sequence = random_dna_sequence(300, seed=152)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            AvoidChanges(location=(0, 100)),
            EnforceChanges(minimum=5, location=(100, 200)),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    assert problem.sequence[:100] == sequence[:100]
    diffs_in_changed = sequences_differences(
        problem.sequence[100:200], sequence[100:200]
    )
    assert diffs_in_changed >= 5


# ============================================================================
# Group 4: Codon Optimization
# ============================================================================


def test_codon_optimize_strategies():
    """User codon-optimizes a coding sequence using multiple strategies,
    verifying protein preservation and score improvement for each."""
    numpy.random.seed(155)
    protein = "MKWVTFISLLLLFSSAYS"
    cds = reverse_translate(protein)

    for method_name in ["use_best_codon", "match_codon_usage"]:
        numpy.random.seed(155)
        problem = DnaOptimizationProblem(
            sequence=cds,
            constraints=[EnforceTranslation(location=(0, len(cds)))],
            objectives=[
                CodonOptimize(
                    species="e_coli", method=method_name, location=(0, len(cds))
                )
            ],
            logger=None,
        )
        score_before = problem.objective_scores_sum()
        problem.resolve_constraints()
        problem.optimize()
        score_after = problem.objective_scores_sum()

        assert score_after >= score_before
        assert translate(problem.sequence[: len(cds)]).rstrip("*") == protein

        obj_evals = list(problem.objectives_evaluations())
        assert len(obj_evals) == 1
        obj_eval = obj_evals[0]
        assert obj_eval.score >= score_before

        if method_name == "use_best_codon":
            # use_best_codon drives the objective to its maximum: every codon
            # becomes the target species' most-frequent synonymous one, so the
            # CAI-maximization score reaches its 0 upper bound exactly. A no-op /
            # broken optimizer would leave the random CDS with score_after < 0.
            assert score_after == 0
            assert obj_eval.score == 0
        else:
            # match_codon_usage matches a usage *profile*, so the optimum is a
            # seed/version-dependent negative value, not 0 — only require
            # non-decrease (asserted above).
            assert score_after < 0

    numpy.random.seed(157)
    problem_rca = DnaOptimizationProblem(
        sequence=cds,
        constraints=[EnforceTranslation(location=(0, len(cds)))],
        objectives=[
            CodonOptimize(
                species="e_coli",
                method="harmonize_rca",
                original_species="h_sapiens",
                location=(0, len(cds)),
            )
        ],
        logger=None,
    )
    problem_rca.resolve_constraints()
    problem_rca.optimize()
    assert translate(problem_rca.sequence[: len(cds)]).rstrip("*") == protein

    numpy.random.seed(156)
    problem_rare = DnaOptimizationProblem(
        sequence=cds,
        constraints=[
            EnforceTranslation(location=(0, len(cds))),
            AvoidRareCodons(
                min_frequency=0.1, species="e_coli", location=(0, len(cds))
            ),
        ],
        logger=None,
    )
    problem_rare.resolve_constraints()
    assert problem_rare.all_constraints_pass()
    assert translate(problem_rare.sequence[: len(cds)]).rstrip("*") == protein


def test_codon_optimize_with_constraints():
    """User codon-optimizes a coding region with the default use_best_codon
    strategy under GC and pattern constraints, and verifies the resolved codons
    are actually driven to the target species' most-frequent synonymous codons."""
    numpy.random.seed(158)
    protein = "MKVLLKASGRFYWELDTQN"
    cds = reverse_translate(protein)
    sequence = random_dna_sequence(150, seed=158) + cds + random_dna_sequence(150, seed=159)
    cds_start = 150
    cds_end = 150 + len(cds)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceTranslation(location=(cds_start, cds_end)),
            EnforceGCContent(mini=0.3, maxi=0.7, window=50),
            AvoidPattern("BsaI_site"),
        ],
        objectives=[
            # No method given -> the default "use_best_codon" strategy.
            CodonOptimize(species="e_coli", location=(cds_start, cds_end)),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    problem.optimize()

    assert problem.all_constraints_pass()
    assert translate(problem.sequence[cds_start:cds_end]).rstrip("*") == protein
    assert "GGTCTC" not in problem.sequence

    # Distinct contract: with use_best_codon, each codon must be driven to the
    # MOST-FREQUENT synonymous codon for the target species. Build the per-amino-acid
    # best codon from the same python_codon_tables source the spec names, then check
    # the actual codon CHOICES (not just that constraints pass / score improved).
    e_coli_table = python_codon_tables.get_codons_table("e_coli")
    best_codon = {
        aa: max(codon_freqs, key=codon_freqs.get)
        for aa, codon_freqs in e_coli_table.items()
        if len(aa) == 1
    }

    def count_best_codons(cds_seq):
        return sum(
            1
            for i in range(0, len(cds_seq), 3)
            if cds_seq[i : i + 3] == best_codon[translate(cds_seq[i : i + 3])]
        )

    n_codons = len(cds) // 3
    optimized_cds = problem.sequence[cds_start:cds_end]
    best_before = count_best_codons(cds)
    best_after = count_best_codons(optimized_cds)

    # Optimization must move the sequence toward the best codons, not away.
    assert best_after > best_before, (
        f"use_best_codon did not increase best-codon usage: "
        f"{best_before} -> {best_after} of {n_codons}"
    )
    # The loose GC window and single BsaI avoidance leave room to reach the
    # best codon at the vast majority of positions, so most codons must be optimal.
    assert best_after >= 0.8 * n_codons, (
        f"Expected most codons at the e_coli best codon, got {best_after}/{n_codons}"
    )


# ============================================================================
# Group 5: Melting Temperature & Primer
# ============================================================================


def test_enforce_melting_temperature():
    """User enforces melting temperature bounds on a primer-length subsequence,
    adjusting AT-rich content to reach the target range."""
    numpy.random.seed(160)
    low_tm_seq = "ATAATATATAATATATATAT" + "ATAATAA"
    sequence = low_tm_seq + random_dna_sequence(474, seed=160)

    import primer3

    initial_tm = primer3.calc_tm(low_tm_seq)
    assert initial_tm < 55

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceMeltingTemperature(mini=55, maxi=70, location=(0, 26)),
        ],
        logger=None,
    )
    assert not problem.all_constraints_pass()
    problem.resolve_constraints()
    assert problem.all_constraints_pass()
    assert problem.sequence[:26] != low_tm_seq

    result_tm = primer3.calc_tm(problem.sequence[:26])
    assert 55 <= result_tm <= 70, f"Tm={result_tm:.1f} outside [55, 70]"


def test_allow_primer():
    """User makes a region primer-compatible via the composite AllowPrimer
    specification covering Tm, uniqueness, and no-repeat constraints."""
    numpy.random.seed(162)
    sequence = random_dna_sequence(500, seed=162)
    primer_loc = (100, 125)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[AllowPrimer(location=primer_loc, tmin=55, tmax=70)],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    import primer3

    primer_seq = problem.sequence[100:125]
    tm = primer3.calc_tm(primer_seq)
    assert 55 <= tm <= 70, f"Tm={tm:.1f} outside [55, 70]"


# ============================================================================
# Group 6: Advanced Specifications
# ============================================================================


def test_enforce_regions_compatibility():
    """User ensures multiple sequence regions have minimum pairwise nucleotide
    differences, verifying Hamming distance after resolution."""
    numpy.random.seed(163)
    locs = [(0, 100), (100, 200), (200, 300)]

    def compat_condition(r1, r2, problem):
        s1 = r1.extract_sequence(problem.sequence) if hasattr(r1, 'extract_sequence') else r1
        s2 = r2.extract_sequence(problem.sequence) if hasattr(r2, 'extract_sequence') else r2
        return sequences_differences(s1, s2) >= 2

    problem = DnaOptimizationProblem(
        sequence=random_dna_sequence(300, seed=163),
        constraints=[
            EnforceRegionsCompatibility(
                locations=locs,
                compatibility_condition=compat_condition,
                condition_label="2+ differences",
            ),
            EnforceGCContent(mini=0.3, maxi=0.7, window=100),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    for (s1, e1), (s2, e2) in combinations(locs, 2):
        d = sequences_differences(
            problem.sequence[s1:e1], problem.sequence[s2:e2]
        )
        assert d >= 2, f"Regions ({s1},{e1}) and ({s2},{e2}) differ by only {d}"


def test_uniquify_all_kmers():
    """User ensures all k-mers of a given length are unique in a 500bp region,
    both as a constraint and as an optimization objective."""
    numpy.random.seed(164)
    sequence = random_dna_sequence(1000, seed=164)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[UniquifyAllKmers(k=9, location=(0, 500))],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    subseq = problem.sequence[:500]
    kmers = [subseq[i : i + 9] for i in range(len(subseq) - 9 + 1)]
    assert len(kmers) == len(set(kmers)), "Duplicate 9-mers found"

    numpy.random.seed(165)
    problem2 = DnaOptimizationProblem(
        sequence=random_dna_sequence(500, seed=165),
        constraints=[EnforceGCContent(mini=0.3, maxi=0.7, window=50)],
        objectives=[UniquifyAllKmers(k=9, location=(0, 500))],
        logger=None,
    )
    problem2.resolve_constraints()
    score_before = problem2.objective_scores_sum()
    problem2.optimize()
    score_after = problem2.objective_scores_sum()
    assert problem2.all_constraints_pass()
    assert score_after >= score_before


def test_enforce_terminal_gc_content():
    """User enforces GC content bounds at both terminal ends of a sequence."""
    numpy.random.seed(166)
    sequence = "A" * 20 + random_dna_sequence(460, seed=166) + "T" * 20

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceTerminalGCContent(window_size=20, mini=0.3, maxi=0.7),
        ],
        logger=None,
    )
    assert not problem.all_constraints_pass()
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    left_gc = gc_content(problem.sequence[:20])
    right_gc = gc_content(problem.sequence[-20:])
    assert 0.3 <= left_gc <= 0.7, f"Left terminal GC={left_gc:.3f}"
    assert 0.3 <= right_gc <= 0.7, f"Right terminal GC={right_gc:.3f}"


# ============================================================================
# Group 7: Hard Multi-Constraint Scenarios
# ============================================================================


def test_overlapping_constraints_on_cds():
    """User applies multiple competing constraints on the same coding region:
    translation preservation, tight GC window, multiple enzyme site avoidance,
    and rare codon avoidance — forcing the solver to navigate a very tight
    mutation space."""
    numpy.random.seed(190)
    protein = "MKVLLKASGRFYWELDTQN"
    cds = reverse_translate(protein)
    sequence = random_dna_sequence(60, seed=190) + cds + random_dna_sequence(60, seed=191)
    cds_start = 60
    cds_end = 60 + len(cds)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceTranslation(location=(cds_start, cds_end)),
            EnforceGCContent(mini=0.35, maxi=0.65, window=30),
            AvoidPattern("BsaI_site"),
            AvoidPattern("EcoRI_site"),
            AvoidPattern("BamHI_site"),
            AvoidRareCodons(
                min_frequency=0.1, species="e_coli", location=(cds_start, cds_end)
            ),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    assert translate(problem.sequence[cds_start:cds_end]).rstrip("*") == protein
    assert "GGTCTC" not in problem.sequence
    assert "GAATTC" not in problem.sequence
    assert "GGATCC" not in problem.sequence

    seq = problem.sequence
    for i in range(0, len(seq) - 30 + 1):
        wgc = gc_content(seq[i : i + 30])
        assert 0.35 <= wgc <= 0.65, f"GC={wgc:.3f} at position {i}"


def test_cascading_constraint_breaches():
    """User creates a scenario where resolving one constraint breach creates
    a new breach of a different constraint, requiring the solver to iterate
    and pass a final consistency check."""
    numpy.random.seed(192)
    protein = "MKVLLKASG"
    cds = reverse_translate(protein)

    bsai_site = "GGTCTC"
    sequence = cds + bsai_site + random_dna_sequence(100, seed=192)
    cds_end = len(cds)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceTranslation(location=(0, cds_end)),
            AvoidPattern("BsaI_site"),
            EnforceGCContent(mini=0.3, maxi=0.7, window=50),
        ],
        logger=None,
    )
    assert not problem.all_constraints_pass()
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    assert translate(problem.sequence[:cds_end]).rstrip("*") == protein
    assert "GGTCTC" not in problem.sequence
    assert "GAGACC" not in problem.sequence


def test_multi_cds_different_species_optimization():
    """User optimizes two separate coding regions in one sequence for different
    target species, with GC and pattern constraints tying the regions together."""
    numpy.random.seed(194)
    protein1 = "MKVLLKASG"
    protein2 = "MWVTFISLL"
    cds1 = reverse_translate(protein1)
    cds2 = reverse_translate(protein2)

    spacer = random_dna_sequence(50, seed=194)
    sequence = cds1 + spacer + cds2
    cds1_start = 0
    cds1_end = len(cds1)
    cds2_start = len(cds1) + len(spacer)
    cds2_end = cds2_start + len(cds2)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            EnforceTranslation(location=(cds1_start, cds1_end)),
            EnforceTranslation(location=(cds2_start, cds2_end)),
            AvoidPattern("BsaI_site"),
            EnforceGCContent(mini=0.3, maxi=0.7, window=50),
        ],
        objectives=[
            CodonOptimize(
                species="e_coli", location=(cds1_start, cds1_end)
            ),
            CodonOptimize(
                species="h_sapiens", location=(cds2_start, cds2_end)
            ),
        ],
        logger=None,
    )
    score_before = problem.objective_scores_sum()
    problem.resolve_constraints()
    problem.optimize()
    score_after = problem.objective_scores_sum()
    assert problem.all_constraints_pass()

    assert translate(problem.sequence[cds1_start:cds1_end]).rstrip("*") == protein1
    assert translate(problem.sequence[cds2_start:cds2_end]).rstrip("*") == protein2
    assert "GGTCTC" not in problem.sequence

    obj_evals = list(problem.objectives_evaluations())
    assert len(obj_evals) == 2
    assert score_after >= score_before


def test_avoid_changes_with_indices():
    """User freezes specific scattered nucleotide positions using the indices
    parameter of AvoidChanges, verifying those exact positions are unchanged
    after optimization modifies the surrounding sequence."""
    numpy.random.seed(196)
    sequence = random_dna_sequence(1000, seed=196)
    frozen_indices = list(range(10, 1000, 25))

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            AvoidChanges(indices=frozen_indices),
            EnforceGCContent(mini=0.4, maxi=0.6, window=50),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    for idx in frozen_indices:
        assert problem.sequence[idx] == sequence[idx], (
            f"Position {idx} changed from {sequence[idx]} to {problem.sequence[idx]}"
        )

    seq = problem.sequence
    for i in range(0, len(seq) - 50 + 1):
        wgc = gc_content(seq[i : i + 50])
        assert 0.4 <= wgc <= 0.6, f"GC={wgc:.3f} at position {i}"


# ============================================================================
# Group 8: Advanced Feature Edge Cases
# ============================================================================


def test_avoid_changes_max_edits():
    """User limits the number of edits in a region using max_edits > 0, allowing
    some changes while capping the total — different from a complete freeze."""
    numpy.random.seed(210)
    sequence = random_dna_sequence(300, seed=210)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            AvoidChanges(max_edits=3, location=(0, 100)),
            EnforceGCContent(mini=0.4, maxi=0.6, window=50),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    edits_in_region = sequences_differences(
        problem.sequence[:100], sequence[:100]
    )
    assert edits_in_region <= 3, f"Expected <= 3 edits, got {edits_in_region}"

    seq = problem.sequence
    for i in range(0, len(seq) - 50 + 1):
        wgc = gc_content(seq[i : i + 50])
        assert 0.4 <= wgc <= 0.6


def test_enforce_gc_content_as_objective():
    """User uses EnforceGCContent as an optimization objective with a target,
    verifying the solver moves GC content toward the target value."""
    numpy.random.seed(212)
    sequence = random_dna_sequence(300, seed=212)

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[],
        objectives=[EnforceGCContent(target=0.5, window=50)],
        logger=None,
    )

    score_before = problem.objective_scores_sum()
    problem.optimize()
    score_after = problem.objective_scores_sum()

    assert score_after >= score_before
    global_gc = gc_content(problem.sequence)
    assert 0.35 <= global_gc <= 0.65


def test_avoid_pattern_strand_specific():
    """User avoids a pattern on only the forward strand, verifying that a
    reverse-strand-only occurrence (the reverse complement) is still allowed.

    Uses BsaI (GGTCTC), whose reverse complement (GAGACC) is a distinct string,
    so the strand=1 (forward-only) behavior is distinguishable from strand=0
    (both strands): only forward-only avoidance leaves the GAGACC occurrence in
    place, whereas both-strand avoidance would also remove it.
    """
    numpy.random.seed(214)

    bsai_site = "GGTCTC"
    bsai_rc = reverse_complement(bsai_site)
    assert bsai_rc != bsai_site  # non-palindromic: forward and reverse strands differ
    sequence = (
        random_dna_sequence(100, seed=214)
        + bsai_site
        + random_dna_sequence(50, seed=215)
        + bsai_rc
        + random_dna_sequence(100, seed=216)
    )
    # The forward site and the reverse-strand-only occurrence each appear exactly once.
    assert sequence.count(bsai_site) == 1
    assert sequence.count(bsai_rc) == 1

    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[AvoidPattern("BsaI_site", strand=1)],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()

    # The forward-strand site is removed, but the reverse-strand-only occurrence is preserved
    # (strand=0 avoidance would have removed both).
    assert bsai_site not in problem.sequence
    assert bsai_rc in problem.sequence


def test_from_record_shorthand_names():
    """User annotates a GenBank file using shorthand specification names
    (@no for AvoidPattern, @cds for EnforceTranslation) and the & syntax
    for multiple specs on one feature."""
    numpy.random.seed(218)
    protein = "MKVLLKASG"
    cds = reverse_translate(protein)
    sequence = random_dna_sequence(100, seed=218) + cds + random_dna_sequence(100, seed=219)
    cds_start = 100
    cds_end = 100 + len(cds)

    record = SeqRecord(Seq(sequence), id="shorthand_test", name="shorthand_test")
    record.annotations["molecule_type"] = "DNA"

    record.features.append(
        SeqFeature(
            FeatureLocation(0, len(sequence)),
            type="misc_feature",
            qualifiers={"label": "@no(BsaI_site)"},
        )
    )

    record.features.append(
        SeqFeature(
            FeatureLocation(cds_start, cds_end),
            type="misc_feature",
            qualifiers={"label": "@cds"},
        )
    )

    problem = DnaOptimizationProblem.from_record(record, logger=None)
    assert len(problem.constraints) == 2
    problem.resolve_constraints()
    assert problem.all_constraints_pass()
    assert "GGTCTC" not in problem.sequence
    assert translate(problem.sequence[cds_start:cds_end]).rstrip("*") == protein


def test_spec_evaluate_directly():
    """User calls evaluate() on individual specifications and inspects the
    SpecEvaluation result fields: score, passes, locations, message."""
    numpy.random.seed(220)

    sequence = "GGTCTC" + random_dna_sequence(200, seed=220) + "GGTCTC"
    problem = DnaOptimizationProblem(
        sequence=sequence,
        constraints=[AvoidPattern("BsaI_site")],
        logger=None,
    )

    spec = problem.constraints[0]
    evaluation = spec.evaluate(problem)
    assert not evaluation.passes
    assert evaluation.score < 0
    assert evaluation.locations is not None
    assert len(evaluation.locations) >= 2
    assert isinstance(evaluation.message, str)
    assert len(evaluation.message) > 0

    problem.resolve_constraints()
    evaluation_after = spec.evaluate(problem)
    assert evaluation_after.passes
    assert evaluation_after.score >= 0
    assert evaluation_after.locations is not None
    assert len(evaluation_after.locations) == 0

    gc_spec = EnforceGCContent(mini=0.4, maxi=0.6, window=50)
    # A 50bp all-AT stretch (GC=0.0) spliced onto an otherwise balanced sequence
    # guarantees at least one 50bp window outside [0.4, 0.6] under any correct
    # windowed-GC computation, so the unresolved spec must fail with a negative
    # breach score. (Constructed explicitly to avoid depending on the exact bytes
    # the seeded RNG happens to emit.)
    gc_problem = DnaOptimizationProblem(
        sequence=("AT" * 25) + random_dna_sequence(150, seed=221),
        constraints=[gc_spec],
        logger=None,
    )
    gc_eval = gc_problem.constraints[0].evaluate(gc_problem)
    assert not gc_eval.passes
    assert gc_eval.score < 0


def test_location_extract_sequence_reverse_strand():
    """User extracts subsequences using Location with strand=-1, verifying
    that reverse-complement extraction works correctly."""
    sequence = "ATGCGATCGA"

    loc_fwd = Location(2, 6, strand=1)
    assert loc_fwd.extract_sequence(sequence) == "GCGA"

    loc_rev = Location(2, 6, strand=-1)
    extracted = loc_rev.extract_sequence(sequence)
    assert extracted == reverse_complement("GCGA")
    assert extracted == "TCGC"

    loc_neutral = Location(2, 6, strand=0)
    assert loc_neutral.extract_sequence(sequence) == "GCGA"


# ============================================================================
# Group 9: Mutation Space & Random Sequences
# ============================================================================


def test_mutation_space_and_random_compatible_sequence():
    """User generates a random sequence that satisfies constraints, and
    verifies the mutation space correctly enumerates variants."""
    numpy.random.seed(167)
    seq = random_compatible_dna_sequence(
        300,
        constraints=[
            AvoidPattern("BsaI_site"),
            EnforceGCContent(mini=0.4, maxi=0.6, window=50),
        ],
        logger=None,
        seed=167,
    )
    assert len(seq) == 300
    assert "GGTCTC" not in seq
    assert "GAGACC" not in seq
    for i in range(0, len(seq) - 50 + 1):
        wgc = gc_content(seq[i : i + 50])
        assert 0.4 <= wgc <= 0.6

    numpy.random.seed(168)
    problem = DnaOptimizationProblem(
        sequence=random_dna_sequence(30, seed=168),
        constraints=[EnforceGCContent(mini=0.4, maxi=0.6)],
        logger=None,
    )
    # EnforceGCContent does not restrict any nucleotide, so all 30 bases are
    # fully free (4 variants each): the unrestricted mutation space has exactly
    # 4 ** 30 variants.
    space_size = problem.mutation_space.space_size
    assert space_size == pytest.approx(4 ** 30)

    edits_before = problem.number_of_edits()
    assert edits_before == 0
    problem.resolve_constraints()
    assert problem.all_constraints_pass()


# ============================================================================
# Group 8: Circular DNA
# ============================================================================


def test_circular_dna_optimization():
    """User optimizes a 2000bp circular DNA sequence, verifying constraints pass
    including at the origin-spanning boundary."""
    numpy.random.seed(172)
    sequence = random_dna_sequence(2000, seed=172)

    problem = CircularDnaOptimizationProblem(
        sequence=sequence,
        constraints=[
            AvoidPattern("BsaI_site"),
            EnforceGCContent(mini=0.4, maxi=0.6, window=50),
        ],
        logger=None,
    )
    problem.resolve_constraints()
    assert problem.all_constraints_pass()
    assert len(problem.sequence) == 2000

    assert "GGTCTC" not in problem.sequence
    assert "GAGACC" not in problem.sequence
    wraparound = problem.sequence[-25:] + problem.sequence[:25]
    assert "GGTCTC" not in wraparound
    assert "GAGACC" not in wraparound


# ============================================================================
# Group 9: GenBank I/O
# ============================================================================


def test_genbank_roundtrip_and_from_record():
    """User loads an annotated GenBank file via from_record, solves constraints,
    and exports the result with edit annotations."""
    numpy.random.seed(175)
    sequence = random_dna_sequence(500, seed=175)
    record = SeqRecord(Seq(sequence), id="test_seq", name="test_seq")
    record.annotations["molecule_type"] = "DNA"

    record.features.append(
        SeqFeature(
            FeatureLocation(0, 500),
            type="misc_feature",
            qualifiers={"label": "@AvoidPattern(BsaI_site)"},
        )
    )

    with tempfile.NamedTemporaryFile(suffix=".gb", delete=False) as f:
        tmppath = f.name
    try:
        write_record(record, tmppath)
        problem = DnaOptimizationProblem.from_record(tmppath, logger=None)
    finally:
        os.unlink(tmppath)

    assert len(problem.constraints) == 1
    problem.resolve_constraints()
    assert problem.all_constraints_pass()
    assert "GGTCTC" not in problem.sequence

    record_without_edits = problem.to_record(with_sequence_edits=False)
    record_with_edits = problem.to_record(with_sequence_edits=True)
    assert len(record_with_edits.seq) == 500
    assert str(record_with_edits.seq) == problem.sequence

    if problem.number_of_edits() > 0:
        assert len(record_with_edits.features) > len(record_without_edits.features)


# ============================================================================
# Group 10: Patterns
# ============================================================================


def test_pattern_types_and_parsing():
    """User creates patterns from string notation for enzyme sites, homopolymers,
    repeated k-mers, and PSSM motifs, and finds matches in known sequences."""
    enz = SequencePattern.from_string("BsaI_site")
    assert isinstance(enz, EnzymeSitePattern)
    matches = enz.find_matches_in_string("AAAGGTCTCAAA")
    assert len(matches) >= 1
    found_positions = {(m[0], m[1]) for m in matches}
    assert (3, 9) in found_positions

    hp = SequencePattern.from_string("5xA")
    assert isinstance(hp, HomopolymerPattern)
    assert len(hp.find_matches_in_string("CCAAAAACCC")) >= 1
    assert len(hp.find_matches_in_string("CCAAAACCC")) == 0

    rk = SequencePattern.from_string("3x3mer")
    assert isinstance(rk, RepeatedKmerPattern)
    assert len(rk.find_matches_in_string("ATGATGATG")) >= 1
    assert len(rk.find_matches_in_string("ATGATGTTG")) == 0

    # threshold=0 means "score at least as likely as the background" — the
    # consensus ATTGCAC is the highest-scoring window and must be reported.
    motif = MotifPssmPattern.from_sequences(
        ["ATTGCAC", "ATTGCGC", "ATTGCAC", "ATTGTAC"],
        name="test_motif",
        pseudocounts=None,
        threshold=0.0,
    )
    test_seq = "AAAA" + "ATTGCAC" + "AAAA"
    motif_matches = motif.find_matches_in_string(test_seq)
    found_motif_positions = {(m[0], m[1]) for m in motif_matches}
    assert (4, 11) in found_motif_positions


# ============================================================================
# Group 11: Biotools Utilities
# ============================================================================


def test_biotools_utilities():
    """User exercises core biotools: translate, reverse_complement, complement,
    gc_content, random sequences, sequence differences, enzyme listing, and
    GenBank I/O roundtrip."""
    assert translate("ATGAAAGTT") == "MKV"
    assert complement("ATGC") == "TACG"
    assert reverse_complement("ATGC") == "GCAT"
    assert reverse_complement(reverse_complement("ATGCGT")) == "ATGCGT"

    protein = "MKV"
    dna = reverse_translate(protein)
    assert len(dna) == 9
    assert translate(dna).rstrip("*") == protein

    numpy.random.seed(178)
    seq = random_dna_sequence(100, seed=178)
    assert len(seq) == 100
    assert set(seq) <= {"A", "T", "G", "C"}

    gc = gc_content("GCGCGC")
    assert gc == 1.0
    gc2 = gc_content("ATATAT")
    assert gc2 == 0.0
    gc3 = gc_content("ATGC")
    assert gc3 == 0.5

    assert sequences_differences("ATGC", "ATGC") == 0
    assert sequences_differences("ATGC", "ATGA") == 1
    assert sequences_differences("ATGC", "TTTT") == 3

    segs = sequences_differences_segments("AATTCC", "AATTGG")
    assert (4, 6) in segs

    enzymes = list_common_enzymes(site_length=(6,))
    assert len(enzymes) > 0
    assert "EcoRI" in enzymes

    record = sequence_to_biopython_record("ATGCATGC")
    assert len(record.seq) == 8
    assert str(record.seq) == "ATGCATGC"

    with tempfile.NamedTemporaryFile(suffix=".gb", delete=False) as f:
        tmppath = f.name
    try:
        record.annotations["molecule_type"] = "DNA"
        write_record(record, tmppath)
        loaded = load_record(tmppath)
        assert str(loaded.seq) == "ATGCATGC"
    finally:
        os.unlink(tmppath)

    loc1 = Location(10, 30, strand=1)
    loc2 = Location(20, 40, strand=1)
    overlap = loc1.overlap_region(loc2)
    assert overlap is not None
    assert overlap.start == 20
    assert overlap.end == 30

    loc3 = Location(50, 60, strand=1)
    assert loc1.overlap_region(loc3) is None

    extended = loc1.extended(5, lower_limit=0)
    assert extended.start == 5
    assert extended.end == 35

    merged = Location.merge_overlapping_locations(
        [Location(0, 10), Location(5, 15), Location(20, 30)]
    )
    assert len(merged) == 2
    assert merged[0].start == 0
    assert merged[0].end == 15
    assert merged[1].start == 20

    prot = random_protein_sequence(10, seed=179)
    assert len(prot) == 10
    assert prot[0] == "M"

    rec = sequence_to_biopython_record("ATGCATGCATGC")
    annotate_record(rec, location=(2, 8), label="test_feature")
    assert len(rec.features) == 1
    label_val = rec.features[0].qualifiers["label"]
    if isinstance(label_val, list):
        assert label_val[0] == "test_feature"
    else:
        assert label_val == "test_feature"

    # 'ATGCATGC' vs 'ATGGATGC' differ at exactly one position (index 3), which is
    # annotated as exactly one difference feature.
    rec1 = sequence_to_biopython_record("ATGCATGC")
    rec2 = sequence_to_biopython_record("ATGGATGC")
    diff_rec = annotate_differences(rec1, rec2)
    assert len(diff_rec.features) == 1

    # 'AAAGGTCTCAAA' contains the pattern GGTCTC exactly once (its reverse complement
    # GAGACC is absent), so exactly one occurrence feature is annotated.
    pattern_rec = sequence_to_biopython_record("AAAGGTCTCAAA")
    pat = DnaNotationPattern("GGTCTC")
    occ_rec = annotate_pattern_occurrences(pattern_rec, pat)
    assert len(occ_rec.features) == 1

    original = sequence_to_biopython_record("ATGCATGC")
    changed = change_biopython_record_sequence(original, "TTTTTTTT")
    assert str(changed.seq) == "TTTTTTTT"
    assert str(original.seq) == "ATGCATGC"


# ============================================================================
# Group 12: Objective Boosting and Passive Objectives
# ============================================================================


def test_avoid_changes_as_objective_with_boost():
    """User uses AvoidChanges as a passive objective with varying boost to
    control how many edits codon optimization introduces — higher boost means
    fewer edits."""
    numpy.random.seed(180)
    protein = "MKWVTFISLLLLFSSAYS"
    cds = reverse_translate(protein)

    edit_counts = []
    for boost in [0.1, 10.0]:
        numpy.random.seed(180)
        problem = DnaOptimizationProblem(
            sequence=cds,
            constraints=[EnforceTranslation(location=(0, len(cds)))],
            objectives=[
                CodonOptimize(species="e_coli", location=(0, len(cds))),
                AvoidChanges().as_passive_objective().copy_with_changes(boost=boost),
            ],
            logger=None,
        )
        problem.resolve_constraints()
        problem.optimize()
        assert problem.all_constraints_pass()
        assert translate(problem.sequence[: len(cds)]).rstrip("*") == protein
        edit_counts.append(
            sequences_differences(problem.sequence[: len(cds)], cds)
        )

    assert edit_counts[0] >= edit_counts[1], (
        f"Higher AvoidChanges boost should produce fewer edits: "
        f"boost=0.1 gave {edit_counts[0]} edits, boost=10.0 gave {edit_counts[1]}"
    )


# ============================================================================
# Group 13: CLI
# ============================================================================


def test_cli_optimization():
    """User optimizes an annotated GenBank file via the dnachisel CLI,
    verifying the output file contains a valid optimized sequence."""
    numpy.random.seed(182)
    sequence = random_dna_sequence(500, seed=182)
    record = sequence_to_biopython_record(sequence, id="cli_test")
    record.annotations["molecule_type"] = "DNA"

    record.features.append(
        SeqFeature(
            FeatureLocation(0, 500),
            type="misc_feature",
            qualifiers={"label": "@AvoidPattern(BsaI_site)"},
        )
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.gb")
        output_path = os.path.join(tmpdir, "output.gb")
        write_record(record, input_path)

        result = subprocess.run(
            ["dnachisel", input_path, output_path, "--mute"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert os.path.isfile(output_path)

        output_record = load_record(output_path)
        assert len(output_record.seq) == 500
        # The annotation "@AvoidPattern(BsaI_site)" has no explicit strand=, so from_record uses
        # the parsed feature's own strand (forward here). Only the forward BsaI site GGTCTC is
        # avoided; the reverse-complement occurrence (GAGACC) is not required to be removed.
        assert "GGTCTC" not in str(output_record.seq)
