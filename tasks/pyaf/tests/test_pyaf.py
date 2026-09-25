import numpy as np
import pandas as pd
import pytest
import json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_linear_signal(n=200, seed=1960):
    np.random.seed(seed)
    dates = pd.date_range(start="2020-01-01", periods=n, freq="D")
    signal = np.arange(n, dtype=float) * 0.5 + np.random.randn(n) * 0.3
    return pd.DataFrame({"Date": dates, "Signal": signal})


def make_seasonal_signal(n=365, seed=42):
    np.random.seed(seed)
    dates = pd.date_range(start="2020-01-01", periods=n, freq="D")
    trend = np.linspace(10, 20, n)
    seasonal = 5 * np.sin(2 * np.pi * np.arange(n) / 7)
    noise = np.random.randn(n) * 0.5
    return pd.DataFrame({"Date": dates, "Signal": trend + seasonal + noise})


def make_intermittent_signal(n=365, seed=1960):
    np.random.seed(seed)
    sig = np.zeros(n)
    for i in range(0, n // 30):
        if np.random.random() < 0.5:
            sig[i * 30] = np.random.randint(100)
    dates = pd.date_range(start="2016-01-25", periods=n, freq="D")
    return pd.DataFrame({"Date": dates, "Signal": sig})


def make_signal_with_exogenous(n=200, seed=1960):
    np.random.seed(seed)
    dates = pd.date_range(start="2020-01-01", periods=n, freq="D")
    temp = 20 + 10 * np.sin(2 * np.pi * np.arange(n) / 365) + np.random.randn(n)
    signal = np.arange(n, dtype=float) * 0.3 + temp * 0.5 + np.random.randn(n) * 0.5
    main_df = pd.DataFrame({"Date": dates, "Signal": signal})
    exog_df = pd.DataFrame({"Date": dates, "Temperature": temp})
    return main_df, exog_df


def train_engine(df, horizon=7, **option_overrides):
    import pyaf.ForecastEngine as autof

    engine = autof.cForecastEngine()
    engine.mOptions.set_active_transformations(["None"])
    engine.mOptions.set_active_trends(["ConstantTrend", "LinearTrend"])
    engine.mOptions.set_active_periodics(["NoCycle", "BestCycle"])
    engine.mOptions.set_active_autoregressions(["NoAR", "AR"])
    engine.mOptions.set_active_decomposition_types(["T+S+R"])

    for key, val in option_overrides.items():
        setattr(engine.mOptions, key, val)

    engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=horizon)
    return engine


# ---------------------------------------------------------------------------
# 1. Core train/forecast pipeline with trend signal
# ---------------------------------------------------------------------------


class TestTrainForecastPipeline:

    def test_forecast_structure_and_values(self):
        """Train on a linear signal, forecast 7 days ahead, and verify the result structure and values across multiple trend types."""
        df = make_linear_signal()
        horizon = 7
        engine = train_engine(df, horizon=horizon)
        result = engine.forecast(iInputDS=df, iHorizon=horizon)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df) + horizon
        assert "Signal_Forecast" in result.columns

        forecast_tail = result["Signal_Forecast"].tail(horizon)
        assert not forecast_tail.isna().all()
        assert np.all(np.isfinite(forecast_tail.values))

        last_train_date = df["Date"].iloc[-1]
        last_forecast_date = result["Date"].iloc[-1]
        assert last_forecast_date > last_train_date

        last_actual = df["Signal"].iloc[-1]
        assert np.mean(forecast_tail.values) > last_actual * 0.5

        import pyaf.ForecastEngine as autof

        for trend in ["Lag1Trend", "PolyTrend", "MovingAverage", "MovingMedian"]:
            e = autof.cForecastEngine()
            e.mOptions.set_active_transformations(["None"])
            e.mOptions.set_active_trends([trend])
            e.mOptions.set_active_periodics(["NoCycle"])
            e.mOptions.set_active_autoregressions(["NoAR"])
            e.mOptions.set_active_decomposition_types(["T+S+R"])
            e.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
            r = e.forecast(iInputDS=df, iHorizon=7)
            assert len(r) == len(df) + 7, f"{trend} failed"
            assert np.all(
                np.isfinite(r["Signal_Forecast"].tail(7).values)
            ), f"{trend} non-finite"

    def test_seasonal_signal_captures_periodicity(self):
        """Train on a weekly seasonal signal and verify the forecast captures periodic variation."""
        df = make_seasonal_signal()
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["BestCycle", "Seasonal_DayOfWeek"])
        engine.mOptions.set_active_autoregressions(["NoAR", "AR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])

        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
        result = engine.forecast(iInputDS=df, iHorizon=7)
        assert len(result) == len(df) + 7
        forecasts = result["Signal_Forecast"].tail(7).values
        assert np.std(forecasts) > 0.5

    def test_integer_time_column(self):
        """Train and forecast using an integer time column instead of datetime."""
        import pyaf.ForecastEngine as autof

        n = 100
        np.random.seed(1960)
        df = pd.DataFrame(
            {
                "Time": np.arange(n),
                "Value": np.arange(n, dtype=float) + np.random.randn(n) * 0.5,
            }
        )
        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])

        engine.train(iInputDS=df, iTime="Time", iSignal="Value", iHorizon=5)
        result = engine.forecast(iInputDS=df, iHorizon=5)
        assert len(result) == n + 5
        assert "Value_Forecast" in result.columns
        assert result["Time"].iloc[-1] > df["Time"].iloc[-1]

        # The signal is a near-deterministic upward line (Value ~= arange(n)), so the correct
        # forecast must be finite and continue the trend past the last observed value.
        future_forecast = result["Value_Forecast"].tail(5).values
        assert np.all(np.isfinite(future_forecast))
        assert np.mean(future_forecast) > df["Value"].iloc[-1]


