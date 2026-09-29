"""Tests for PipelineDP — a differential privacy framework for data pipelines.

Tests exercise the public API through realistic user workflows using
LocalBackend + DPEngine, covering all major DP aggregation metrics,
budget accounting, contribution bounding, partition selection,
parameter validation, noise mechanisms, dataset histograms, and the
explain-computation report system.
"""

import collections
import math
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Test: End-to-end COUNT aggregation with public partitions
# ---------------------------------------------------------------------------


class TestCountAggregation:
    """Aggregate COUNT metric end-to-end through LocalBackend."""

    def test_count_with_public_partitions_returns_noised_counts(self):
        """A user computes DP counts per partition with known partition keys.

        Sets up a small dataset with known per-partition counts, runs
        DPEngine.aggregate with COUNT metric and public partitions, and
        verifies that every public partition appears in the output and
        the noised counts are within a plausible range of the true counts.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=100, total_delta=0)

        engine = pipeline_dp.DPEngine(accountant, backend)

        # 3 users, partitions "A" and "B". True counts: A=5, B=3.
        data = [
            ("u1", "A", 1),
            ("u1", "A", 1),
            ("u1", "B", 1),
            ("u2", "A", 1),
            ("u2", "B", 1),
            ("u2", "B", 1),
            ("u3", "A", 1),
            ("u3", "A", 1),
        ]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=2,
            max_contributions_per_partition=3,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["A", "B", "C"],
        )
        accountant.compute_budgets()

        result = dict(list(result))

        assert set(result.keys()) == {"A", "B", "C"}
        # With eps=100 noise is negligible. True count A=5, B=3.
        assert abs(result["A"].count - 5) < 2
        assert abs(result["B"].count - 3) < 2
        # C has no data → count ≈ 0
        assert abs(result["C"].count) < 2


# ---------------------------------------------------------------------------
# Test: End-to-end SUM aggregation
# ---------------------------------------------------------------------------


class TestSumAggregation:
    """Aggregate SUM metric end-to-end."""

    def test_sum_with_value_clipping(self):
        """A user computes DP sum with min/max value clipping.

        Values outside [min_value, max_value] should be clipped before
        summing. With high epsilon the noised result should be close
        to the clipped true sum.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        # eps=1000 keeps the Laplace scale b = (max_value*max_contributions)/eps =
        # (50*5)/1000 = 0.25 well below the tol=5 check (P(|noise|>5) ~ 2e-9), so the
        # clipped-sum assertion stays tight and deterministic.
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=1000, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        # One user contributes values 10, 20, 100 to partition "X".
        # With max_value=50, the 100 gets clipped to 50.
        # Clipped sum = 10 + 20 + 50 = 80.
        data = [
            ("user1", "X", 10),
            ("user1", "X", 20),
            ("user1", "X", 100),
        ]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=5,
            min_value=0,
            max_value=50,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["X"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        assert "X" in result
        # Clipped sum is 80; noise is negligible at eps=100
        assert abs(result["X"].sum - 80) < 5


# ---------------------------------------------------------------------------
# Test: End-to-end MEAN aggregation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test: End-to-end VARIANCE aggregation
# ---------------------------------------------------------------------------


class TestVarianceAggregation:
    """Aggregate VARIANCE metric end-to-end."""

    def test_variance_returns_value_near_true_variance(self):
        """A user computes DP variance using the GAUSSIAN mechanism.

        Exercises the Gaussian-calibrated variance combiner (delta > 0), a
        distinct mechanism path from the Laplace variance. With high epsilon
        the DP variance approximates the true population variance of the
        (possibly clipped) values.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=1e-6
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # 10 users contribute values 1..10 to partition "V".
        # Population variance = 8.25.
        data = [(f"u{i}", "V", float(i)) for i in range(1, 11)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.VARIANCE],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=10,
            noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["V"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        true_var = np.var([float(i) for i in range(1, 11)])
        assert abs(result["V"].variance - true_var) < 3


# ---------------------------------------------------------------------------
# Test: End-to-end PRIVACY_ID_COUNT aggregation
# ---------------------------------------------------------------------------


class TestPrivacyIdCountAggregation:
    """Aggregate PRIVACY_ID_COUNT metric end-to-end."""

    def test_privacy_id_count_counts_distinct_users(self):
        """A user computes DP privacy_id_count (distinct user count).

        Even when users contribute multiple records per partition,
        PRIVACY_ID_COUNT should approximate the number of distinct users.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=100, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        # 4 distinct users in partition "Q", with varying contributions.
        data = [
            ("u1", "Q", 1),
            ("u1", "Q", 2),
            ("u2", "Q", 3),
            ("u3", "Q", 4),
            ("u3", "Q", 5),
            ("u3", "Q", 6),
            ("u4", "Q", 7),
        ]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.PRIVACY_ID_COUNT],
            max_partitions_contributed=1,
            max_contributions_per_partition=5,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["Q"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        # True distinct user count = 4
        assert abs(result["Q"].privacy_id_count - 4) < 2


# ---------------------------------------------------------------------------
# Test: Multiple metrics in a single aggregation
# ---------------------------------------------------------------------------


class TestMultiMetricAggregation:
    """Compute COUNT, SUM, MEAN, and PRIVACY_ID_COUNT in one call."""

    def test_multiple_metrics_returned_as_named_tuple(self):
        """A user requests multiple metrics in one aggregation call.

        The result should be a named tuple with fields for each metric.
        All metric values should approximate the true values with
        high epsilon.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        # eps=1000 (the budget is split across the four metrics' mechanisms) keeps
        # every per-metric Laplace scale small enough that the tolerances below hold
        # deterministically (the SUM mechanism, the noisiest here, has b ~ 0.1 so
        # P(|noise|>10) ~ 0).
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=1000, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [
            ("u1", "K", 10.0),
            ("u2", "K", 20.0),
            ("u3", "K", 30.0),
        ]

        params = pipeline_dp.AggregateParams(
            metrics=[
                pipeline_dp.Metrics.COUNT,
                pipeline_dp.Metrics.SUM,
                pipeline_dp.Metrics.MEAN,
                pipeline_dp.Metrics.PRIVACY_ID_COUNT,
            ],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=50,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["K"],
        )
        accountant.compute_budgets()
        result = dict(list(result))
        metrics = result["K"]

        assert abs(metrics.count - 3) < 2
        assert abs(metrics.sum - 60) < 10
        assert abs(metrics.mean - 20) < 8
        assert abs(metrics.privacy_id_count - 3) < 2


# ---------------------------------------------------------------------------
# Test: VECTOR_SUM aggregation
# ---------------------------------------------------------------------------


class TestVectorSumAggregation:
    """Aggregate VECTOR_SUM metric end-to-end."""

    def test_vector_sum_aggregates_vectors_per_partition(self):
        """A user computes DP vector sum across contributions.

        Each value is a numpy array; the result should approximate the
        element-wise sum of all (clipped) contributions.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=100, total_delta=1e-5
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # Use many users so partition survives private selection
        data = [(f"u{i}", "P", np.array([1.0, 2.0, 3.0])) for i in range(20)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.VECTOR_SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            vector_size=3,
            vector_max_norm=10.0,
            vector_norm_kind=pipeline_dp.aggregate_params.NormKind.L2,
            noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors)
        accountant.compute_budgets()
        result = dict(list(result))

        assert "P" in result
        vec = result["P"].vector_sum
        assert len(vec) == 3
        # 20 users each contribute [1,2,3] with L2 norm sqrt(14)~=3.74 < 10 (no
        # clipping); at total_epsilon=100 the noised sum stays close to [20,40,60].
        assert abs(vec[0] - 20) < 5
        assert abs(vec[1] - 40) < 8
        assert abs(vec[2] - 60) < 10


# ---------------------------------------------------------------------------
# Test: Private partition selection
# ---------------------------------------------------------------------------


class TestPrivatePartitionSelection:
    """Test partition selection without public partitions."""

    def test_private_partitions_filters_rare_partitions(self):
        """Without public partitions, partitions with too few users are dropped.

        A partition contributed to by a single user must not survive private
        partition selection at a tiny thresholding delta, while a
        heavily-contributed partition does.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        # A tiny total_delta makes the single-user keep-probability negligible,
        # so the "rare" partition is reliably filtered out.
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10, total_delta=1e-9
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # Partition "popular" has 20 distinct users; "rare" has 1 user.
        data = [(f"u{i}", "popular", 1) for i in range(20)]
        data.append(("lonely_user", "rare", 1))

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=2,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
            partition_selection_strategy=pipeline_dp.PartitionSelectionStrategy.TRUNCATED_GEOMETRIC,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors)
        accountant.compute_budgets()
        result_keys = {k for k, _ in result}

        # The popular partition survives; the single-user partition is dropped.
        assert "popular" in result_keys
        assert "rare" not in result_keys


# ---------------------------------------------------------------------------
# Test: Post-aggregation thresholding
# ---------------------------------------------------------------------------


class TestPostAggregationThresholding:
    """Post-aggregation thresholding drops partitions below a noised privacy_id_count threshold."""

    def test_post_aggregation_thresholding_drops_low_count_partitions(self):
        """A user enables post_aggregation_thresholding.

        Partitions with noised privacy_id_count below the threshold are
        dropped from the output. PRIVACY_ID_COUNT must be in the metrics
        for this mode.

        The keep/drop decision for a partition is inherently stochastic (it
        compares a *noised* privacy_id_count against the threshold), so the
        drop of the 1-user partition is asserted statistically over repeated
        runs rather than as a probability-1 event on a single draw.
        """
        import pipeline_dp

        # "big" has 50 users, "tiny" has 1.
        data = [(f"u{i}", "big", 1.0) for i in range(50)]
        data.append(("sole", "tiny", 1.0))

        params = pipeline_dp.AggregateParams(
            metrics=[
                pipeline_dp.Metrics.COUNT,
                pipeline_dp.Metrics.PRIVACY_ID_COUNT,
            ],
            max_partitions_contributed=2,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
            post_aggregation_thresholding=True,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        n_trials = 20
        tiny_dropped = 0
        for _ in range(n_trials):
            backend = pipeline_dp.LocalBackend()
            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=800, total_delta=1e-5
            )
            engine = pipeline_dp.DPEngine(accountant, backend)

            result = engine.aggregate(
                data,
                params,
                extractors,
                public_partitions=["big", "tiny"],
            )
            accountant.compute_budgets()
            result = dict(list(result))

            # "big" (50 users) survives thresholding on every run, with a
            # noised privacy_id_count near the true value of 50 at eps=800.
            assert "big" in result
            assert abs(result["big"].privacy_id_count - 50) < 10

            if "tiny" not in result:
                tiny_dropped += 1

        # "tiny" (1 user) sits far below the threshold, so it is dropped in the
        # overwhelming majority of runs. Allow at most one rare keep so a single
        # unlucky noise draw does not fail the suite.
        assert tiny_dropped >= n_trials - 1


# ---------------------------------------------------------------------------
# Test: select_partitions standalone
# ---------------------------------------------------------------------------


class TestSelectPartitions:
    """Test DPEngine.select_partitions."""

    def test_select_partitions_returns_partition_keys(self):
        """A user retrieves differentially-private partition keys.

        select_partitions returns only partition keys (not metrics): the
        output is a flat collection of keys, not (key, metrics) pairs. A
        heavily-contributed partition survives; a single-user one is dropped.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10, total_delta=1e-9
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [(f"u{i}", "kept", 1) for i in range(30)]
        data.append(("solo", "dropped", 1))

        params = pipeline_dp.SelectPartitionsParams(
            max_partitions_contributed=2,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.select_partitions(data, params, extractors)
        accountant.compute_budgets()
        partitions = list(result)

        # The result is a flat list of keys (not (key, value) tuples).
        assert all(not isinstance(p, tuple) for p in partitions)
        partition_set = set(partitions)
        assert "kept" in partition_set
        assert "dropped" not in partition_set


# ---------------------------------------------------------------------------
# Test: add_dp_noise on pre-aggregated data
# ---------------------------------------------------------------------------


class TestAddDpNoise:
    """Test DPEngine.add_dp_noise for pre-aggregated data."""

    def test_add_dp_noise_returns_noised_values(self):
        """A user adds DP noise to pre-aggregated values.

        Given pre-computed per-partition sums, add_dp_noise injects
        calibrated noise without any contribution bounding.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=100, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        pre_aggregated = [("A", 100.0), ("B", 200.0)]

        params = pipeline_dp.AddDPNoiseParams(
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
            l0_sensitivity=1,
            linf_sensitivity=300.0,
        )

        result = engine.add_dp_noise(pre_aggregated, params)
        accountant.compute_budgets()
        result = dict(list(result))

        # Laplace scale here is b = linf/eps = 300/100 = 3 (no contribution bounding),
        # so tol=60 (= 20*b) keeps the assertion deterministic (P(|noise|>60) ~ 4e-9)
        # while still rejecting a no-op (returns 0) or a non-DP doubling of the input.
        assert abs(result["A"] - 100) < 60
        assert abs(result["B"] - 200) < 60

    def test_add_dp_noise_with_noise_stddev_output(self):
        """A user requests noise standard deviation alongside the noised value.

        When output_noise_stddev=True, the per-partition result is a
        DpNoiseAdditionResult named tuple exposing the documented fields
        noised_value and noise_stddev (the exact calibration value is covered by
        test_laplace_add_dp_noise_stddev_matches_formula).
        """
        import pipeline_dp
        from pipeline_dp.dp_engine import DpNoiseAdditionResult

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=1, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        pre_aggregated = [("X", 50.0)]

        params = pipeline_dp.AddDPNoiseParams(
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
            l0_sensitivity=1,
            linf_sensitivity=100.0,
            output_noise_stddev=True,
        )

        result = engine.add_dp_noise(pre_aggregated, params)
        accountant.compute_budgets()
        result = dict(list(result))

        r = result["X"]
        assert isinstance(r, DpNoiseAdditionResult)
        # The named tuple exposes exactly the two documented fields.
        assert r._fields == ("noised_value", "noise_stddev")
        assert isinstance(r.noised_value, float)
        assert isinstance(r.noise_stddev, float)
        assert r.noise_stddev > 0


# ---------------------------------------------------------------------------
# Test: Budget accounting
# ---------------------------------------------------------------------------


class TestBudgetAccounting:
    """Test NaiveBudgetAccountant and PLDBudgetAccountant."""

    def test_naive_budget_splits_delta_proportionally(self):
        """NaiveBudgetAccountant splits total_delta across delta-using mechanisms.

        Only mechanisms that use delta (e.g. GAUSSIAN) draw from the total
        delta. Two equal-weight GAUSSIAN mechanisms each get half the total
        epsilon and half the total delta.
        """
        from pipeline_dp.budget_accounting import NaiveBudgetAccountant
        from pipeline_dp.aggregate_params import MechanismType

        accountant = NaiveBudgetAccountant(total_epsilon=2.0, total_delta=1e-4)
        spec1 = accountant.request_budget(MechanismType.GAUSSIAN)
        spec2 = accountant.request_budget(MechanismType.GAUSSIAN)
        accountant.compute_budgets()

        assert abs(spec1.eps - 1.0) < 1e-10
        assert abs(spec2.eps - 1.0) < 1e-10
        assert abs(spec1.delta - 0.5e-4) < 1e-12
        assert abs(spec2.delta - 0.5e-4) < 1e-12

    def test_naive_budget_with_unequal_weights(self):
        """NaiveBudgetAccountant distributes budget by weight when weights differ.

        A mechanism with weight 3 gets 3x the epsilon of one with weight 1.
        """
        from pipeline_dp.budget_accounting import NaiveBudgetAccountant
        from pipeline_dp.aggregate_params import MechanismType

        accountant = NaiveBudgetAccountant(total_epsilon=4.0, total_delta=0)
        spec1 = accountant.request_budget(MechanismType.LAPLACE, weight=1)
        spec2 = accountant.request_budget(MechanismType.LAPLACE, weight=3)
        accountant.compute_budgets()

        assert abs(spec1.eps - 1.0) < 1e-10
        assert abs(spec2.eps - 3.0) < 1e-10

    def test_compute_budgets_can_only_be_called_once(self):
        """Calling compute_budgets() twice raises an error."""
        from pipeline_dp.budget_accounting import NaiveBudgetAccountant
        from pipeline_dp.aggregate_params import MechanismType

        accountant = NaiveBudgetAccountant(total_epsilon=1.0, total_delta=0)
        accountant.request_budget(MechanismType.LAPLACE)
        accountant.compute_budgets()

        with pytest.raises(Exception):
            accountant.compute_budgets()

    def test_budget_scope_normalizes_weights(self):
        """Budget scope normalizes mechanism weights within the scope.

        Two mechanisms inside a scope with weight=1 should together
        consume half the total budget when there is also one mechanism outside.
        """
        from pipeline_dp.budget_accounting import NaiveBudgetAccountant
        from pipeline_dp.aggregate_params import MechanismType

        accountant = NaiveBudgetAccountant(total_epsilon=2.0, total_delta=0)
        spec_outside = accountant.request_budget(MechanismType.LAPLACE)
        with accountant.scope(weight=1):
            spec_inside1 = accountant.request_budget(MechanismType.LAPLACE)
            spec_inside2 = accountant.request_budget(MechanismType.LAPLACE)
        accountant.compute_budgets()

        # Outside and scope each get weight 1, so 1.0 eps each.
        # Inside the scope, two mechanisms split 1.0 -> 0.5 each.
        assert abs(spec_outside.eps - 1.0) < 1e-10
        assert abs(spec_inside1.eps - 0.5) < 1e-10
        assert abs(spec_inside2.eps - 0.5) < 1e-10

    def test_pld_budget_accountant_calibrates_gaussian_noise(self):
        """PLDBudgetAccountant calibrates a single GAUSSIAN mechanism's noise to
        the requested (epsilon, delta) via the PLD composition.

        The reported noise_standard_deviation must be a positive, finite value no
        larger than the classical analytic Gaussian bound
        sqrt(2*ln(1.25/delta))/epsilon (PLD yields a tighter, i.e. smaller, sigma
        than the loose analytic bound).
        """
        from pipeline_dp.budget_accounting import PLDBudgetAccountant
        from pipeline_dp.aggregate_params import MechanismType

        epsilon, delta = 1.0, 1e-5
        pld = PLDBudgetAccountant(total_epsilon=epsilon, total_delta=delta)
        spec = pld.request_budget(MechanismType.GAUSSIAN)
        pld.compute_budgets()

        sigma = spec.noise_standard_deviation
        assert sigma > 0
        assert math.isfinite(sigma)
        # Classical (loose) analytic Gaussian-mechanism sigma upper-bounds the
        # PLD-calibrated optimal sigma.
        classical_sigma = math.sqrt(2 * math.log(1.25 / delta)) / epsilon
        assert sigma <= classical_sigma


# ---------------------------------------------------------------------------
# Test: AggregateParams validation
# ---------------------------------------------------------------------------


class TestAggregateParamsValidation:
    """Parameter validation on AggregateParams construction."""

    def test_sum_without_bounds_raises(self):
        """AggregateParams raises if SUM is requested without value bounds."""
        import pipeline_dp

        with pytest.raises(ValueError):
            pipeline_dp.AggregateParams(
                metrics=[pipeline_dp.Metrics.SUM],
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
            )

    def test_max_contributions_mutual_exclusion(self):
        """Cannot set both max_contributions and max_partitions_contributed."""
        import pipeline_dp

        with pytest.raises(ValueError):
            pipeline_dp.AggregateParams(
                metrics=[pipeline_dp.Metrics.COUNT],
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                max_contributions=5,
            )

    def test_negative_epsilon_rejected(self):
        """NaiveBudgetAccountant rejects non-positive epsilon."""
        import pipeline_dp

        with pytest.raises(ValueError):
            pipeline_dp.NaiveBudgetAccountant(total_epsilon=-1, total_delta=0)

    def test_delta_out_of_range_rejected(self):
        """NaiveBudgetAccountant rejects delta >= 1."""
        import pipeline_dp

        with pytest.raises(ValueError):
            pipeline_dp.NaiveBudgetAccountant(total_epsilon=1, total_delta=1.0)


# ---------------------------------------------------------------------------
# Test: Gaussian noise mechanism
# ---------------------------------------------------------------------------


class TestGaussianNoise:
    """Test Gaussian noise mechanism (requires delta > 0)."""

    def test_gaussian_noise_requires_delta(self):
        """Using GAUSSIAN noise with delta=0 should fail.

        The Gaussian mechanism requires delta > 0 for its privacy guarantee.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=1, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("u1", "A", 1.0)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        with pytest.raises((ValueError, Exception)):
            result = engine.aggregate(
                data,
                params,
                extractors,
                public_partitions=["A"],
            )
            accountant.compute_budgets()
            list(result)

    def test_gaussian_noise_with_delta_succeeds(self):
        """Using GAUSSIAN noise with delta > 0 produces valid results."""
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        # eps=1000 shrinks the Gaussian sigma (the SUM mechanism's sigma ~ 1 here) so
        # the tolerances below hold deterministically; this test is about GAUSSIAN +
        # delta>0 succeeding, not a specific low-eps regime (the delta=0 failure case
        # is covered by test_gaussian_noise_requires_delta).
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=1e-5
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("u1", "A", 10.0), ("u2", "A", 20.0)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT, pipeline_dp.Metrics.SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=30,
            noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["A"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        assert abs(result["A"].count - 2) < 2
        assert abs(result["A"].sum - 30) < 10


# ---------------------------------------------------------------------------
# Test: Explain computation report
# ---------------------------------------------------------------------------


class TestExplainComputationReport:
    """Test the computation explanation/report system."""

    def test_explain_computation_report_contains_stages(self):
        """ExplainComputationReport produces human-readable text describing
        the DP computation stages applied during aggregation.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=1, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("u1", "A", 1)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        from pipeline_dp.report_generator import ExplainComputationReport

        report = ExplainComputationReport()
        engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["A"],
            out_explain_computation_report=report,
        )
        accountant.compute_budgets()

        text = report.text()
        assert isinstance(text, str)
        assert len(text) > 0
        low = text.lower()
        # The report must describe the actual computation graph, not just echo
        # the method name. For this COUNT-with-public-partitions aggregation the
        # graph has the two contribution-bounding stages, the public-partition
        # selection stage, and the count-computation stage.
        assert "computation graph:" in low
        assert "per-partition contribution bounding" in low
        assert "cross-partition contribution bounding" in low
        assert "public partition selection" in low
        assert "computed dp count" in low

    def test_engine_explain_computations_report_lists_all_aggregations(self):
        """DPEngine.explain_computations_report returns one report per
        aggregate() call, each describing its own aggregation.

        Runs two *different* aggregations (a COUNT and a SUM) on one engine and
        checks that the returned reports are per-aggregation: both are non-empty
        and distinct, and each report's computation graph names the metric it
        computed (the COUNT report mentions the count stage, the SUM report the
        sum stage).
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=2, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("u1", "A", 1.0)]
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )
        params_count = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        params_sum = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=10,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )

        engine.aggregate(data, params_count, extractors, public_partitions=["A"])
        engine.aggregate(data, params_sum, extractors, public_partitions=["A"])
        accountant.compute_budgets()

        reports = engine.explain_computations_report()
        assert len(reports) == 2

        texts = [r.text() if hasattr(r, "text") else str(r) for r in reports]
        assert all(isinstance(t, str) and len(t) > 0 for t in texts)
        # The two reports describe two different aggregations, so their bodies
        # must differ and each must name the metric stage it computed.
        assert texts[0] != texts[1]
        lows = [t.lower() for t in texts]
        assert any("computed dp count" in low for low in lows)
        assert any("computed dp sum" in low for low in lows)


