"""Hidden grading suite for the csvq task.

Drives the compiled csvq CLI (built by setup.sh at /app/csvq) entirely through subprocess —
program/args + optional stdin in, stdout/stderr/exit-code out. Each test models a realistic SQL
usage scenario and asserts the EXACT expected output (no shape-only checks), so the pass fraction
tracks real implementation completeness of the SQL engine + CLI.

Set BIN_ENV to point at the binary (defaults to /app/csvq). Iterate against a local GT build with:
    BIN_ENV=/tmp/csvq-gt pytest tests/test_csvq.py -q

Harness note: csvq treats an *empty piped stdin* as an implicit empty STDIN table, which corrupts
no-FROM query results. Tests that do not feed stdin therefore run with stdin=DEVNULL; only the
STDIN-table and `calc` tests pipe real data. No @pytest.mark.parametrize (one test == one CTRF entry).
"""

import os
import subprocess
import tempfile

BIN = os.environ.get("BIN_ENV", "/app/csvq")

USERS = "id,name,age\n1,Alice,30\n2,Bob,25\n3,Carol,40\n"
DEPTS = "id,dept\n1,Eng\n2,Sales\n3,Eng\n"
D2 = "id,dept\n1,Eng\n2,Sales\n3,Eng\n4,HR\n"


def _run(args, files=None, data=None):
    """Run csvq with argv in a temp cwd holding `files`; return (stdout, stderr, rc).

    When `data` is None stdin is DEVNULL (see module docstring); otherwise `data` is piped in.
    """
    with tempfile.TemporaryDirectory() as d:
        for name, content in (files or {}).items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(content)
        kw = {"input": data} if data is not None else {"stdin": subprocess.DEVNULL}
        proc = subprocess.run(
            [BIN, *args], capture_output=True, text=True, cwd=d, timeout=20, **kw
        )
    return proc.stdout, proc.stderr, proc.returncode


def q(sql, files=None, args=None, data=None):
    """Run a query expecting success; assert exit 0 and return stdout."""
    so, se, rc = _run([*(args or []), sql], files=files, data=data)
    assert rc == 0, f"expected success, got rc={rc}, stderr={se!r}"
    return so


# ----------------------------------------------------------------------------- output formats

def test_select_csv_default():
    """Default output is CSV with a header row and unquoted simple values."""
    assert q("SELECT id, name FROM `users.csv`", {"users.csv": USERS}) == "id,name\n1,Alice\n2,Bob\n3,Carol\n"


def test_projection_and_alias():
    """Column aliases rename output headers; expressions can be projected."""
    assert q("SELECT name AS who, age + 1 AS nxt FROM `users.csv` WHERE id = 2", {"users.csv": USERS}) == "who,nxt\nBob,26\n"


def test_format_tsv():
    """`-f TSV` emits tab-separated values with a header."""
    assert q("SELECT id, name FROM `users.csv` WHERE id < 3", {"users.csv": USERS}, args=["-f", "TSV"]) == "id\tname\n1\tAlice\n2\tBob\n"


def test_format_json_values_are_strings():
    """`-f JSON` renders an array of objects; CSV-loaded fields are JSON strings."""
    assert q("SELECT id, name FROM `users.csv` WHERE id = 1", {"users.csv": USERS}, args=["-f", "JSON"]) == '[{"id":"1","name":"Alice"}]\n'


def test_format_text_box():
    """`-f TEXT` draws an ASCII table with box borders and centered headers."""
    expected = (
        "+----+--------+\n"
        "| id |  name  |\n"
        "+----+--------+\n"
        "| 1  | Alice  |\n"
        "+----+--------+\n"
    )
    assert q("SELECT id, name FROM `users.csv` WHERE id = 1", {"users.csv": USERS}, args=["-f", "TEXT"]) == expected


def test_format_gfm():
    """`-f GFM` emits a GitHub-Flavored-Markdown table."""
    expected = (
        "|  id  |  name  |\n"
        "| ---- | ------ |\n"
        "| 1    | Alice  |\n"
        "| 2    | Bob    |\n"
    )
    assert q("SELECT id, name FROM `users.csv` WHERE id < 3", {"users.csv": USERS}, args=["-f", "GFM"]) == expected


def test_header_flags():
    """`--no-header` reads input without a header (auto-naming columns c1,c2); `-N`/`--without-header` drops the output header line."""
    nh = "10,20\n30,40\n"
    assert q("SELECT c1, c2 FROM `nh.csv`", {"nh.csv": nh}, args=["--no-header"]) == "c1,c2\n10,20\n30,40\n"
    assert q("SELECT id, name FROM `users.csv` WHERE id = 1", {"users.csv": USERS}, args=["-N"]) == "1,Alice\n"


