# FireAnt — Analytics and Reporting Library

Implement `fireant`, a Python package for building analytical queries against SQL databases. FireAnt lets users define datasets with typed fields (dimensions and metrics), build queries using a fluent API, and render results as tables, charts, and CSV. It supports multiple database backends, time-over-time comparisons (references), cumulative/rolling operations, totals/rollup, and data blending across datasets.

## Dependencies

The environment is **offline** and these dependencies are **already installed** — do not install anything (there is no network):

- `pandas>=2.0.0`
- `pypika>=0.50.0,<1.0.0`
- `toposort>=1.6,<2`

pypika provides SQL query building primitives (`Table`, `Field`, `Query`, `functions`, `JoinType`, `Order`). FireAnt builds on pypika to generate platform-specific SQL. The database backends (Vertica, PostgreSQL, MySQL, Snowflake, MSSQL, Redshift) only generate SQL strings, so no database drivers are required.

The project itself is installed offline by a `setup.sh` (`pip install -e . --no-build-isolation`) that runs against these pre-installed packages — you do not need to set up the environment.

## Package Structure

```python
import fireant
from fireant import (
    DataSet, DataSetBlender, Field, DataType, Join,
    Pandas, CSV, ReactTable, HighCharts,
    CumSum, CumProd, CumMean, RollingMean, Share, Rollup,
    DayOverDay, WeekOverWeek, MonthOverMonth, QuarterOverQuarter, YearOverYear,
    DaysOverDays, YearsOverYears,
    VerticaDatabase, PostgreSQLDatabase, MySQLDatabase,
    SnowflakeDatabase, MSSQLDatabase, RedshiftDatabase,
    day, hour, week, month, quarter, year,
)
from fireant.dataset.fields import DataSetFilterException
from fireant.dataset.filters import VoidFilter
from fireant.dataset.references import ReferenceType
from fireant.dataset.totals import get_totals_marker_for_dtype
from fireant.database import VerticaTypeEngine
from fireant.utils import alias_selector
```

## 1. DataSet and Fields

A `DataSet` is the core object. It wraps a pypika `Table`, a database backend, a list of `Field` objects, and optional `Join` definitions.

```python
DataSet(table, database, fields=(), joins=(), ...)
```

Each entry in `joins` is a `Join`:

```python
Join(table, criterion, join_type=JoinType.left)
```

- `table` — the pypika `Table` being joined in.
- `criterion` — the pypika join condition (e.g. `main.customer_id == other.id`).
- `join_type` — a pypika `JoinType` naming the join kind (keyword named `join_type`, default `JoinType.left`).

**Field** represents a column or aggregate expression:

```python
Field(alias, definition, data_type=DataType.number, label=None,
      prefix=None, suffix=None, thousands=None, precision=None, ...)
```

- `alias` — unique string identifier. Fields are accessed via `dataset.fields.alias` or `dataset.fields["alias"]`.
- `definition` — a pypika expression. If it uses an aggregate function (e.g. `fn.Sum(table.col)`), the field is a **metric** (`is_aggregate=True`, `groupable=False`). Otherwise it is a **dimension** (`is_aggregate=False`, `groupable=True`).
- `data_type` — one of `DataType.date`, `DataType.text`, `DataType.number`, `DataType.boolean`.
- `label` — display name; defaults to alias.
- `prefix`, `suffix`, `thousands`, `precision` — formatting hints used by widgets.

`dataset.fields` is a container that supports attribute access (`ds.fields.clicks`), bracket access (`ds.fields["clicks"]`), iteration, and `in` checks. Adding a duplicate alias raises `ValueError`.

`dataset.extra_fields(*fields)` returns a **new** DataSet with the additional fields (immutable — the original is not modified).

### Field Arithmetic

Fields support `+`, `-`, `*`, `/` operators, producing pypika `ArithmeticExpression` objects that can be used as definitions for computed fields.

## 2. Filters

Fields expose filter methods that produce filter objects. When passed to `.filter()` on the query builder, non-aggregate filters go to `WHERE` and aggregate filters go to `HAVING`.

| Method | Data types | SQL |
|--------|-----------|-----|
| `field == value` / `field.eq(value)` | all | `"col"=<value>` |
| `field != value` / `field.ne(value)` | all | `"col"<><value>` |
| `field > value` / `field.gt(value)` | number, date | `"col"><value>` |
| `field < value` / `field.lt(value)` | number, date | `"col"<<value>` |
| `field >= value` / `field.gte(value)` | number, date | |
| `field <= value` / `field.lte(value)` | number, date | |
| `field.between(start, stop)` | number, date | `"col" BETWEEN <start> AND <stop>` |
| `field.isin(values)` | all | `"col" IN (<v1>,<v2>)` |
| `field.notin(values)` | all | `"col" NOT IN (<v>)` |
| `field.like(pattern)` | text | `LOWER("col") LIKE LOWER('pattern')` |
| `field.not_like(pattern)` | text | `NOT LOWER("col") LIKE LOWER('pattern')` |
| `field.is_(bool)` | boolean | `"col"` or `NOT "col"` |
| `field.void()` | all | Empty criterion (no-op filter) |