# ---------------------------------------------------------------------------
# Test: Noise mechanisms (dp_computations)
# ---------------------------------------------------------------------------


class TestNoiseMechanisms:
    """Test Gaussian noise calibration through the public add_dp_noise surface."""

    def test_gaussian_add_dp_noise_matches_reported_stddev(self):
        """Gaussian noise added via add_dp_noise is unbiased and its empirical
        spread matches the reported noise_stddev.

        Drives the public add_dp_noise(output_noise_stddev=True) path many
        times over a single pre-aggregated partition and checks that (a) the
        sample mean stays near the true value (unbiased) and (b) the sample
        standard deviation matches the noise_stddev the engine reports.
        """
        import pipeline_dp

        true_value = 50.0
        noised = []
        reported_std = None
        for _ in range(400):
            backend = pipeline_dp.LocalBackend()
            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=1.0, total_delta=1e-5
            )
            engine = pipeline_dp.DPEngine(accountant, backend)

            params = pipeline_dp.AddDPNoiseParams(
                noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
                l0_sensitivity=1,
                linf_sensitivity=1.0,
                output_noise_stddev=True,
            )
            result = engine.add_dp_noise([("X", true_value)], params)
            accountant.compute_budgets()
            r = dict(list(result))["X"]
            noised.append(r.noised_value)
            reported_std = r.noise_stddev

        assert reported_std > 0  # noise was actually calibrated
        # Sample mean stays near the true value (Gaussian noise is unbiased).
        assert abs(np.mean(noised) - true_value) < reported_std
        # Empirical spread tracks the reported stddev (within ~25% over 400 draws).
        assert abs(np.std(noised) - reported_std) < 0.25 * reported_std