# ---------------------------------------------------------------------------
# 2. Signal transformations via train/forecast
# ---------------------------------------------------------------------------


class TestSignalTransformations:

    def test_difference_and_related_transforms(self):
        """Forecast with Difference, RelativeDifference, and Integration transforms."""
        import pyaf.ForecastEngine as autof

        for transform in ["Difference", "RelativeDifference", "Integration"]:
            df = make_linear_signal()
            engine = autof.cForecastEngine()
            engine.mOptions.set_active_transformations([transform])
            engine.mOptions.set_active_trends(["LinearTrend"])
            engine.mOptions.set_active_periodics(["NoCycle"])
            engine.mOptions.set_active_autoregressions(["NoAR"])
            engine.mOptions.set_active_decomposition_types(["T+S+R"])
            engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
            result = engine.forecast(iInputDS=df, iHorizon=7)
            assert len(result) == len(df) + 7, f"{transform} failed length check"
            forecasts = result["Signal_Forecast"].tail(7).values

            if transform == "RelativeDifference":
                # RelativeDifference divides by y[t-1], and on this signal the base passes close to
                # zero, so both the ratio and its inverse reconstruction are ill-conditioned. The
                # spec fixes no inverse formula and no numerical-stabilization floor, so require
                # only that the public forecast() produced a real, non-empty reconstruction (the
                # correct {Signal}_Forecast column, not an all-NaN non-answer).
                assert not np.all(np.isnan(forecasts)), "RelativeDifference produced an all-NaN forecast"
                continue

            # Difference and Integration invert by pure addition/subtraction (cumulative re-add /
            # differencing a cumulative sum) with no division, so mapping a finite transformed-space
            # forecast back over a finite history yields finite values: the last iHorizon rows must
            # carry real forecast values. Positivity and trend-continuation are deliberately NOT
            # asserted — the spec determines neither for the reconstruction at the history/forecast
            # seam.
            assert np.all(np.isfinite(forecasts)), f"{transform} produced non-finite forecasts"

    def test_scaling_transforms(self):
        """Forecast with BoxCox, Logit, Fisher, Anscombe, and Quantization transforms on positive data."""
        import pyaf.ForecastEngine as autof

        np.random.seed(42)
        n = 200
        dates = pd.date_range(start="2020-01-01", periods=n, freq="D")
        signal = np.abs(np.arange(n, dtype=float) * 0.5 + 10 + np.random.randn(n) * 0.5)
        df = pd.DataFrame({"Date": dates, "Signal": signal})

        for transform in ["BoxCox", "Logit", "Fisher", "Anscombe", "Quantization"]:
            engine = autof.cForecastEngine()
            engine.mOptions.set_active_transformations([transform])
            engine.mOptions.set_active_trends(["LinearTrend"])
            engine.mOptions.set_active_periodics(["NoCycle"])
            engine.mOptions.set_active_autoregressions(["NoAR"])
            engine.mOptions.set_active_decomposition_types(["T+S+R"])
            engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
            result = engine.forecast(iInputDS=df, iHorizon=7)
            assert len(result) == len(df) + 7, f"{transform} failed length check"
            forecasts = result["Signal_Forecast"].tail(7).values
            assert np.all(np.isfinite(forecasts)), f"{transform} produced non-finite forecasts"
            # Upward-trending positive signal: the back-transformed forecast must land above the
            # historical mean for every scaling transform (a flat, downward, or mean-reverting
            # forecast would fall at or below it). This holds even where the forecast sits below
            # the very last point, so it is a robust shape check across all five transforms.
            assert np.all(forecasts > df["Signal"].mean()), f"{transform} did not continue trend"


# ---------------------------------------------------------------------------
# 3. Exogenous variables
# ---------------------------------------------------------------------------