def test_csv_quote_escaping():
    """CSV output quotes fields containing commas/quotes and doubles embedded quotes (RFC 4180)."""
    assert q("""SELECT 'a,b' AS comma, 'say "hi"' AS quote, 'plain' AS plain""") == 'comma,quote,plain\n"a,b","say ""hi""",plain\n'


def test_float_normalization():
    """A float with no fractional part prints as an integer (3.0 -> 3)."""
    assert q("SELECT 3.0 AS a, 6.0 / 2 AS b, FLOAT('3') AS c") == "a,b,c\n3,3,3\n"


# ----------------------------------------------------------------------------- predicates / WHERE

def test_where_comparison_and_order():
    """WHERE filters numerically and ORDER BY DESC sorts results."""
    assert q("SELECT name, age FROM `users.csv` WHERE age > 26 ORDER BY age DESC", {"users.csv": USERS}) == "name,age\nCarol,40\nAlice,30\n"


def test_where_and_or_not():
    """AND/OR/NOT combine predicates with standard precedence and parentheses."""
    assert q("SELECT name FROM `users.csv` WHERE age > 20 AND NOT (name = 'Bob') ORDER BY name", {"users.csv": USERS}) == "name\nAlice\nCarol\n"


def test_like_wildcards():
    """LIKE supports % (any run) and _ (single char) wildcards."""
    assert q("SELECT name FROM `users.csv` WHERE name LIKE 'A%'", {"users.csv": USERS}) == "name\nAlice\n"
    assert q("SELECT name FROM `users.csv` WHERE name LIKE 'Bo_'", {"users.csv": USERS}) == "name\nBob\n"


def test_in_list():
    """IN tests membership against a value list."""
    assert q("SELECT name FROM `users.csv` WHERE id IN (1, 3) ORDER BY id", {"users.csv": USERS}) == "name\nAlice\nCarol\n"


def test_between():
    """BETWEEN is an inclusive range test."""
    assert q("SELECT name FROM `users.csv` WHERE age BETWEEN 26 AND 35", {"users.csv": USERS}) == "name\nAlice\n"


def test_is_null_and_is_not_null():
    """IS NULL / IS NOT NULL test for null presence."""
    assert q("SELECT IF(NULL IS NULL, 'a', 'b') AS x, IF(1 IS NOT NULL, 'c', 'd') AS y") == "x,y\na,c\n"


def test_string_comparison_ordering():
    """String comparisons order lexicographically."""
    assert q("SELECT name FROM `users.csv` WHERE name > 'Bob' ORDER BY name", {"users.csv": USERS}) == "name\nCarol\n"


# ----------------------------------------------------------------------------- arithmetic / operators

def test_integer_division_and_modulo():
    """Division of two integers truncates toward zero; %% is modulo."""
    assert q("SELECT 7 / 2 AS a, 6 / 2 AS b, 7 % 3 AS c") == "a,b,c\n3,3,1\n"


def test_float_promotion():
    """Mixing a float operand promotes the result to float."""
    assert q("SELECT 7 / 2.0 AS a, 3.0 / 2 AS b") == "a,b\n3.5,1.5\n"


def test_operator_precedence():
    """Multiplication binds tighter than addition; subtraction is left-associative."""
    assert q("SELECT 1 + 2 * 3 AS a, (1 + 2) * 3 AS b, 10 - 2 - 3 AS c") == "a,b,c\n7,9,5\n"


def test_string_concat_and_null_propagation():
    """`||` concatenates strings; a NULL operand makes the whole concatenation NULL."""
    assert q("SELECT 'a' || 'b' || 'c' AS r, 'a' || NULL || 'b' AS n") == "r,n\nabc,\n"


# ----------------------------------------------------------------------------- string functions

def test_string_case_and_trim():
    """UPPER/LOWER change case; TRIM/LTRIM/RTRIM strip a charset from the ends."""
    assert q("SELECT UPPER('abc') AS u, LOWER('ABC') AS l, TRIM('  x  ') AS t, LTRIM('xxab','x') AS lt, RTRIM('abyy','y') AS rt") == "u,l,t,lt,rt\nABC,abc,x,ab,ab\n"


def test_substr_and_substring():
    """SUBSTRING is 1-based; SUBSTR is 0-based; negative start counts from the end; over-run length clamps."""
    assert q("SELECT SUBSTRING('hello', 2, 2) AS a, SUBSTR('hello', 2) AS b, SUBSTR('hello', -2) AS c, SUBSTRING('hello', 2, 10) AS d") == "a,b,c,d\nel,llo,lo,ello\n"