**Value quoting is by Python type.** In comparison filters (`==`, `!=`, `>`, `<`, `>=`, `<=`), `BETWEEN`, and `IN`/`NOT IN`, each rendered value is quoted according to its type: **string and date/datetime values are single-quoted**, while **numeric (int/float) and boolean values are rendered without quotes**. This applies identically in `WHERE` and `HAVING`. Examples: `"category"='X'` and `"timestamp">'2024-01-01'` (quoted), versus `"account_id">100` and `SUM("clicks")>100` (unquoted); a numeric `BETWEEN` renders `"col" BETWEEN 100 AND 200` while a date one renders `"col" BETWEEN '2024-01-01' AND '2024-12-31'`.

Type-restricted methods (`gt`, `lt`, `gte`, `lte`, `between` on non-continuous types; `like`/`not_like` on non-text; `is_` on non-boolean) raise `DataSetFilterException`.

`VoidFilter` is accessible at `fireant.dataset.filters.VoidFilter`.

## 3. Query Builder

Access the query builder via `dataset.query`. It uses a fluent, immutable API — each method returns a new builder copy.

```python
dataset.query
    .widget(widget1)
    .widget(widget2)
    .dimension(field_or_interval)
    .filter(filter_expr)
    .reference(reference)
    .orderby(field, Order.desc)
    .sql  # returns list of pypika Query objects
    .fetch()  # executes queries and returns widget data
```

`.sql` returns a `list` of query objects. `str(query)` produces the SQL string.

**SQL generation rules:**
- Dimensions become a `SELECT` term aliased with the `$` prefix (e.g., `"category" "$category"`), and the same dimension also appears in `GROUP BY`.
- Metrics become `SELECT` with `$` alias (e.g., `SUM("clicks") "$clicks"`).
- `GROUP BY` references each selected dimension by its `$`-prefixed alias (not the raw column or expression), in selection order — e.g. a single `category` dimension yields `GROUP BY "$category"`, and a `day(timestamp)` + `category` query yields `GROUP BY "$timestamp","$category"`. An interval-wrapped date dimension groups by its `$`-alias (e.g. `GROUP BY "$timestamp"`), **not** by the underlying `TRUNC(...)` expression.
- By default a query orders by every selected dimension, in selection order, ascending, referencing each dimension's `$`-prefixed alias — e.g. a single `category` dimension yields `ORDER BY "$category"`, and two dimensions yield `ORDER BY "$timestamp","$category"`. An explicit `.orderby(field, Order.desc)` overrides the default (e.g. `ORDER BY "$clicks" DESC` when ordering by a metric). Aggregate (metric) fields are never part of the default ordering.
- Queries include a default `LIMIT 200000` (from `database.max_result_set_size`).
- Joins are only included when a selected field references a joined table.
- Non-aggregate filters go to `WHERE`; aggregate filters go to `HAVING`.

### alias_selector

`fireant.utils.alias_selector(alias)` prefixes an alias with `$` unless it already starts with `$`. This is used throughout for column naming in DataFrames and SQL.

## 4. DateTime Intervals

Wrap a date dimension with an interval function to truncate dates:

```python
from fireant import hour, day, week, month, quarter, year

dataset.query.dimension(day(dataset.fields.timestamp))
```

Each returns a `DatetimeInterval` wrapper with an `interval_key` attribute (`"hour"`, `"day"`, `"week"`, `"month"`, `"quarter"`, `"year"`). The database backend translates these into platform-specific SQL (see §5).

## 5. Database Backends

Each backend extends a `Database` base class and implements `trunc_date(field, interval)` and `date_add(field, date_part, interval)` with platform-specific SQL.

**VerticaDatabase** (host=`"localhost"`, port=`5433`):
- `trunc_date`: `TRUNC("field",'<code>')` where codes are `HH`, `DD`, `IW`, `MM`, `Q`, `Y`
- `date_add`: `TIMESTAMPADD(day,1,"field")`

**PostgreSQLDatabase** (host=`"localhost"`, port=`5432`):
- `trunc_date`: `DATE_TRUNC('day',"field")`
- `date_add`: `"field" + INTERVAL '1 DAY'`

**MySQLDatabase**:
- `trunc_date`: renders via a `DATE_FORMAT("field", ...)` call. `week` and `quarter` additionally
  apply compound date arithmetic rather than a single bare `DATE_FORMAT`.