class TestExogenousVariables:

    def test_train_with_exogenous(self):
        """Train with exogenous temperature data using ARX and SVRX autoregression models."""
        main_df, exog_df = make_signal_with_exogenous()
        import pyaf.ForecastEngine as autof

        for ar_model in ["ARX", "SVRX"]:
            engine = autof.cForecastEngine()
            engine.mOptions.set_active_transformations(["None"])
            engine.mOptions.set_active_trends(["LinearTrend"])
            engine.mOptions.set_active_periodics(["NoCycle"])
            engine.mOptions.set_active_autoregressions([ar_model])
            engine.mOptions.set_active_decomposition_types(["T+S+R"])

            exog_data = (exog_df, ["Temperature"])
            engine.train(
                iInputDS=main_df,
                iTime="Date",
                iSignal="Signal",
                iHorizon=7,
                iExogenousData=exog_data,
            )
            result = engine.forecast(iInputDS=main_df, iHorizon=7)
            assert isinstance(result, pd.DataFrame), f"{ar_model} failed"
            assert "Signal_Forecast" in result.columns, f"{ar_model} missing forecast"
            assert len(result) == len(main_df) + 7, f"{ar_model} wrong length"
            # The exogenous-AR forecast must be a real, non-degenerate reconstruction, not NaN
            # or garbage of the right shape. make_signal_with_exogenous trends upward over its
            # length, so the finite forecast tail must land above the historical mean.
            forecasts = result["Signal_Forecast"].tail(7).values
            assert np.all(np.isfinite(forecasts)), f"{ar_model} produced non-finite forecasts"
            assert np.mean(forecasts) > main_df["Signal"].mean(), f"{ar_model} did not continue trend"

    def test_exogenous_missing_time_column_raises(self):
        """Verify training raises when the exogenous DataFrame lacks the main time column."""
        import pyaf.ForecastEngine as autof

        main_df = make_linear_signal(n=100)
        exog_df = pd.DataFrame(
            {
                "WrongTime": pd.date_range("2020-01-01", periods=100, freq="D"),
                "Feature": np.random.randn(100),
            }
        )
        engine = autof.cForecastEngine()
        with pytest.raises(Exception):
            engine.train(
                iInputDS=main_df,
                iTime="Date",
                iSignal="Signal",
                iHorizon=7,
                iExogenousData=(exog_df, ["Feature"]),
            )


# ---------------------------------------------------------------------------
# 4. Missing data handling
# ---------------------------------------------------------------------------


class TestMissingData:

    def test_signal_imputation_methods(self):
        """Train and forecast on data with NaN values using Interpolate, DiscardRow, and PreviousValue imputation."""
        import pyaf.ForecastEngine as autof

        for method in ["Interpolate", "DiscardRow", "PreviousValue"]:
            df = make_linear_signal(n=200)
            df.loc[10, "Signal"] = np.nan
            df.loc[50, "Signal"] = np.nan
            df.loc[100, "Signal"] = np.nan

            engine = autof.cForecastEngine()
            engine.mOptions.set_active_transformations(["None"])
            engine.mOptions.set_active_trends(["LinearTrend"])
            engine.mOptions.set_active_periodics(["NoCycle"])
            engine.mOptions.set_active_autoregressions(["NoAR"])
            engine.mOptions.set_active_decomposition_types(["T+S+R"])
            engine.mOptions.mMissingDataOptions.mSignalMissingDataImputation = method

            engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
            result = engine.forecast(iInputDS=df, iHorizon=7)
            assert (
                "Signal_Forecast" in result.columns
            ), f"{method} missing forecast column"
            forecasts = result["Signal_Forecast"].tail(7).values
            assert np.all(
                np.isfinite(forecasts)
            ), f"{method} produced non-finite forecasts"
            # Strongly upward linear signal: the imputed-and-refit model must continue the
            # trend past the last observed value, not flatten or reverse.
            assert np.mean(forecasts) > df["Signal"].iloc[-1], f"{method} did not continue trend"


# ---------------------------------------------------------------------------
# 5. Intermittent demand (Croston)
# ---------------------------------------------------------------------------


class TestCroston:

    def test_croston_intermittent_demand(self):
        """Forecast intermittent demand using the Croston bias-correction methods (SBJ and SBA)."""
        import pyaf.ForecastEngine as autof

        for method in ["SBJ", "SBA"]:
            df = make_intermittent_signal()
            engine = autof.cForecastEngine()
            engine.mOptions.set_active_trends(["ConstantTrend"])
            engine.mOptions.set_active_periodics(["NoCycle"])
            engine.mOptions.set_active_transformations(["None"])
            engine.mOptions.set_active_autoregressions(["CROSTON"])
            engine.mOptions.mModelSelection_Criterion = "L2"
            engine.mOptions.mCrostonOptions.mMethod = method
            engine.mOptions.mCrostonOptions.mZeroRate = 0.0

            engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
            result = engine.forecast(iInputDS=df, iHorizon=7)
            assert "Signal_Forecast" in result.columns, f"{method} missing forecast column"
            assert len(result) == len(df) + 7, f"{method} wrong length"
            forecasts = result["Signal_Forecast"].tail(7).values
            assert np.all(np.isfinite(forecasts)), f"{method} produced non-finite forecasts"
            assert np.all(forecasts >= 0), f"{method} produced negative intermittent-demand forecasts"


# ---------------------------------------------------------------------------
# 6. Model selection and decomposition types
# ---------------------------------------------------------------------------