def test_pad_and_replace():
    """LPAD/RPAD pad to a width with a fill string; REPLACE substitutes all occurrences."""
    assert q("SELECT LPAD('7', 3, '0') AS lp, RPAD('7', 3, 'x') AS rp, REPLACE('a-b-c', '-', '_') AS re") == "lp,rp,re\n007,7xx,a_b_c\n"


def test_instr_zero_based():
    """INSTR returns the 0-based index of the first occurrence, or NULL when absent."""
    assert q("SELECT INSTR('hello', 'h') AS a, INSTR('hello', 'l') AS b, INSTR('hello', 'o') AS c, INSTR('hello', 'z') AS d") == "a,b,c,d\n0,2,4,\n"


def test_len_counts_runes():
    """LEN counts Unicode characters (runes), not bytes."""
    assert q("SELECT LEN('hello') AS a, LEN('héllo') AS b") == "a,b\n5,5\n"


def test_title_case_and_format():
    """TITLE_CASE capitalizes each word; FORMAT applies printf-style verbs."""
    assert q("""SELECT TITLE_CASE('hello world') AS t, FORMAT('%s-%d-%.2f', 'a', 3, 1.5) AS f""") == "t,f\nHello World,a-3-1.50\n"


# ----------------------------------------------------------------------------- numeric functions

def test_numeric_basic():
    """ABS/CEIL/FLOOR compute as expected; CEIL/FLOOR take an optional decimal place."""
    assert q("SELECT ABS(-5) AS a, CEIL(1.001, 1) AS c, FLOOR(1.999, 1) AS f") == "a,c,f\n5,1.1,1.9\n"


def test_round_with_place():
    """ROUND rounds to the given number of decimal places."""
    assert q("SELECT ROUND(3.14159, 2) AS a, ROUND(3.14159, 0) AS b") == "a,b\n3.14,3\n"


def test_pow_and_sqrt():
    """POW raises to a power (fractional exponents allowed); SQRT is the square root."""
    assert q("SELECT POW(2, 10) AS a, SQRT(16) AS b, POW(2, 0.5) AS c") == "a,b,c\n1024,4,1.4142135623730951\n"


def test_number_format():
    """NUMBER_FORMAT groups thousands with commas (quoted by CSV); a place arg sets decimals."""
    assert q("SELECT NUMBER_FORMAT(1234567) AS a, NUMBER_FORMAT(1234567.891, 2) AS b") == 'a,b\n"1,234,567","1,234,567.89"\n'


def test_base_conversions():
    """BIN/OCT/HEX render an integer in the given base."""
    assert q("SELECT BIN(5) AS b, OCT(8) AS o, HEX(255) AS h") == "b,o,h\n101,10,ff\n"


# ----------------------------------------------------------------------------- cast functions

def test_cast_functions():
    """Cast functions convert types; INTEGER truncates toward zero; BOOLEAN parses logicals."""
    assert q("SELECT INTEGER(3.9) AS a, INTEGER(-3.9) AS b, FLOAT('2.5') AS c, STRING(42) AS d, BOOLEAN('false') AS e") == "a,b,c,d,e\n3,-3,2.5,42,false\n"


# ----------------------------------------------------------------------------- logical / null / case

def test_coalesce_if_ifnull_nullif():
    """COALESCE returns the first non-NULL; IF branches; IFNULL/NULLIF handle null substitution."""
    assert q("SELECT COALESCE(NULL, NULL, 'x') AS c, IF(2 > 1, 'a', 'b') AS i, IFNULL(NULL, 9) AS f, NULLIF(5, 5) AS n") == "c,i,f,n\nx,a,9,\n"


def test_case_searched():
    """A searched CASE evaluates WHEN conditions in order."""
    assert q("SELECT CASE WHEN 1 > 2 THEN 'x' WHEN 2 > 1 THEN 'y' ELSE 'z' END AS r") == "r\ny\n"


def test_case_simple():
    """A simple CASE compares an operand against WHEN values."""
    assert q("SELECT CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' ELSE 'c' END AS r") == "r\nb\n"


def test_three_valued_logic():
    """NULL comparisons yield UNKNOWN (rendered empty); IS NULL yields a real boolean."""
    assert q("SELECT (NULL = NULL) AS eq, (NULL IS NULL) AS isn, TERNARY(NULL) AS t") == "eq,isn,t\n,true,\n"


# ----------------------------------------------------------------------------- datetime

def test_datetime_format_placeholders():
    """DATETIME parses a timestamp and DATETIME_FORMAT renders it via %% placeholders (%i = minute)."""
    assert q("SELECT DATETIME_FORMAT(DATETIME('2021-03-04 05:06:07'), '%Y/%m/%d %H:%i:%s') AS d") == "d\n2021/03/04 05:06:07\n"


