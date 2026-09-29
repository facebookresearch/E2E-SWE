# PipelineDP

Build `pipeline_dp`, a Python framework for applying differentially private (DP) aggregations to datasets. The library encapsulates the complexities of differential privacy — noise injection, privacy budget accounting, and contribution bounding — behind a pipeline-oriented API that supports pluggable processing backends.

## Dependencies

The environment is **offline**: every dependency below is **already installed**, and the project is
installed for you by a `setup.sh` (at the repo root) that runs offline. **Do not install anything**
and do not attempt any network access — there is none.

Runtime dependencies (pre-installed):

- `python-dp` (PyDP) >= 1.1.5 — Google's C++ differential privacy library with Python bindings. Provides the core noise generation primitives (Laplace/Gaussian mechanisms via `pydp.algorithms.laplace.BoundedMean` etc.) and partition selection strategies (`pydp.algorithms.partition_selection`).
- `numpy` >= 1.20.1
- `scipy` >= 1.7.3
- `dill` >= 0.3.7

Optional-backend dependencies, also pre-installed so the Apache Beam and Apache Spark backends work
out of the box: `apache-beam`, `pyspark` (plus `pandas` for the Spark DataFrame API), and
`dp-accounting` (used by `PLDBudgetAccountant`). The Python runtime is 3.11.

## Overview

The library's core workflow:

1. Create a **budget accountant** that tracks the total privacy budget (epsilon, delta).
2. Create a **pipeline backend** (e.g., `LocalBackend` for in-memory processing).
3. Create a **`DPEngine`** with the accountant and backend.
4. Call `engine.aggregate()` with parameters specifying which DP metrics to compute, contribution bounds, and noise type. This builds a lazy computation graph.
5. Call `accountant.compute_budgets()` to finalize budget distribution.
6. Materialize results by iterating the returned collection. Each element is `(partition_key, MetricsTuple)` where `MetricsTuple` is a named tuple with fields corresponding to the requested metrics.

## Top-level exports

The package `pipeline_dp` re-exports these from its `__init__.py`:

- `DPEngine`, `AggregateParams`, `SelectPartitionsParams`, `AddDPNoiseParams`
- `CountParams`, `SumParams`, `MeanParams`, `VarianceParams`, `PrivacyIdCountParams`
- `CalculatePrivateContributionBoundsParams`, `PrivateContributionBounds`
- `Metrics`, `NoiseKind`, `PartitionSelectionStrategy`
- `NaiveBudgetAccountant`, `PLDBudgetAccountant`, `BudgetAccountant`
- `DataExtractors`, `PreAggregateExtractors`
- `PipelineBackend`, `LocalBackend`, `SparkRDDBackend`, `BeamBackend`
- `ExplainComputationReport`

## DPEngine (`pipeline_dp.dp_engine`)

`DPEngine(budget_accountant, backend)` — the central orchestrator for DP aggregations.

### `aggregate(col, params, data_extractors, public_partitions=None, out_explain_computation_report=None)`

Computes DP aggregate metrics. The pipeline:
1. Extracts `(privacy_id, partition_key, value)` from each element using `data_extractors`.
2. If `public_partitions` is provided and `params.public_partitions_already_filtered` is False, drops records whose partition key is not in `public_partitions`.
3. Unless `params.contribution_bounds_already_enforced` is True, applies contribution bounding:
   - **Cross-partition bounding**: samples at most `max_partitions_contributed` partitions per privacy ID.
   - **Per-partition bounding**: samples at most `max_contributions_per_partition` records per (privacy_id, partition_key).
   - If `max_contributions` is set instead, samples at most that many total records per privacy ID across all partitions.