- `date_add`: `DATE_ADD("field",INTERVAL <n> DAY)`

**SnowflakeDatabase**:
- Same SQL patterns as Vertica (`TRUNC` and `TIMESTAMPADD`)

**MSSQLDatabase**:
- `trunc_date`: `DATEADD(day,DATEDIFF(day,0,"field"),0)`
- `date_add`: `DATEADD(day,1,"field")`

**RedshiftDatabase**:
- Same SQL patterns as PostgreSQL (`DATE_TRUNC` and `INTERVAL` arithmetic)

All backends use pypika's query classes (`VerticaQuery`, `PostgreSQLQuery`, `MySQLQuery`, `MSSQLQuery`, `SnowflakeQuery`) to ensure correct quoting and SQL dialect.

### VerticaTypeEngine

`fireant.database.VerticaTypeEngine` maps database-specific type names to ANSI SQL types and back:
- `db_to_ansi_mapper` dict: maps strings like `"varchar"`, `"integer"`, `"boolean"`, `"timestamp"` to ANSI type objects
- `ansi_to_db_mapper` dict: maps `"VARCHAR"`, `"INTEGER"`, etc. back to Vertica type strings
- `to_ansi(db_type)` method: looks up the ANSI type for a given database type string

Converting an ANSI type object to a string (`str(...)`) yields its ANSI type name — the same uppercase token that keys `ansi_to_db_mapper`.

## 6. References (Time-over-Time Comparisons)

References compare current data to a prior time period by generating additional shifted queries.

Built-in reference types (each is a `ReferenceType` with `time_unit` and `interval`):

| Reference | time_unit | interval |
|-----------|-----------|----------|
| `DayOverDay` | `"day"` | `1` |
| `WeekOverWeek` | `"week"` | `1` |
| `MonthOverMonth` | `"month"` | `1` |
| `QuarterOverQuarter` | `"quarter"` | `1` |
| `YearOverYear` | `"year"` | `1` |

Custom intervals via factory functions: `DaysOverDays(7)`, `YearsOverYears(2)`, etc. These return `ReferenceType` instances that can be called with a dimension field.

```python
ref = DayOverDay(dataset.fields.timestamp, delta=True, delta_percent=False)
```

- `delta=True` — alias includes `"_delta"`, computes the difference
- `delta_percent=True` — alias includes `"_delta_percent"`, implies delta

Each reference in a query produces an additional SQL query where the date dimension is shifted using `date_add`. The reference query's SQL contains the backend's date arithmetic function (e.g. `TIMESTAMPADD` for Vertica). In the reference query, metrics are aliased with the reference type suffix — e.g. `$clicks_dod` for a DayOverDay reference on the clicks metric. Date filters in the reference query are also shifted by the inverse interval (e.g. a `BETWEEN '2024-01-01' AND '2024-06-30'` filter becomes `BETWEEN TIMESTAMPADD(day,-1,'2024-01-01') AND TIMESTAMPADD(day,-1,'2024-06-30')` for DayOverDay).

Each built-in reference type has a distinct alias: `DayOverDay` → `"dod"`, `WeekOverWeek` → `"wow"`, `MonthOverMonth` → `"mom"`, `QuarterOverQuarter` → `"qoq"`, `YearOverYear` → `"yoy"` (5 total). The `delta`/`delta_percent` flags append `"_delta"`/`"_delta_percent"` to the base alias.

## 7. Operations

Operations transform result DataFrames after query execution:

```python
CumSum(field)        # cumulative sum
CumProd(field)       # cumulative product
CumMean(field)       # cumulative mean (cumsum / count)
RollingMean(field, window=N)  # rolling window average
Share(field, over=dimension)  # percentage share
```

**apply(data_frame, reference)** — returns a `pd.Series` containing the transformed values for the operation's metric column. The returned Series is aligned to the input DataFrame: it carries the **same index and preserves the input's original row order** (grouped operations compute per group but do not reorder rows), so the value at each position corresponds to the same input row. This holds for both single-index and MultiIndex inputs and for every operation (cumulative, rolling, share).
- On a single-index DataFrame, cumulative operations accumulate across all rows.
- On a MultiIndex DataFrame, cumulative operations group by the second (and subsequent) index levels, accumulating only within each group.
- `RollingMean` with `window=2` produces `NaN` for the first row (single-index) or the first row of each group (MultiIndex).
- `Share(metric, over=dim)` computes percentages relative to the totals row for the `over` dimension. The totals row is identified by `get_totals_marker_for_dtype()` applied to the index level's dtype.
- `Share(metric, over=None)` expresses each row's value as a percentage of itself, so every row evaluates to `100.0`.