def test_datetime_extract():
    """YEAR/MONTH/DAY/HOUR/MINUTE/SECOND extract integer components."""
    assert q("SELECT YEAR(DATETIME('2021-03-04 05:06:07')) AS y, MONTH(DATETIME('2021-03-04 05:06:07')) AS mo, DAY(DATETIME('2021-03-04 05:06:07')) AS d, HOUR(DATETIME('2021-03-04 05:06:07')) AS h, MINUTE(DATETIME('2021-03-04 05:06:07')) AS mi, SECOND(DATETIME('2021-03-04 05:06:07')) AS s") == "y,mo,d,h,mi,s\n2021,3,4,5,6,7\n"


def test_datetime_arithmetic():
    """ADD_DAY rolls over month boundaries; DATE_DIFF returns whole-day differences."""
    assert q("SELECT DATETIME_FORMAT(ADD_DAY(DATETIME('2021-01-30'), 5), '%Y-%m-%d') AS d, DATE_DIFF(DATETIME('2021-01-10'), DATETIME('2021-01-01')) AS diff") == "d,diff\n2021-02-04,9\n"


# ----------------------------------------------------------------------------- aggregates

def test_aggregate_basic():
    """COUNT(*)/SUM/AVG/MIN/MAX aggregate over all rows."""
    assert q("SELECT COUNT(*) AS c, SUM(age) AS s, AVG(age) AS a, MIN(age) AS mn, MAX(age) AS mx FROM `users.csv`", {"users.csv": USERS}) == "c,s,a,mn,mx\n3,95,31.666666666666668,25,40\n"


def test_count_distinct():
    """COUNT(DISTINCT expr) counts unique non-null values."""
    assert q("SELECT COUNT(DISTINCT dept) AS d FROM `depts.csv`", {"depts.csv": DEPTS}) == "d\n2\n"


def test_median():
    """MEDIAN returns the middle value of the distribution."""
    assert q("SELECT MEDIAN(age) AS m FROM `users.csv`", {"users.csv": USERS}) == "m\n30\n"


def test_stdev_var_sample():
    """STDEV/VAR are sample statistics (divide by n-1)."""
    assert q("SELECT ROUND(STDEV(age), 4) AS sd, ROUND(VAR(age), 4) AS v FROM `users.csv`", {"users.csv": USERS}) == "sd,v\n7.6376,58.3333\n"


def test_listagg_within_group():
    """LISTAGG concatenates values with a separator, ordered by WITHIN GROUP."""
    assert q("SELECT LISTAGG(name, ', ') WITHIN GROUP (ORDER BY name) AS names FROM `users.csv`", {"users.csv": USERS}) == 'names\n"Alice, Bob, Carol"\n'


def test_json_agg():
    """JSON_AGG aggregates values into a JSON array (quoted by CSV output)."""
    assert q("SELECT JSON_AGG(name) AS j FROM `users.csv`", {"users.csv": USERS}) == 'j\n"[""Alice"",""Bob"",""Carol""]"\n'


def test_aggregate_over_empty():
    """Over an empty group COUNT is 0 while SUM/MAX are NULL."""
    assert q("SELECT COUNT(*) AS c, SUM(age) AS s, MAX(age) AS m FROM `users.csv` WHERE age > 1000", {"users.csv": USERS}) == "c,s,m\n0,,\n"


# ----------------------------------------------------------------------------- grouping

def test_group_by_and_count():
    """GROUP BY partitions rows and aggregates per group."""
    assert q("SELECT dept, COUNT(*) AS n FROM `depts.csv` GROUP BY dept ORDER BY dept", {"depts.csv": DEPTS}) == "dept,n\nEng,2\nSales,1\n"


def test_having():
    """HAVING filters groups after aggregation."""
    assert q("SELECT dept, COUNT(*) AS n FROM `depts.csv` GROUP BY dept HAVING COUNT(*) >= 2 ORDER BY dept", {"depts.csv": DEPTS}) == "dept,n\nEng,2\n"


def test_group_by_multiple_keys():
    """GROUP BY can partition on several keys."""
    rows = "a,b,v\nx,1,10\nx,1,5\nx,2,7\ny,1,3\n"
    assert q("SELECT a, b, SUM(v) AS s FROM `r.csv` GROUP BY a, b ORDER BY a, b", {"r.csv": rows}) == "a,b,s\nx,1,15\nx,2,7\ny,1,3\n"


# ----------------------------------------------------------------------------- ordering / limit / distinct