# ---------------------------------------------------------------------------
# Test: Dataset histograms
# ---------------------------------------------------------------------------


class TestDatasetHistograms:
    """Test histogram computation for parameter tuning."""

    def test_compute_dataset_histograms_returns_all_histogram_types(self):
        """compute_dataset_histograms returns a DatasetHistograms object
        containing histograms for L0 contributions, Linf contributions,
        partition counts, etc.
        """
        import pipeline_dp
        from pipeline_dp.dataset_histograms.computing_histograms import (
            compute_dataset_histograms,
        )
        from pipeline_dp.dataset_histograms.histograms import (
            DatasetHistograms,
            HistogramType,
        )

        backend = pipeline_dp.LocalBackend()

        data = [
            ("u1", "A", 10),
            ("u1", "B", 20),
            ("u2", "A", 30),
            ("u2", "A", 40),
            ("u3", "B", 50),
        ]

        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = compute_dataset_histograms(data, extractors, backend)
        histograms = list(result)[0]

        assert isinstance(histograms, DatasetHistograms)
        l0 = histograms.l0_contributions_histogram
        assert l0 is not None
        # 3 distinct privacy IDs (u1, u2, u3) → L0 histogram total_count == 3.
        assert l0.total_count() == 3

    def test_linf_contributions_histogram_counts_id_partition_pairs(self):
        """The Linf contributions histogram bins (privacy_id, partition) pairs:
        total_count() equals the number of distinct such pairs and total_sum()
        equals the total number of contributions across those pairs.
        """
        import pipeline_dp
        from pipeline_dp.dataset_histograms.computing_histograms import (
            compute_dataset_histograms,
        )

        backend = pipeline_dp.LocalBackend()

        # 4 distinct (privacy_id, partition) pairs, each with one contribution:
        # (u1,A), (u1,B), (u2,A), (u3,C).
        data = [
            ("u1", "A", 1),
            ("u1", "B", 2),
            ("u2", "A", 3),
            ("u3", "C", 4),
        ]

        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = compute_dataset_histograms(data, extractors, backend)
        histograms = list(result)[0]

        linf = histograms.linf_contributions_histogram
        # One bin counted per (privacy_id, partition) pair → 4 pairs total.
        assert linf.total_count() == 4
        # Each pair has exactly one contribution → 4 contributions total.
        assert linf.total_sum() == 4


# ---------------------------------------------------------------------------
# Test: Partition selection strategies
# ---------------------------------------------------------------------------


