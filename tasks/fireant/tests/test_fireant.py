"""
Test suite for fireant — analytics and reporting library.
"""

from datetime import date
from unittest import TestCase
from unittest.mock import MagicMock, Mock

import numpy as np
import pandas as pd
from pypika import Field as PyPikaField, JoinType, Table, functions as fn, Order

from fireant import (
    CSV, CumMean, CumProd, CumSum, DataSet, DataSetBlender, DataType,
    DayOverDay, DaysOverDays, Field, HighCharts, Join, MSSQLDatabase,
    MySQLDatabase, Pandas, PostgreSQLDatabase, ReactTable, RedshiftDatabase,
    RollingMean, Rollup, Share, SnowflakeDatabase, VerticaDatabase,
    WeekOverWeek, MonthOverMonth, QuarterOverQuarter, YearOverYear,
    YearsOverYears, day, hour, month, quarter, week, year,
)
from fireant.dataset.fields import DataSetFilterException
from fireant.dataset.filters import VoidFilter
from fireant.dataset.totals import get_totals_marker_for_dtype
from fireant.utils import alias_selector as f


class _MockDBMixin:
    connect = Mock()
    get_column_definitions = MagicMock(return_value=[])
    def __eq__(self, other):
        return isinstance(other, _MockDBMixin)

class MockVerticaDB(_MockDBMixin, VerticaDatabase):
    pass
class MockPostgresDB(_MockDBMixin, PostgreSQLDatabase):
    pass
class MockMySQLDB(_MockDBMixin, MySQLDatabase):
    pass

_db = MockVerticaDB()
_t = Table("analytics")
_t2 = Table("customers")

def _make_dataset(db=None):
    db = db or _db
    return DataSet(
        table=_t, database=db,
        fields=[
            Field("timestamp", definition=_t.timestamp, data_type=DataType.date, label="Timestamp"),
            Field("category", definition=_t.category, data_type=DataType.text, label="Category"),
            Field("account_id", definition=_t.account_id, data_type=DataType.number, label="Account"),
            Field("is_active", definition=_t.is_active, data_type=DataType.boolean, label="Active"),
            Field("clicks", definition=fn.Sum(_t.clicks), data_type=DataType.number, label="Clicks", thousands=","),
            Field("revenue", definition=fn.Sum(_t.revenue), data_type=DataType.number, label="Revenue", prefix="$", precision=2),
            Field("cust_name", definition=_t2.name, data_type=DataType.text, label="Customer Name"),
        ],
        joins=[Join(_t2, _t.customer_id == _t2.id, join_type=JoinType.left)],
    )


# ---------------------------------------------------------------------------
# 1. DataSet, Fields, Filters — consolidated
# ---------------------------------------------------------------------------

class TestDataSetFieldsAndFilters(TestCase):
    """DataSet creation, field properties, filter SQL generation, type
    restrictions, and WHERE vs HAVING — all in one realistic workflow."""

    def test_dataset_fields_filters_and_having(self):
        """Create dataset, verify field properties, exercise all filter
        operators with exact SQL, check type restrictions and HAVING."""
        ds = _make_dataset()
        self.assertIs(ds.fields.clicks, ds.fields["clicks"])
        self.assertTrue(ds.fields.clicks.is_aggregate)
        self.assertFalse(ds.fields.timestamp.is_aggregate)
        self.assertEqual("$", ds.fields.revenue.prefix)
        self.assertEqual(",", ds.fields.clicks.thousands)

        ds2 = ds.extra_fields(Field("bonus", definition=fn.Sum(_t.bonus)))
        self.assertIn("bonus", ds2.fields)
        self.assertNotIn("bonus", ds.fields)

        def sql(*filters):
            q = ds.query.widget(Pandas(ds.fields.clicks))
            for fltr in filters:
                q = q.filter(fltr)
            return str(q.sql[0])

        self.assertIn("\"category\"='X'", sql(ds.fields.category == "X"))
        self.assertIn("\"timestamp\"<>'2024-01-01'", sql(ds.fields.timestamp != date(2024, 1, 1)))
        self.assertIn("\"timestamp\">'2024-01-01'", sql(ds.fields.timestamp > date(2024, 1, 1)))
        self.assertIn("\"timestamp\" BETWEEN '2024-01-01' AND '2024-12-31'",
                      sql(ds.fields.timestamp.between(date(2024, 1, 1), date(2024, 12, 31))))
        self.assertIn("IN ('a','b')", sql(ds.fields.category.isin(["a", "b"])))
        self.assertIn("\"category\" NOT IN ('x')", sql(ds.fields.category.notin(["x"])))
        self.assertIn("LOWER(\"category\") LIKE LOWER('%foo%')", sql(ds.fields.category.like("%foo%")))
        self.assertIn("NOT LOWER(\"category\") LIKE LOWER('%bar%')", sql(ds.fields.category.not_like("%bar%")))
        self.assertIsInstance(ds.fields.category.void(), VoidFilter)

        having_sql = str(ds.query.widget(Pandas(ds.fields.clicks))
                         .dimension(ds.fields.category).filter(ds.fields.clicks > 100).sql[0])
        self.assertIn("HAVING", having_sql)
        self.assertIn("SUM(\"clicks\")>100", having_sql)

        with self.assertRaises(DataSetFilterException):
            ds.fields.category.gt(5)
        with self.assertRaises(DataSetFilterException):
            ds.fields.account_id.like("%x%")