def test_order_by_multiple_keys():
    """ORDER BY sorts by several keys with per-key direction."""
    assert q("SELECT id, dept FROM `depts.csv` ORDER BY dept ASC, id DESC", {"depts.csv": DEPTS}) == "id,dept\n3,Eng\n1,Eng\n2,Sales\n"


def test_order_by_expression():
    """ORDER BY can sort on a computed expression."""
    assert q("SELECT name FROM `users.csv` ORDER BY LEN(name) DESC, name ASC LIMIT 1", {"users.csv": USERS}) == "name\nAlice\n"


def test_order_by_alias():
    """ORDER BY can reference a select-list alias."""
    assert q("SELECT name, age * 2 AS d FROM `users.csv` ORDER BY d DESC LIMIT 1", {"users.csv": USERS}) == "name,d\nCarol,80\n"


def test_limit_offset():
    """LIMIT bounds the row count; OFFSET skips leading rows."""
    assert q("SELECT id FROM `users.csv` ORDER BY id LIMIT 1 OFFSET 1", {"users.csv": USERS}) == "id\n2\n"


def test_distinct():
    """SELECT DISTINCT removes duplicate rows."""
    assert q("SELECT DISTINCT dept FROM `depts.csv` ORDER BY dept", {"depts.csv": DEPTS}) == "dept\nEng\nSales\n"


# ----------------------------------------------------------------------------- joins

def test_inner_join():
    """An inner join matches rows on the ON condition."""
    assert q("SELECT u.name, d.dept FROM `users.csv` u JOIN `depts.csv` d ON u.id = d.id ORDER BY u.id", {"users.csv": USERS, "depts.csv": DEPTS}) == "name,dept\nAlice,Eng\nBob,Sales\nCarol,Eng\n"


def test_left_join_null_fill():
    """A LEFT JOIN keeps unmatched left rows with NULLs for right columns."""
    assert q("SELECT d.id, u.name FROM `d2.csv` d LEFT JOIN `users.csv` u ON d.id = u.id ORDER BY d.id", {"users.csv": USERS, "d2.csv": D2}) == "id,name\n1,Alice\n2,Bob\n3,Carol\n4,\n"


def test_cross_join():
    """A CROSS JOIN produces the Cartesian product."""
    assert q("SELECT COUNT(*) AS c FROM `users.csv` CROSS JOIN `depts.csv`", {"users.csv": USERS, "depts.csv": DEPTS}) == "c\n9\n"


def test_self_join():
    """A table can be joined to itself via aliases."""
    assert q("SELECT a.name AS x, b.name AS y FROM `users.csv` a JOIN `users.csv` b ON a.id + 1 = b.id ORDER BY a.id", {"users.csv": USERS}) == "x,y\nAlice,Bob\nBob,Carol\n"


# ----------------------------------------------------------------------------- subqueries / set ops / CTE

def test_scalar_subquery():
    """A scalar subquery can supply a single value to a predicate."""
    assert q("SELECT name FROM `users.csv` WHERE age = (SELECT MAX(age) FROM `users.csv`)", {"users.csv": USERS}) == "name\nCarol\n"


def test_in_subquery():
    """IN can test membership against a subquery result set."""
    assert q("SELECT name FROM `users.csv` WHERE id IN (SELECT id FROM `depts.csv` WHERE dept = 'Eng') ORDER BY name", {"users.csv": USERS, "depts.csv": DEPTS}) == "name\nAlice\nCarol\n"


def test_union_dedup_and_all():
    """UNION removes duplicates; UNION ALL keeps them."""
    assert q("SELECT 1 AS x UNION SELECT 2 ORDER BY x") == "x\n1\n2\n"
    assert q("SELECT 1 AS x UNION ALL SELECT 1") == "x\n1\n1\n"


def test_intersect_except():
    """INTERSECT keeps common rows; EXCEPT subtracts the second set."""
    assert q("SELECT 1 AS x UNION SELECT 2 EXCEPT SELECT 2") == "x\n1\n"


def test_cte_with():
    """A WITH common table expression can be referenced by the main query."""
    assert q("WITH t AS (SELECT 1 AS x UNION SELECT 2) SELECT SUM(x) AS s FROM t") == "s\n3\n"


def test_recursive_cte():
    """A WITH RECURSIVE CTE iterates a self-referencing query."""
    assert q("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT i FROM n") == "i\n1\n2\n3\n"


# ----------------------------------------------------------------------------- analytic / window

def test_row_number():
    """ROW_NUMBER assigns a unique sequential rank over the window ordering."""
    assert q("SELECT name, ROW_NUMBER() OVER (ORDER BY age DESC) AS rn FROM `users.csv` ORDER BY rn", {"users.csv": USERS}) == "name,rn\nCarol,1\nAlice,2\nBob,3\n"


