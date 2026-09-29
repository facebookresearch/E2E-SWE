"""End-to-end tests for the ``sqlparse`` non-validating SQL parser / formatter.

Two public surfaces are exercised:

* The **Python API** — ``sqlparse.parse`` / ``parsestream`` / ``split`` / ``format``, the
  ``sqlparse.lexer.tokenize`` token stream, and the ``sqlparse.sql`` / ``sqlparse.tokens``
  object model. Tests assert observable contracts (the values accessors return, the class a
  construct is grouped into, a token's ``ttype``, the exact formatted string) rather than a
  particular internal token layout, so any faithful reimplementation passes.
* The **command-line interface** (``sqlformat``) via ``python -m sqlparse`` as a subprocess —
  this is the only way to exercise argparse wiring, file / stdin I/O, and process exit codes.

Every formatted-output value was captured from the reference implementation, which is
deterministic (pure string transforms, no randomness / time / network). Argparse's own error
wording differs across Python versions, so CLI usage-error tests assert the exit code plus a
stable substring, never argparse's exact message.
"""

import subprocess
import sys
import types

import pytest

import sqlparse
from sqlparse import lexer, sql
from sqlparse import tokens as T
from sqlparse.exceptions import SQLParseError

SQLFORMAT = [sys.executable, "-m", "sqlparse"]