4. Creates accumulators via a `CompoundCombiner` and merges them per partition key.
5. If `public_partitions` is provided, adds empty accumulators for missing public partitions.
6. If no public partitions and `post_aggregation_thresholding` is False, performs private partition selection using the strategy in `params.partition_selection_strategy`.
7. Computes DP metrics by adding calibrated noise to each accumulator.
8. If `post_aggregation_thresholding` is True, drops partitions whose noised `privacy_id_count` is below the threshold (partitions that don't survive have `privacy_id_count` set to `None`). The keep/drop decision is made by a `ThresholdingMechanism` built for the aggregation's `noise_kind`.

Returns a collection of `(partition_key, MetricsTuple)`. `MetricsTuple` is a `collections.namedtuple` whose fields are the lowercase metric names (e.g., `count`, `sum`, `mean`, `variance`, `privacy_id_count`, `vector_sum`).

### `select_partitions(col, params, data_extractors)`

Selects partition keys in a differentially private manner without computing metrics. Applies cross-partition contribution bounding, then uses partition selection (the strategy from `params.partition_selection_strategy`) to decide which partitions to keep. Returns a collection of partition keys (not tuples).

### `add_dp_noise(col, params, out_explain_computation_report=None)`

Adds DP noise to pre-aggregated data. `col` is a collection of `(partition_key, value)`. Does **not** apply contribution bounding — the caller must ensure sensitivities are correct. If `params.output_noise_stddev` is True, returns `(partition_key, DpNoiseAdditionResult)` where `DpNoiseAdditionResult` is a named tuple with fields `noised_value` and `noise_stddev`. Otherwise returns `(partition_key, noised_value)`.

`DpNoiseAdditionResult` is importable from `pipeline_dp.dp_engine`; it is a named tuple exposing exactly two fields in this order: `noised_value` then `noise_stddev` (so `r._fields == ("noised_value", "noise_stddev")`).

### `explain_computations_report()`

Returns a list of report strings, one per `aggregate()` call made on this engine.

### `calculate_private_contribution_bounds(col, params, data_extractors, partitions, partitions_already_filtered=False)`

Experimental. Uses the exponential mechanism to privately choose `max_partitions_contributed`. Returns a 1-element collection of `PrivateContributionBounds`.

## AggregateParams (`pipeline_dp.aggregate_params`)

`@dataclass` specifying aggregation parameters. Key fields:

- `metrics: list[Metric]` — which metrics to compute (required, non-empty).
- `max_partitions_contributed: int` — max partitions one privacy ID can contribute to.
- `max_contributions_per_partition: int` — max records per (privacy_id, partition).
- `max_contributions: int` — alternative to the above two; total records per privacy ID. **Mutually exclusive** with `max_partitions_contributed`/`max_contributions_per_partition` — setting both raises `ValueError`.
- `min_value, max_value: float` — per-contribution value clipping range. Required for SUM, MEAN, VARIANCE.
- `min_sum_per_partition, max_sum_per_partition: float` — alternative per-partition sum clipping. When set, the sum of all contributions from one privacy ID to one partition is clipped to this range instead of clipping individual values.
- `noise_kind: NoiseKind` — LAPLACE or GAUSSIAN. Gaussian requires `delta > 0`.
- `partition_selection_strategy: PartitionSelectionStrategy` — used when no public partitions are provided.
- `post_aggregation_thresholding: bool` — if True, drops partitions with low noised privacy_id_count. Requires `PRIVACY_ID_COUNT` in metrics.
- `contribution_bounds_already_enforced: bool` — if True, skips contribution bounding.
- `public_partitions_already_filtered: bool` — if True, skips partition filtering.
- `budget_weight: float` — relative weight for budget allocation (default 1).
- `vector_size: int` — required for VECTOR_SUM.
- `vector_max_norm: float` — norm bound for vector clipping.
- `vector_norm_kind: NormKind` — which norm to use for vector clipping (L1, L2, or Linf). Required for VECTOR_SUM. The clipping semantics differ by norm: with `NormKind.Linf`, each vector element is **independently clamped** to `[-vector_max_norm, vector_max_norm]` (an element already in range is left unchanged); with `NormKind.L1` or `NormKind.L2`, the whole vector is rescaled by `vector_max_norm / ||v||` only when its L1 (resp. L2) norm `||v||` exceeds `vector_max_norm` (a vector already within the bound, or the zero vector, is left unchanged).
- `custom_combiners` — for user-defined combiners.

Validation in `__post_init__`:
- `metrics` must be non-empty.
- `max_contributions` and `max_partitions_contributed` cannot both be set.
- SUM/MEAN/VARIANCE require value bounds (`min_value`/`max_value` or `min_sum_per_partition`/`max_sum_per_partition`).

## Other parameter classes

- `SelectPartitionsParams(max_partitions_contributed, partition_selection_strategy=TRUNCATED_GEOMETRIC, pre_threshold=None, budget_weight=1, contribution_bounds_already_enforced=False)` — for `select_partitions()`.
- `AddDPNoiseParams(noise_kind, l0_sensitivity, linf_sensitivity, l1_sensitivity=None, l2_sensitivity=None, output_noise_stddev=False, budget_weight=1)` — for `add_dp_noise()`.
- `CalculatePrivateContributionBoundsParams(aggregation_noise_kind, aggregation_eps, aggregation_delta, calculation_eps, max_partitions_contributed_upper_bound)` — for `calculate_private_contribution_bounds()`. The `aggregation_*` fields describe the downstream aggregation the chosen bound will be used for (its noise kind and epsilon/delta budget); `calculation_eps` is the epsilon spent on the private L0 selection itself; `max_partitions_contributed_upper_bound` (int) caps the candidate `max_partitions_contributed` values fed to the exponential mechanism.

## Metrics (`pipeline_dp.aggregate_params`)

`Metrics` is a class with class-level constants, each a `Metric` dataclass with a `name` field:

- `Metrics.COUNT` — name: `"count"`
- `Metrics.SUM` — name: `"sum"`
- `Metrics.MEAN` — name: `"mean"`
- `Metrics.VARIANCE` — name: `"variance"`
- `Metrics.PRIVACY_ID_COUNT` — name: `"privacy_id_count"`
- `Metrics.VECTOR_SUM` — name: `"vector_sum"`
- `Metrics.PERCENTILE(percentile)` — factory method returning a `Metric` with a quantile parameter.

## NoiseKind (`pipeline_dp.aggregate_params`)

Enum with values `LAPLACE` and `GAUSSIAN`. Each has a `convert_to_mechanism_type()` method mapping to the corresponding `MechanismType`.

## PartitionSelectionStrategy (`pipeline_dp.aggregate_params`)

Enum with values:
- `TRUNCATED_GEOMETRIC`
- `LAPLACE_THRESHOLDING`
- `GAUSSIAN_THRESHOLDING`
- `WEIGHTED_GAUSSIAN_THRESHOLDING`

Properties: `is_thresholding`, `mechanism_type`, `is_weighted_gaussian`.

## NormKind (`pipeline_dp.aggregate_params`)

Enum with values: `Linf`, `L0`, `L1`, `L2`. Used for `vector_norm_kind` in `AggregateParams`.

## MechanismType (`pipeline_dp.aggregate_params`)

Enum with values: `LAPLACE`, `GAUSSIAN`, `LAPLACE_THRESHOLDING`, `GAUSSIAN_THRESHOLDING`, `TRUNCATED_GEOMETRIC`, `GENERIC`.

## Budget Accounting (`pipeline_dp.budget_accounting`)

### `BudgetAccountant` (ABC)

Base class. Constructor: `BudgetAccountant(total_epsilon, total_delta, num_aggregations=None, aggregation_weights=None)`. Validates epsilon > 0 and 0 <= delta < 1.

- `request_budget(mechanism_type, weight=1, name=None)` — returns a lazy `MechanismSpec` whose values are populated after `compute_budgets()`.
- `compute_budgets()` — finalizes and distributes the budget. Can only be called once; calling twice raises an error.
- `scope(weight)` — context manager. The scope itself is treated as a single mechanism with the given weight from the parent's perspective. Inside the scope, mechanism weights are normalized to sum to 1, then scaled by the scope's allocated budget. For example: one mechanism outside (weight=1) + one scope (weight=1) with two mechanisms inside → outside gets half the budget, and the two inside mechanisms each get a quarter.

### `NaiveBudgetAccountant(BudgetAccountant)`

Splits the total (epsilon, delta) proportionally among all requested mechanisms by their weights. Simple composition theorem.

### `PLDBudgetAccountant(BudgetAccountant)`

Uses the `dp_accounting` library (Privacy Loss Distributions) for tighter budget composition. Produces lower noise standard deviations than `NaiveBudgetAccountant` under the same total budget. Uses binary search to find the minimum noise standard deviation that satisfies the total (epsilon, delta) via PLD composition.

### `MechanismSpec`

Lazy budget holder. After `compute_budgets()`, exposes:
- `eps` — allocated epsilon.
- `delta` — allocated delta.
- `noise_standard_deviation` — for PLD-based accounting.
- `thresholding_delta` — for thresholding mechanisms.
- `standard_deviation_is_set` — True if noise_standard_deviation was set (PLD case).

## Data Extractors (`pipeline_dp.data_extractors`)

### `DataExtractors`

`@dataclass` with fields:
- `privacy_id_extractor: Callable` — extracts privacy ID from a record.
- `partition_extractor: Callable` — extracts partition key.
- `value_extractor: Callable` — extracts the value to aggregate.

### `PreAggregateExtractors`

`@dataclass` with fields:
- `partition_extractor: Callable`
- `preaggregate_extractor: Callable` — returns a tuple `(count, sum, n_partitions, n_contributions)`.

## Pipeline Backends (`pipeline_dp.pipeline_backend`)

### `PipelineBackend` (ABC)

Abstract interface for data processing. Methods include: `map(col, fn, stage_name)`, `flat_map(col, fn, stage_name)`, `map_tuple(col, fn, stage_name)`, `map_values(col, fn, stage_name)`, `group_by_key(col, stage_name)`, `filter(col, fn, stage_name)`, `filter_by_key(col, keys, stage_name)`, `keys(col, stage_name)`, `values(col, stage_name)`, `sample_fixed_per_key(col, n, stage_name)`, `count_per_element(col, stage_name)`, `sum_per_key(col, stage_name)`, `combine_accumulators_per_key(col, combiner, stage_name)`, `reduce_per_key(col, fn, stage_name)`, `flatten(cols, stage_name)`, `distinct(col, stage_name)`, `annotate(col, stage_name, **kwargs)`, `to_collection(col, other_col, stage_name)`.

### `LocalBackend(PipelineBackend)`

Pure-Python in-memory implementation. Processes data lazily using generators. Suitable for small datasets.

- `map(col, fn, stage_name)` — applies `fn` to each element.
- `flat_map(col, fn, stage_name)` — applies `fn` to each element and flattens.
- `filter(col, fn, stage_name)` — keeps elements where `fn` returns True.
- `group_by_key(col, stage_name)` — groups `(key, value)` pairs; returns `(key, [values])`.
- `keys(col, stage_name)` / `values(col, stage_name)` — extracts keys or values from pairs.
- `reduce_per_key(col, fn, stage_name)` — reduces values per key with a binary function.
- `sample_fixed_per_key(col, n, stage_name)` — groups by key, then samples at most `n` values per key. Returns `(key, [sampled_values])`.
- `combine_accumulators_per_key(col, combiner, stage_name)` — merges accumulators per key using a combiner's `merge_accumulators`.
- `flatten(cols, stage_name)` — concatenates multiple collections.

## Noise Mechanisms (`pipeline_dp.dp_computations`)

### `AdditiveMechanism` (ABC)

Base for noise mechanisms. Methods:
- `add_noise(value) -> float` — adds calibrated noise to the value.
- `noise_kind -> str` — returns `"Laplace"` or `"Gaussian"`.
- `noise_parameter -> float` — the scale parameter (b for Laplace, sigma for Gaussian).
- `std -> float` — noise standard deviation.
- `sensitivity -> float`
- `describe() -> str`

### `LaplaceMechanism(AdditiveMechanism)`

Factory methods:
- `create_from_epsilon(epsilon, l1_sensitivity)` — creates a Laplace mechanism with scale `b = l1_sensitivity / epsilon`. The standard deviation is `sqrt(2) * b`.
- `create_from_std_deviation(std_deviation, l1_sensitivity)` — creates from a target std.

Uses PyDP's `BoundedMean` or direct Laplace sampling internally.

### `GaussianMechanism(AdditiveMechanism)`

Factory methods:
- `create_from_epsilon_delta(epsilon, delta, l2_sensitivity)` — computes optimal sigma satisfying (epsilon, delta)-DP.
- `create_from_std_deviation(std_deviation, l2_sensitivity)` — creates from a target std.

### `Sensitivities`

`@dataclass` holding `l0`, `linf`, and optionally `l1`, `l2`. If `l1` is not provided, it is auto-derived as `l0 * linf`. If `l2` is not provided, it is auto-derived as `sqrt(l0) * linf`. If `l1` or `l2` is explicitly provided but contradicts the derived value (e.g., `l1 != l0 * linf`), raises `ValueError`.

### `MeanMechanism`

Computes DP mean via separate noised count and noised normalized sum. Normalizes values to the midpoint of `[min_value, max_value]` for better utility.

### `ThresholdingMechanism`

For partition selection. `noised_value_if_should_keep(num_privacy_units)` returns the noised count if the partition should be kept, else `None`. Its keep/drop threshold is calibrated from the mechanism's `MechanismSpec.thresholding_delta`, using the same thresholding machinery as private partition selection.

### `ExponentialMechanism`

Selects a parameter from a candidate list using the exponential mechanism. Contains an abstract `ScoringFunction` with `score(k)`, `global_sensitivity`, and `is_monotonic`.

### Helper functions

- `compute_sigma(eps, delta, l2_sensitivity)` — optimal Gaussian sigma.
- `compute_middle(min_val, max_val)` — overflow-safe midpoint.
- `add_noise_vector(vec, noise_params)` — per-element noise for vectors.
- `create_additive_mechanism(spec, sensitivities)` — factory that creates the right mechanism type from a `MechanismSpec`.

## Combiners (`pipeline_dp.combiners`)

The combiner pattern (similar to Beam's CombineFn) encapsulates accumulator creation, merging, and DP metric computation.

### `Combiner` (ABC)

- `create_accumulator(values)` — creates an accumulator from a list of values.
- `merge_accumulators(a1, a2)` — merges two accumulators.
- `compute_metrics(accumulator)` — computes the DP metric from the accumulator.
- `metrics_names()` — returns the metric names this combiner produces.
- `expects_per_partition_sampling()` — whether per-partition sampling is needed before this combiner.

### Concrete combiners

One combiner per metric: `CountCombiner`, `PrivacyIdCountCombiner` (counts each privacy ID at most once per partition; `expects_per_partition_sampling() = False`), `SumCombiner` (clips values to `[min_value, max_value]` or per-partition bounds), `MeanCombiner` (uses `MeanMechanism`), `VarianceCombiner` (splits its budget across its count / sum / sum-of-squares sub-metrics), `QuantileCombiner` (uses PyDP's `QuantileTree`), `VectorSumCombiner` (clips by L1/L2/Linf norm per the `vector_norm_kind` contract above), and `PostAggregationThresholdingCombiner` (uses `ThresholdingMechanism`; drops a partition by returning `None`).

### `CompoundCombiner`

Holds multiple child combiners and delegates to them. Its `compute_metrics` returns a `MetricsTuple` named tuple whose fields are the metric names from all children.

### Factory functions

- `create_compound_combiner(params, budget_accountant)` — creates the right combination of child combiners based on the requested metrics.

## Partition Selection (`pipeline_dp.partition_selection`)

Thin wrapper around PyDP's C++ partition selection.

- `create_partition_selection_strategy(strategy, epsilon, delta, max_partitions_contributed, pre_threshold)` — creates the partition selector.
- `create_gaussian_thresholding(sigma, thresholding_delta, max_partitions_contributed, pre_threshold)` — Gaussian thresholding from sigma/delta.
- `create_laplace_thresholding(sigma, thresholding_delta, max_partitions_contributed, pre_threshold)` — Laplace thresholding.
- `create_weighted_gaussian_thresholding(epsilon, delta, max_partitions_contributed)` — weighted Gaussian.

Each returns an object with `should_keep(count) -> bool`.

## Report Generator (`pipeline_dp.report_generator`)

### `ReportGenerator(params, method_name, is_public_partition=None)`

Collects stage descriptions. `add_stage(description)` appends a stage (description can be a string or a callable returning a string). `report()` produces a formatted string including the method name, parameters, and all stages.

The formatted string begins with a `DPEngine method: <method_name>` line, then the parameters, then a `Computation graph:` line followed by the numbered stages added during the pipeline. The stage descriptions name the pipeline steps that ran, so for an `aggregate()` call they include the contribution-bounding stages (`Per-partition contribution bounding: ...` and `Cross-partition contribution bounding: ...`), a partition-selection stage (`Public partition selection: dropped non public partitions` when `public_partitions` are supplied, otherwise a `Private Partition selection: ...` stage), and a metric-computation stage (`Computed DP count with ...`, `Computed DP sum with ...`, etc.).

### `ExplainComputationReport`

Container passed as an output argument to `aggregate()`. After `compute_budgets()`, `text()` returns the formatted report string.

## Sampling Utilities (`pipeline_dp.sampling_utils`)

- `choose_from_list_without_replacement(a, size)` — samples `min(size, len(a))` elements from list `a` without replacement. Uses `np.random.choice` on indices. Returns all elements if `size >= len(a)`.
- `ValueSampler(sampling_rate)` — deterministic sampler using SHA-1 hash. `keep(value) -> bool` returns True with probability `sampling_rate`. With `sampling_rate=1.0`, keeps all values; with `0.0`, keeps none.

## Dataset Histograms (`pipeline_dp.dataset_histograms`)

Subpackage for computing dataset statistics used in parameter tuning.

### `pipeline_dp.dataset_histograms.histograms`

- `FrequencyBin(lower, upper, count, sum, max, min)` — a named tuple representing one histogram bin.
- `HistogramType` — enum with types: `L0_CONTRIBUTIONS`, `L1_CONTRIBUTIONS`, `LINF_CONTRIBUTIONS`, `LINF_SUM_CONTRIBUTIONS`, `LINF_SUM_CONTRIBUTIONS_LOG`, `COUNT_PER_PARTITION`, `COUNT_PRIVACY_ID_PER_PARTITION`, `SUM_PER_PARTITION`, `SUM_PER_PARTITION_LOG`.
- `Histogram(name: HistogramType, bins: list[FrequencyBin])` — a named tuple. `total_count()` returns the sum of all bin counts. `total_sum()` returns the sum of all bin sums.
- `DatasetHistograms` — container holding all 9 histogram types. Accessed via properties like `l0_contributions_histogram`, `linf_contributions_histogram`, `count_per_partition_histogram`, etc.

### `pipeline_dp.dataset_histograms.computing_histograms`

- `compute_dataset_histograms(col, data_extractors, backend)` — computes all histograms from raw data. Returns a 1-element collection of `DatasetHistograms`. The L0 contributions histogram's `total_count()` equals the number of distinct privacy IDs. The Linf contributions histogram bins per (privacy_id, partition) pair: its `total_count()` equals the number of distinct (privacy_id, partition) pairs and its `total_sum()` equals the total number of contributions across those pairs.

### `pipeline_dp.dataset_histograms.histogram_error_estimator`

- `create_estimator_for_count_and_privacy_id_count(histograms, epsilon, delta, metric, noise)` — creates an `ErrorEstimator` for COUNT or PRIVACY_ID_COUNT. `histograms` is a `DatasetHistograms` object. `epsilon` and `delta` are the DP parameters (`delta` is None for Laplace). `metric` is a `Metric` (e.g., `Metrics.COUNT`). `noise` is a `NoiseKind`.
- `create_estimator_for_sum(...)` — for sum metric.
- `ErrorEstimator.estimate_rmse(l0_bound, linf_bound)` — estimates RMSE for the given contribution bounds deterministically (no sampling). It combines the fraction of data dropped by contribution bounding at those bounds with the calibrated mechanism noise std `noise_std` for the sensitivities those bounds imply (see the Noise Mechanisms section). When the chosen bounds drop no data, the estimate equals `noise_std`. Returns a finite, non-negative float.

## Private Contribution Bounds (`pipeline_dp.private_contribution_bounds`)

- `PrivateL0Calculator` — calculates `max_partitions_contributed` privately using `ExponentialMechanism`.
- `generate_possible_contribution_bounds(upper_bound)` — generates logarithmically-spaced candidate bounds.

## Apache Beam Integration (`pipeline_dp.private_beam`)

The library provides a Beam-native API for DP aggregations through `PrivatePCollection` — a safety wrapper that ensures data can only be extracted through DP transforms.

### `BeamBackend` (`pipeline_dp.beam_backend`)

`BeamBackend(PipelineBackend)` — Beam implementation of the pipeline backend. Wraps all operations with `beam.Map`, `beam.FlatMap`, `beam.GroupByKey`, `beam.CombinePerKey`, etc.

- `UniqueLabelsGenerator` — ensures Beam stage names are unique (Beam requires unique labels). Has a `unique(label)` method.
- All operations take a PCollection and return a PCollection.
- `reduce_per_key(col, fn, stage_name)` — `fn` is a binary function `(a, b) -> c`. Wraps it with `functools.reduce` to create a combiner compatible with `beam.CombinePerKey`.
- `filter_by_key(col, keys, stage_name)` — supports both in-memory sets and PCollection-based joins.

### `PrivatePTransform` (extends `apache_beam.transforms.ptransform.PTransform`)

Abstract base class for all DP transforms. Inherits from Beam's `PTransform` so transforms can be used with Beam's `|` operator on both `PCollection` (for `MakePrivate`) and `PrivatePCollection` (for aggregation transforms).

Constructor: `PrivatePTransform(return_anonymized, label=None)`. The `label` is made unique via `BeamBackend`'s `UniqueLabelsGenerator`. Has `set_additional_parameters(budget_accountant)` to inject the budget. Subclasses implement `expand(pcol)`.

### `PrivatePCollection`

`PrivatePCollection(pcol, budget_accountant)` — wraps a Beam `PCollection` of `(privacy_id, element)` pairs. Only `PrivatePTransform` subclasses can extract data, enforcing DP safety.

The `__or__` operator (`|`) applies a `PrivatePTransform` after injecting the budget accountant into it. If `return_anonymized` is True the result is a raw PCollection; otherwise it is a new `PrivatePCollection` (which can be `|`-chained with further transforms).

### `MakePrivate` (extends `PrivatePTransform`)

`MakePrivate(budget_accountant, privacy_id_extractor, label=None)` — a PTransform that creates a `PrivatePCollection` from a raw PCollection. Used as `pcol | MakePrivate(accountant, extractor)`. The `expand` method maps each element to `(privacy_id_extractor(element), element)` and wraps the result in a `PrivatePCollection`. Since `MakePrivate` is a Beam `PTransform`, it can be applied directly to a `PCollection` via the `|` operator.

### Aggregation transforms

Each aggregation is a `PrivatePTransform` subclass with `return_anonymized=True`. They accept the corresponding `*Params` dataclass and optional `public_partitions`. Since they extend `PTransform`, they work with both Beam's `|` operator on `PCollection` and `PrivatePCollection`'s `|` operator.

- **`Count(count_params, public_partitions=None)`** — DP count per partition. Returns `PCollection[(partition_key, noised_count)]`.
- **`Sum(sum_params, public_partitions=None)`** — DP sum per partition. Returns `PCollection[(partition_key, noised_sum)]`.
- **`Mean(mean_params, public_partitions=None)`** — DP mean per partition. Returns `PCollection[(partition_key, noised_mean)]`.
- **`Variance(variance_params, public_partitions=None)`** — DP variance per partition. Returns `PCollection[(partition_key, noised_variance)]`.
- **`PrivacyIdCount(privacy_id_count_params, public_partitions=None)`** — DP distinct user count per partition.
- **`SelectPartitions(select_partitions_params, partition_extractor, label)`** — DP partition selection. Returns `PCollection[partition_key]`.

### Non-anonymizing transforms

- **`Map(fn)`** — applies `fn` to the element part of each `(privacy_id, element)` pair. Returns a new `PrivatePCollection`.
- **`FlatMap(fn)`** — applies `fn` to the element, flattens the result, and preserves privacy_id association. Returns a new `PrivatePCollection`.

### Convenience parameter classes

Each has `partition_extractor` and (for Sum/Mean/Variance) `value_extractor` fields, plus a `to_aggregate_params()` method:

- `CountParams(noise_kind, max_partitions_contributed, max_contributions_per_partition, partition_extractor, budget_weight=1)`
- `SumParams(max_partitions_contributed, max_contributions_per_partition, min_value, max_value, partition_extractor, value_extractor, noise_kind=LAPLACE, budget_weight=1)`
- `MeanParams(max_partitions_contributed, max_contributions_per_partition, min_value, max_value, partition_extractor, value_extractor, noise_kind=LAPLACE, budget_weight=1)`
- `VarianceParams(max_partitions_contributed, max_contributions_per_partition, min_value, max_value, partition_extractor, value_extractor, noise_kind=LAPLACE, budget_weight=1)`
- `PrivacyIdCountParams(noise_kind, max_partitions_contributed, partition_extractor, budget_weight=1)` — note: no `max_contributions_per_partition` (privacy ID count only needs cross-partition bounding)

## Apache Spark Integration (`pipeline_dp.private_spark`)

The library provides a Spark-native API for DP aggregations through `PrivateRDD`.

### `SparkRDDBackend` (`pipeline_dp.spark_rdd_backend`)

`SparkRDDBackend(spark_context)` — Spark implementation of `PipelineBackend`. Constructor takes a `SparkContext`. Wraps Spark RDD operations: `rdd.map`, `rdd.flatMap`, `rdd.groupByKey`, `rdd.filter`, `rdd.reduceByKey`. `filter_by_key` supports both broadcast sets and RDD joins.

### `PrivateRDD` (`pipeline_dp.private_spark`)

`PrivateRDD(rdd, budget_accountant, privacy_id_extractor=None)` — wraps a Spark RDD. If `privacy_id_extractor` is provided, maps each element to `(privacy_id_extractor(element), element)`. If None, assumes RDD is already `(privacy_id, element)` pairs.

Methods (each creates a `DPEngine` with `SparkRDDBackend` internally):
- `map(fn)` — transforms the element part of each `(privacy_id, element)` pair via `rdd.mapValues(fn)`. Returns a new `PrivateRDD`.
- `flat_map(fn)` — flat-maps the element part via `rdd.flatMapValues(fn)`. Returns a new `PrivateRDD`.
- `count(count_params, public_partitions=None)` — DP count. Returns `RDD[(partition_key, noised_count)]`.
- `sum(sum_params, public_partitions=None)` — DP sum. Returns `RDD[(partition_key, noised_sum)]`.
- `mean(mean_params, public_partitions=None)` — DP mean. Returns `RDD[(partition_key, noised_mean)]`.
- `variance(variance_params, public_partitions=None)` — DP variance.
- `privacy_id_count(privacy_id_count_params, public_partitions=None)` — DP distinct user count.
- `select_partitions(select_partitions_params, partition_extractor)` — DP partition selection. Returns `RDD[partition_key]`.

### `make_private` (factory function)

`make_private(rdd, budget_accountant, privacy_id_extractor) -> PrivateRDD` — creates a `PrivateRDD` from a Spark RDD.

## Spark DataFrame API (`pipeline_dp.dataframes`)

A higher-level DataFrame API built on top of `PrivateRDD` / `SparkRDDBackend`.

### `Budget`

Simple dataclass: `Budget(epsilon, delta)`.

### `Columns`

Dataclass mapping column names: `Columns(privacy_key, partition_key, value)`. `partition_key` can be a single string or a list of strings (multi-column groupby).

### `ContributionBounds`

Dataclass: `ContributionBounds(max_partitions_contributed, max_contributions_per_partition, min_value=None, max_value=None)`.

### `QueryBuilder`

Builder pattern for constructing DP queries on Spark DataFrames.

`QueryBuilder(df, privacy_unit_column)` — takes a Spark DataFrame and the name of the privacy unit column.

Methods (each returns `self` for chaining):
- `groupby(by, *, max_groups_contributed, max_contributions_per_group, public_keys=None)` — group by one or more columns. Must be called before any aggregation.
- `count(name=None)` — add COUNT aggregation. `name` is the output column name.
- `sum(column, min_value=None, max_value=None, name=None)` — add SUM aggregation on `column`.
- `mean(column, min_value=None, max_value=None, name=None)` — add MEAN aggregation.
- `build_query()` — returns a `Query` object. Validates that groupby was called and at least one aggregation exists.

When `name` is not given for an aggregation, the output column defaults to the lowercase metric name (`count`, `sum`, `mean`). The result DataFrame therefore carries the partition column(s) plus one column per aggregation, named either by the supplied `name` or by that default.

### `Query`

`Query.run_query(budget, noise_kind=NoiseKind.LAPLACE)` — runs the DP query and returns a Spark DataFrame with the partition column(s) and one column per aggregation metric (named by the supplied `name` or the default lowercase metric name).

### `SparkConverter`

Converts between Spark DataFrame and RDD with schema preservation. Used internally by `Query.run_query()`.

## Agent instructions

Create a Python package named `pipeline_dp` that implements all the above. The package must be installable via `pip install -e .` using a `setup.py` or `pyproject.toml`. Provide a `setup.sh` file at the repo root containing the install command — it runs **offline** (the environment has no network and all dependencies are pre-installed), so the install must not fetch anything (e.g. `pip install -e . --no-build-isolation`).

The library depends on `python-dp` (PyDP) for the actual noise generation and partition selection C++ implementations. Your package should import from `pydp` for these primitives. It also supports Apache Beam and Apache Spark as backends; `apache-beam`, `pyspark`, and `pandas` are already installed in the environment, so the Beam and Spark code paths can simply import them.