def test_rank_with_ties():
    """RANK leaves gaps after ties."""
    assert q("SELECT dept, RANK() OVER (ORDER BY dept) AS r FROM `depts.csv` ORDER BY dept, r", {"depts.csv": DEPTS}) == "dept,r\nEng,1\nEng,1\nSales,3\n"


def test_dense_rank_partition():
    """DENSE_RANK with PARTITION BY ranks within each partition without gaps."""
    assert q("SELECT dept, id, DENSE_RANK() OVER (PARTITION BY dept ORDER BY id) AS r FROM `d2.csv` ORDER BY dept, id", {"d2.csv": D2}) == "dept,id,r\nEng,1,1\nEng,3,2\nHR,4,1\nSales,2,1\n"


# ----------------------------------------------------------------------------- input handling / subcommands

def test_bare_table_name():
    """A bare identifier (no backticks, no extension) resolves to the matching .csv file."""
    assert q("SELECT name FROM users WHERE id = 1", {"users.csv": USERS}) == "name\nAlice\n"


def test_stdin_table():
    """The STDIN keyword exposes piped CSV as a queryable table."""
    assert q("SELECT SUM(x) AS s FROM STDIN", data="x\n5\n6\n") == "s\n11\n"


def test_calc_subcommand():
    """`calc` evaluates an expression over a single piped CSV row (columns c1..cN), no trailing newline."""
    assert q("c1 + c3", args=["calc"], data="1,2,3") == "4"
    assert q("c1 || '-' || c2", args=["calc"], data="foo,bar") == "foo-bar"


def test_delimiter_input():
    """`-d` sets the input field delimiter (here a tab for TSV input)."""
    assert q("SELECT a, b FROM `t.tsv`", {"t.tsv": "a\tb\n1\t2\n"}, args=["-d", "\\t"]) == "a,b\n1,2\n"


def test_select_star_preserves_columns():
    """SELECT * returns all columns in file order."""
    assert q("SELECT * FROM `users.csv` WHERE id = 1", {"users.csv": USERS}) == "id,name,age\n1,Alice,30\n"


# ----------------------------------------------------------------------------- harder corners

def test_round_half_away_from_zero():
    """ROUND rounds halves away from zero (2.5 -> 3, -2.5 -> -3), not banker's rounding."""
    assert q("SELECT ROUND(2.5) AS a, ROUND(3.5) AS b, ROUND(0.5) AS c, ROUND(-2.5) AS d") == "a,b,c,d\n3,4,1,-3\n"


def test_string_number_coercion_in_comparison():
    """A field/literal usable as a number is compared numerically, not lexically (`'10' > 9`)."""
    assert q("SELECT IF('02' = 2, 'eq', 'ne') AS a, IF('10' > 9, 'gt', 'le') AS b") == "a,b\neq,gt\n"


def test_concat_coerces_numbers():
    """`||` stringifies numeric operands before concatenating."""
    assert q("SELECT 1 || 'x' || 2 AS r") == "r\n1x2\n"


def test_not_in_with_null():
    """NOT IN against a list containing NULL yields UNKNOWN, so no rows qualify."""
    assert q("SELECT 1 AS x WHERE 5 NOT IN (1, NULL)") == "x\n"


def test_exists_correlated_subquery():
    """EXISTS with a correlated subquery filters rows by a related table."""
    assert q("SELECT name FROM `users.csv` u WHERE EXISTS (SELECT 1 FROM `depts.csv` d WHERE d.id = u.id AND d.dept = 'Eng') ORDER BY name", {"users.csv": USERS, "depts.csv": DEPTS}) == "name\nAlice\nCarol\n"


def test_not_like():
    """NOT LIKE negates a pattern match."""
    assert q("SELECT name FROM `users.csv` WHERE name NOT LIKE 'A%' ORDER BY name", {"users.csv": USERS}) == "name\nBob\nCarol\n"


def test_aggregate_skips_null():
    """COUNT(*) counts rows; COUNT(expr) and SUM/AVG skip NULLs."""
    assert q("SELECT COUNT(*) AS c, COUNT(v) AS cv, SUM(v) AS s FROM (SELECT 10 AS v UNION ALL SELECT NULL UNION ALL SELECT 20) t") == "c,cv,s\n3,2,30\n"


def test_empty_field_is_null():
    """An empty CSV field is treated as NULL (skipped by COUNT(column))."""
    ev = "id,v\n1,10\n2,\n3,20\n"
    assert q("SELECT COUNT(*) AS c, COUNT(v) AS cv FROM `ev.csv`", {"ev.csv": ev}) == "c,cv\n3,2\n"