# ---------------------------------------------------------------------------
# 2. Exact SQL — dimension/metric with $-aliased GROUP BY
# ---------------------------------------------------------------------------

class TestExactSQL(TestCase):
    """SQL generation uses $-prefixed aliases in GROUP BY. Full SQL
    string verification for multiple query patterns."""

    @classmethod
    def setUpClass(cls):
        t = Table("analytics")
        cls.ds = DataSet(table=t, database=MockVerticaDB(), fields=[
            Field("ts", definition=t.ts, data_type=DataType.date),
            Field("cat", definition=t.cat, data_type=DataType.text),
            Field("clicks", definition=fn.Sum(t.clicks)),
        ])

    def test_exact_sql_basic_dimension_metric(self):
        """Full SQL with $-alias in GROUP BY and ORDER BY."""
        sql = str(self.ds.query.widget(ReactTable(self.ds.fields.clicks))
                  .dimension(self.ds.fields.cat).sql[0])
        self.assertEqual(
            'SELECT "cat" "$cat",SUM("clicks") "$clicks" '
            'FROM "analytics" GROUP BY "$cat" ORDER BY "$cat" LIMIT 200000', sql)

    def test_exact_sql_day_interval(self):
        """TRUNC in SELECT, $-alias in GROUP BY."""
        sql = str(self.ds.query.widget(ReactTable(self.ds.fields.clicks))
                  .dimension(day(self.ds.fields.ts)).sql[0])
        self.assertEqual(
            'SELECT TRUNC("ts",\'DD\') "$ts",SUM("clicks") "$clicks" '
            'FROM "analytics" GROUP BY "$ts" ORDER BY "$ts" LIMIT 200000', sql)

    def test_exact_sql_with_where_filter(self):
        """WHERE clause with $-alias GROUP BY, and WHERE/HAVING partitioning
        when one query carries both a non-aggregate and an aggregate filter."""
        sql = str(self.ds.query.widget(ReactTable(self.ds.fields.clicks))
                  .dimension(self.ds.fields.cat).filter(self.ds.fields.cat == "X").sql[0])
        self.assertEqual(
            'SELECT "cat" "$cat",SUM("clicks") "$clicks" '
            'FROM "analytics" WHERE "cat"=\'X\' '
            'GROUP BY "$cat" ORDER BY "$cat" LIMIT 200000', sql)

        combined = str(self.ds.query.widget(ReactTable(self.ds.fields.clicks))
                       .dimension(self.ds.fields.cat)
                       .filter(self.ds.fields.cat == "tech")
                       .filter(self.ds.fields.clicks > 100).sql[0])
        self.assertIn("WHERE \"cat\"='tech'", combined)
        self.assertIn('HAVING SUM("clicks")>100', combined)

    def test_exact_sql_orderby_desc(self):
        """ORDER BY uses $-aliased metric with DESC."""
        sql = str(self.ds.query.widget(ReactTable(self.ds.fields.clicks))
                  .dimension(self.ds.fields.cat)
                  .orderby(self.ds.fields.clicks, Order.desc).sql[0])
        self.assertIn('ORDER BY "$clicks" DESC', sql)