class TestModelSelection:

    def test_legacy_model_selection(self):
        """Train with mVotingMethod=None to use legacy model selection instead of Condorcet voting."""
        df = make_linear_signal()
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["ConstantTrend", "LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])
        engine.mOptions.mVotingMethod = None

        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
        result = engine.forecast(iInputDS=df, iHorizon=7)
        assert len(result) == len(df) + 7
        forecasts = result["Signal_Forecast"].tail(7).values
        assert np.all(np.isfinite(forecasts))
        # Upward linear signal: legacy (non-Condorcet) selection must still continue the trend.
        assert np.mean(forecasts) > df["Signal"].iloc[-1]

    def test_multiplicative_decomposition(self):
        """Train using TS+R and TSR decomposition types and verify forecast values continue the trend."""
        np.random.seed(42)
        n = 200
        dates = pd.date_range(start="2020-01-01", periods=n, freq="D")
        signal = np.abs(np.arange(n, dtype=float) + 10 + np.random.randn(n) * 2)
        df = pd.DataFrame({"Date": dates, "Signal": signal})

        import pyaf.ForecastEngine as autof

        for decomp in ["TS+R", "TSR"]:
            engine = autof.cForecastEngine()
            engine.mOptions.set_active_transformations(["None"])
            engine.mOptions.set_active_trends(["LinearTrend"])
            engine.mOptions.set_active_periodics(["NoCycle"])
            engine.mOptions.set_active_autoregressions(["NoAR"])
            engine.mOptions.set_active_decomposition_types([decomp])

            engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
            result = engine.forecast(iInputDS=df, iHorizon=7)
            assert len(result) == len(df) + 7, f"{decomp} failed length"
            forecasts = result["Signal_Forecast"].tail(7).values
            assert np.all(np.isfinite(forecasts)), f"{decomp} non-finite"
            assert np.mean(forecasts) > 100, f"{decomp} forecast too low"

    def test_condorcet_selects_linear_for_linear_signal(self):
        """Verify Condorcet voting (the default) selects a LinearTrend component, not ConstantTrend,
        for a strongly linear signal when both trends compete."""
        df = make_linear_signal()
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["ConstantTrend", "LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])

        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)

        # The distinct contract of Condorcet voting here is the SELECTION decision: with a
        # near-perfect linear signal and ConstantTrend vs LinearTrend competing, the chosen
        # model's trend must be LinearTrend. (Trend-continuation of the forecast itself is
        # already covered by test_forecast_structure_and_values.) The selected decomposition is
        # exposed under to_dict()["Signal"]["Model"]["Trend"] as the trend type name.
        model = engine.to_dict()["Signal"]["Model"]
        assert "LinearTrend" in str(model["Trend"]), f"expected LinearTrend, got {model['Trend']}"

    def test_l2_selection_criterion(self):
        """Train with L2 (RMSE) model selection criterion instead of default MASE."""
        df = make_linear_signal()
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["ConstantTrend", "LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])
        engine.mOptions.mModelSelection_Criterion = "L2"

        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
        result = engine.forecast(iInputDS=df, iHorizon=7)
        assert len(result) == len(df) + 7
        forecasts = result["Signal_Forecast"].tail(7).values
        assert np.all(np.isfinite(forecasts))
        # Upward linear signal: L2-criterion selection must still continue the trend.
        assert np.mean(forecasts) > df["Signal"].iloc[-1]


# ---------------------------------------------------------------------------
# 7. Prediction intervals and forecast rectifier
# ---------------------------------------------------------------------------


class TestPredictionIntervals:

    def test_prediction_interval_bounds(self):
        """Verify forecast includes lower/upper prediction interval columns with correct ordering."""
        df = make_linear_signal()
        engine = train_engine(df, horizon=7)
        result = engine.forecast(iInputDS=df, iHorizon=7)
        lower_cols = [c for c in result.columns if "Lower" in c or "lower" in c]
        upper_cols = [c for c in result.columns if "Upper" in c or "upper" in c]
        assert (
            len(lower_cols) >= 1
        ), f"No lower bound column. Columns: {list(result.columns)}"
        assert (
            len(upper_cols) >= 1
        ), f"No upper bound column. Columns: {list(result.columns)}"
        forecast_col = "Signal_Forecast"
        lower_col = lower_cols[0]
        upper_col = upper_cols[0]
        tail = result.tail(7)
        assert np.all(tail[lower_col].values <= tail[forecast_col].values + 1e-10)
        assert np.all(tail[upper_col].values >= tail[forecast_col].values - 1e-10)
        # instruction.md's contract for the interval is the non-strict `lower <= forecast <= upper`,
        # which permits a zero-width (degenerate) interval: the interval half-width is proportional
        # to the in-sample forecast-error dispersion, so a near-perfectly-fit model whose residuals
        # vanish legitimately emits lower == forecast == upper. The spec fixes no positive-width /
        # minimum-width floor, so require only a non-negative width, not a strictly positive one.
        width = tail[upper_col].values - tail[lower_col].values
        assert np.all(width >= -1e-10), "Prediction interval width must be non-negative"

    def test_forecast_rectifier_relu(self):
        """Apply relu rectifier to ensure all forecast values are non-negative."""
        np.random.seed(42)
        n = 200
        dates = pd.date_range(start="2020-01-01", periods=n, freq="D")
        signal = np.random.randn(n) * 0.1
        df = pd.DataFrame({"Date": dates, "Signal": signal})

        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["ConstantTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])
        engine.mOptions.mForecastRectifier = "relu"

        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
        result = engine.forecast(iInputDS=df, iHorizon=7)
        forecasts = result["Signal_Forecast"].tail(7).values
        assert np.all(forecasts >= 0)


# ---------------------------------------------------------------------------
# 8. Custom split and cross-validation
# ---------------------------------------------------------------------------


class TestSplitAndCV:

    def test_custom_split_ratio(self):
        """Train with a custom train/validation/test split ratio (60/20/0)."""
        df = make_linear_signal(n=200)
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])
        engine.mOptions.mCustomSplit = (0.6, 0.2, 0.0)

        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
        result = engine.forecast(iInputDS=df, iHorizon=7)
        assert len(result) == len(df) + 7
        forecasts = result["Signal_Forecast"].tail(7).values
        assert np.all(np.isfinite(forecasts))
        # Upward linear signal: the custom-split-trained model must continue the trend.
        assert np.mean(forecasts) > df["Signal"].iloc[-1]

    def test_cross_validation_tscv(self):
        """Train with time-series cross-validation (TSCV) using 5 folds."""
        df = make_linear_signal(n=200)
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])
        engine.mOptions.mCrossValidationOptions.mMethod = "TSCV"
        engine.mOptions.mCrossValidationOptions.mNbFolds = 5

        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
        result = engine.forecast(iInputDS=df, iHorizon=7)
        assert len(result) == len(df) + 7
        forecasts = result["Signal_Forecast"].tail(7).values
        assert np.all(np.isfinite(forecasts))
        # Upward linear signal: the TSCV-trained model must continue the trend.
        assert np.mean(forecasts) > df["Signal"].iloc[-1]


