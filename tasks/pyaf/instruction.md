# PyAF — Python Automatic Forecasting

## Overview

Implement **PyAF** (Python Automatic Forecasting) — a library that decomposes time series into trend, seasonal/cycle, and autoregressive components, runs a combinatorial competition among all valid model combinations, and selects the best model via Condorcet voting. Follows a scikit-learn-style `fit`/`predict` pattern through a facade API.

## Dependencies

The environment is **offline** — every dependency below is **already installed**, so do **not**
attempt to install anything (there is no network). The project is installed for you by a `setup.sh`
that runs offline (`pip install -e . --no-build-isolation`); your `pyproject.toml` / `setup.py` must
be editable-installable against these pre-installed packages.

- `numpy`, `scipy`, `pandas`, `scikit-learn` — numerical / data-frame / regression backbone.
- `statsmodels` — classic autoregression models.
- `xgboost` — gradient-boosted autoregression model.
- `matplotlib`, `pydot` — plotting / model-graph rendering.
- `dill` — model serialization via pickle.

---

## 1. User API

Users interact with two facade classes:

```python
import pyaf.ForecastEngine as autof
import pyaf.HierarchicalForecastEngine as hierf
```

### `cForecastEngine`

```python
lEngine = autof.cForecastEngine()
lEngine.mOptions  # cSignalDecomposition_Options — configure before training
lEngine.train(iInputDS, iTime, iSignal, iHorizon, iExogenousData=None)
lEngine.forecast(iInputDS, iHorizon)  # returns DataFrame
lEngine.getModelInfo()
lEngine.to_json(iWithOptions=False)  # returns JSON string
lEngine.to_dict(iWithOptions=False)  # returns dict
lEngine.standardPlots(name=None, format='png')
lEngine.getPlotsAsDict()
lEngine.computePerf(actual, predicted, name)  # returns cPerf
```

- `train()`: trains on a pandas DataFrame. `iTime` = time column name (datetime or numeric), `iSignal` = signal column name (numeric `i`/`u`/`f`), `iHorizon` = integer forecast horizon. Wraps all exceptions as `PyAF_Error("TRAIN_FAILED")` except `PyAF_Error` subclasses which re-raise directly.
- `forecast()`: returns DataFrame with original data + `{Signal}_Forecast` column + prediction interval bound columns named `{Signal}_Forecast_Lower_Bound` and `{Signal}_Forecast_Upper_Bound` (emitted by default when `mAddPredictionIntervals` is True), with `lower <= forecast <= upper`. Last `iHorizon` rows are future forecast values. Wraps exceptions as `PyAF_Error("FORECAST_FAILED")`.
- Input validation: checks column existence, signal must be numeric (`i`/`u`/`f`), time must be datetime (`M`) or numeric, horizon must be positive. Exogenous data time column type must match.
- `to_dict()` / `to_json()`: serialize a trained engine. `to_dict()` returns a dict keyed by signal name (one entry per trained signal), where each per-signal entry is itself a dict that describes the selected model. That per-signal dict contains (at least) a `Model` sub-dict summarizing the chosen decomposition — the selected transformation, trend, cycle, and AR component. `to_json()` returns the JSON string for the *same* structure (so `json.loads(engine.to_json())` round-trips back to `to_dict()`). Example shape:

```python
{
    "Signal": {            # keyed by the signal column name
        "Model": {         # the selected/trained model
            "Best_Decomposition": "...",
            "Trend": "...", "Cycle": "...", "AR_Model": "...",
        },
        # ... other per-signal model metadata
    },
}
```

### `cHierarchicalForecastEngine`

Same API as `cForecastEngine` except `train()` takes an additional `iHierarchy` parameter:

```python
lEngine = hierf.cHierarchicalForecastEngine()
lEngine.train(iInputDS, iTime, iSignal, iHorizon, iHierarchy, iExogenousData=None)
```

Hierarchy types specified via `iHierarchy['Type']`: `"Standard"`, `"Grouped"`, `"Temporal"`. Dispatches to appropriate internal hierarchy class.

For grouped hierarchies, `iSignal` is None (signals are the DataFrame columns excluding the time column). The hierarchy dict:

```python
hierarchy = {
    "Type": "Grouped",
    "Groups": {"Region": ["A", "B"], "Product": ["X", "Y"]},
    "GroupOrder": ["Region", "Product"],
    "Levels": None,
    "Data": None,
}
```