# ---------------------------------------------------------------------------
# 3. Joins, immutability, intervals — consolidated
# ---------------------------------------------------------------------------

class TestJoinsIntervalsImmutability(TestCase):
    """Joins only when needed, builder immutability, all 6 intervals,
    and multi-join queries."""

    def test_joins_intervals_and_immutability(self):
        """No JOIN for local fields. JOIN for joined-table fields.
        All 6 intervals produce correct TRUNC. Builder is immutable."""
        ds = _make_dataset()
        self.assertNotIn("JOIN", str(ds.query.widget(ReactTable(ds.fields.clicks))
                                     .dimension(ds.fields.category).sql[0]))
        self.assertIn("JOIN", str(ds.query.widget(ReactTable(ds.fields.clicks))
                                  .dimension(ds.fields.cust_name).sql[0]))

        for fn_int, code in [(hour, "HH"), (day, "DD"), (week, "IW"),
                             (month, "MM"), (quarter, "Q"), (year, "Y")]:
            sql = str(ds.query.widget(ReactTable(ds.fields.clicks))
                      .dimension(fn_int(ds.fields.timestamp)).sql[0])
            self.assertIn(f"TRUNC(\"timestamp\",'{code}')", sql)

        q1 = ds.query.widget(ReactTable(ds.fields.clicks)).dimension(ds.fields.category)
        q2 = q1.orderby(ds.fields.clicks, Order.desc)
        self.assertNotEqual(str(q1.sql), str(q2.sql))


# ---------------------------------------------------------------------------
# 4. Database backends — consolidated
# ---------------------------------------------------------------------------

class TestDatabaseBackends(TestCase):
    """All backends produce correct trunc_date and date_add SQL."""

    def test_all_backends_trunc_and_dateadd(self):
        """Vertica, PostgreSQL, MySQL, Snowflake, MSSQL, Redshift."""
        v = VerticaDatabase()
        self.assertEqual("TRUNC(\"dt\",'DD')", str(v.trunc_date(PyPikaField("dt"), "day")))
        self.assertEqual('TIMESTAMPADD(day,1,"dt")', str(v.date_add(PyPikaField("dt"), "day", 1)))

        pg = PostgreSQLDatabase()
        self.assertEqual("DATE_TRUNC('day',\"dt\")", str(pg.trunc_date(PyPikaField("dt"), "day")))

        sf = SnowflakeDatabase()
        self.assertEqual("TRUNC(\"dt\",'DD')", str(sf.trunc_date(PyPikaField("dt"), "day")))

        ms = MSSQLDatabase()
        self.assertIn("DATEADD", str(ms.trunc_date(PyPikaField("dt"), "day")))
        self.assertEqual('DATEADD(day,1,"dt")', str(ms.date_add(PyPikaField("dt"), "day", 1)))

        my = MySQLDatabase()
        self.assertIn("DATE_FORMAT", str(my.trunc_date(PyPikaField("dt"), "day")))


# ---------------------------------------------------------------------------
# 5. References — properties + SQL generation
# ---------------------------------------------------------------------------

class TestReferences(TestCase):
    """Reference types, delta flags, SQL generation with shifted
    dimensions and aliased metrics."""

    def test_reference_properties_and_sql(self):
        """5 builtin types with distinct aliases. Delta/delta_percent flags.
        Reference query has TIMESTAMPADD and aliased metric."""
        ds = _make_dataset()
        aliases = {ref_type(ds.fields.timestamp).alias
                   for ref_type in [DayOverDay, WeekOverWeek, MonthOverMonth,
                                    QuarterOverQuarter, YearOverYear]}
        self.assertEqual({"dod", "wow", "mom", "qoq", "yoy"}, aliases)

        ref_d = DayOverDay(ds.fields.timestamp, delta=True)
        self.assertTrue(ref_d.delta)
        self.assertIn("delta", ref_d.alias)

        ref_dp = DayOverDay(ds.fields.timestamp, delta_percent=True)
        self.assertTrue(ref_dp.delta_percent)
        self.assertIn("delta_percent", ref_dp.alias)

        queries = (ds.query.widget(ReactTable(ds.fields.clicks))
                   .dimension(day(ds.fields.timestamp))
                   .reference(DayOverDay(ds.fields.timestamp)).sql)
        self.assertEqual(2, len(queries))
        ref_sql = str(queries[1])
        self.assertIn("TIMESTAMPADD", ref_sql)
        self.assertIn("$clicks_dod", ref_sql)