class TestPartitionSelectionStrategies:
    """Test that different partition selection strategies work end-to-end."""

    def test_laplace_thresholding_partition_selection(self):
        """Laplace thresholding partition selection keeps popular partitions
        and drops rare ones.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10, total_delta=1e-9
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [(f"u{i}", "popular", 1) for i in range(50)]
        data.append(("solo", "rare", 1))

        params = pipeline_dp.SelectPartitionsParams(
            max_partitions_contributed=2,
            partition_selection_strategy=pipeline_dp.PartitionSelectionStrategy.LAPLACE_THRESHOLDING,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.select_partitions(data, params, extractors)
        accountant.compute_budgets()
        partitions = set(list(result))

        assert "popular" in partitions
        assert "rare" not in partitions

    def test_gaussian_thresholding_partition_selection(self):
        """Gaussian thresholding partition selection keeps popular partitions
        and drops rare ones.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10, total_delta=1e-9
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [(f"u{i}", "popular", 1) for i in range(50)]
        data.append(("solo", "rare", 1))

        params = pipeline_dp.SelectPartitionsParams(
            max_partitions_contributed=2,
            partition_selection_strategy=pipeline_dp.PartitionSelectionStrategy.GAUSSIAN_THRESHOLDING,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.select_partitions(data, params, extractors)
        accountant.compute_budgets()
        partitions = set(list(result))

        assert "popular" in partitions
        assert "rare" not in partitions


# ---------------------------------------------------------------------------
# Test: max_contributions (combined L0/Linf bounding)
# ---------------------------------------------------------------------------


class TestMaxContributions:
    """Test the max_contributions parameter (alternative to separate L0/Linf)."""

    def test_max_contributions_limits_total_records_per_user(self):
        """With max_contributions=3, a user contributing 10 records (each value
        2.0) across partitions has at most 3 records kept total across all
        partitions. The single cross-partition bound governs both the total
        COUNT (~3) and the total SUM (~6 = 3 kept records * 2.0).
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("user1", f"p{i % 3}", 2.0) for i in range(10)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT, pipeline_dp.Metrics.SUM],
            max_contributions=3,
            min_value=0,
            max_value=2,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["p0", "p1", "p2"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        # With eps=1000, noise is ~0. Total bounded to 3 records.
        total_count = sum(v.count for v in result.values())
        assert abs(total_count - 3) < 2
        # Same bound caps the total SUM: 3 kept records * value 2.0 = 6.
        total_sum = sum(v.sum for v in result.values())
        assert abs(total_sum - 6.0) < 4


# ---------------------------------------------------------------------------
# Test: Contribution bounds already enforced
# ---------------------------------------------------------------------------


class TestContributionBoundsAlreadyEnforced:
    """Test aggregate with contribution_bounds_already_enforced=True."""

    def test_skips_bounding_when_already_enforced(self):
        """When contribution_bounds_already_enforced=True, the engine skips
        contribution bounding and directly aggregates. This is useful for
        pre-processed data where bounding was done externally.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # Pre-bounded data: each row is already one contribution
        data = [
            (None, "A", 10.0),
            (None, "A", 20.0),
            (None, "B", 30.0),
        ]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT, pipeline_dp.Metrics.SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=5,
            min_value=0,
            max_value=50,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
            contribution_bounds_already_enforced=True,
            public_partitions_already_filtered=True,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["A", "B"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        # No bounding -> all rows kept. A has count=2, sum=30; B has count=1, sum=30.
        # SUM shares eps=1000 with COUNT (b = max_value/eps = 50/500 = 0.5); tol=10
        # (= 20*b) keeps the no-bounding check deterministic while still pinning the
        # sum near 30 (rejects a result that wrongly applied clipping/bounding).
        assert abs(result["A"].count - 2) < 1
        assert abs(result["A"].sum - 30) < 10
        assert abs(result["B"].count - 1) < 1
        assert abs(result["B"].sum - 30) < 10


# ---------------------------------------------------------------------------
# Test: Histogram error estimator
# ---------------------------------------------------------------------------


class TestHistogramErrorEstimator:
    """Test the error estimation system for parameter tuning."""

    def test_error_estimator_returns_finite_rmse(self):
        """ErrorEstimator.estimate_rmse returns the deterministic RMSE estimate.

        The estimate is fully determined by the bounds and data (no sampling).
        Here every user contributes to at most 2 partitions and at most once per
        partition, so the chosen bounds (l0=2, linf=1) drop no data: the dropped
        ratio is 0 and the estimate collapses to the per-partition Laplace noise
        std sqrt(2)*l0*linf/eps = sqrt(2)*2*1/1 = 2*sqrt(2).
        """
        import pipeline_dp
        from pipeline_dp.dataset_histograms.computing_histograms import (
            compute_dataset_histograms,
        )
        from pipeline_dp.dataset_histograms.histogram_error_estimator import (
            create_estimator_for_count_and_privacy_id_count,
        )
        from pipeline_dp.aggregate_params import NoiseKind, Metrics

        backend = pipeline_dp.LocalBackend()

        data = [
            ("u1", "A", 1),
            ("u1", "B", 2),
            ("u2", "A", 3),
            ("u2", "B", 4),
            ("u3", "A", 5),
        ]
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = compute_dataset_histograms(data, extractors, backend)
        histograms = list(result)[0]

        estimator = create_estimator_for_count_and_privacy_id_count(
            histograms,
            epsilon=1.0,
            delta=None,
            metric=Metrics.COUNT,
            noise=NoiseKind.LAPLACE,
        )

        rmse = estimator.estimate_rmse(l0_bound=2, linf_bound=1)
        # No data dropped → RMSE equals the per-partition Laplace noise std.
        expected = math.sqrt(2) * 2 * 1 / 1.0
        assert rmse == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Test: min/max sum per partition bounds
# ---------------------------------------------------------------------------


class TestSumPerPartitionBounds:
    """Test sum aggregation with per-partition sum bounds."""

    def test_sum_with_per_partition_bounds(self):
        """A user sets min_sum_per_partition and max_sum_per_partition
        instead of per-contribution min_value/max_value. The total sum
        per partition is clipped to the specified range.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # Single user contributes total sum = 150 to partition "S".
        data = [
            ("u1", "S", 50.0),
            ("u1", "S", 50.0),
            ("u1", "S", 50.0),
        ]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=5,
            min_sum_per_partition=-100,
            max_sum_per_partition=100,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["S"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        # Sum is clipped to max_sum_per_partition=100
        assert abs(result["S"].sum - 100) < 5


# ---------------------------------------------------------------------------
# Test: Multiple aggregations sharing a budget
# ---------------------------------------------------------------------------


class TestMultipleAggregationsSharedBudget:
    """Test that multiple aggregate() calls share the total budget correctly."""

    def test_two_aggregations_split_budget(self):
        """Two aggregate() calls on the same engine share the total epsilon.

        Each aggregation gets half the budget, so noise is higher than if
        one aggregation used the full budget. Both should still produce
        reasonable results with high total epsilon.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=200, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [
            ("u1", "A", 10.0),
            ("u2", "A", 20.0),
            ("u3", "B", 30.0),
        ]
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        params_count = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=2,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        params_sum = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.SUM],
            max_partitions_contributed=2,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=50,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )

        result_count = engine.aggregate(
            data, params_count, extractors, public_partitions=["A", "B"]
        )
        result_sum = engine.aggregate(
            data, params_sum, extractors, public_partitions=["A", "B"]
        )
        accountant.compute_budgets()

        counts = dict(list(result_count))
        sums = dict(list(result_sum))

        assert abs(counts["A"].count - 2) < 2
        assert abs(counts["B"].count - 1) < 2
        # The SUM aggregation gets half of eps=200 (b = max_value/eps = 50/100 = 0.5
        # per partition); tol=20 (= 40*b) keeps the budget-sharing check deterministic
        # while still rejecting a wrong sum (true 30; tol admits only [10, 50]).
        assert abs(sums["A"].sum - 30) < 20
        assert abs(sums["B"].sum - 30) < 20

        reports = engine.explain_computations_report()
        assert len(reports) == 2


# ---------------------------------------------------------------------------
# Test: Mean computation with midpoint normalization
# ---------------------------------------------------------------------------


class TestMeanMidpointNormalization:
    """Test that mean computation clips values to the specified bounds."""

    def test_mean_with_values_outside_bounds_are_clipped(self):
        """Values outside [min_value, max_value] are clipped before mean is computed.

        If all users contribute values above max_value, the clipped values
        are all max_value, so the mean should be close to max_value.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=500, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [(f"u{i}", "C", 100.0) for i in range(10)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.MEAN],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=10,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors, public_partitions=["C"])
        accountant.compute_budgets()
        result = dict(list(result))

        # All clipped to 10, so mean ≈ 10
        assert abs(result["C"].mean - 10.0) < 2.0


# ---------------------------------------------------------------------------
# Test: Combined contribution bounding + value clipping
# ---------------------------------------------------------------------------


class TestBoundingAndClippingInteraction:
    """Test that contribution bounding and value clipping compose correctly."""

    def test_cross_partition_bounding_with_sum_clipping(self):
        """A user contributes to 5 partitions with values exceeding max_value.

        With max_partitions_contributed=2 and max_value=10, the user's
        influence is limited in two ways: only 2 of 5 partitions are kept,
        and within each kept partition, values are clipped to 10.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("user1", f"p{i}", 999.0) for i in range(5)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.SUM, pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=2,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=10,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=[f"p{i}" for i in range(5)],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        kept_partitions = [k for k, v in result.items() if v.count > 0.5]
        assert len(kept_partitions) <= 2

        for k in kept_partitions:
            assert abs(result[k].sum - 10.0) < 2


# ---------------------------------------------------------------------------
# Test: Combiner accumulator merge correctness
# ---------------------------------------------------------------------------


class TestCombinerMerging:
    """Test that CompoundCombiner merges accumulators correctly across partitions."""

    def test_count_combiner_merge_keeps_per_partition_totals_distinct(self):
        """Accumulators must merge per partition key, not across keys.

        Many partitions are populated with different, known per-partition
        contribution counts in a single aggregation. A correct merge keeps each
        partition's accumulator separate and yields that partition's own count;
        a merge that mixed partition keys (or summed everything into one bucket)
        would not reproduce the distinct per-partition totals checked here.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # Partition pk{j} gets exactly (j+1) distinct single-record users, so the
        # expected per-partition counts are 1, 2, 3, 4, 5 across 5 partitions.
        data = []
        for j in range(5):
            for u in range(j + 1):
                data.append((f"p{j}_u{u}", f"pk{j}", 1.0))

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        public_pks = [f"pk{j}" for j in range(5)]
        result = engine.aggregate(data, params, extractors, public_partitions=public_pks)
        accountant.compute_budgets()
        result = dict(list(result))

        # With eps=1000 noise is ~0; each partition recovers its own count.
        for j in range(5):
            assert abs(result[f"pk{j}"].count - (j + 1)) < 2, (
                f"pk{j} count {result[f'pk{j}'].count} not near {j + 1} — "
                f"per-partition accumulator merge likely broken"
            )


# ---------------------------------------------------------------------------
# Test: Negative value handling in SUM
# ---------------------------------------------------------------------------


class TestNegativeValues:
    """Test that negative values are handled correctly in SUM."""

    def test_sum_with_negative_min_value(self):
        """SUM with min_value < 0 correctly handles negative contributions.

        Values are clipped to [min_value, max_value]. Negative values
        within the range should reduce the sum.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [
            ("u1", "N", -5.0),
            ("u2", "N", 10.0),
            ("u3", "N", -3.0),
        ]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=-10,
            max_value=10,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors, public_partitions=["N"])
        accountant.compute_budgets()
        result = dict(list(result))

        # True sum = -5 + 10 + (-3) = 2
        assert abs(result["N"].sum - 2.0) < 3


# ---------------------------------------------------------------------------
# Test: Empty public partitions get zero-valued metrics
# ---------------------------------------------------------------------------