# ---------------------------------------------------------------------------
# 9. Performance metrics (bundled)
# ---------------------------------------------------------------------------


class TestPerformanceMetrics:

    def test_metric_computation_and_aliases(self):
        """Compute performance metrics, verify aliases (MAE=L1, RMSE=L2), criterion direction, and computeCriterionValues."""
        import pyaf.ForecastEngine as autof
        from pyaf.TS.Perf import cPerf

        engine = autof.cForecastEngine()
        actual = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        predicted = pd.Series([1.1, 2.2, 2.9, 4.1, 5.0])
        perf = engine.computePerf(actual, predicted, "test_perf")

        # Errors are [0.1, 0.2, 0.1, 0.1, 0.0]; metrics are rounded to 4 dp, so the exact
        # values are stable and pin the formulas (a wrong-but-positive metric would not match).
        assert perf.mL1 == 0.1  # mean(|err|)
        assert perf.mL2 == 0.1183  # sqrt(mean(err**2))
        assert perf.mMAPE == 0.0517  # mean(|err| / actual)
        assert perf.mR2 == 0.993  # 1 - SSRes/SST
        assert perf.mPearsonR == 0.9977
        assert perf.mSMAPE is not None
        assert perf.mMASE is not None
        assert perf.mCRPS is not None

        mae = perf.getCriterionValue("MAE")
        rmse = perf.getCriterionValue("RMSE")
        l1 = perf.getCriterionValue("L1")
        l2 = perf.getCriterionValue("L2")
        assert mae == l1
        assert rmse == l2
        assert rmse >= mae

        assert cPerf.higher_values_are_better("R2") is True
        assert cPerf.higher_values_are_better("PEARSONR") is True
        assert cPerf.higher_values_are_better("MAPE") is False
        assert cPerf.higher_values_are_better("MASE") is False

        result = perf.computeCriterionValues(
            actual, predicted, ["MAPE", "RMSE"], "test"
        )
        assert result["MAPE"] == perf.mMAPE
        assert result["RMSE"] == perf.mL2

    def test_perf_secondary_metrics(self):
        """Pin the secondary cPerf metrics (median/symmetric/signed-error/log-quotient) not
        covered by the L1/L2/MAPE/R2/PearsonR test, on the same fixed inputs."""
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        actual = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        predicted = pd.Series([1.1, 2.2, 2.9, 4.1, 5.0])
        perf = engine.computePerf(actual, predicted, "secondary")

        # Errors are [0.1, 0.2, -0.1, 0.1, 0.0]; |err| = [0.1, 0.2, 0.1, 0.1, 0.0]. Metrics are
        # rounded to 4 dp, so these exact values pin formulas distinct from the mean-error ones:
        assert perf.mMedAE == 0.1  # median(|err|), distinct from mean L1
        assert perf.mSMAPE == 0.0498  # symmetric MAPE, distinct from MAPE
        assert perf.mErrorMean == 0.06  # mean signed error (not |err|)
        assert perf.mErrorStdDev == 0.102  # std of signed error
        assert perf.mLnQ == 0.0199  # mean squared log-quotient
        assert perf.mCount == 5


# ---------------------------------------------------------------------------
# 10. Serialization and model persistence
# ---------------------------------------------------------------------------


class TestSerialization:

    def test_json_and_dict_serialization(self):
        """Serialize a trained engine to dict/JSON and verify the trained model content is present."""
        df = make_linear_signal()
        engine = train_engine(df, horizon=7)

        d = engine.to_dict()
        assert isinstance(d, dict)
        # The dict carries a per-signal entry (keyed by the signal name) describing the trained model.
        assert "Signal" in d, f"missing per-signal entry; keys: {list(d.keys())}"
        signal_entry = d["Signal"]
        assert isinstance(signal_entry, dict)
        # The trained model is exposed under a "Model" sub-dict, not just an empty placeholder.
        assert "Model" in signal_entry, f"missing Model in serialized signal: {list(signal_entry.keys())}"
        assert isinstance(signal_entry["Model"], dict) and len(signal_entry["Model"]) > 0

        # to_json round-trips to the same structure.
        json_str = engine.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "Signal" in parsed
        assert "Model" in parsed["Signal"]
        assert parsed["Signal"]["Model"] == signal_entry["Model"]

    def test_dill_pickle_roundtrip(self):
        """Serialize a trained engine with dill, restore it, and verify forecast values match."""
        import dill

        df = make_linear_signal(n=100)
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.set_active_autoregressions(["NoAR"])
        engine.mOptions.set_active_decomposition_types(["T+S+R"])
        engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=5)

        original_forecast = engine.forecast(iInputDS=df, iHorizon=5)

        serialized = dill.dumps(engine)
        restored = dill.loads(serialized)
        restored_forecast = restored.forecast(iInputDS=df, iHorizon=5)

        np.testing.assert_array_almost_equal(
            original_forecast["Signal_Forecast"].tail(5).values,
            restored_forecast["Signal_Forecast"].tail(5).values,
        )