def test_avg_integer_when_exact():
    """AVG yields an integer when the mean divides evenly, otherwise a float."""
    assert q("SELECT AVG(v) AS a FROM (SELECT 2 AS v UNION ALL SELECT 4) t") == "a\n3\n"


def test_case_no_else_is_null():
    """A CASE with no matching branch and no ELSE evaluates to NULL."""
    assert q("SELECT CASE WHEN 1 > 2 THEN 'x' END AS r") == "r\n\n"


def test_listagg_distinct():
    """LISTAGG DISTINCT concatenates only unique values."""
    assert q("SELECT LISTAGG(DISTINCT dept, '|') WITHIN GROUP (ORDER BY dept) AS d FROM `depts.csv`", {"depts.csv": DEPTS}) == "d\nEng|Sales\n"


def test_multi_join_three_tables():
    """Three tables can be chained with successive JOINs."""
    city = "id,city\n1,NYC\n2,LA\n3,SF\n"
    assert q("SELECT u.name, d.dept, c.city FROM `users.csv` u JOIN `depts.csv` d ON u.id = d.id JOIN `c.csv` c ON u.id = c.id ORDER BY u.id", {"users.csv": USERS, "depts.csv": DEPTS, "c.csv": city}) == "name,dept,city\nAlice,Eng,NYC\nBob,Sales,LA\nCarol,Eng,SF\n"


def test_having_with_where_and_aggregate_order():
    """WHERE pre-filters rows, HAVING filters groups by an aggregate, ORDER BY sorts by it."""
    assert q("SELECT dept, SUM(id) AS s FROM `depts.csv` WHERE id <= 3 GROUP BY dept HAVING SUM(id) > 1 ORDER BY s DESC", {"depts.csv": DEPTS}) == "dept,s\nEng,4\nSales,2\n"


def test_window_lag_lead():
    """LAG/LEAD read the previous/next row in the window ordering (NULL at the edges)."""
    assert q("SELECT id, LAG(id) OVER (ORDER BY id) AS prev, LEAD(id) OVER (ORDER BY id) AS nxt FROM `users.csv`", {"users.csv": USERS}) == "id,prev,nxt\n1,,2\n2,1,3\n3,2,\n"


def test_window_running_aggregate():
    """An aggregate used as a window function with ORDER BY computes a running total."""
    assert q("SELECT id, SUM(id) OVER (ORDER BY id) AS run FROM `users.csv`", {"users.csv": USERS}) == "id,run\n1,1\n2,3\n3,6\n"


def test_window_first_value():
    """FIRST_VALUE returns the first row's value in the window frame."""
    assert q("SELECT id, FIRST_VALUE(name) OVER (ORDER BY id) AS fv FROM `users.csv`", {"users.csv": USERS}) == "id,fv\n1,Alice\n2,Alice\n3,Alice\n"


def test_ntile():
    """NTILE distributes rows into the given number of buckets."""
    assert q("SELECT id, NTILE(2) OVER (ORDER BY id) AS nt FROM `users.csv`", {"users.csv": USERS}) == "id,nt\n1,1\n2,1\n3,2\n"


def test_percent_rank():
    """PERCENT_RANK is (rank - 1) / (rows - 1) over the window ordering."""
    assert q("SELECT id, PERCENT_RANK() OVER (ORDER BY id) AS p FROM `users.csv`", {"users.csv": USERS}) == "id,p\n1,0\n2,0.5\n3,1\n"


def test_regexp_replace():
    """REGEXP_REPLACE replaces all matches of a regular expression."""
    assert q("SELECT REGEXP_REPLACE('a1b2c3', '[0-9]', '#') AS r") == "r\na#b#c#\n"


def test_width_and_byte_len():
    """WIDTH is display width, BYTE_LEN is the UTF-8 byte count, LEN is the rune count."""
    assert q("SELECT WIDTH('ab') AS w, BYTE_LEN('héllo') AS b, LEN('héllo') AS l") == "w,b,l\n2,6,5\n"


def test_json_value():
    """JSON_VALUE extracts a value from a JSON document by dotted path."""
    assert q("""SELECT JSON_VALUE('obj.a', '{"obj":{"a":42}}') AS v""") == "v\n42\n"


def test_weekday_and_day_of_year():
    """WEEKDAY (Sun=0) and DAY_OF_YEAR extract calendar components."""
    assert q("SELECT WEEKDAY(DATETIME('2021-03-04')) AS w, DAY_OF_YEAR(DATETIME('2021-03-04')) AS d") == "w,d\n4,63\n"


# ----------------------------------------------------------------------------- more output formats / idiosyncrasies