class TestEmptyPublicPartitions:
    """Test that public partitions with no data get appropriate metric values."""

    def test_empty_partition_has_near_zero_count(self):
        """A public partition with no data contributions should have
        count ≈ 0 (just noise around zero).
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=100, total_delta=0)
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("u1", "present", 5.0), ("u2", "present", 10.0)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT, pipeline_dp.Metrics.SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=20,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data,
            params,
            extractors,
            public_partitions=["present", "empty"],
        )
        accountant.compute_budgets()
        result = dict(list(result))

        assert "present" in result
        assert "empty" in result
        assert abs(result["present"].count - 2) < 2
        assert abs(result["empty"].count) < 2
        assert abs(result["empty"].sum) < 10


# ---------------------------------------------------------------------------
# Test: Variance with all four metrics (count, sum, mean, variance)
# ---------------------------------------------------------------------------


class TestVarianceWithAllMetrics:
    """Test VARIANCE computed alongside COUNT, SUM, MEAN in one call."""

    def test_variance_with_all_scalar_metrics(self):
        """A user computes VARIANCE, COUNT, SUM, and MEAN in a single
        aggregation. The variance combiner splits its budget 3 ways
        (count, normalized_sum, normalized_sum_of_squares) and the
        returned named tuple must include all four fields with
        numerically consistent values.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=2000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # 20 users contribute values uniformly from 1..20
        data = [(f"u{i}", "W", float(i)) for i in range(1, 21)]

        params = pipeline_dp.AggregateParams(
            metrics=[
                pipeline_dp.Metrics.VARIANCE,
                pipeline_dp.Metrics.COUNT,
                pipeline_dp.Metrics.SUM,
                pipeline_dp.Metrics.MEAN,
            ],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=20,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors, public_partitions=["W"])
        accountant.compute_budgets()
        result = dict(list(result))
        m = result["W"]

        assert abs(m.count - 20) < 3
        assert abs(m.sum - 210) < 30
        assert abs(m.mean - 10.5) < 2
        # Population variance of 1..20 = 33.25
        assert abs(m.variance - 33.25) < 10
        # Consistency: sum ≈ mean * count
        assert abs(m.sum - m.mean * m.count) < 30


# ---------------------------------------------------------------------------
# Test: Laplace noise scale exactly matches sensitivity/epsilon
# ---------------------------------------------------------------------------


class TestLaplaceNoiseCalibration:
    """Verify Laplace noise scale is calibrated to sensitivity/epsilon."""

    def test_laplace_add_dp_noise_stddev_matches_formula(self):
        """The Laplace noise reported by add_dp_noise has std = sqrt(2)*b with
        b = l1/eps = (l0*linf)/eps, across several (eps, l0, linf) inputs.

        Verifies the calibration formula through the public
        add_dp_noise(output_noise_stddev=True) surface (which reports the
        mechanism std) rather than constructing the internal mechanism.
        """
        import pipeline_dp

        for eps, l0, linf in [(0.5, 1, 2.0), (1.0, 1, 1.0), (2.0, 2, 2.0), (0.1, 1, 10.0)]:
            backend = pipeline_dp.LocalBackend()
            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=eps, total_delta=0
            )
            engine = pipeline_dp.DPEngine(accountant, backend)

            params = pipeline_dp.AddDPNoiseParams(
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                l0_sensitivity=l0,
                linf_sensitivity=linf,
                output_noise_stddev=True,
            )
            result = engine.add_dp_noise([("X", 0.0)], params)
            accountant.compute_budgets()
            r = dict(list(result))["X"]

            expected_b = (l0 * linf) / eps
            expected_std = math.sqrt(2) * expected_b
            assert r.noise_stddev == pytest.approx(
                expected_std, rel=1e-6
            ), f"eps={eps}, l0={l0}, linf={linf}: expected std={expected_std}, got {r.noise_stddev}"


# ---------------------------------------------------------------------------
# Test: Gaussian sigma computation
# ---------------------------------------------------------------------------


class TestGaussianSigmaComputation:
    """Verify Gaussian noise std satisfies the (epsilon, delta) guarantee."""

    def test_gaussian_add_dp_noise_stddev_monotonic(self):
        """The Gaussian noise_stddev reported by add_dp_noise grows linearly with
        L2 sensitivity and shrinks as epsilon increases.

        Checks the calibration behavior through the public
        add_dp_noise(output_noise_stddev=True) surface, varying the
        sensitivity/epsilon supplied to AddDPNoiseParams.
        """
        import pipeline_dp

        def reported_std(eps, l2_sensitivity):
            backend = pipeline_dp.LocalBackend()
            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=eps, total_delta=1e-5
            )
            engine = pipeline_dp.DPEngine(accountant, backend)
            params = pipeline_dp.AddDPNoiseParams(
                noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
                l0_sensitivity=1,
                linf_sensitivity=l2_sensitivity,
                l2_sensitivity=l2_sensitivity,
                output_noise_stddev=True,
            )
            result = engine.add_dp_noise([("X", 0.0)], params)
            accountant.compute_budgets()
            return dict(list(result))["X"].noise_stddev

        # std scales linearly with L2 sensitivity (eps, delta fixed).
        std_low = reported_std(eps=1.0, l2_sensitivity=1.0)
        std_high = reported_std(eps=1.0, l2_sensitivity=10.0)
        assert std_high > std_low
        assert abs(std_high / std_low - 10.0) < 0.5

        # std decreases as epsilon increases (sensitivity, delta fixed).
        std_tight = reported_std(eps=0.1, l2_sensitivity=1.0)
        std_loose = reported_std(eps=10.0, l2_sensitivity=1.0)
        assert std_tight > std_loose


# ---------------------------------------------------------------------------
# Test: L1/L2 sensitivity derivation and validation
# ---------------------------------------------------------------------------


class TestSensitivityDerivation:
    """L1/L2 sensitivities are derived from (l0, linf), and checked when given."""

    def test_sensitivities_are_derived_and_validated(self):
        """A user supplies only (l0, linf) and lets the library derive L1/L2.

        Observed through the public add_dp_noise(output_noise_stddev=True)
        surface: Gaussian noise is calibrated to the derived L2, so raising l0
        from 1 to 4 doubles the noise std. An explicitly supplied sensitivity
        that contradicts the derived one is rejected.
        """
        import pipeline_dp

        def reported_std(l0):
            backend = pipeline_dp.LocalBackend()
            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=1.0, total_delta=1e-5
            )
            engine = pipeline_dp.DPEngine(accountant, backend)
            params = pipeline_dp.AddDPNoiseParams(
                noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
                l0_sensitivity=l0,
                linf_sensitivity=1.0,
                output_noise_stddev=True,
            )
            result = engine.add_dp_noise([("X", 0.0)], params)
            accountant.compute_budgets()
            return dict(list(result))["X"].noise_stddev

        # Gaussian noise is calibrated to L2 = sqrt(l0)*linf, so l0=4 gives 2x
        # the noise of l0=1 (an L1-style l0*linf derivation would give 4x).
        ratio = reported_std(4) / reported_std(1)
        assert abs(ratio - 2.0) < 0.1, (
            f"noise std ratio {ratio} for l0=4 vs l0=1: L2 sensitivity does not "
            f"look like sqrt(l0)*linf"
        )

        # An explicit L1 that contradicts l0*linf is inconsistent and rejected.
        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=1.0, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)
        with pytest.raises(ValueError):
            result = engine.add_dp_noise(
                [("X", 0.0)],
                pipeline_dp.AddDPNoiseParams(
                    noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                    l0_sensitivity=3,
                    linf_sensitivity=10.0,
                    l1_sensitivity=5.0,
                ),
            )
            accountant.compute_budgets()
            list(result)


# ---------------------------------------------------------------------------
# Test: Vector sum with L1 norm clipping
# ---------------------------------------------------------------------------


class TestVectorSumL1Norm:
    """Test vector sum aggregation with L1 norm clipping."""

    def test_vector_sum_clips_by_l1_norm(self):
        """With vector_norm_kind=L1 and vector_max_norm=5, a vector with
        L1 norm > 5 should be scaled down to have L1 norm = 5 before
        aggregation.
        """
        import pipeline_dp
        from pipeline_dp.aggregate_params import NormKind

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=100, total_delta=1e-5
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # 30 users each contribute [10, 10, 10] (L1 norm = 30).
        # After L1 clipping to max_norm=5, each vector is scaled to
        # [10/30*5, 10/30*5, 10/30*5] = [5/3, 5/3, 5/3].
        # Sum of 30 clipped vectors ≈ [50, 50, 50].
        data = [(f"u{i}", "V", np.array([10.0, 10.0, 10.0])) for i in range(30)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.VECTOR_SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            vector_size=3,
            vector_max_norm=5.0,
            vector_norm_kind=NormKind.L1,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors)
        accountant.compute_budgets()
        result = dict(list(result))

        assert "V" in result
        vec = result["V"].vector_sum
        assert len(vec) == 3
        # Each element should be ≈ 50 (not 300 which would be unclipped)
        for v in vec:
            assert v < 80, f"Vector element {v} too large — L1 clipping not applied"
            assert v > 15, f"Vector element {v} too small"


# ---------------------------------------------------------------------------
# Test: Vector sum with Linf norm clipping
# ---------------------------------------------------------------------------


class TestVectorSumLinfNorm:
    """Test vector sum aggregation with Linf norm clipping."""

    def test_vector_sum_clips_by_linf_norm(self):
        """With vector_norm_kind=Linf and vector_max_norm=2, each element
        of the vector is independently clipped to [-2, 2].
        """
        import pipeline_dp
        from pipeline_dp.aggregate_params import NormKind

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=100, total_delta=1e-5
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # 10 users each contribute [100, -100, 0.5].
        # After Linf clipping to max_norm=2: [2, -2, 0.5].
        # Sum = [20, -20, 5].
        data = [(f"u{i}", "L", np.array([100.0, -100.0, 0.5])) for i in range(10)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.VECTOR_SUM],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            vector_size=3,
            vector_max_norm=2.0,
            vector_norm_kind=NormKind.Linf,
            noise_kind=pipeline_dp.NoiseKind.GAUSSIAN,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors)
        accountant.compute_budgets()
        result = dict(list(result))

        assert "L" in result
        vec = result["L"].vector_sum
        # Linf-clipped: each element was clipped to [-2,2], then summed
        assert abs(vec[0] - 20.0) < 5
        assert abs(vec[1] - (-20.0)) < 5
        assert abs(vec[2] - 5.0) < 3


# ---------------------------------------------------------------------------
# Test: Budget weight parameter affects noise
# ---------------------------------------------------------------------------