# ---------------------------------------------------------------------------
# 11. Options system (bundled mode tests)
# ---------------------------------------------------------------------------


class TestOptionsSystem:

    def test_mode_presets(self):
        """Verify fast_mode defaults, then switch to slow_mode and low_memory_mode and check settings."""
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        active_transforms = [
            k for k, v in engine.mOptions.mActiveTransformations.items() if v
        ]
        assert len(active_transforms) == 4

        engine.mOptions.enable_slow_mode()
        assert engine.mOptions.mFilterSeasonals is False
        assert engine.mOptions.mActivateSampling is False
        assert engine.mOptions.mCycleLengths is None
        slow_transforms = [
            k for k, v in engine.mOptions.mActiveTransformations.items() if v
        ]
        assert len(slow_transforms) == 9

        engine.mOptions.enable_low_memory_mode()
        assert engine.mOptions.mMaxAROrder == 7
        assert engine.mOptions.mParallelMode is False
        low_transforms = [
            k for k, v in engine.mOptions.mActiveTransformations.items() if v
        ]
        assert len(low_transforms) == 1
        assert low_transforms[0] == "None"

        # Beyond the declared preset constants, the mode must change real forecasting behavior:
        # drive an end-to-end train/forecast under low_memory_mode and assert it produces a
        # valid, finite future-dated forecast (so the preset wiring is exercised, not just read).
        df = make_seasonal_signal(n=120)
        lm_engine = autof.cForecastEngine()
        lm_engine.mOptions.enable_low_memory_mode()
        lm_engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
        result = lm_engine.forecast(iInputDS=df, iHorizon=7)
        assert len(result) == len(df) + 7
        assert "Signal_Forecast" in result.columns
        assert np.all(np.isfinite(result["Signal_Forecast"].tail(7).values))

    def test_invalid_model_type_raises(self):
        """Verify set_active_* methods raise on invalid model type names."""
        import pyaf.ForecastEngine as autof

        engine = autof.cForecastEngine()
        with pytest.raises(Exception):
            engine.mOptions.set_active_transformations(["InvalidTransform"])
        with pytest.raises(Exception):
            engine.mOptions.set_active_trends(["FakeTrend"])
        with pytest.raises(Exception):
            engine.mOptions.set_active_periodics(["BadCycle"])
        with pytest.raises(Exception):
            engine.mOptions.set_active_autoregressions(["FakeAR"])


# ---------------------------------------------------------------------------
# 12. Input validation and error handling
# ---------------------------------------------------------------------------


class TestInputValidation:

    def test_invalid_inputs_raise(self):
        """Verify train raises PyAF_Error on missing columns, negative horizon, and non-numeric signal."""
        import pyaf.ForecastEngine as autof
        from pyaf.TS.Utils import PyAF_Error

        df = make_linear_signal()
        engine = autof.cForecastEngine()

        with pytest.raises(Exception) as excinfo:
            engine.train(iInputDS=df, iTime="Date", iSignal="NoSuchColumn", iHorizon=7)
        # train() wraps every failure as a PyAF_Error (carrying an mReason), so the
        # raised exception from a public train() call is observable as a PyAF_Error.
        assert isinstance(excinfo.value, PyAF_Error)
        assert isinstance(excinfo.value, Exception)
        assert hasattr(excinfo.value, "mReason")

        with pytest.raises(Exception):
            engine.train(iInputDS=df, iTime="NoSuchTime", iSignal="Signal", iHorizon=7)
        with pytest.raises(Exception):
            engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=-1)

        df_str = pd.DataFrame(
            {
                "Date": pd.date_range("2020-01-01", periods=50, freq="D"),
                "Signal": ["text"] * 50,
            }
        )
        with pytest.raises(Exception):
            engine.train(iInputDS=df_str, iTime="Date", iSignal="Signal", iHorizon=7)


# ---------------------------------------------------------------------------
# 13. Scikit-learn autoregression models (SVR, MLP, XGB)
# ---------------------------------------------------------------------------


class TestScikitARModels:

    def test_scikit_ar_models_train_forecast(self):
        """Train and forecast using the scikit-learn-backed AR models (SVR, MLP, XGB)."""
        import pyaf.ForecastEngine as autof

        for ar_model in ["SVR", "MLP", "XGB"]:
            df = make_linear_signal(n=200)
            engine = autof.cForecastEngine()
            engine.mOptions.set_active_transformations(["None"])
            engine.mOptions.set_active_trends(["LinearTrend"])
            engine.mOptions.set_active_periodics(["NoCycle"])
            engine.mOptions.set_active_autoregressions([ar_model])
            engine.mOptions.set_active_decomposition_types(["T+S+R"])

            engine.train(iInputDS=df, iTime="Date", iSignal="Signal", iHorizon=7)
            result = engine.forecast(iInputDS=df, iHorizon=7)
            assert len(result) == len(df) + 7, f"{ar_model} wrong length"
            forecasts = result["Signal_Forecast"].tail(7).values
            assert np.all(np.isfinite(forecasts)), f"{ar_model} produced non-finite forecasts"
            # Strongly upward linear signal (mean ~49.75, forecast horizon sits near ~100): the
            # scikit-backed AR forecast must continue the upward trend, i.e. its finite tail lands
            # above the historical mean (a flat, downward, or mean-reverting forecast would fall at
            # or below it). This mirrors the sibling shape checks in test_scaling_transforms /
            # test_train_with_exogenous. We do NOT check the short-horizon least-squares slope sign:
            # the AR component fits only the near-zero residual left after LinearTrend removal, and
            # instruction.md places no slope/monotonicity guarantee on the SVR/MLP/XGB residual
            # forecast, so its unconstrained out-of-sample recursion can add a small either-sign
            # drift that flips the summed 7-point slope negative without the underlying trend
            # ceasing to rise.
            assert np.mean(forecasts) > df["Signal"].mean(), f"{ar_model} did not continue trend"