Column names must match the Cartesian product of group values joined by `_` (e.g. `A_X`, `A_Y`, `B_X`, `B_Y`). The engine automatically creates aggregate signals for each group level (e.g. `_X`, `_Y` for product totals, `A_`, `B_` for region totals, `_` for grand total).

For standard hierarchies, `iSignal` is None. The hierarchy dict uses `Levels` (list of level names from leaves to root) and `Data` (a DataFrame whose columns match the level names, each row mapping a leaf node to its ancestors):

```python
hierarchy = {
    "Type": "Standard",
    "Levels": ["Leaf", "Top"],
    "Data": pd.DataFrame({"Leaf": ["A", "B"], "Top": ["Total", "Total"]}),
    "Groups": None,
}
```

The DataFrame columns correspond to the signal column names in the input data. The engine builds a summing matrix from this structure and trains a model per node. `{Signal}_Forecast` columns are created for each node.

For temporal hierarchies, `iSignal` is the signal column name (not None). The hierarchy dict uses `Periods` — a list of pandas frequency strings in increasing order of aggregation (e.g., `["D", "W"]` for daily→weekly). The engine resamples the signal at each period, creating `{Signal}_{Period}` columns (e.g., `Signal_D`, `Signal_W`), and trains a model per temporal level. Requires physical (datetime) time column. Forecast columns follow the same `{Signal}_{Period}_Forecast` pattern.

`forecast()` for a temporal hierarchy returns a single DataFrame at the **finest** period's time resolution (the first/most granular entry in `Periods`), of length `n + iHorizon` (the original `n` rows plus `iHorizon` future rows on that finest grid). Each coarser `{Signal}_{Period}_Forecast` column is aligned onto that finest grid, so every row — including each of the last `iHorizon` future-horizon rows — carries the forecast of the coarse period bucket that row falls in (the coarse forecast is broadcast/propagated across the finer rows of its bucket). Consequently no `{Signal}_{Period}_Forecast` column has NaN in its last `iHorizon` rows.

```python
hierarchy = {
    "Type": "Temporal",
    "Periods": ["D", "W"],
    "Levels": None,
    "Data": None,
    "Groups": None,
}
```