class TestBudgetWeight:
    """Test that budget_weight on AggregateParams affects budget allocation."""

    def test_higher_weight_gets_more_budget_less_noise(self):
        """Two aggregations with different budget_weight values.

        The one with higher weight should get more of the total budget,
        resulting in lower noise. We verify this by running many times
        and comparing variance of the noised count.
        """
        import pipeline_dp

        results_high = []
        results_low = []

        # 100 runs (not 30): the assertion compares two sample variances, and the
        # sample-variance estimator is itself noisy. At 30 runs the var_high < var_low
        # check fails ~0.25% of the time; 100 runs drives that below 1e-6 (the true
        # variances differ by ~9x, so the estimators separate cleanly at this n).
        for _ in range(100):
            backend = pipeline_dp.LocalBackend()
            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=2, total_delta=0
            )
            engine = pipeline_dp.DPEngine(accountant, backend)

            data = [("u1", "X", 1.0)]
            extractors = pipeline_dp.DataExtractors(
                privacy_id_extractor=lambda x: x[0],
                partition_extractor=lambda x: x[1],
                value_extractor=lambda x: x[2],
            )

            params_high = pipeline_dp.AggregateParams(
                metrics=[pipeline_dp.Metrics.COUNT],
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                budget_weight=3,
            )
            params_low = pipeline_dp.AggregateParams(
                metrics=[pipeline_dp.Metrics.COUNT],
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                budget_weight=1,
            )

            r_high = engine.aggregate(
                data, params_high, extractors, public_partitions=["X"]
            )
            r_low = engine.aggregate(
                data, params_low, extractors, public_partitions=["X"]
            )
            accountant.compute_budgets()

            results_high.append(dict(list(r_high))["X"].count)
            results_low.append(dict(list(r_low))["X"].count)

        # Higher weight → more budget → less noise → lower variance
        var_high = np.var(results_high)
        var_low = np.var(results_low)
        assert var_high < var_low, (
            f"Higher-weight aggregation has more variance ({var_high}) "
            f"than lower-weight ({var_low})"
        )


# ---------------------------------------------------------------------------
# Test: Sensitivity computation for SUM uses correct formula
# ---------------------------------------------------------------------------


class TestSensitivityForSum:
    """Verify that SUM sensitivity is computed from the contribution bounds."""

    def test_sum_sensitivity_scales_with_max_value(self):
        """SUM with max_value=100 should produce ~10x more noise than
        SUM with max_value=10, all else equal. We verify by comparing
        the variance of noised sums across many runs.
        """
        import pipeline_dp

        def run_sum_eval(max_val, n_runs=100):
            results = []
            for _ in range(n_runs):
                backend = pipeline_dp.LocalBackend()
                accountant = pipeline_dp.NaiveBudgetAccountant(
                    total_epsilon=1, total_delta=0
                )
                engine = pipeline_dp.DPEngine(accountant, backend)
                data = [("u1", "X", 5.0)]
                params = pipeline_dp.AggregateParams(
                    metrics=[pipeline_dp.Metrics.SUM],
                    max_partitions_contributed=1,
                    max_contributions_per_partition=1,
                    min_value=0,
                    max_value=max_val,
                    noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                )
                extractors = pipeline_dp.DataExtractors(
                    privacy_id_extractor=lambda x: x[0],
                    partition_extractor=lambda x: x[1],
                    value_extractor=lambda x: x[2],
                )
                r = engine.aggregate(data, params, extractors, public_partitions=["X"])
                accountant.compute_budgets()
                results.append(dict(list(r))["X"].sum)
            return np.var(results)

        var_small = run_sum_eval(10)
        var_large = run_sum_eval(100)

        # Laplace variance = 2*b^2, b = sensitivity/eps.
        # sensitivity ∝ max_value, so variance ∝ max_value^2.
        # var_large / var_small should be ≈ 100 (10^2).
        ratio = var_large / max(var_small, 1e-10)
        assert ratio > 20, (
            f"Noise variance ratio {ratio} too low — SUM sensitivity "
            f"doesn't scale correctly with max_value"
        )


# ---------------------------------------------------------------------------
# Test: Per-partition sampling interacts correctly with COUNT
# ---------------------------------------------------------------------------


class TestPerPartitionSamplingCount:
    """Verify per-partition sampling bounds the count correctly."""

    def test_per_partition_sampling_bounds_count_exactly(self):
        """With max_contributions_per_partition=K, one user contributing
        N >> K records should have their count bounded to K.
        Multiple users contributing to the same partition should have
        their counts independently bounded and then summed.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        K = 3
        # User A contributes 20 records, user B contributes 15 records.
        data = [("A", "P", 1.0) for _ in range(20)]
        data += [("B", "P", 1.0) for _ in range(15)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=1,
            max_contributions_per_partition=K,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors, public_partitions=["P"])
        accountant.compute_budgets()
        result = dict(list(result))

        # Each user bounded to K=3 contributions, total = 2*K = 6
        assert abs(result["P"].count - 2 * K) < 1


# ---------------------------------------------------------------------------
# Test: Cross-partition bounding preserves exact count
# ---------------------------------------------------------------------------


class TestCrossPartitionExactCount:
    """Verify cross-partition sampling keeps exactly max_partitions_contributed."""

    def test_user_contributing_many_partitions_bounded_exactly(self):
        """A single user contributing to 20 partitions with
        max_partitions_contributed=5 should have exactly 5 partitions
        with non-zero count (at high epsilon where noise is negligible).
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [("sole_user", f"p{i}", 1.0) for i in range(20)]
        public_pks = [f"p{i}" for i in range(20)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.COUNT],
            max_partitions_contributed=5,
            max_contributions_per_partition=1,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(
            data, params, extractors, public_partitions=public_pks
        )
        accountant.compute_budgets()
        result = dict(list(result))

        nonzero = sum(1 for v in result.values() if v.count > 0.5)
        assert nonzero == 5, f"Expected exactly 5 partitions with data, got {nonzero}"


# ---------------------------------------------------------------------------
# Test: Mean denormalization produces values in [min, max] range
# ---------------------------------------------------------------------------


class TestMeanDenormalization:
    """Test that DP mean output is properly denormalized back to the original scale."""

    def test_mean_respects_value_range(self):
        """DP mean is denormalized back to the original (large-offset) value scale.

        The data mean (149) differs from the bounds midpoint (150), so an
        implementation that fails to denormalize — or collapses to the
        midpoint — would not land on the true mean. With high epsilon the
        reported mean must match the true data mean closely.
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=5000, total_delta=0
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        # 50 users contribute values 100, 102, ..., 198 → true mean 149.0
        # (distinct from the [100,200] midpoint of 150.0).
        data = [(f"u{i}", "D", 100.0 + 2.0 * i) for i in range(50)]

        params = pipeline_dp.AggregateParams(
            metrics=[pipeline_dp.Metrics.MEAN],
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=100,
            max_value=200,
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.aggregate(data, params, extractors, public_partitions=["D"])
        accountant.compute_budgets()
        result = dict(list(result))

        mean_val = result["D"].mean
        # True mean is 149.0 on the original scale; must be recovered closely.
        assert abs(mean_val - 149.0) < 5, (
            f"Mean {mean_val} not near true mean 149 — denormalization to the "
            f"original value scale likely broken"
        )


# ---------------------------------------------------------------------------
# Test: LocalBackend pipeline operation contract
# ---------------------------------------------------------------------------


class TestLocalBackendOperations:
    """LocalBackend implements the documented PipelineBackend operations."""

    def test_local_backend_operations_return_documented_shapes(self):
        """A user drives the exported LocalBackend directly.

        Each operation takes (col, ..., stage_name) and produces the documented
        output: map/filter/flat_map element-wise, group_by_key as
        (key, [values]), reduce_per_key folded with a binary function,
        keys/values projected out of pairs, and sample_fixed_per_key as
        (key, [at most n values]).
        """
        import pipeline_dp

        backend = pipeline_dp.LocalBackend()

        col = [1, 2, 3, 4, 5]
        assert list(backend.map(col, lambda x: x * 2, "double")) == [2, 4, 6, 8, 10]
        assert list(backend.filter(col, lambda x: x % 2 == 0, "evens")) == [2, 4]

        expanded = list(backend.flat_map([1, 2, 3], lambda x: [x, x * 10], "expand"))
        assert sorted(expanded) == [1, 2, 3, 10, 20, 30]

        pairs = [("a", 1), ("b", 2), ("a", 3)]
        grouped = dict((k, sorted(v)) for k, v in backend.group_by_key(pairs, "grp"))
        assert grouped == {"a": [1, 3], "b": [2]}

        assert dict(backend.reduce_per_key(pairs, lambda x, y: x + y, "sum")) == {
            "a": 4,
            "b": 2,
        }

        assert sorted(backend.keys(pairs, "k")) == ["a", "a", "b"]
        assert sorted(backend.values(pairs, "v")) == [1, 2, 3]

        # sample_fixed_per_key groups by key and caps each group at n values.
        sampled = list(
            backend.sample_fixed_per_key([("a", i) for i in range(10)], 3, "sample")
        )
        assert len(sampled) == 1
        key, values = sampled[0]
        assert key == "a"
        assert len(values) == 3
        assert set(values) <= set(range(10))


# ===========================================================================
# BEAM BACKEND TESTS
# ===========================================================================


class TestBeamCount:
    """Test DP count aggregation via the Beam PrivatePCollection API."""

    def test_beam_count_with_public_partitions(self):
        """A user runs a Beam pipeline to compute DP count per partition.

        Creates a PCollection, wraps it in a PrivatePCollection via
        MakePrivate, applies the Count transform with public partitions,
        and verifies the noised counts approximate the true counts.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, Count

        with TestPipeline() as p:
            data = [
                ("u1", "A", 1),
                ("u1", "A", 2),
                ("u1", "B", 3),
                ("u2", "A", 4),
                ("u2", "B", 5),
                ("u3", "A", 6),
            ]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=100, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            count_params = pipeline_dp.CountParams(
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                max_partitions_contributed=2,
                max_contributions_per_partition=3,
                partition_extractor=lambda x: x[1],
            )

            result = private | Count(
                count_params,
                public_partitions=["A", "B"],
            )

            accountant.compute_budgets()

            # Collect and verify
            class AssertResults(beam.DoFn):
                def process(self, element):
                    pk, count = element
                    if pk == "A":
                        assert abs(count - 4) < 3
                    elif pk == "B":
                        assert abs(count - 2) < 3

            result | "Assert" >> beam.ParDo(AssertResults())