def test_format_ltsv():
    """`-f LTSV` emits one `key:value` tab-separated record per row (no header line)."""
    assert q("SELECT id, name FROM `users.csv` WHERE id < 3", {"users.csv": USERS}, args=["-f", "LTSV"]) == "id:1\tname:Alice\nid:2\tname:Bob\n"


def test_format_org():
    """`-f ORG` emits an Emacs org-mode table (separator row uses `+` at column joins)."""
    expected = (
        "| id |  name  |\n"
        "|----+--------|\n"
        "| 1  | Alice  |\n"
        "| 2  | Bob    |\n"
    )
    assert q("SELECT id, name FROM `users.csv` WHERE id < 3", {"users.csv": USERS}, args=["-f", "ORG"]) == expected


def test_format_fixed():
    """`-f FIXED` emits fixed-width space-padded columns (header + rows, each column the width of its widest cell)."""
    expected = (
        "id name \n"
        "1  Alice\n"
        "2  Bob  \n"
    )
    assert q("SELECT id, name FROM `users.csv` WHERE id < 3", {"users.csv": USERS}, args=["-f", "FIXED"]) == expected


def test_text_right_aligns_numbers():
    """In TEXT/box output numeric columns are right-aligned while string columns are left-aligned."""
    expected = (
        "+-----+-----+\n"
        "| num | str |\n"
        "+-----+-----+\n"
        "|   5 | hi  |\n"
        "+-----+-----+\n"
    )
    assert q("SELECT 5 AS num, 'hi' AS str", args=["-f", "TEXT"]) == expected


def test_json_renders_null_and_object():
    """JSON output renders NULL as `null`; JSON_OBJECT builds an object keyed by argument names."""
    assert q("SELECT id, NULL AS x FROM `users.csv` WHERE id = 1", {"users.csv": USERS}, args=["-f", "JSON"]) == '[{"id":"1","x":null}]\n'
    assert q("SELECT JSON_OBJECT(id, name) AS j FROM `users.csv` WHERE id = 1", {"users.csv": USERS}) == 'j\n"{""id"":""1"",""name"":""Alice""}"\n'


def test_like_is_case_insensitive():
    """LIKE matches case-insensitively (`'ABC' LIKE 'a%'` is true)."""
    assert q("SELECT IF('ABC' LIKE 'a%', 'y', 'n') AS a, IF('Hello' LIKE 'h_llo', 'y', 'n') AS b") == "a,b\ny,y\n"


def test_add_month_date_normalization():
    """ADD_MONTH normalizes overflow days Go-style: Jan 31 + 1 month -> Mar 3, not Feb 28."""
    assert q("SELECT DATETIME_FORMAT(ADD_MONTH(DATETIME('2021-01-31'), 1), '%Y-%m-%d') AS a, DATETIME_FORMAT(ADD_MONTH(DATETIME('2021-03-15'), -1), '%Y-%m-%d') AS b") == "a,b\n2021-03-03,2021-02-15\n"


def test_datetime_name_placeholders():
    """DATETIME_FORMAT name placeholders: %a abbrev weekday, %b abbrev month, %W full weekday, %p AM/PM."""
    assert q("SELECT DATETIME_FORMAT(DATETIME('2021-03-04 13:06:07'), '%a %b %W %p') AS d") == "d\nThu Mar Thursday PM\n"


def test_number_format_negative():
    """NUMBER_FORMAT groups a negative number and keeps the requested decimal places."""
    assert q("SELECT NUMBER_FORMAT(-1234.5, 1) AS n") == 'n\n"-1,234.5"\n'


def test_intersect_all():
    """INTERSECT ALL keeps matching duplicate rows from both inputs."""
    assert q("SELECT 1 AS x UNION ALL SELECT 1 INTERSECT ALL SELECT 1") == "x\n1\n1\n"


# ----------------------------------------------------------------------------- error handling

def test_error_missing_file():
    """Querying a nonexistent file exits nonzero with a diagnostic and no stdout."""
    so, se, rc = _run(["SELECT * FROM `nope.csv`"])
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_error_syntax():
    """A syntactically invalid statement exits nonzero with a diagnostic and no stdout."""
    so, se, rc = _run(["SELCT 1"])
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_error_unknown_column():
    """Referencing an unknown column exits nonzero with a diagnostic and no stdout."""
    so, se, rc = _run(["SELECT nosuch FROM `users.csv`"], files={"users.csv": USERS})
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_error_unknown_function():
    """Calling an undefined function exits nonzero with a diagnostic and no stdout."""
    so, se, rc = _run(["SELECT NOPE(1)"])
    assert rc != 0
    assert so == "" and se.strip() != ""