Reconciliation methods (`mHierarchicalCombinationMethod`): `"BU"` (bottom-up), `"TD"` (top-down). Reconciliation does not overwrite the plain per-node `{Signal}_Forecast` column (which stays each node's independent forecast); instead it adds **dedicated reconciled columns** alongside it, named by appending a method-specific suffix to the node signal name:

- **BU (bottom-up)** writes `{Signal}_BU_Forecast` for every node, where each parent's value equals the sum of its children's forecasts (so a leaf's `_BU_Forecast` equals its own `_Forecast`, and the root's `_BU_Forecast` equals the sum of all leaf forecasts).
- **TD (top-down)** writes `{Signal}_AHP_TD_Forecast` for every node — the parent forecast split proportionally down to the children using Average Historical Proportions (AHP), so the children's `_AHP_TD_Forecast` values sum back to the parent's.

For grouped hierarchies the aggregate/grand-total signal names follow the rule above (e.g. the grand-total node `_` yields columns `__BU_Forecast` and `__AHP_TD_Forecast`).

---

## 2. Options System

`cSignalDecomposition_Options` is the type of `lEngine.mOptions`, the single options object you configure before calling `train()`. It aggregates all of the configuration groups below — the model-control known-type lists and activation methods, the mode presets, and the scalar/nested configuration attributes — onto that one object.

### Model Control

Class-level lists of all known model types. Instance methods to activate subsets:

**Known decomposition types:** `['T+S+R', 'TS+R', 'TSR']`

**Known transformations (9):** `['None', 'Difference', 'RelativeDifference', 'Integration', 'BoxCox', 'Quantization', 'Logit', 'Fisher', 'Anscombe']`

Each transform must be invertible: forecasts are produced in transformed space and mapped back into the signal's original units. Definitions:
- `None`: identity (no transform).
- `Difference`: first difference `y[t] - y[t-1]`.
- `RelativeDifference`: relative first difference `(y[t] - y[t-1]) / y[t-1]`.
- `Integration`: cumulative sum.
- `BoxCox`: power transform `(y**lambda - 1) / lambda` for `lambda != 0`, else `log(y)`.
- `Quantization`: a non-linear, lossy, monotone mapping of the signal onto a small number of discrete levels.
- `Logit`: log-odds `log(y / (1 - y))`.
- `Fisher`: inverse hyperbolic tangent `arctanh(y)`.
- `Anscombe`: variance-stabilizing transform for count-like data, `2 * sqrt(y + 3/8)`.

**Known trends (6):** `['ConstantTrend', 'Lag1Trend', 'LinearTrend', 'PolyTrend', 'MovingAverage', 'MovingMedian']`

**Known periodics (19):** `['NoCycle', 'BestCycle', 'Seasonal_MonthOfYear', 'Seasonal_Second', 'Seasonal_Minute', 'Seasonal_Hour', 'Seasonal_HourOfWeek', 'Seasonal_TwoHourOfWeek', 'Seasonal_ThreeHourOfWeek', 'Seasonal_FourHourOfWeek', 'Seasonal_SixHourOfWeek', 'Seasonal_EightHourOfWeek', 'Seasonal_TwelveHourOfWeek', 'Seasonal_DayOfWeek', 'Seasonal_DayOfMonth', 'Seasonal_DayOfYear', 'Seasonal_WeekOfMonth', 'Seasonal_DayOfNthWeekOfMonth', 'Seasonal_WeekOfYear']`

**Known autoregressions (14):** `['NoAR', 'AR', 'ARX', 'SVR', 'SVRX', 'MLP', 'MLPX', 'LSTM', 'LSTMX', 'XGB', 'XGBX', 'CROSTON', 'LGB', 'LGBX']`

Active-set attributes — each is a dict mapping every known type name to a bool (`True` = active), populated by the corresponding `set_active_*` method:
- `mActiveTransformations`, `mActiveTrends`, `mActivePeriodics`, `mActiveAutoRegressions`, `mActiveDecompositionTypes`.

Methods:
- `set_active_transformations(list)` / `set_active_trends(list)` / `set_active_periodics(list)` / `set_active_autoregressions(list)` / `set_active_decomposition_types(list)` — validates each entry against the corresponding known list (raising on an unknown type name) and marks exactly the listed types active in the matching `mActive*` dict. If the list activates none of the known types (e.g. an empty list), the type's default — the first element of its known list — is activated instead, so each `mActive*` dict always has at least one `True` value.
- `disable_all_transformations()` / `disable_all_trends()` / `disable_all_periodics()` / `disable_all_autoregressions()` — activates only the default (first element of the known list).

### Mode Presets

- `enable_fast_mode()` (default): first 4 transforms, first 4 trends, all periodics, first 3 ARs (NoAR, AR, ARX), only `T+S+R`. `mQuantiles=[20]`, `mCycleLengths=[5,7,12,24,30,60]`, `mMaxAROrder=64`, `mFilterSeasonals=True`.
- `enable_slow_mode()`: all model types. `mCycleLengths=None`, `mFilterSeasonals=False`, `mActivateSampling=False`.
- `enable_low_memory_mode()`: fast mode + `mMaxAROrder=7`, only `'None'` transform, `mParallelMode=False`.

### Configuration Options

- `mModelSelection_Criterion` (`"MASE"` default), `mVotingMethod` (`"Condorcet"` or None for legacy)
- `mEstimRatio` (0.8), `mCustomSplit` (None — or tuple `(train_ratio, validation_ratio, test_ratio)`)
- `mCrossValidationOptions.mMethod` (None or `"TSCV"`), `mCrossValidationOptions.mNbFolds` (10)
- `mAddPredictionIntervals` (True), `mForecastRectifier` (None or `"relu"`)
- `mSeed` (1960), `mActivateSampling` (True), `mSamplingThreshold` (8192)
- `mParallelMode` (True), `mNbCores` (8)
- `mMissingDataOptions.mSignalMissingDataImputation` (None, `"DiscardRow"`, `"Interpolate"`, `"Mean"`, `"Median"`, `"Constant"`, `"PreviousValue"`)
- `mMissingDataOptions.mTimeMissingDataImputation` (None, `"DiscardRow"`, `"Interpolate"`)
- `mMissingDataOptions.mConstant` (0.0)
- `mCrostonOptions.mMethod` (None, `"CROSTON"`, `"SBJ"`, `"SBA"`), `mCrostonOptions.mAlpha` (0.1), `mCrostonOptions.mZeroRate` (0.1)
- `mHierarchicalCombinationMethod` (`"BU"`, `"TD"`, `"MO"`, `"OC"`)

### Croston intermittent-demand forecasting

The `CROSTON` autoregression (Known autoregressions list) is Croston's intermittent-demand estimator: it models a mostly-zero demand signal as a smoothed demand-per-period rate. `mCrostonOptions` configures it:

- `mMethod` selects the variant: `"CROSTON"` is the base method; `"SBJ"` and `"SBA"` are the Syntetos-Boylan-Johnston bias-corrected variants (they apply a correction factor to the base demand-rate estimate).
- `mAlpha` is the exponential-smoothing constant applied to the demand estimate (default `0.1`).
- `mZeroRate` controls zero-demand handling (default `0.1`).

---

## 3. Exogenous Variables

```python
exog_data = (exog_df, ['Temperature', 'Holiday'])
lEngine.train(df, 'Date', 'Signal', 7, iExogenousData=exog_data)
```

Exogenous DataFrame must have the same time column name and type. Used by `X`-suffixed AR models (ARX, SVRX, etc.).

---

## 4. Performance Metrics (`cPerf`)

The `cPerf` class lives in `pyaf.TS.Perf` (`from pyaf.TS.Perf import cPerf`).

`computePerf(actual, predicted, name)` returns a `cPerf` object with:
- `mMAPE`, `mSMAPE`, `mDiffSMAPE`, `mMASE`, `mRMSSE`
- `mL1` (MAE), `mL2` (RMSE), `mMedAE`, `mR2`, `mPearsonR`
- `mLnQ`, `mCRPS`, `mKS`, `mKendallTau`, `mMWU`, `mAUC`
- `mErrorMean`, `mErrorStdDev`, `mCount`

Every stored numeric metric attribute (e.g. `mL1`, `mL2`, `mMAPE`, `mSMAPE`, `mR2`, `mPearsonR`, `mMedAE`, `mMASE`, `mRMSSE`, `mLnQ`, `mErrorMean`, `mErrorStdDev`) is rounded to **4 decimal places** when computed (`mCount` is the integer sample count and is not rounded).

The **error** is `error = predicted - actual` (signed, predicted minus actual). With `actual` and `predicted` the two input series and the error as defined, the metrics use these exact conventions (all are returned as a raw value/fraction — never multiplied by 100):

- `mL1` = `mean(|error|)` (MAE); `mL2` = `sqrt(mean(error**2))` (RMSE); `mMedAE` = `median(|error|)`.
- `mMAPE` = `mean(|error| / |actual|)` — a **fraction**, NOT a percentage.
- `mSMAPE` = `mean(2 * |error| / (|actual| + |predicted|))` — a fraction (equivalently `mean(|error| / ((|actual| + |predicted|) / 2))`).
- `mErrorMean` = `mean(error)` and `mErrorStdDev` = `std(error)`, the mean and **population** standard deviation (`ddof=0`, i.e. `numpy.std`) of the signed error.
- `mLnQ` = `sum((ln(predicted) - ln(actual))**2)`, the **sum** (not mean) of squared log-quotients; defined only when both series are strictly positive (otherwise it is `+inf`).
- `mR2` = `1 - sum(error**2) / sum((actual - mean(actual))**2)`; `mPearsonR` = Pearson correlation of `actual` and `predicted`.

Methods:
- `getCriterionValue(criterion)` — `"MAE"` maps to `mL1`, `"RMSE"` maps to `mL2`
- `computeCriterionValues(signal, estimator, criterions, name)` — computes only specified metrics, returns dict
- `higher_values_are_better(criterion)` — static method, True for `["R2", "PEARSONR", "KendallTau", "KS", "MWU", "AUC"]`

---

## 5. Utilities

- `PyAF_Error(reason)` — main exception, `mReason` attribute. In `pyaf.TS.Utils`.
- `Internal_PyAF_Error(reason)` — subclass of `PyAF_Error`.

---

## 6. setup.sh

The environment is offline with all dependencies pre-installed, so `setup.sh` installs the project
without build isolation:

```bash
pip install -e . --no-build-isolation
```