class TestBeamSum:
    """Test DP sum aggregation via the Beam PrivatePCollection API."""

    def test_beam_sum_with_value_clipping(self):
        """A user runs a Beam pipeline to compute DP sum with value clipping.

        Values outside [min_value, max_value] are clipped. The noised sum
        should approximate the clipped true sum.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, Sum

        with TestPipeline() as p:
            data = [
                ("u1", "X", 10.0),
                ("u2", "X", 20.0),
                ("u3", "X", 100.0),  # clipped to 50
            ]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=100, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            sum_params = pipeline_dp.SumParams(
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                min_value=0,
                max_value=50,
                partition_extractor=lambda x: x[1],
                value_extractor=lambda x: x[2],
            )

            result = private | Sum(
                sum_params,
                public_partitions=["X"],
            )

            accountant.compute_budgets()

            # Clipped sum = 10 + 20 + 50 = 80
            class AssertSum(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    assert pk == "X"
                    assert abs(val - 80) < 10, f"Sum {val} not near 80"

            result | "Assert" >> beam.ParDo(AssertSum())


class TestBeamMean:
    """Test DP mean aggregation via the Beam PrivatePCollection API."""

    def test_beam_mean_approximates_true_mean(self):
        """A user computes DP mean through Beam. The result should be close
        to the true mean of the clipped values with high epsilon.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, Mean

        with TestPipeline() as p:
            data = [(f"u{i}", "M", float(i * 10)) for i in range(1, 6)]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=500, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            mean_params = pipeline_dp.MeanParams(
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                min_value=0,
                max_value=50,
                partition_extractor=lambda x: x[1],
                value_extractor=lambda x: x[2],
            )

            result = private | Mean(
                mean_params,
                public_partitions=["M"],
            )

            accountant.compute_budgets()

            # True mean = (10+20+30+40+50)/5 = 30
            class AssertMean(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    assert abs(val - 30) < 10, f"Mean {val} not near 30"

            result | "Assert" >> beam.ParDo(AssertMean())


class TestBeamPrivacyIdCount:
    """Test DP privacy_id_count via Beam."""

    def test_beam_privacy_id_count(self):
        """A user counts distinct privacy IDs per partition using Beam.

        Even with multiple contributions per user, privacy_id_count
        should approximate the number of distinct users.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, PrivacyIdCount

        with TestPipeline() as p:
            data = [
                ("u1", "P", 1),
                ("u1", "P", 2),
                ("u2", "P", 3),
                ("u3", "P", 4),
                ("u3", "P", 5),
                ("u4", "P", 6),
                ("u5", "P", 7),
            ]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=100, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            params = pipeline_dp.PrivacyIdCountParams(
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                max_partitions_contributed=1,
                partition_extractor=lambda x: x[1],
            )

            result = private | PrivacyIdCount(
                params,
                public_partitions=["P"],
            )

            accountant.compute_budgets()

            # 5 distinct users
            class AssertPidCount(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    assert abs(val - 5) < 2, f"PID count {val} not near 5"

            result | "Assert" >> beam.ParDo(AssertPidCount())


class TestBeamSelectPartitions:
    """Test DP partition selection via Beam."""

    def test_beam_select_partitions_keeps_popular(self):
        """A user selects partitions in a DP manner using Beam.

        Partitions with many contributing users should survive selection.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        from apache_beam.testing.util import assert_that
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, SelectPartitions

        with TestPipeline() as p:
            data = [(f"u{i}", "popular", 1) for i in range(30)]
            data.append(("lone", "rare", 1))
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=10, total_delta=1e-3
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            params = pipeline_dp.SelectPartitionsParams(
                max_partitions_contributed=2,
            )

            result = private | SelectPartitions(
                params,
                partition_extractor=lambda x: x[1],
                label="SelectParts",
            )

            accountant.compute_budgets()

            # The 30-user "popular" partition must survive selection; the
            # single-user "rare" partition is dropped with overwhelming
            # probability (mirrors the Spark test_spark_select_partitions check).
            def check_popular_kept(selected):
                assert "popular" in selected, (
                    f"'popular' partition (30 users) was not selected: {selected}"
                )
                assert "rare" not in selected, (
                    f"'rare' partition (1 user) should have been dropped: {selected}"
                )

            assert_that(result, check_popular_kept)


class TestBeamMapFlatMap:
    """Test Map and FlatMap transforms on PrivatePCollection."""

    def test_beam_map_then_count(self):
        """A user applies a Map transform to a PrivatePCollection before
        computing a DP count. The Map should transform the data while
        preserving the privacy ID association.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, Map, Count

        with TestPipeline() as p:
            data = [
                ("u1", "mon", 10),
                ("u1", "tue", 20),
                ("u2", "mon", 30),
                ("u2", "mon", 40),
                ("u3", "tue", 50),
            ]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=100, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            mapped = private | Map(lambda x: (x[1], x[2] * 2))

            count_params = pipeline_dp.CountParams(
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                max_partitions_contributed=2,
                max_contributions_per_partition=3,
                partition_extractor=lambda x: x[0],
            )

            result = mapped | Count(
                count_params,
                public_partitions=["mon", "tue"],
            )

            accountant.compute_budgets()

            class AssertCounts(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    if pk == "mon":
                        assert abs(val - 3) < 2, f"mon count {val} not near 3"
                    elif pk == "tue":
                        assert abs(val - 2) < 2, f"tue count {val} not near 2"

            result | "Assert" >> beam.ParDo(AssertCounts())


class TestBeamBackendOperations:
    """BeamBackend implements the documented PipelineBackend operations."""

    def test_beam_backend_reduce_per_key(self):
        """BeamBackend.reduce_per_key folds a binary function over each key.

        The binary function is turned into a Beam-compatible per-key combiner,
        so summing [("a",1),("b",2),("a",3)] yields [("a",4),("b",2)].
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        from apache_beam.testing.util import assert_that, equal_to
        from pipeline_dp.beam_backend import BeamBackend

        with TestPipeline() as p:
            backend = BeamBackend()

            col = p | "Create" >> beam.Create([("a", 1), ("b", 2), ("a", 3)])

            summed = backend.reduce_per_key(col, lambda x, y: x + y, "Sum")

            assert_that(summed, equal_to([("a", 4), ("b", 2)]))


class TestBeamMultipleAggregations:
    """Test multiple DP aggregations sharing budget in a single Beam pipeline."""

    def test_beam_count_and_sum_share_budget(self):
        """Two DP aggregations (count and sum) on the same PrivatePCollection
        share the total privacy budget. Both should produce valid results.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, Count, Sum

        with TestPipeline() as p:
            data = [
                ("u1", "A", 10.0),
                ("u2", "A", 20.0),
                ("u3", "A", 30.0),
            ]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=200, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            count_params = pipeline_dp.CountParams(
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                partition_extractor=lambda x: x[1],
            )

            sum_params = pipeline_dp.SumParams(
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                min_value=0,
                max_value=50,
                partition_extractor=lambda x: x[1],
                value_extractor=lambda x: x[2],
            )

            count_result = private | Count(count_params, public_partitions=["A"])
            sum_result = private | Sum(sum_params, public_partitions=["A"])

            accountant.compute_budgets()

            class AssertCount(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    assert abs(val - 3) < 2, f"Count {val} not near 3"

            class AssertSum(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    assert abs(val - 60) < 15, f"Sum {val} not near 60"

            count_result | "AssertCount" >> beam.ParDo(AssertCount())
            sum_result | "AssertSum" >> beam.ParDo(AssertSum())


# ===========================================================================
# SPARK BACKEND TESTS
# ===========================================================================

import pytest


@pytest.fixture(scope="module")
def spark_context():
    """Create a SparkContext for the test module, shared across tests."""
    from pyspark import SparkContext, SparkConf

    conf = SparkConf().setMaster("local[1]").setAppName("pipelinedp_test")
    sc = SparkContext.getOrCreate(conf=conf)
    yield sc
    sc.stop()


class TestSparkCount:
    """Test DP count via Spark PrivateRDD."""

    def test_spark_count_with_public_partitions(self, spark_context):
        """A user computes DP count per partition using Spark's PrivateRDD.

        Creates an RDD, wraps it via make_private, calls .count() with
        public partitions, and collects the results.
        """
        import pipeline_dp
        from pipeline_dp.private_spark import make_private

        sc = spark_context
        data = [
            ("u1", "A", 1),
            ("u1", "A", 2),
            ("u1", "B", 3),
            ("u2", "A", 4),
            ("u2", "B", 5),
            ("u3", "A", 6),
        ]
        rdd = sc.parallelize(data)

        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=100, total_delta=0)

        private_rdd = make_private(rdd, accountant, lambda x: x[0])

        count_params = pipeline_dp.CountParams(
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
            max_partitions_contributed=2,
            max_contributions_per_partition=3,
            partition_extractor=lambda x: x[1],
        )

        result = private_rdd.count(count_params, public_partitions=["A", "B"])

        accountant.compute_budgets()
        result_dict = dict(result.collect())

        # A has 4 records, B has 2
        assert abs(result_dict["A"] - 4) < 3
        assert abs(result_dict["B"] - 2) < 3


class TestSparkSum:
    """Test DP sum via Spark PrivateRDD."""

    def test_spark_sum_with_clipping(self, spark_context):
        """A user computes DP sum with value clipping via Spark."""
        import pipeline_dp
        from pipeline_dp.private_spark import make_private

        sc = spark_context
        data = [
            ("u1", "X", 10.0),
            ("u2", "X", 20.0),
            ("u3", "X", 100.0),
        ]
        rdd = sc.parallelize(data)

        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=100, total_delta=0)

        private_rdd = make_private(rdd, accountant, lambda x: x[0])

        sum_params = pipeline_dp.SumParams(
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=50,
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = private_rdd.sum(sum_params, public_partitions=["X"])

        accountant.compute_budgets()
        result_dict = dict(result.collect())

        # 100 clipped to 50: sum = 10 + 20 + 50 = 80
        assert abs(result_dict["X"] - 80) < 10


class TestSparkMean:
    """Test DP mean via Spark PrivateRDD."""

    def test_spark_mean(self, spark_context):
        """A user computes DP mean via Spark."""
        import pipeline_dp
        from pipeline_dp.private_spark import make_private

        sc = spark_context
        data = [(f"u{i}", "M", float(i * 10)) for i in range(1, 6)]
        rdd = sc.parallelize(data)

        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=500, total_delta=0)

        private_rdd = make_private(rdd, accountant, lambda x: x[0])

        mean_params = pipeline_dp.MeanParams(
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=50,
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = private_rdd.mean(mean_params, public_partitions=["M"])

        accountant.compute_budgets()
        result_dict = dict(result.collect())

        # True mean = 30
        assert abs(result_dict["M"] - 30) < 10


class TestSparkPrivateRDDMap:
    """Test PrivateRDD.map preserves privacy ID association."""

    def test_spark_map_then_count(self, spark_context):
        """A user maps a PrivateRDD then counts. The map should transform
        the data while maintaining the privacy_id association.
        """
        import pipeline_dp
        from pipeline_dp.private_spark import make_private

        sc = spark_context
        data = [
            ("u1", "mon", 10),
            ("u1", "tue", 20),
            ("u2", "mon", 30),
            ("u3", "tue", 40),
        ]
        rdd = sc.parallelize(data)

        accountant = pipeline_dp.NaiveBudgetAccountant(total_epsilon=100, total_delta=0)

        private_rdd = make_private(rdd, accountant, lambda x: x[0])
        mapped = private_rdd.map(lambda x: (x[1], x[2] * 2))

        count_params = pipeline_dp.CountParams(
            noise_kind=pipeline_dp.NoiseKind.LAPLACE,
            max_partitions_contributed=2,
            max_contributions_per_partition=2,
            partition_extractor=lambda x: x[0],
        )

        result = mapped.count(count_params, public_partitions=["mon", "tue"])

        accountant.compute_budgets()
        result_dict = dict(result.collect())

        assert abs(result_dict["mon"] - 2) < 2
        assert abs(result_dict["tue"] - 2) < 2


# ===========================================================================
# COVERAGE GAP TESTS
# ===========================================================================


class TestBeamFlatMap:
    """Test FlatMap transform on PrivatePCollection."""

    def test_beam_flatmap_then_count(self):
        """A user applies FlatMap to a PrivatePCollection, expanding each
        record into multiple records, then counts per partition.
        """
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, FlatMap, Count

        with TestPipeline() as p:
            data = [
                ("u1", ("A", "B")),
                ("u2", ("A", "C")),
                ("u3", ("B",)),
            ]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=100, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            expanded = private | FlatMap(lambda x: [(pk, 1) for pk in x[1]])

            count_params = pipeline_dp.CountParams(
                noise_kind=pipeline_dp.NoiseKind.LAPLACE,
                max_partitions_contributed=3,
                max_contributions_per_partition=1,
                partition_extractor=lambda x: x[0],
            )

            result = expanded | Count(count_params, public_partitions=["A", "B", "C"])

            accountant.compute_budgets()

            class AssertCounts(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    if pk == "A":
                        assert abs(val - 2) < 2
                    elif pk == "B":
                        assert abs(val - 2) < 2

            result | "Assert" >> beam.ParDo(AssertCounts())


class TestBeamVariance:
    """Test Variance transform via Beam PrivatePCollection."""

    def test_beam_variance(self):
        """A user computes DP variance through Beam."""
        import apache_beam as beam
        from apache_beam.testing.test_pipeline import TestPipeline
        import pipeline_dp
        from pipeline_dp.private_beam import MakePrivate, Variance

        with TestPipeline() as p:
            data = [(f"u{i}", "V", float(i)) for i in range(1, 11)]
            pcol = p | "Create" >> beam.Create(data)

            accountant = pipeline_dp.NaiveBudgetAccountant(
                total_epsilon=2000, total_delta=0
            )

            private = pcol | MakePrivate(
                budget_accountant=accountant,
                privacy_id_extractor=lambda x: x[0],
            )

            var_params = pipeline_dp.VarianceParams(
                max_partitions_contributed=1,
                max_contributions_per_partition=1,
                min_value=0,
                max_value=10,
                partition_extractor=lambda x: x[1],
                value_extractor=lambda x: x[2],
            )

            result = private | Variance(var_params, public_partitions=["V"])

            accountant.compute_budgets()

            class AssertVariance(beam.DoFn):
                def process(self, element):
                    pk, val = element
                    # Population variance of values 1..10 is 8.25. With
                    # epsilon=2000 the noise is negligible.
                    assert abs(val - 8.25) < 3, f"Variance {val} not near 8.25"

            result | "Assert" >> beam.ParDo(AssertVariance())


class TestSparkVariance:
    """Test DP variance via Spark PrivateRDD."""

    def test_spark_variance(self, spark_context):
        """A user computes DP variance via Spark's PrivateRDD."""
        import pipeline_dp
        from pipeline_dp.private_spark import make_private

        sc = spark_context
        data = [(f"u{i}", "V", float(i)) for i in range(1, 11)]
        rdd = sc.parallelize(data)

        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=2000, total_delta=0
        )

        private_rdd = make_private(rdd, accountant, lambda x: x[0])

        var_params = pipeline_dp.VarianceParams(
            max_partitions_contributed=1,
            max_contributions_per_partition=1,
            min_value=0,
            max_value=10,
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = private_rdd.variance(var_params, public_partitions=["V"])

        accountant.compute_budgets()
        result_dict = dict(result.collect())

        # Population variance of values 1..10 is 8.25. With epsilon=2000 the
        # noise is negligible.
        assert abs(result_dict["V"] - 8.25) < 3


class TestSparkSelectPartitions:
    """Test DP partition selection via Spark PrivateRDD."""

    def test_spark_select_partitions(self, spark_context):
        """A user selects partitions via Spark's PrivateRDD."""
        import pipeline_dp
        from pipeline_dp.private_spark import make_private

        sc = spark_context
        data = [(f"u{i}", "popular", 1) for i in range(30)]
        data.append(("lone", "rare", 1))
        rdd = sc.parallelize(data)

        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10, total_delta=1e-3
        )

        private_rdd = make_private(rdd, accountant, lambda x: x[0])

        params = pipeline_dp.SelectPartitionsParams(
            max_partitions_contributed=2,
        )

        result = private_rdd.select_partitions(
            params, partition_extractor=lambda x: x[1]
        )

        accountant.compute_budgets()
        partitions = result.collect()

        assert "popular" in partitions
        assert "rare" not in partitions