# ---------------------------------------------------------------------------
# 6. Reference filter shifting
# ---------------------------------------------------------------------------

class TestReferenceFilterShifting(TestCase):
    """Date filters in reference queries are shifted by the inverse interval."""

    def test_shifts_date_filter_by_inverse_interval(self):
        """Reference query shifts a BETWEEN date filter by the reference's inverse
        interval, regardless of the reference's time unit (day, week, ...)."""
        ds = _make_dataset()
        for ref_type, unit in [(DayOverDay, "day"), (WeekOverWeek, "week")]:
            queries = (ds.query.widget(ReactTable(ds.fields.clicks))
                       .dimension(day(ds.fields.timestamp))
                       .filter(ds.fields.timestamp.between(date(2024, 1, 1), date(2024, 6, 30)))
                       .reference(ref_type(ds.fields.timestamp)).sql)
            ref_sql = str(queries[1]).lower()
            self.assertIn(f"timestampadd({unit},-1", ref_sql)


# ---------------------------------------------------------------------------
# 7. CumSum — return type + exact values, single + multiindex
# ---------------------------------------------------------------------------

class TestCumSum(TestCase):
    """CumSum returns a Series with exact cumulative sums. On MultiIndex,
    groups by the second level."""

    def test_cumsum_single_index(self):
        """Returns Series [10, 30, 60, 100]. Alias = 'cumsum(clicks)'."""
        df = pd.DataFrame({"$v": [10, 20, 30, 40]}, index=pd.Index(list("abcd"), name="$x"))
        result = CumSum(Field("v", definition=fn.Sum(_t.v))).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual([10, 30, 60, 100], list(result))
        self.assertEqual("cumsum(clicks)", CumSum(Field("clicks", definition=fn.Sum(_t.clicks))).alias)

    def test_cumsum_multiindex(self):
        """Groups by second level: A=[10,40], B=[20,60]."""
        idx = pd.MultiIndex.from_tuples(
            [("g1", "A"), ("g1", "B"), ("g2", "A"), ("g2", "B")], names=["$d1", "$d2"])
        df = pd.DataFrame({"$v": [10, 20, 30, 40]}, index=idx)
        result = CumSum(Field("v", definition=fn.Sum(_t.v))).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        pd.testing.assert_series_equal(
            result, pd.Series([10, 20, 40, 60], index=idx, name="$v"),
            check_names=False, check_dtype=False)


# ---------------------------------------------------------------------------
# 8. CumProd — return type + exact values, single + multiindex
# ---------------------------------------------------------------------------

class TestCumProd(TestCase):
    """CumProd returns a Series with exact cumulative products."""

    def test_cumprod_single_index(self):
        """Returns Series [2, 6, 30]."""
        df = pd.DataFrame({"$v": [2, 3, 5]}, index=pd.Index(list("abc"), name="$x"))
        result = CumProd(Field("v", definition=fn.Sum(_t.v))).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual([2, 6, 30], list(result))

    def test_cumprod_multiindex(self):
        """Groups by second level: A=[10,300], B=[20,800]."""
        idx = pd.MultiIndex.from_tuples(
            [("g1", "A"), ("g1", "B"), ("g2", "A"), ("g2", "B")], names=["$d1", "$d2"])
        df = pd.DataFrame({"$v": [10, 20, 30, 40]}, index=idx)
        result = CumProd(Field("v", definition=fn.Sum(_t.v))).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        pd.testing.assert_series_equal(
            result, pd.Series([10, 20, 300, 800], index=idx, name="$v"),
            check_names=False, check_dtype=False)