**Alias format:** `"cumsum(clicks)"`, `"rollingmean(clicks,3)"`, `"share(clicks,category)"`, `"share(clicks,None)"`.

**metrics property:** returns the list of metric `Field` objects the operation wraps.

### Totals

`fireant.dataset.totals.get_totals_marker_for_dtype(dtype)` returns the sentinel value used in DataFrame indices to mark totals rows. For string/object dtypes this is `"~~totals"`.

## 8. Rollup

`Rollup(dimension)` wraps a dimension to request totals computation. A query with one Rollup dimension produces 2 SQL queries: the base query (with the real dimension) and a totals query where the dimension value is replaced with a sentinel string `'_FIREANT_ROLLUP_VALUE_'`.

Multiple Rollup dimensions add up rather than multiply: each Rollup dimension contributes one progressive totals query on top of the single base query, so **N Rollup dimensions produce N+1 SQL queries**. The totals queries are cascading — for 2 Rollup dimensions you get 3 queries: the base query, a totals query rolling up the last dimension, and a totals query rolling up both dimensions.

Combining Rollup with references multiplies the two counts: with R references and N Rollup dimensions the total is `(N+1) × (R+1)` queries. For example, 1 Rollup dimension × 1 reference = 4 queries (base, base+ref, totals, totals+ref).

## 9. Widgets

Widgets define which metrics to display and transform result DataFrames into output formats.

**Pandas** — `Pandas(field1, field2, ..., transpose=False, hide=None)`:
- `.transform(data_frame, dimensions, references)` returns a `pd.DataFrame` with:
  - Index renamed from alias-selector format to dimension labels (supports MultiIndex for multiple dimensions)
  - Columns restricted to only the metrics specified in the widget (not all DataFrame columns)
  - Columns renamed from alias-selector format to metric labels
  - Cell values are always rendered as their formatted **string** representation (the same formatting as the ReactTable `"display"` value). With `prefix`/`suffix`/`precision` set, formatting is applied (e.g. prefix="$", precision=2 formats `1234.567` as `"$1234.57"`); when a metric has no `prefix`/`suffix`/`precision`, a numeric value is rendered as its plain string form (e.g. `10` becomes `"10"`).
- `transpose=True`: swaps rows and columns — dimension values become columns, metric names become the row index
- `hide=[field]`: removes the specified dimension from the output index

**CSV** — `CSV(field1, field2, ...)`:
- Extends Pandas. `.transform()` returns a CSV **string** (not a DataFrame).

**ReactTable** — `ReactTable(field1, field2, ...)`:
- `.transform()` returns a `dict` with keys `"columns"` (list of column definitions with `"Header"` labels) and `"data"` (list of row dicts). The number of data entries matches the number of DataFrame rows.
- Each row dict in `"data"` is keyed by each field's `$`-prefixed alias (i.e. `alias_selector(alias)`) — for example `row["$val"]` for a `val` metric and `row["$cat"]` for a `cat` dimension.
- Each cell value in the data rows is wrapped in a dict: `{"raw": <value>, "display": "<formatted>"}` for metric fields, and `{"raw": <value>}` for dimension fields. The `"display"` value is a formatted string representation.

**HighCharts** — `HighCharts().axis(HighCharts.LineSeries(field))`:
- `.transform()` returns a `dict` with key `"series"` containing a list of series objects. Each series has a `"data"` list with one entry per DataFrame row.
- For date-indexed data, each data point is a tuple of `(timestamp_milliseconds, value)` where the timestamp is the number of milliseconds since the Unix epoch.

## 10. Data Blending

`DataSetBlender` combines two datasets:

```python
blender = ds1.blend(ds2).on_dimensions().extra_fields(
    Field("ratio", definition=ds2.fields.x / ds1.fields.y, ...)
)
```

The result is a `DataSetBlender` instance with a `.fields` container that includes both original and extra blended fields. Blended fields can reference metrics from either dataset in their definitions.

A blender exposes the same `.query` builder as a `DataSet` (`blender.query.widget(...).dimension(...)`). When a widget selects a blended field, `.sql` returns a **single** combined query: each underlying dataset's query becomes a subquery (each selecting its own metrics with their `$`-aliases — e.g. an inner `SUM("spend") "$spend"` and `SUM("clicks") "$clicks"`), the subqueries are `LEFT JOIN`ed on their shared (mapped) dimension, and the blended field is rendered in the outer `SELECT` as the arithmetic expression over the subqueries' `$`-aliased metric **columns**, aliased to the blended field's own `$`-alias — e.g. a `spend / clicks` blended field renders as `"$spend"/"$clicks" "$spc"` (the per-subquery prefixes on those columns are an internal detail). The outer expression therefore divides the aliased metric columns, **not** a literal `SUM("spend")/SUM("clicks")`. The combined query references both datasets' tables.