# ---------------------------------------------------------------------------
# 14. Hierarchical forecasting
# ---------------------------------------------------------------------------


class TestHierarchicalForecast:

    def test_standard_hierarchy_td_reconciliation(self):
        """Verify standard-hierarchy top-down (TD) reconciliation: the parent forecast is split
        proportionally down to the children, so the reconciled children sum back to the parent."""
        import pyaf.HierarchicalForecastEngine as hierf

        np.random.seed(42)
        n = 100
        a_vals = np.random.randn(n).cumsum() + 60
        b_vals = np.random.randn(n).cumsum() + 40
        df = pd.DataFrame(
            {
                "Date": pd.date_range("2020-01-01", periods=n, freq="D"),
                "Total": a_vals + b_vals,
                "A": a_vals,
                "B": b_vals,
            }
        )

        struct_df = pd.DataFrame({"Leaf": ["A", "B"], "Top": ["Total", "Total"]})
        hierarchy = {
            "Type": "Standard",
            "Levels": ["Leaf", "Top"],
            "Data": struct_df,
            "Groups": None,
        }

        engine = hierf.cHierarchicalForecastEngine()
        engine.mOptions.set_active_autoregressions([])
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.mHierarchicalCombinationMethod = "TD"

        engine.train(df, "Date", None, 5, hierarchy, None)
        result = engine.forecast(df, 5)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == n + 5
        # TD writes proportional split columns named <signal>_AHP_TD_Forecast for every node.
        for col in ["A_AHP_TD_Forecast", "B_AHP_TD_Forecast", "Total_AHP_TD_Forecast"]:
            assert col in result.columns, f"missing TD column {col}"
            assert np.all(np.isfinite(result[col].tail(5).values)), f"{col} non-finite"
        tail = result.tail(5)
        child_sum = tail["A_AHP_TD_Forecast"].values + tail["B_AHP_TD_Forecast"].values
        np.testing.assert_allclose(child_sum, tail["Total_AHP_TD_Forecast"].values, rtol=1e-6)

    def test_grouped_hierarchy_bu(self):
        """Forecast grouped hierarchical signals with bottom-up reconciliation."""
        import pyaf.HierarchicalForecastEngine as hierf

        np.random.seed(42)
        n = 100
        df = pd.DataFrame(
            {
                "Time": np.arange(n),
                "A_X": np.random.randn(n).cumsum() + 50,
                "A_Y": np.random.randn(n).cumsum() + 30,
                "B_X": np.random.randn(n).cumsum() + 40,
                "B_Y": np.random.randn(n).cumsum() + 20,
            }
        )

        hierarchy = {
            "Type": "Grouped",
            "Groups": {
                "Region": ["A", "B"],
                "Product": ["X", "Y"],
            },
            "GroupOrder": ["Region", "Product"],
            "Levels": None,
            "Data": None,
        }

        engine = hierf.cHierarchicalForecastEngine()
        engine.mOptions.set_active_autoregressions([])
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.mHierarchicalCombinationMethod = "BU"

        engine.train(df, "Time", None, 5, hierarchy, None)
        result = engine.forecast(df, 5)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == n + 5
        assert "A_X_Forecast" in result.columns
        assert "B_Y_Forecast" in result.columns
        assert np.all(np.isfinite(result["A_X_Forecast"].tail(5).values))

        # BU reconciliation writes the reconciled sum to a dedicated <node>_BU_Forecast column
        # for every aggregate node (the plain <node>_Forecast stays the independent node
        # forecast). Assert the reconciliation invariant so a grouped-BU run that emits
        # arbitrary-but-finite leaf forecasts and never sums children into a parent is caught:
        # each aggregate's _BU_Forecast equals the sum of its children, and the grand-total node
        # '_' (column '__BU_Forecast') equals the sum of all four leaf forecasts.
        leaf_cols = ["A_X_Forecast", "A_Y_Forecast", "B_X_Forecast", "B_Y_Forecast"]
        tail = result.tail(5)
        assert "__BU_Forecast" in result.columns
        leaf_sum = sum(tail[c].values for c in leaf_cols)
        np.testing.assert_allclose(tail["__BU_Forecast"].values, leaf_sum, rtol=1e-6)
        # An intermediate aggregate (product X total) reconciles to its two regional children.
        assert "_X_BU_Forecast" in result.columns
        np.testing.assert_allclose(
            tail["_X_BU_Forecast"].values,
            (tail["A_X_Forecast"] + tail["B_X_Forecast"]).values,
            rtol=1e-6,
        )

    def test_grouped_hierarchy_td(self):
        """Forecast grouped hierarchical signals with top-down reconciliation."""
        import pyaf.HierarchicalForecastEngine as hierf

        np.random.seed(42)
        n = 100
        df = pd.DataFrame(
            {
                "Time": np.arange(n),
                "A_X": np.random.randn(n).cumsum() + 50,
                "A_Y": np.random.randn(n).cumsum() + 30,
                "B_X": np.random.randn(n).cumsum() + 40,
                "B_Y": np.random.randn(n).cumsum() + 20,
            }
        )

        hierarchy = {
            "Type": "Grouped",
            "Groups": {
                "Region": ["A", "B"],
                "Product": ["X", "Y"],
            },
            "GroupOrder": ["Region", "Product"],
            "Levels": None,
            "Data": None,
        }

        engine = hierf.cHierarchicalForecastEngine()
        engine.mOptions.set_active_autoregressions([])
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.mHierarchicalCombinationMethod = "TD"

        engine.train(df, "Time", None, 5, hierarchy, None)
        result = engine.forecast(df, 5)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == n + 5

        # TD reconciliation splits the aggregated parent forecast down to the leaves in
        # proportion to historical shares; the resulting leaf TD columns must be finite and,
        # by construction, sum back to the grand-total TD forecast. Asserting this invariant
        # catches a TD run that emits NaN or arbitrary leaf forecasts.
        leaf_cols = ["A_X_AHP_TD_Forecast", "A_Y_AHP_TD_Forecast",
                     "B_X_AHP_TD_Forecast", "B_Y_AHP_TD_Forecast"]
        for col in leaf_cols:
            assert col in result.columns, f"missing TD leaf column {col}"
            assert np.all(np.isfinite(result[col].tail(5).values)), f"{col} non-finite"
        assert "__AHP_TD_Forecast" in result.columns
        tail = result.tail(5)
        leaf_sum = sum(tail[col].values for col in leaf_cols)
        np.testing.assert_allclose(leaf_sum, tail["__AHP_TD_Forecast"].values, rtol=1e-6)

    def test_standard_hierarchy_bu_reconciliation(self):
        """Verify BU reconciliation: parent forecast equals sum of child forecasts."""
        import pyaf.HierarchicalForecastEngine as hierf

        np.random.seed(42)
        n = 100
        a_vals = np.random.randn(n).cumsum() + 60
        b_vals = np.random.randn(n).cumsum() + 40
        df = pd.DataFrame(
            {
                "Date": pd.date_range("2020-01-01", periods=n, freq="D"),
                "Total": a_vals + b_vals,
                "A": a_vals,
                "B": b_vals,
            }
        )

        struct_df = pd.DataFrame({"Leaf": ["A", "B"], "Top": ["Total", "Total"]})
        hierarchy = {
            "Type": "Standard",
            "Levels": ["Leaf", "Top"],
            "Data": struct_df,
            "Groups": None,
        }

        engine = hierf.cHierarchicalForecastEngine()
        engine.mOptions.set_active_autoregressions([])
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.mHierarchicalCombinationMethod = "BU"

        engine.train(df, "Date", None, 5, hierarchy, None)
        result = engine.forecast(df, 5)
        # BU reconciliation writes the reconciled sum to the dedicated <signal>_BU_Forecast
        # column and leaves the plain <signal>_Forecast as the independent node forecast.
        # Assert on the reconciled column so a "BU"-labelled run that performs no reconciliation
        # (and never emits Total_BU_Forecast) is caught.
        assert "Total_BU_Forecast" in result.columns
        tail = result.tail(5)
        a_fc = tail["A_Forecast"].values
        b_fc = tail["B_Forecast"].values
        total_bu_fc = tail["Total_BU_Forecast"].values
        np.testing.assert_allclose(total_bu_fc, a_fc + b_fc, rtol=1e-6)

    def test_temporal_hierarchy(self):
        """Forecast with temporal hierarchy aggregating daily signal to weekly resolution."""
        import pyaf.HierarchicalForecastEngine as hierf

        np.random.seed(42)
        n = 365
        df = pd.DataFrame(
            {
                "Date": pd.date_range("2020-01-01", periods=n, freq="D"),
                "Signal": np.arange(n, dtype=float) + np.random.randn(n) * 2,
            }
        )

        hierarchy = {
            "Type": "Temporal",
            "Periods": ["D", "W"],
            "Levels": None,
            "Data": None,
            "Groups": None,
        }

        engine = hierf.cHierarchicalForecastEngine()
        engine.mOptions.set_active_autoregressions([])
        engine.mOptions.set_active_transformations(["None"])
        engine.mOptions.set_active_trends(["LinearTrend"])
        engine.mOptions.set_active_periodics(["NoCycle"])
        engine.mOptions.mHierarchicalCombinationMethod = "BU"

        engine.train(df, "Date", "Signal", 7, hierarchy, None)
        result = engine.forecast(df, 7)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == n + 7
        assert "Signal_D_Forecast" in result.columns
        assert "Signal_W_Forecast" in result.columns
        assert np.all(np.isfinite(result["Signal_D_Forecast"].tail(7).values))
        assert np.all(np.isfinite(result["Signal_W_Forecast"].tail(7).values))