# ---------------------------------------------------------------------------
# 9. CumMean — return type + exact values, single + multiindex
# ---------------------------------------------------------------------------

class TestCumMean(TestCase):
    """CumMean returns a Series with exact running averages."""

    def test_cummean_single_index(self):
        """Returns Series [10, 15, 20, 25]."""
        df = pd.DataFrame({"$v": [10, 20, 30, 40]}, index=pd.Index(list("abcd"), name="$x"))
        result = CumMean(Field("v", definition=fn.Sum(_t.v))).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual([10.0, 15.0, 20.0, 25.0], list(result))

    def test_cummean_multiindex(self):
        """Groups by second level: A=[10,20], B=[20,30]."""
        idx = pd.MultiIndex.from_tuples(
            [("g1", "A"), ("g1", "B"), ("g2", "A"), ("g2", "B")], names=["$d1", "$d2"])
        df = pd.DataFrame({"$v": [10, 20, 30, 40]}, index=idx)
        result = CumMean(Field("v", definition=fn.Sum(_t.v))).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        self.assertAlmostEqual(10.0, result.iloc[0])
        self.assertAlmostEqual(20.0, result.iloc[1])
        self.assertAlmostEqual(20.0, result.iloc[2])
        self.assertAlmostEqual(30.0, result.iloc[3])


# ---------------------------------------------------------------------------
# 10. RollingMean — return type + NaN handling, single + multiindex
# ---------------------------------------------------------------------------

class TestRollingMean(TestCase):
    """RollingMean returns Series. NaN for first row (single) or first
    row of each group (multiindex)."""

    def test_rolling_mean_single_index(self):
        """NaN first, then [15, 25, 35]. Alias = 'rollingmean(clicks,3)'."""
        df = pd.DataFrame({"$v": [10, 20, 30, 40]}, index=pd.Index(list("abcd"), name="$x"))
        result = RollingMean(Field("v", definition=fn.Sum(_t.v)), window=2).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertAlmostEqual(15.0, result.iloc[1])
        self.assertEqual(
            "rollingmean(clicks,3)",
            RollingMean(Field("clicks", definition=fn.Sum(_t.clicks)), window=3).alias)

    def test_rolling_mean_multiindex_nan_per_group(self):
        """NaN at start of each group."""
        idx = pd.MultiIndex.from_tuples(
            [("g1", "A"), ("g1", "B"), ("g2", "A"), ("g2", "B")], names=["$d1", "$d2"])
        df = pd.DataFrame({"$v": [10, 20, 30, 40]}, index=idx)
        result = RollingMean(Field("v", definition=fn.Sum(_t.v)), window=2).apply(df, reference=None)
        self.assertIsInstance(result, pd.Series)
        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertTrue(pd.isna(result.iloc[1]))
        self.assertAlmostEqual(20.0, result.iloc[2])
        self.assertAlmostEqual(30.0, result.iloc[3])


# ---------------------------------------------------------------------------
# 11. Share — with over dimension + without
# ---------------------------------------------------------------------------

class TestShare(TestCase):
    """Share computes percentages using totals markers."""

    def test_share_with_over_dimension(self):
        """Divides by totals row: [30, 70, 100] → [30%, 70%, 100%]."""
        metric = Field("clicks", definition=fn.Sum(_t.clicks))
        over = Field("cat", definition=_t.cat, data_type=DataType.text)
        totals = get_totals_marker_for_dtype(pd.Index(["A"]).dtype)
        idx = pd.MultiIndex.from_tuples(
            [("2024", "A"), ("2024", "B"), ("2024", totals)], names=[f("ts"), f("cat")])
        df = pd.DataFrame({f("clicks"): [30, 70, 100]}, index=idx)
        result = Share(metric, over=over).apply(df, reference=None)
        np.testing.assert_array_almost_equal(result.values, [30.0, 70.0, 100.0])

    def test_share_without_over(self):
        """Without over: each row = 100% of itself. Alias = 'share(clicks,None)'."""
        result = Share(Field("v", definition=fn.Sum(_t.v)), over=None).apply(
            pd.DataFrame({"$v": [50]}, index=pd.Index(["x"], name="$c")), reference=None)
        self.assertAlmostEqual(100.0, result.iloc[0])
        self.assertEqual("share(clicks,None)", Share(Field("clicks", definition=fn.Sum(_t.clicks)), over=None).alias)