def cli(args, source=None):
    """Run ``python -m sqlparse <args>`` (feeding ``source`` on stdin when given).

    Returns ``(returncode, stdout, stderr)``.
    """
    proc = subprocess.run(
        SQLFORMAT + list(args), input=source, capture_output=True, text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def leaf_ttype(statement_sql, value):
    """Return the ``ttype`` of the first flattened leaf token whose value == ``value``."""
    for tok in sqlparse.parse(statement_sql)[0].flatten():
        if tok.value == value:
            return tok.ttype
    return None


def find(token_list, cls):
    """Return the first descendant token that is an instance of ``cls`` (depth-first)."""
    for tok in token_list.tokens:
        if isinstance(tok, cls):
            return tok
        if tok.is_group:
            hit = find(tok, cls)
            if hit is not None:
                return hit
    return None


def find_all(token_list, cls, out=None):
    """Collect every descendant token that is an instance of ``cls`` (depth-first)."""
    out = [] if out is None else out
    for tok in token_list.tokens:
        if isinstance(tok, cls):
            out.append(tok)
        if tok.is_group:
            find_all(tok, cls, out)
    return out


def joined(tokens):
    """Concatenate the string forms of a token iterable."""
    return "".join(str(t) for t in tokens)


# --------------------------------------------------------------------------- #
# Tokenization / lexing                                                        #
# --------------------------------------------------------------------------- #

def test_tokenize_returns_typed_token_stream():
    """``sqlparse.lexer.tokenize`` yields a generator of ``(ttype, value)`` pairs: a canonical
    ``SELECT`` produces the expected leading DML keyword, the ``*`` wildcard, the ``FROM``
    keyword, the table name, and a trailing punctuation semicolon."""
    stream = lexer.tokenize("select * from foo;")
    assert isinstance(stream, types.GeneratorType)
    toks = list(stream)
    assert toks[0] == (T.DML, "select")
    assert toks[-1] == (T.Punctuation, ";")
    ttypes = [ttype for ttype, _ in toks]
    assert T.Wildcard in ttypes
    assert (T.Keyword, "from") in toks
    assert (T.Name, "foo") in toks


def test_literal_type_classification():
    """Numeric literals are typed by kind (integer / float / hexadecimal), single-quoted text
    is a ``String.Single`` while a double-quoted name is parsed as an ``Identifier``, and a
    bare word that merely looks numeric (``e1``) is NOT a number."""
    assert leaf_ttype("select 42", "42") is T.Number.Integer
    assert leaf_ttype("select 1.5", "1.5") is T.Number.Float
    assert leaf_ttype("select .5", ".5") is T.Number.Float
    assert leaf_ttype("select 6.67428E-8", "6.67428E-8") is T.Number.Float
    assert leaf_ttype("select 0xdeadbeef", "0xdeadbeef") is T.Number.Hexadecimal
    assert leaf_ttype("select 'foo'", "'foo'") is T.String.Single
    assert isinstance(sqlparse.parse('select "foo"')[0].tokens[-1], sql.Identifier)
    assert leaf_ttype("select e1", "e1") is T.Name  # looks scientific but is a Name, not a Number


def test_placeholder_recognition():
    """Bind-parameter placeholders in all supported spellings are typed ``Name.Placeholder``,
    while a modulo operator is not mistaken for one."""
    for ph in ("?", ":name", "%s", "%(foo)s", ":1"):
        assert leaf_ttype("select " + ph, ph) is T.Name.Placeholder, ph
    assert leaf_ttype("select x %3", "%") is T.Operator


def test_keyword_and_operator_classification():
    """Keyword/operator recognition: ``*`` is a Wildcard in a column list but an arithmetic
    Operator between operands; ``LIKE`` is a comparison operator; ``DESC`` is an ordering
    keyword; and a multi-word keyword such as ``UNION ALL`` is recognised as one keyword."""
    assert leaf_ttype("select * from t", "*") is T.Wildcard
    assert leaf_ttype("select 1 * 2", "*") is T.Operator
    assert leaf_ttype("select a from t where a like 'x'", "like") is T.Operator.Comparison
    assert leaf_ttype("select a from t order by a desc", "desc") is T.Keyword.Order
    assert leaf_ttype("select 1 union all select 2", "union all") is T.Keyword


# --------------------------------------------------------------------------- #
# Parsing & the object model                                                   #
# --------------------------------------------------------------------------- #

def test_parse_returns_tuple_parsestream_generator_and_roundtrip():
    """``parse`` returns a tuple of statements, ``parsestream`` a generator, empty input yields
    no statements, and ``str(statement)`` round-trips the original source verbatim (whitespace
    and non-ASCII preserved)."""
    assert isinstance(sqlparse.parse("select 1"), tuple)
    assert isinstance(sqlparse.parsestream("select 1"), types.GeneratorType)
    assert sqlparse.parse("") == ()
    for src in ("select  *   from\tfoo", "select 業者 from t", "select a -- c"):
        assert str(sqlparse.parse(src)[0]) == src
    assert len(sqlparse.parse("select 1; select 2")) == 2


def test_statement_get_type():
    """``Statement.get_type`` reports the leading DML/DDL verb, resolves the inner verb of a
    ``WITH`` CTE, sees past a leading comment, and returns ``'UNKNOWN'`` when there is none."""
    assert sqlparse.parse("select * from t")[0].get_type() == "SELECT"
    assert sqlparse.parse("insert into t values (1)")[0].get_type() == "INSERT"
    assert sqlparse.parse("update t set x=1")[0].get_type() == "UPDATE"
    assert sqlparse.parse("delete from t")[0].get_type() == "DELETE"
    assert sqlparse.parse("create table t (a int)")[0].get_type() == "CREATE"
    assert sqlparse.parse("with cte as (select 1) select * from cte")[0].get_type() == "SELECT"
    assert sqlparse.parse("-- c\nselect 1")[0].get_type() == "SELECT"
    assert sqlparse.parse("foo bar baz")[0].get_type() == "UNKNOWN"


def test_token_type_containment_and_identity():
    """Token types form a prefix hierarchy: a child type is ``in`` its parent, but a parent is not
    ``in`` a child. Each type is a stable singleton, so the ``ttype`` of the same construct across
    independent parses is the identical object. A keyword token derives ``is_keyword`` and an
    upper-cased ``normalized`` form from its type."""
    assert T.DML in T.Keyword
    assert T.Number.Integer in T.Number
    assert T.Keyword not in T.DML
    assert leaf_ttype("select * from a", "*") is leaf_ttype("select * from b", "*") is T.Wildcard
    kw = sqlparse.parse("select 1")[0].token_first()
    assert kw.ttype is T.DML
    assert kw.is_keyword
    assert kw.normalized == "SELECT"


def test_identifier_name_and_alias_accessors():
    """``Identifier`` exposes the real name, the alias, the combined display name, and the parent
    (schema/table) qualifier across dotted names, ``AS`` aliases, plain aliases and quoted
    identifiers."""
    dotted = find(sqlparse.parse("select a.b from t")[0], sql.Identifier)
    assert (dotted.get_real_name(), dotted.get_parent_name(), dotted.get_alias()) == ("b", "a", None)

    as_alias = find(sqlparse.parse("select x.y as z from t")[0], sql.Identifier)
    assert (as_alias.get_real_name(), as_alias.get_parent_name(), as_alias.get_alias()) == ("y", "x", "z")
    assert as_alias.get_name() == "z"

    plain = find(sqlparse.parse("select foo as bar from t")[0], sql.Identifier)
    assert (plain.get_real_name(), plain.get_alias()) == ("foo", "bar")

    quoted = find(sqlparse.parse('select "quoted" from t')[0], sql.Identifier)
    assert quoted.get_real_name() == "quoted"


def test_identifier_typecast_ordering_wildcard():
    """``Identifier`` reports a PostgreSQL ``::`` typecast target, an ``ASC``/``DESC`` ordering,
    and whether it is a (possibly qualified) wildcard."""
    cast = find(sqlparse.parse("select col::int from t")[0], sql.Identifier)
    assert cast.get_typecast() == "int"

    stmt = sqlparse.parse("select a from t order by b desc")[0]
    ordered = next(i for i in find_all(stmt, sql.Identifier) if i.get_ordering())
    assert ordered.get_ordering() == "DESC"

    star = find(sqlparse.parse("select a.* from t")[0], sql.Identifier)
    assert star.is_wildcard() is True
    assert (star.get_real_name(), star.get_parent_name()) == ("*", "a")


def test_identifier_list_and_function_grouping():
    """A comma-separated column list groups into an ``IdentifierList`` whose members are
    enumerable; ``name(args)`` groups into a ``Function`` with retrievable parameters; a bare
    keyword before parentheses (``IN (...)``) is NOT a function; and a ``CREATE TABLE`` target
    keeps its dotted name as an identifier rather than a function call."""
    ilist = find(sqlparse.parse("select a, b, c from t")[0], sql.IdentifierList)
    assert [str(i) for i in ilist.get_identifiers()] == ["a", "b", "c"]

    func = find(sqlparse.parse("select foo(a, b) from t")[0], sql.Function)
    assert func.get_real_name() == "foo"
    assert [str(p) for p in func.get_parameters()] == ["a", "b"]

    agg = find(sqlparse.parse("select count(*) from t")[0], sql.Function)
    assert agg.get_real_name() == "count"

    assert find(sqlparse.parse("select a from t where a in (1, 2)")[0], sql.Function) is None
    assert find(sqlparse.parse("create table db.tbl (a int)")[0], sql.Function) is None


def test_grouping_operation_and_array_index():
    """An arithmetic expression groups into an ``Operation``, and a subscripted identifier
    exposes its array indices via ``get_array_indices``."""
    op = find(sqlparse.parse("select a + b from t")[0], sql.Operation)
    assert op is not None and str(op) == "a + b"
    indexed = find(sqlparse.parse("select col[1] from t")[0], sql.Identifier)
    indices = ["".join(str(t) for t in idx) for idx in indexed.get_array_indices()]
    assert indices == ["1"]


def test_comparison_where_and_case_structure():
    """A ``WHERE`` clause groups into a ``Where`` (bounded before ``ORDER BY``); a comparison
    groups into a ``Comparison`` exposing its left/right operands; and a ``CASE`` expression
    exposes its ``(condition, value)`` branches with a ``None`` condition for ``ELSE``."""
    stmt = sqlparse.parse("select * from t where a = 1 order by b")[0]
    where = find(stmt, sql.Where)
    assert where is not None
    assert "order by" not in str(where).lower()  # ORDER BY terminates the WHERE clause

    comp = find(where, sql.Comparison)
    assert str(comp.left) == "a"
    assert str(comp.right) == "1"

    case = find(sqlparse.parse("select case when a then 1 else 2 end from t")[0], sql.Case)
    branches = case.get_cases(skip_ws=True)
    assert len(branches) == 2
    assert branches[0][0] is not None and "1" in joined(branches[0][1])
    assert branches[-1][0] is None and "2" in joined(branches[-1][1])


def test_tree_navigation_helpers():
    """The token tree supports flattening to leaves, ancestry queries (``within`` /
    ``is_child_of`` / ``has_ancestor``), offset lookup, first-token access, and ``match``."""
    stmt = sqlparse.parse("select a from t where x = 1")[0]
    assert all(not t.is_group for t in stmt.flatten())

    comp = find(stmt, sql.Comparison)
    assert comp.within(sql.Where)
    assert comp.has_ancestor(stmt)

    where = find(stmt, sql.Where)
    assert comp.is_child_of(where)

    assert str(stmt.get_token_at_offset(0)) == "select"
    assert str(stmt.get_token_at_offset(7)) == "a"

    first = stmt.token_first()
    assert first.match(T.DML, "select")


# --------------------------------------------------------------------------- #
# Statement splitting                                                          #
# --------------------------------------------------------------------------- #

def test_split_statements_and_strip_semicolon():
    """``split`` returns one stripped statement string per top-level ``;``, does not split on a
    semicolon inside a string literal, and (with ``strip_semicolon=True``) drops the trailing
    semicolons."""
    assert sqlparse.split("select 1; select 2;") == ["select 1;", "select 2;"]
    assert sqlparse.split("select 'a;b'; select 2") == ["select 'a;b';", "select 2"]
    assert sqlparse.split("select 1; select 2;", strip_semicolon=True) == ["select 1", "select 2"]


def test_split_respects_blocks_and_batches():
    """The splitter understands block structure: semicolons inside a ``BEGIN ... END`` block do
    not split it, ``BEGIN TRANSACTION`` is an ordinary standalone statement (not a block), a
    dollar-quoted function body stays intact, and ``GO`` acts as a batch separator."""
    assert len(sqlparse.split("BEGIN foo; bar; END; select 1;")) == 2
    assert len(sqlparse.split("BEGIN TRANSACTION; select 1; COMMIT;")) == 3
    assert len(sqlparse.split(
        "CREATE FUNCTION f() RETURNS int AS $$ BEGIN return 1; END; $$ LANGUAGE plpgsql; select 9;"
    )) == 2
    assert sqlparse.split("select 1\nGO\nselect 2\nGO") == ["select 1\nGO", "select 2\nGO"]


# --------------------------------------------------------------------------- #
# Formatting via the Python API                                                #
# --------------------------------------------------------------------------- #

def test_format_keyword_case():
    """``keyword_case`` upper/lower/capitalizes only keyword tokens (identifiers and string
    literals are untouched)."""
    base = "select a, b from foo where id = 1"
    assert sqlparse.format(base, keyword_case="upper") == "SELECT a, b FROM foo WHERE id = 1"
    assert sqlparse.format("SELECT A FROM T", keyword_case="lower") == "select A from T"
    assert sqlparse.format(base, keyword_case="capitalize") == "Select a, b From foo Where id = 1"
    assert sqlparse.format("select 'From Me' from t", keyword_case="upper") == "SELECT 'From Me' FROM t"


def test_format_identifier_case():
    """``identifier_case`` recases identifier names but never a double-quoted identifier."""
    base = "select a, b from foo where id = 1"
    assert sqlparse.format(base, identifier_case="upper") == "select A, B from FOO where ID = 1"
    assert sqlparse.format('select foo, "BarCol" from t', identifier_case="upper") == 'select FOO, "BarCol" from T'
    assert sqlparse.format("select foo_bar from t", identifier_case="capitalize") == "select Foo_bar from T"


def test_format_strip_comments():
    """``strip_comments`` removes ordinary block and line comments but preserves optimizer
    hint comments (``/*+ ... */``). (Exact inter-token spacing left by removal is an
    implementation detail and is not asserted.)"""
    out = sqlparse.format("select a, /* remove me */ b from foo -- gone\n", strip_comments=True)
    assert "remove me" not in out and "gone" not in out
    assert out.startswith("select a,") and "b" in out and "from foo" in out
    hinted = sqlparse.format("select /*+ keephint */ a from t", strip_comments=True)
    assert "/*+ keephint */" in hinted


def test_format_strip_whitespace():
    """``strip_whitespace`` collapses runs of whitespace between tokens to a single space."""
    assert sqlparse.format("select   a  ,   b   from   t", strip_whitespace=True) == "select a , b from t"


def test_format_reindent_select_list_where_from():
    """``reindent`` puts each major clause on its own line and wraps the select list, aligning
    continuation columns under the first column."""
    assert sqlparse.format("select a, b from foo where id = 1", reindent=True) == (
        "select a,\n"
        "       b\n"
        "from foo\n"
        "where id = 1"
    )


def test_format_reindent_joins_and_subquery():
    """``reindent`` keeps a JOIN ... ON on its own line, and indents a parenthesised subquery by
    ``indent_width`` (default 2)."""
    assert sqlparse.format("select a, b from t1 join t2 on t1.id = t2.id", reindent=True) == (
        "select a,\n"
        "       b\n"
        "from t1\n"
        "join t2 on t1.id = t2.id"
    )
    assert sqlparse.format("select * from (select 1 from dual)", reindent=True) == (
        "select *\n"
        "from\n"
        "  (select 1\n"
        "   from dual)"
    )
    assert sqlparse.format("select * from (select 1 from dual)", reindent=True, indent_width=4) == (
        "select *\n"
        "from\n"
        "    (select 1\n"
        "     from dual)"
    )


def test_format_reindent_case():
    """``reindent`` lays out a ``CASE`` expression with each ``WHEN``/``ELSE`` on its own line and
    the ``END`` de-indented back under the expression."""
    assert sqlparse.format("select case when a then 1 else 2 end from t", reindent=True) == (
        "select case\n"
        "           when a then 1\n"
        "           else 2\n"
        "       end\n"
        "from t"
    )


def test_format_reindent_multiple_statements():
    """``reindent`` separates successive statements with a blank line."""
    assert sqlparse.format("select 1; select 2", reindent=True) == "select 1;\n\nselect 2"


def test_format_reindent_group_by_order_by():
    """``reindent`` puts the GROUP BY and ORDER BY clauses each on their own line beneath the
    reindented select list and FROM."""
    assert sqlparse.format("select a, count(*) from t group by a order by a desc", reindent=True) == (
        "select a,\n"
        "       count(*)\n"
        "from t\n"
        "group by a\n"
        "order by a desc"
    )


def test_format_reindent_where_conditions():
    """``reindent`` places the WHERE clause on its own line and indents each additional boolean
    condition (AND/OR) beneath the WHERE keyword."""
    assert sqlparse.format("select * from t where a = 1 and b = 2", reindent=True) == (
        "select *\n"
        "from t\n"
        "where a = 1\n"
        "  and b = 2"
    )


def test_format_reindent_union():
    """``reindent`` puts a UNION on its own line between the two reindented SELECT statements."""
    assert sqlparse.format("select a from t1 union select b from t2", reindent=True) == (
        "select a\n"
        "from t1\n"
        "union\n"
        "select b\n"
        "from t2"
    )


def test_format_reindent_insert_values():
    """``reindent`` lays out INSERT ... VALUES with each value tuple on its own line, aligned
    under the first tuple."""
    assert sqlparse.format("insert into t (a, b) values (1, 2), (3, 4)", reindent=True) == (
        "insert into t (a, b)\n"
        "values (1, 2),\n"
        "       (3, 4)"
    )


def test_format_reindent_modifiers():
    """The reindent modifier options each change layout: ``indent_columns`` puts every column on
    its own ``indent_width`` line, ``indent_after_first`` indents subsequent clauses, and
    ``comma_first`` leads continuation lines with the comma."""
    assert sqlparse.format("select a, b, c from t", reindent=True, indent_columns=True) == (
        "select\n  a,\n  b,\n  c\nfrom t"
    )
    assert sqlparse.format("select a, b from t", reindent=True, indent_after_first=True) == (
        "select a,\n       b\n  from t"
    )
    assert sqlparse.format("select a, b, c from foo", reindent=True, comma_first=True) == (
        "select a\n     , b\n     , c\nfrom foo"
    )


def test_format_reindent_aligned():
    """``reindent_aligned`` right-aligns clause keywords to a common column and lines JOIN/ON/WHERE
    up beneath the SELECT list."""
    src = "select a, b from table1 join table2 on table1.id = table2.id where c is true"
    assert sqlparse.format(src, reindent_aligned=True) == (
        "select a,\n"
        "       b\n"
        "  from table1\n"
        "  join table2\n"
        "    on table1.id = table2.id\n"
        " where c is true"
    )


def test_format_space_around_operators():
    """``use_space_around_operators`` inserts a single space around arithmetic operators."""
    assert sqlparse.format("select 1+2 from foo", use_space_around_operators=True) == "select 1 + 2 from foo"


def test_format_truncate_strings():
    """``truncate_strings`` shortens long single-quoted string literals to N characters plus a
    marker (default ``[...]``, overridable via ``truncate_char``); quoted identifiers are never
    truncated."""
    assert sqlparse.format("select 'aaaaaaaaaaaaaaaaaaaa' from t", truncate_strings=10) == (
        "select 'aaaaaaaaaa[...]' from t"
    )
    assert sqlparse.format("select 'aaaaaaaaaaaaaaaaaaaa' from t", truncate_strings=10, truncate_char="~") == (
        "select 'aaaaaaaaaa~' from t"
    )
    out = sqlparse.format('select "aaaaaaaaaaaaaaaaaaaa" from t', truncate_strings=10)
    assert '"aaaaaaaaaaaaaaaaaaaa"' in out  # identifier left intact


def test_format_output_python_and_php():
    """``output_format`` wraps the statement as an assignment in the target language."""
    assert sqlparse.format("select * from foo", output_format="python") == "sql = 'select * from foo'"
    assert sqlparse.format("select * from foo", output_format="php") == '$sql = "select * from foo";'


# --------------------------------------------------------------------------- #
# Command-line interface                                                       #
# --------------------------------------------------------------------------- #

def test_cli_formatting_options_via_stdin():
    """The CLI wires its formatting flags through to the formatter and writes the result to
    stdout when reading from stdin (``-``): ``-k`` (keyword case), ``-r`` (reindent),
    ``-s`` (space around operators), and their combination."""
    assert cli(["-k", "upper", "-"], "select a from t") == (0, "SELECT a FROM t", "")
    assert cli(["-r", "-"], "select a, b from t") == (0, "select a,\n       b\nfrom t", "")
    assert cli(["-s", "-"], "select 1+2 from foo") == (0, "select 1 + 2 from foo", "")
    assert cli(["-r", "-k", "upper", "-"], "select a, b from t") == (
        0, "SELECT a,\n       b\nFROM t", "",
    )


def test_cli_version_and_help():
    """``--version`` prints the package version and exits 0; ``--help`` exits 0."""
    rc, out, err = cli(["--version"])
    assert rc == 0
    assert sqlparse.__version__ in out
    assert cli(["--help"])[0] == 0


def test_cli_outfile_and_in_place(tmp_path):
    """``-o/--outfile`` writes the formatted result to a file, ``--in-place`` rewrites the input
    file, and multiple input files without ``--in-place`` are rejected."""
    src = tmp_path / "q.sql"
    src.write_text("select a from t")

    out = tmp_path / "out.sql"
    rc, _, _ = cli(["-k", "upper", "-o", str(out), str(src)])
    assert rc == 0
    assert out.read_text() == "SELECT a FROM t"

    rc, _, _ = cli(["-k", "upper", "--in-place", str(src)])
    assert rc == 0
    assert src.read_text() == "SELECT a FROM t"

    second = tmp_path / "q2.sql"
    second.write_text("select b from t")
    rc, _, err = cli([str(src), str(second)])
    assert rc == 1
    assert "Multiple files" in err


def test_cli_argparse_and_runtime_errors():
    """The CLI distinguishes argparse usage errors (exit 2) from runtime errors (exit 1). An
    invalid option *value* and a missing input file exit 1 with an ``[ERROR]`` message; an
    invalid *choice* and a missing file argument are argparse errors that exit 2."""
    # Runtime errors -> exit 1, sqlparse's own [ERROR] messages (deterministic, spec-stable).
    assert cli(["--indent_width", "0", "-"], "select 1") == (
        1, "", "[ERROR] Invalid options: indent_width requires a positive integer\n",
    )
    assert cli(["--in-place", "-"], "select 1") == (
        1, "", "[ERROR] Cannot use --in-place with stdin\n",
    )
    rc, out, err = cli(["/no/such/file.sql"])
    assert rc == 1
    assert err.startswith("[ERROR] Failed to read /no/such/file.sql:")

    # Argparse usage errors -> exit 2 (assert code + stable substring, not argparse's wording).
    rc, out, err = cli(["-l", "xml", "-"], "select 1")
    assert rc == 2
    assert "invalid choice" in err
    rc, out, err = cli([])
    assert rc == 2
    assert err  # usage error; argparse's surfaced positional metavar/dest name is not spec-pinned


# --------------------------------------------------------------------------- #
# Option validation & DoS robustness                                          #
# --------------------------------------------------------------------------- #

def test_format_option_validation_errors():
    """``format`` validates its options and raises ``SQLParseError`` with a specific message for
    each invalid value (bad enum choice, non-boolean where a bool is required, non-positive or
    non-integer numerics)."""
    cases = {
        "Invalid value for keyword_case: 'bogus'": dict(keyword_case="bogus"),
        "Unknown output format: 'xml'": dict(output_format="xml"),
        "Invalid value for strip_comments: 'yes'": dict(strip_comments="yes"),
        "Invalid value for reindent: 2": dict(reindent=2),
        "indent_width requires an integer": dict(indent_width="foo"),
        "indent_width requires a positive integer": dict(indent_width=-1),
        "wrap_after requires a positive integer": dict(wrap_after=-1),
        "comma_first requires a boolean value": dict(comma_first="x"),
        "Invalid value for truncate_strings: 0": dict(truncate_strings=0),
    }
    for message, opts in cases.items():
        with pytest.raises(SQLParseError) as exc:
            sqlparse.format("select 1", **opts)
        assert str(exc.value) == message


def test_dos_prevention_limits():
    """Pathological inputs are rejected with ``SQLParseError`` rather than hanging or crashing:
    exceeding the token cap, exceeding the grouping-depth cap, and exhausting the recursion
    limit each raise; ordinary SQL still parses."""
    with pytest.raises(SQLParseError, match="Maximum number of tokens exceeded"):
        sqlparse.parse("select " + ", ".join(["a"] * 15000))

    with pytest.raises(SQLParseError, match="Maximum grouping depth exceeded"):
        sqlparse.parse("(" * 200 + ")" * 200)

    old_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(100)
        # Deeply nested parentheses are a spec-determined recursive grouping construct (subqueries /
        # function arguments), unlike bare square brackets. Which nesting cap trips (the Python
        # recursion guard vs the grouping-depth cap) depends on the implementation's per-level call
        # depth, not the spec, so accept either documented message.
        with pytest.raises(SQLParseError, match=r"Maximum (recursion|grouping) depth exceeded"):
            sqlparse.parse("(" * 1000 + ")" * 1000)
    finally:
        sys.setrecursionlimit(old_limit)

    assert len(sqlparse.parse("select 1 from t")) == 1