class TestSparkDataFrameAPI:
    """Test the QueryBuilder / Query DataFrame API via Spark."""

    def test_query_builder_count_and_sum(self, spark_context):
        """A user builds a DP query using QueryBuilder on a Spark DataFrame,
        computing count and sum grouped by a partition column.
        """
        from pyspark.sql import SparkSession
        from pipeline_dp.dataframes import QueryBuilder, Budget
        from pipeline_dp.aggregate_params import NoiseKind

        spark = SparkSession(spark_context)

        df = spark.createDataFrame(
            [
                ("u1", "mon", 10.0),
                ("u1", "tue", 20.0),
                ("u2", "mon", 30.0),
                ("u2", "mon", 15.0),
                ("u3", "tue", 25.0),
            ],
            ["user_id", "day", "amount"],
        )

        query = (
            QueryBuilder(df, "user_id")
            .groupby(
                "day",
                max_groups_contributed=2,
                max_contributions_per_group=2,
                public_keys=["mon", "tue"],
            )
            .count()
            .sum("amount", min_value=0, max_value=50)
            .build_query()
        )

        budget = Budget(epsilon=100, delta=0)
        result_df = query.run_query(budget, noise_kind=NoiseKind.LAPLACE)
        result = {row["day"]: row for row in result_df.collect()}

        assert "mon" in result
        assert "tue" in result
        assert abs(result["mon"]["count"] - 3) < 3
        assert abs(result["tue"]["count"] - 2) < 3


class TestCalculatePrivateContributionBounds:
    """Test DPEngine.calculate_private_contribution_bounds."""

    def test_private_contribution_bounds_returns_valid_bound(self):
        """A user calculates max_partitions_contributed privately using
        the exponential mechanism. The returned bound should be a positive
        integer from the set of candidate values.
        """
        import pipeline_dp
        from pipeline_dp.private_contribution_bounds import (
            generate_possible_contribution_bounds,
        )

        backend = pipeline_dp.LocalBackend()
        accountant = pipeline_dp.NaiveBudgetAccountant(
            total_epsilon=10, total_delta=1e-3
        )
        engine = pipeline_dp.DPEngine(accountant, backend)

        data = [(f"u{i}", f"p{i % 5}", 1.0) for i in range(50)]
        partitions = [f"p{i}" for i in range(5)]

        params = pipeline_dp.CalculatePrivateContributionBoundsParams(
            aggregation_noise_kind=pipeline_dp.NoiseKind.LAPLACE,
            aggregation_eps=5.0,
            aggregation_delta=0,
            calculation_eps=5.0,
            max_partitions_contributed_upper_bound=10,
        )
        extractors = pipeline_dp.DataExtractors(
            privacy_id_extractor=lambda x: x[0],
            partition_extractor=lambda x: x[1],
            value_extractor=lambda x: x[2],
        )

        result = engine.calculate_private_contribution_bounds(
            data, params, extractors, partitions
        )
        accountant.compute_budgets()

        bounds = list(result)
        assert len(bounds) == 1
        bound = bounds[0]
        # The exponential mechanism is randomized, but its output must be one of
        # the well-defined candidate bounds for upper_bound=10 (i.e. [1..10]).
        candidates = generate_possible_contribution_bounds(upper_bound=10)
        assert bound.max_partitions_contributed in candidates