# ---------------------------------------------------------------------------
# 12. Pandas widget — labels, formatting, transpose, hide, metric restriction
# ---------------------------------------------------------------------------

class TestPandasWidget(TestCase):
    """Pandas widget labels, formats values, restricts metrics, transposes."""

    @classmethod
    def setUpClass(cls):
        t = Table("t")
        cls.ds = DataSet(table=t, database=MockVerticaDB(), fields=[
            Field("cat", definition=t.cat, data_type=DataType.text, label="Cat"),
            Field("m1", definition=fn.Sum(t.m1), label="M1"),
            Field("m2", definition=fn.Sum(t.m2), label="M2"),
            Field("m3", definition=fn.Sum(t.m3), label="M3", prefix="$", precision=2),
        ])

    def test_restricts_to_widget_metrics_and_labels(self):
        """Only widget metrics appear as columns with correct labels."""
        df = pd.DataFrame({f("m1"): [10], f("m2"): [20], f("m3"): [30]},
                          index=pd.Index(["A"], name=f("cat")))
        result = Pandas(self.ds.fields.m1, self.ds.fields.m2).transform(
            df, [self.ds.fields.cat], [])
        self.assertEqual("Cat", result.index.name)
        self.assertEqual(["M1", "M2"], list(result.columns))

    def test_prefix_precision_formatting(self):
        """prefix='$' precision=2 → '$1234.57'."""
        df = pd.DataFrame({f("m3"): [1234.567]}, index=pd.Index(["A"], name=f("cat")))
        result = Pandas(self.ds.fields.m3).transform(df, [self.ds.fields.cat], [])
        self.assertIn("$", str(result.iloc[0, 0]))
        self.assertIn("1234.57", str(result.iloc[0, 0]))

    def test_transpose_and_hide(self):
        """transpose swaps rows/cols. hide removes dimension from index."""
        df = pd.DataFrame({f("m1"): [10, 20]}, index=pd.Index(["A", "B"], name=f("cat")))
        transposed = Pandas(self.ds.fields.m1, transpose=True).transform(
            df, [self.ds.fields.cat], [])
        # Dimension values become the columns and the metric label becomes the single row.
        self.assertEqual(["A", "B"], list(transposed.columns))
        self.assertEqual(["M1"], list(transposed.index))
        self.assertEqual(["10", "20"], list(transposed.loc["M1"]))

        hidden = Pandas(self.ds.fields.m1, hide=[self.ds.fields.cat]).transform(
            df, [self.ds.fields.cat], [])
        # The sole dimension is dropped from the index (no remaining named level) while the
        # metric column is retained.
        self.assertIsNone(hidden.index.name)
        self.assertEqual(["M1"], list(hidden.columns))


# ---------------------------------------------------------------------------
# 13. CSV — exact output
# ---------------------------------------------------------------------------

class TestCSVWidget(TestCase):
    """CSV produces exact header and data rows."""

    def test_csv_exact_output(self):
        """Header=Category,Total. Rows=Alpha,10 and Beta,20."""
        t = Table("t")
        ds = DataSet(table=t, database=MockVerticaDB(), fields=[
            Field("cat", definition=t.cat, data_type=DataType.text, label="Category"),
            Field("val", definition=fn.Sum(t.val), label="Total"),
        ])
        df = pd.DataFrame({f("val"): [10, 20]}, index=pd.Index(["Alpha", "Beta"], name=f("cat")))
        lines = CSV(ds.fields.val).transform(df, [ds.fields.cat], []).strip().split("\n")
        self.assertEqual("Category,Total", lines[0])
        self.assertEqual("Alpha,10", lines[1])


# ---------------------------------------------------------------------------
# 14. ReactTable — cell format with raw/display dicts
# ---------------------------------------------------------------------------

class TestReactTableWidget(TestCase):
    """ReactTable cells are dicts with raw/display, not bare values."""

    def test_cell_format_and_structure(self):
        """Metric cells = {'raw': N, 'display': str}. Dim cells = {'raw': val}.
        Columns include dimension and metric headers."""
        t = Table("t")
        ds = DataSet(table=t, database=MockVerticaDB(), fields=[
            Field("cat", definition=t.cat, data_type=DataType.text, label="Category"),
            Field("val", definition=fn.Sum(t.val), label="Total"),
        ])
        df = pd.DataFrame({f("val"): [42]}, index=pd.Index(["Alpha"], name=f("cat")))
        result = ReactTable(ds.fields.val).transform(df, [ds.fields.cat], [])
        self.assertEqual(1, len(result["data"]))
        headers = [c["Header"] for c in result["columns"]]
        self.assertIn("Category", headers)
        self.assertIn("Total", headers)

        metric_cell = result["data"][0][f("val")]
        self.assertIsInstance(metric_cell, dict)
        self.assertEqual(42, metric_cell["raw"])
        self.assertEqual("42", metric_cell["display"])

        dim_cell = result["data"][0][f("cat")]
        self.assertIsInstance(dim_cell, dict)
        self.assertEqual("Alpha", dim_cell["raw"])


# ---------------------------------------------------------------------------
# 15. HighCharts — (timestamp_ms, value) tuple format
# ---------------------------------------------------------------------------

class TestHighChartsWidget(TestCase):
    """HighCharts data points are (timestamp_ms, value) tuples."""

    def test_data_point_tuple_format_and_multiple_axes(self):
        """Each point is a (ms_since_epoch, value) tuple. Two axes → two series."""
        t = Table("t")
        ds = DataSet(table=t, database=MockVerticaDB(), fields=[
            Field("ts", definition=t.ts, data_type=DataType.date, label="Time"),
            Field("a", definition=fn.Sum(t.a), label="A"),
            Field("b", definition=fn.Sum(t.b), label="B"),
        ])
        idx = pd.DatetimeIndex(["2024-01-01", "2024-02-01"], name=f("ts"))
        df = pd.DataFrame({f("a"): [42, 99], f("b"): [10, 20]}, index=idx)

        result = HighCharts().axis(HighCharts.LineSeries(ds.fields.a)).transform(
            df, [ds.fields.ts], [])
        data = result["series"][0]["data"]
        self.assertIsInstance(data[0], (tuple, list))
        self.assertEqual(2, len(data[0]))
        # x is the index date converted to epoch milliseconds (UTC): 2024-01-01 -> 1704067200000,
        # 2024-02-01 -> 1706745600000; y is the metric value.
        self.assertEqual((1704067200000, 42), tuple(data[0]))
        self.assertEqual((1706745600000, 99), tuple(data[1]))

        result2 = (HighCharts().axis(HighCharts.LineSeries(ds.fields.a))
                   .axis(HighCharts.LineSeries(ds.fields.b))
                   .transform(df, [ds.fields.ts], []))
        self.assertEqual(2, len(result2["series"]))


# ---------------------------------------------------------------------------
# 16. Rollup — query counts
# ---------------------------------------------------------------------------

class TestRollup(TestCase):
    """Rollup query count: 1 dim → 2, 2 dims → 3, rollup+ref → 4."""

    def test_rollup_query_counts(self):
        """One rollup → 2 queries with sentinel. Two rollups → 3. Rollup+ref → 4."""
        ds = _make_dataset()
        q1 = ds.query.widget(ReactTable(ds.fields.clicks)).dimension(Rollup(ds.fields.category)).sql
        self.assertEqual(2, len(q1))
        self.assertIn("_FIREANT_ROLLUP_VALUE_", str(q1[1]))

        q2 = (ds.query.widget(ReactTable(ds.fields.clicks))
              .dimension(Rollup(ds.fields.timestamp)).dimension(Rollup(ds.fields.category)).sql)
        self.assertEqual(3, len(q2))

        q3 = (ds.query.widget(ReactTable(ds.fields.clicks))
              .dimension(day(ds.fields.timestamp)).dimension(Rollup(ds.fields.category))
              .reference(DayOverDay(ds.fields.timestamp)).sql)
        self.assertEqual(4, len(q3))


# ---------------------------------------------------------------------------
# 17. Data blending, field arithmetic, type engine — consolidated
# ---------------------------------------------------------------------------

class TestBlendingArithmeticTypeEngine(TestCase):
    """DataSetBlender, field arithmetic, type engine, totals marker."""

    def test_blending_arithmetic_and_type_engine(self):
        """Blender query combines both datasets into one SQL statement that
        references both tables and computes the blended field. Field arithmetic
        produces SQL operators. VerticaTypeEngine translates db <-> ANSI types.
        Totals marker = '~~totals'."""
        ds1 = _make_dataset()
        t2 = Table("spend")
        ds2 = DataSet(table=t2, database=_db, fields=[
            Field("timestamp", definition=t2.timestamp, data_type=DataType.date),
            Field("spend", definition=fn.Sum(t2.spend)),
        ])
        blender = ds1.blend(ds2).on_dimensions().extra_fields(
            Field("spc", definition=ds2.fields.spend / ds1.fields.clicks))
        self.assertIsInstance(blender, DataSetBlender)
        self.assertIn("spc", blender.fields)

        # The blended query is a single statement that combines both datasets and
        # computes spc = SUM(spend) / SUM(clicks) over them.
        queries = (blender.query.widget(ReactTable(blender.fields["spc"]))
                   .dimension(day(blender.fields.timestamp)).sql)
        self.assertEqual(1, len(queries))
        blended_sql = str(queries[0])
        self.assertIn('"analytics"', blended_sql)
        self.assertIn('"spend"', blended_sql)
        self.assertIn('SUM("clicks")', blended_sql)
        self.assertIn('SUM("spend")', blended_sql)
        # spc is the numerator metric column divided by the denominator metric column,
        # aliased "$spc" (subquery prefixes between the two columns are an internal detail).
        self.assertIn('"$spend"/', blended_sql)
        self.assertIn('"$clicks" "$spc"', blended_sql)

        f1 = Field("a", definition=_t.a)
        f2 = Field("b", definition=_t.b)
        self.assertIn('"a"+"b"', (f1 + f2).get_sql(quote_char='"'))
        self.assertIn('"a"/"b"', (f1 / f2).get_sql(quote_char='"'))

        # Imported here rather than at module level so a missing type engine costs this one
        # test instead of collapsing collection for the whole suite.
        from fireant.database import VerticaTypeEngine

        engine = VerticaTypeEngine()
        # Observable type-mapping surface: to_ansi resolves the Vertica type string to the ANSI
        # VARCHAR type, and the ansi->db mapper inverts "VARCHAR" back to the Vertica string.
        self.assertEqual("VARCHAR", str(engine.to_ansi("varchar")))
        self.assertEqual("varchar", engine.ansi_to_db_mapper["VARCHAR"])

        self.assertEqual("~~totals", get_totals_marker_for_dtype(pd.Index(["a"]).dtype))


# ---------------------------------------------------------------------------
# 18. Integration — full query with all features
# ---------------------------------------------------------------------------

class TestIntegration(TestCase):
    """Complex query combining all features."""

    def test_full_query_with_all_features(self):
        """day interval + text dim + date filter + DayOverDay → correct SQL."""
        ds = _make_dataset()
        queries = (ds.query
                   .widget(ReactTable(ds.fields.clicks, ds.fields.revenue))
                   .dimension(day(ds.fields.timestamp)).dimension(ds.fields.category)
                   .filter(ds.fields.timestamp.between(date(2024, 1, 1), date(2024, 6, 30)))
                   .reference(DayOverDay(ds.fields.timestamp)).sql)
        self.assertEqual(2, len(queries))
        base = str(queries[0])
        self.assertIn("TRUNC(\"timestamp\",'DD')", base)
        self.assertIn('SUM("clicks") "$clicks"', base)
        self.assertIn('SUM("revenue") "$revenue"', base)
        self.assertIn('GROUP BY "$timestamp","$category"', base)
        ref = str(queries[1])
        self.assertIn("TIMESTAMPADD", ref)
        self.assertIn("$clicks_dod", ref)
