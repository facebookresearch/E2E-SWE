"""Hidden grading suite for the goawk task.

These tests drive the compiled `goawk` CLI (built by setup.sh at /app/goawk) entirely through
subprocess — program text + stdin/files in, stdout/stderr/exit-code out. Each test models a
realistic AWK usage scenario and asserts a distinct behavioral contract with exact expected
values (no shape-only checks), so the pass fraction tracks real implementation completeness of a
POSIX-compatible AWK interpreter plus GoAWK's CSV extensions.

Set GOAWK_BIN to point at the binary (defaults to /app/goawk, the grading location).
"""

import os
import subprocess

GOAWK = os.environ.get("GOAWK_BIN", "/app/goawk")


def goawk(argv, stdin="", env=None):
    """Run the goawk binary with argv (list); return (stdout, stderr, returncode)."""
    proc = subprocess.run(
        [GOAWK, *argv], input=stdin, capture_output=True, text=True, env=env, timeout=20
    )
    return proc.stdout, proc.stderr, proc.returncode


def out(program, stdin="", pre=(), files=(), env=None):
    """Run a program expected to succeed; assert exit 0 and return stdout."""
    so, se, rc = goawk([*pre, program, *files], stdin=stdin, env=env)
    assert rc == 0, f"expected success, got rc={rc}, stderr={se!r}"
    return so


# --------------------------------------------------------------------------------------
# Records, fields, and field rebuilding
# --------------------------------------------------------------------------------------

def test_default_field_splitting_and_special_vars():
    """Default whitespace splitting: NR/NF and $1..$NF on runs of spaces/tabs, trimmed ends."""
    res = out('{ print NR, NF, $1, $NF }', stdin="  a  b\tc  \nd e\n")
    assert res == "1 3 a c\n2 2 d e\n"


def test_field_assignment_rebuilds_record_with_ofs():
    """Assigning a field rebuilds $0 using OFS between all fields."""
    res = out('BEGIN { OFS="-" } { $2="X"; print $0 }', stdin="a b c\n")
    assert res == "a-X-c\n"


def test_increasing_nf_pads_fields_and_assigning_nf_truncates():
    """Setting a field past NF extends with empty fields; lowering NF drops trailing fields."""
    res = out('{ $5="e"; print NF, $0 }', stdin="a b\n")
    assert res == "5 a b   e\n"
    res2 = out('{ NF=2; print $0 }', stdin="a b c d\n")
    assert res2 == "a b\n"


def test_reassigning_dollar0_resplits_fields():
    """Assigning $0 re-splits into fields and recomputes NF."""
    res = out('{ $0="x y z w"; print NF, $3 }', stdin="one two\n")
    assert res == "4 z\n"


def test_negative_field_index_counts_from_right():
    """GoAWK extension: $-1 is the last field, $-2 the second-to-last."""
    res = out('{ print $-1, $-2 }', stdin="alpha beta gamma\n")
    assert res == "gamma beta\n"


# --------------------------------------------------------------------------------------
# Field and record separators
# --------------------------------------------------------------------------------------

def test_fs_single_char_via_flag():
    """-F sets a single-character field separator."""
    res = out('{ print $1, $3 }', stdin="1,2,3\n4,5,6\n", pre=("-F", ","))
    assert res == "1 3\n4 6\n"


def test_fs_regex_splits_on_pattern():
    """A multi-char FS is treated as a regular expression."""
    res = out('BEGIN { FS="[0-9]+" } { print $2, $3 }', stdin="a12b345c\n")
    assert res == "b c\n"


def test_fs_empty_splits_into_characters():
    """FS=\"\" splits the record into individual characters."""
    res = out('BEGIN { FS="" } { print NF, $1, $4 }', stdin="abcd\n")
    assert res == "4 a d\n"


def test_custom_rs_record_separator():
    """RS changes the record separator; here records are semicolon-delimited."""
    res = out('{ print NR": "$0 }', stdin="a b;c;d e", pre=("-v", "RS=;"))
    assert res == "1: a b\n2: c\n3: d e\n"


def test_paragraph_mode_rs_empty():
    """RS=\"\" is paragraph mode: blank-line-separated records, newlines also split fields."""
    res = out('BEGIN { RS="" } { print NR, NF }', stdin="a b\nc\n\nd\ne f g\n")
    assert res == "1 3\n2 4\n"


def test_ofs_ors_affect_print():
    """OFS joins comma-separated print args; ORS terminates each print."""
    res = out('{ print $1, $2 }', stdin="a b\nc d\n", pre=("-v", "OFS=:", "-v", "ORS=;"))
    assert res == "a:b;c:d;"


# --------------------------------------------------------------------------------------
# Numeric / string semantics
# --------------------------------------------------------------------------------------

def test_numeric_string_comparison_from_fields():
    """Fields that look numeric compare numerically, not lexically."""
    res = out('{ print ($1 > $2) }', stdin="10 9\n2 100\n")
    assert res == "1\n0\n"


def test_string_literal_comparison_is_lexical():
    """String constants compare lexically even when they look like numbers."""
    res = out('BEGIN { print ("10" < "9"), (10 < 9) }')
    assert res == "1 0\n"


def test_uninitialized_variable_is_zero_and_empty():
    """An unset variable acts as 0 in numeric context and \"\" in string context."""
    res = out('BEGIN { print x+5; print "[" x "]" }')
    assert res == "5\n[]\n"


def test_number_to_string_uses_convfmt():
    """Non-integer numbers convert to strings via CONVFMT (default %.6g) in concatenation."""
    res = out('BEGIN { x = 1/3; print "v=" x }')
    assert res == "v=0.333333\n"


def test_integers_print_without_decimal_point():
    """Whole-number values print as integers, not floats."""
    res = out('BEGIN { print 6/2, 2^10, 7 }')
    assert res == "3 1024 7\n"


# --------------------------------------------------------------------------------------
# Expressions and operators
# --------------------------------------------------------------------------------------

def test_arithmetic_operators_and_precedence():
    """Exponentiation binds tighter than unary minus context; modulo and integer division work."""
    res = out('BEGIN { print 2+3*4, 2^3^2, 17%5, -2^2 }')
    assert res == "14 512 2 -4\n"


def test_pre_and_post_increment():
    """Pre-increment updates before use; post-increment updates after use."""
    res = out('BEGIN { i=5; print i++, i, ++i }')
    assert res == "5 6 7\n"


def test_ternary_and_logical_operators():
    """Ternary, short-circuit &&/||, and ! produce 1/0 truth values."""
    res = out('BEGIN { print (3>2 ? "y" : "n"), (0 || 5), (1 && 0), !"" }')
    assert res == "y 1 0 1\n"


def test_string_concatenation():
    """Adjacent expressions concatenate; numbers stringify in the process."""
    res = out('BEGIN { print "a" 1+2 "b" }')
    assert res == "a3b\n"


# --------------------------------------------------------------------------------------
# Built-in string functions
# --------------------------------------------------------------------------------------

def test_substr_three_and_two_arg_and_out_of_range():
    """substr is 1-indexed; the 2-arg form runs to end; length past the end clamps; start past the end is empty."""
    res = out('BEGIN { print substr("hello",2,3); print substr("hello",3); print substr("hello",4,99); print "[" substr("hello",6,2) "]" }')
    assert res == "ell\nllo\nlo\n[]\n"


def test_index_and_length():
    """index returns 1-based position or 0; length with no arg is length($0)."""
    res = out('{ print index($0,"ll"), index($0,"zz"), length($0) }', stdin="hello\n")
    assert res == "3 0 5\n"


def test_toupper_tolower():
    """Case conversion of mixed-case strings."""
    res = out('BEGIN { print toupper("MixEd"), tolower("MixEd") }')
    assert res == "MIXED mixed\n"


def test_split_with_separator_and_default():
    """split returns the count and fills the array; 3-arg uses given FS, 2-arg uses FS."""
    res = out('BEGIN { n=split("a:b:c",arr,":"); print n, arr[1], arr[3] }')
    assert res == "3 a c\n"
    res2 = out('BEGIN { FS=","; n=split("x,y,z",a); print n, a[2] }')
    assert res2 == "3 y\n"


def test_sub_returns_count_and_modifies_target():
    """sub replaces the first match in the target (default $0) and returns # replacements."""
    res = out('{ n=sub(/o/,"0"); print n, $0 }', stdin="foo boo\n")
    assert res == "1 f0o boo\n"


def test_gsub_global_and_ampersand_replacement():
    """gsub replaces all matches; & in the replacement inserts the matched text."""
    res = out('{ n=gsub(/o/,"[&]"); print n, $0 }', stdin="foo\n")
    assert res == "2 f[o][o]\n"


def test_match_sets_rstart_and_rlength():
    """match returns start (0 if none) and sets RSTART/RLENGTH (-1 length when not found)."""
    res = out('{ if (match($0,/l+/)) print RSTART, RLENGTH; else print "no" }', stdin="hello\nxyz\n")
    assert res == "3 2\nno\n"


def test_dynamic_regex_from_variable():
    """A string value used in a match context is compiled as a regular expression."""
    res = out('{ if ($0 ~ pat) print }', stdin="cat\ndog\ncot\n", pre=("-v", "pat=c.t"))
    assert res == "cat\ncot\n"


# --------------------------------------------------------------------------------------
# printf / sprintf
# --------------------------------------------------------------------------------------

def test_printf_numeric_format_specifiers():
    """%d truncates, %o/%x/%X are bases, with width and zero-padding flags."""
    res = out('BEGIN { printf "%d|%5d|%-5d|%05d|%o|%x|%X\\n", 3.9, 42, 42, 42, 8, 255, 255 }')
    assert res == "3|   42|42   |00042|10|ff|FF\n"


def test_printf_float_and_string_and_char():
    """%f/%e/%g formatting, %s with precision, and %c with a code point vs a string."""
    res = out('BEGIN { printf "%.2f %e %g [%3.2s] %c %c\\n", 3.14159, 12345.0, 0.0001, "hello", 65, "XYZ" }')
    assert res == "3.14 1.234500e+04 0.0001 [ he] A X\n"


def test_printf_star_width_and_percent_literal():
    """A * argument supplies the field width dynamically; %% prints a literal percent."""
    res = out('BEGIN { printf "%*d%%\\n", 6, 42 }')
    assert res == "    42%\n"


def test_sprintf_returns_formatted_string():
    """sprintf formats into a string usable in further expressions."""
    res = out('BEGIN { s = sprintf("[%03d]", 7); print s, length(s) }')
    assert res == "[007] 5\n"


# --------------------------------------------------------------------------------------
# Control flow
# --------------------------------------------------------------------------------------

def test_for_while_do_loops():
    """C-style for, while, and do-while all produce the expected accumulations."""
    res = out('BEGIN { for(i=1;i<=3;i++) s=s i; w=0; while(w<3){t=t"x"; w++}; d=0; do{u=u"y"}while(++d<2); print s, t, u }')
    assert res == "123 xxx yy\n"


def test_break_and_continue():
    """break exits a loop; continue skips to the next iteration."""
    res = out('BEGIN { for(i=1;i<=6;i++){ if(i==4)break; if(i%2==0)continue; printf "%d",i }; print "" }')
    assert res == "13\n"


def test_if_else_chain_on_records():
    """if/else if/else classifies each record."""
    res = out('{ if ($1>0) print "pos"; else if ($1<0) print "neg"; else print "zero" }', stdin="5\n-3\n0\n")
    assert res == "pos\nneg\nzero\n"


def test_next_skips_remaining_rules():
    """next stops processing the current record against later rules."""
    res = out('/skip/ { next } { print }', stdin="keep1\nskip this\nkeep2\n")
    assert res == "keep1\nkeep2\n"


def test_exit_runs_end_and_sets_status():
    """exit jumps to END and sets the process exit status."""
    so, se, rc = goawk(['{ if ($1=="stop") exit 3; print } END { print "done" }'], stdin="a\nstop\nb\n")
    assert so == "a\ndone\n"
    assert rc == 3


# --------------------------------------------------------------------------------------
# Arrays
# --------------------------------------------------------------------------------------

def test_associative_array_in_and_delete():
    """The in operator tests membership; delete removes a single key."""
    res = out('BEGIN { a["x"]=1; a["y"]=2; delete a["x"]; print ("x" in a), ("y" in a), a["y"] }')
    assert res == "0 1 2\n"


def test_array_counting_words():
    """A realistic word-frequency tally using an associative array."""
    res = out('{ for(i=1;i<=NF;i++) c[$i]++ } END { print c["a"], c["b"], c["c"] }', stdin="a b a\nc a b\n")
    assert res == "3 2 1\n"


def test_multidimensional_array_with_subsep():
    """Multi-subscript arrays join keys with SUBSEP and support (i,j) in arr."""
    res = out('BEGIN { m[1,2]=7; m[3,4]=9; print m[1,2], ((3,4) in m), ((5,6) in m) }')
    assert res == "7 1 0\n"


def test_delete_entire_array():
    """delete arr removes every element."""
    res = out('BEGIN { a[1]=1;a[2]=2;a[3]=3; delete a; n=0; for(k in a)n++; print n, (1 in a) }')
    assert res == "0 0\n"


# --------------------------------------------------------------------------------------
# User-defined functions
# --------------------------------------------------------------------------------------

def test_recursive_function():
    """User functions support recursion and return values."""
    res = out('function fact(n){ return n<=1 ? 1 : n*fact(n-1) } BEGIN { print fact(5) }')
    assert res == "120\n"


def test_array_parameter_passed_by_reference():
    """Array parameters are passed by reference; scalars by value."""
    res = out('function fill(a){ a["k"]="v" } function bump(x){ x++; return x } BEGIN { fill(arr); print arr["k"]; n=5; print bump(n), n }')
    assert res == "v\n6 5\n"


def test_local_variables_via_extra_params():
    """Extra function parameters act as locals and do not leak to globals."""
    res = out('function f(  i,s){ for(i=1;i<=3;i++) s=s i; return s } BEGIN { print f(); print "i=" i }')
    assert res == "123\ni=\n"


# --------------------------------------------------------------------------------------
# getline forms
# --------------------------------------------------------------------------------------

def test_getline_command_into_variable():
    """cmd | getline var captures a command's output and returns 1 on success."""
    res = out('BEGIN { r = ("echo hello" | getline x); print r, x }')
    assert res == "1 hello\n"


def test_getline_loop_over_command_output():
    """Looping cmd | getline reads successive lines until it returns 0 at EOF."""
    res = out('BEGIN { while (("printf \'a\\nb\\nc\\n\'" | getline line) > 0) n++; print n }')
    assert res == "3\n"


def test_getline_plain_advances_record():
    """Bare getline reads the next record, advancing NR and updating fields."""
    res = out('NR==1 { getline; print "after:", $0, NR }', stdin="first\nsecond\nthird\n")
    assert res == "after: second 2\n"


# --------------------------------------------------------------------------------------
# Output redirection and pipes
# --------------------------------------------------------------------------------------

def test_print_redirect_to_file_and_read_back(tmp_path):
    """print > file writes to a file; a later getline reads it back."""
    f = tmp_path / "data.txt"
    prog = 'BEGIN { print "line1" > F; print "line2" > F; close(F); while ((getline l < F) > 0) print "got:", l }'
    res = out(prog, pre=("-v", f"F={f}"))
    assert res == "got: line1\ngot: line2\n"


def test_print_append_to_file(tmp_path):
    """>> appends to an existing file rather than truncating it."""
    f = tmp_path / "log.txt"
    out('BEGIN { print "a" > F; close(F) }', pre=("-v", f"F={f}"))
    res = out('BEGIN { print "b" >> F; close(F); while ((getline x < F) > 0) print x }', pre=("-v", f"F={f}"))
    assert res == "a\nb\n"


def test_print_pipe_to_command():
    """print | cmd pipes output through an external command (sort)."""
    res = out('BEGIN { print "banana" | "sort"; print "apple" | "sort"; print "cherry" | "sort" }')
    assert res == "apple\nbanana\ncherry\n"


# --------------------------------------------------------------------------------------
# Multiple files, FILENAME, FNR
# --------------------------------------------------------------------------------------

def test_filename_fnr_nr_across_files(tmp_path):
    """FILENAME, FNR (per-file) and NR (global) track multi-file input correctly."""
    f1 = tmp_path / "g1"
    f2 = tmp_path / "g2"
    f1.write_text("one\ntwo\n")
    f2.write_text("three\n")
    res = out('{ print FILENAME, FNR, NR, $0 }', files=(str(f1), str(f2)))
    assert res == f"{f1} 1 1 one\n{f1} 2 2 two\n{f2} 1 3 three\n"


def test_nextfile_skips_rest_of_current_file(tmp_path):
    """nextfile abandons the current file and moves to the next one."""
    f1 = tmp_path / "a"
    f2 = tmp_path / "b"
    f1.write_text("x1\nx2\nx3\n")
    f2.write_text("y1\ny2\n")
    res = out('FNR==1 { print $0 } FNR==1 { nextfile }', files=(str(f1), str(f2)))
    assert res == "x1\ny1\n"


def test_command_line_var_assignment_between_files(tmp_path):
    """A var=value argument between files takes effect when reached in the argument list."""
    f1 = tmp_path / "f1"
    f2 = tmp_path / "f2"
    f1.write_text("1\n")
    f2.write_text("2\n")
    res = out('{ print v, $0 }', files=(str(f1), "v=set", str(f2)))
    assert res == f" 1\nset 2\n"


# --------------------------------------------------------------------------------------
# BEGIN/END and patterns
# --------------------------------------------------------------------------------------

def test_begin_end_and_accumulation():
    """BEGIN runs before input, END after; state accumulates across records."""
    res = out('BEGIN { print "start" } { sum += $1 } END { print "sum", sum }', stdin="10\n20\n30\n")
    assert res == "start\nsum 60\n"


def test_range_pattern():
    """A /start/,/end/ range pattern selects an inclusive span of records."""
    res = out('/begin/,/end/', stdin="skip\nbegin\nmid\nend\nafter\n")
    assert res == "begin\nmid\nend\n"


def test_only_begin_does_not_read_input():
    """A program with only a BEGIN block never blocks on or consumes stdin."""
    res = out('BEGIN { print "hi" }', stdin="should be ignored\n")
    assert res == "hi\n"


# --------------------------------------------------------------------------------------
# Escapes, -v, and command-line behavior
# --------------------------------------------------------------------------------------

def test_v_assignment_processes_escapes():
    """-v values undergo escape processing (\\t becomes a tab)."""
    res = out('BEGIN { printf "%s", X }', pre=("-v", "X=a\\tb"))
    assert res == "a\tb"


def test_format_string_escapes():
    """Escape sequences in a printf format string are interpreted."""
    res = out('BEGIN { printf "a\\tb\\nc\\n" }')
    assert res == "a\tb\nc\n"


def test_environ_special_array():
    """ENVIRON exposes the process environment to the program."""
    env = dict(os.environ)
    env["GOAWK_TASK_VAR"] = "present"
    res = out('BEGIN { print ENVIRON["GOAWK_TASK_VAR"] }', env=env)
    assert res == "present\n"


# --------------------------------------------------------------------------------------
# Errors and exit codes
# --------------------------------------------------------------------------------------

def test_division_by_zero_errors():
    """Dividing by zero is a runtime error with a nonzero exit and message."""
    so, se, rc = goawk(['BEGIN { print 1/0 }'])
    assert rc != 0
    assert "division by zero" in se


def test_missing_input_file_errors():
    """Referencing a nonexistent input file fails: nonzero exit, no stdout, and a stderr
    diagnostic that names the offending file."""
    so, se, rc = goawk(['{ print }', "/no/such/file_xyz"])
    assert rc != 0
    assert so == ""
    assert "file_xyz" in se


def test_undefined_flag_errors():
    """An unknown command-line flag is rejected with a nonzero exit and a diagnostic."""
    so, se, rc = goawk(['-z', 'BEGIN {}'])
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_parse_error_reports_location():
    """A syntax error exits nonzero with a stderr diagnostic naming the offending line (2)."""
    so, se, rc = goawk(['BEGIN {\n\tx*;\n}'])
    assert rc != 0
    assert so == "" and "2" in se


# --------------------------------------------------------------------------------------
# CSV / TSV input mode (GoAWK extension)
# --------------------------------------------------------------------------------------

def test_csv_input_handles_quotes_and_embedded_commas():
    """-i csv parses RFC 4180 quoting: embedded commas/quotes stay within one field."""
    data = 'a,"b,c","she said ""hi"""\n'
    res = out('{ print NF; print $2; print $3 }', stdin=data, pre=("-i", "csv"))
    assert res == '3\nb,c\nshe said "hi"\n'


def test_csv_input_embedded_newline_in_quoted_field():
    """A quoted field may span multiple physical lines as a single record/field."""
    data = '1,"line one\nline two",3\n'
    res = out('{ print NR, NF; print $2 }', stdin=data, pre=("-i", "csv"))
    assert res == "1 3\nline one\nline two\n"


def test_csv_named_fields_with_header():
    """-i csv -H parses the header and enables @\"name\" field access."""
    data = "name,age\nBob,42\nJane,37\n"
    res = out('{ print @"age", @"name" }', stdin=data, pre=("-i", "csv", "-H"))
    assert res == "42 Bob\n37 Jane\n"


def test_csv_fields_array_and_dynamic_named_access():
    """The FIELDS array maps position to name; @() accepts a dynamic name expression."""
    data = "id,name,email\n1,Bob,b@bob.com\n"
    res = out('{ for(i=1;i in FIELDS;i++) printf "%d:%s ", i, FIELDS[i]; print ""; print @("nam" "e") }',
              stdin=data, pre=("-i", "csv", "-H"))
    assert res == "1:id 2:name 3:email \nBob\n"


def test_csv_split_two_arg_uses_csv_rules():
    """In CSV input mode, 2-arg split() uses CSV field splitting."""
    res = out('BEGIN { n=split("x,\\"y,z\\"",a); print n, a[1], a[2] }', pre=("-i", "csv"))
    assert res == "2 x y,z\n"


def test_tsv_input_mode():
    """-i tsv parses tab-separated values."""
    res = out('{ print $1, $3 }', stdin="a\tb\tc\n", pre=("-i", "tsv"))
    assert res == "a c\n"


def test_csv_input_comment_and_separator_options():
    """Mode options configure a custom separator and a comment character to skip."""
    data = "# header comment\nAlabama|AL\nAlaska|AK\n"
    res = out('{ print $2, $1 }', stdin=data, pre=("-i", "csv separator=| comment=#"))
    assert res == "AL Alabama\nAK Alaska\n"


# --------------------------------------------------------------------------------------
# CSV / TSV output mode (GoAWK extension)
# --------------------------------------------------------------------------------------

def test_csv_output_quotes_when_needed():
    """-o csv quotes fields containing the separator, quotes, or newlines; doubles inner quotes."""
    res = out('BEGIN { print "plain", "has,comma", "has\\"quote" }', pre=("-o", "csv"))
    assert res == 'plain,"has,comma","has""quote"\n'


def test_csv_output_with_field_reassign_reformats_record():
    """$1=$1 reformats $0 to the output format; bare print emits it (csv -> tsv conversion)."""
    res = out('{ $1=$1; print }', stdin='Alabama,AL\nAlaska,AK\n', pre=("-i", "csv", "-o", "tsv"))
    assert res == "Alabama\tAL\nAlaska\tAK\n"


def test_tsv_output_separator_override():
    """-o 'csv separator=|' overrides the output separator character."""
    res = out('BEGIN { print "a", "b", "c" }', pre=("-o", "csv separator=|"))
    assert res == "a|b|c\n"


# --------------------------------------------------------------------------------------
# Unicode (chars) mode
# --------------------------------------------------------------------------------------

def test_chars_mode_length_and_printf_c():
    """-c makes length operate on Unicode characters rather than bytes."""
    res = out('{ print length($0) }', stdin="絵\n", pre=("-c",))
    assert res == "1\n"


def test_default_byte_mode_length():
    """Without -c, length counts bytes for multi-byte UTF-8 input."""
    res = out('{ print length($0) }', stdin="絵\n")
    assert res == "3\n"


# --------------------------------------------------------------------------------------
# Harder corners: field lvalues, gsub escaping, CONVFMT subscripts, regex split
# --------------------------------------------------------------------------------------

def test_field_increment_rebuilds_record():
    """A field is an lvalue: ++ on $1 updates it and rebuilds $0 with OFS."""
    res = out('{ $1++; print $0, $1 }', stdin="5 9\n")
    assert res == "6 9 6\n"


def test_gsub_literal_ampersand_escape():
    r"""In a gsub replacement, \& inserts a literal & rather than the matched text."""
    res = out(r'BEGIN { s="ab"; gsub(/b/, "[\\&]", s); print s }')
    assert res == "a[&]\n"


def test_convfmt_applies_to_array_subscript():
    """A non-integer numeric array subscript is converted to a string via CONVFMT."""
    res = out('BEGIN { CONVFMT="%.2f"; x=3.14159; a[x]=1; for (k in a) print k }')
    assert res == "3.14\n"


def test_split_with_regex_separator():
    """split's separator may be a regex (here matching runs of digits)."""
    res = out('BEGIN { n=split("a1b22c", arr, /[0-9]+/); print n, arr[1], arr[2], arr[3] }')
    assert res == "3 a b c\n"


def test_chars_mode_substr_and_index():
    """-c also makes substr and index operate on Unicode characters."""
    res = out('BEGIN { s="絵文字"; print substr(s,2,1), index(s,"字") }', pre=("-c",))
    assert res == "文 3\n"


# --------------------------------------------------------------------------------------
# Math built-ins, system(), and the PRNG
# --------------------------------------------------------------------------------------

def test_math_builtins():
    """int truncates toward zero; sqrt/exp/log/sin/cos/atan2 compute the standard values."""
    res = out('BEGIN { printf "%d %d %.4f %.4f %.4f %.4f %.4f %.5f\\n", '
              'int(3.9), int(-3.9), sqrt(2), exp(1), log(exp(1)), sin(0), cos(0), atan2(1,1) }')
    assert res == "3 -3 1.4142 2.7183 1.0000 0.0000 1.0000 0.78540\n"


def test_system_runs_command_and_returns_status():
    """system() flushes pending output, runs a shell command, and returns its exit status."""
    res = out('BEGIN { print "before"; r = system("exit 7"); print "after", r }')
    assert res == "before\nafter 7\n"


def test_rand_is_reproducible_with_srand_seed():
    """rand() yields values in [0,1); re-seeding with the same srand() value reproduces the sequence."""
    res = out('BEGIN { srand(1); a=rand(); srand(1); b=rand(); print (a==b), (a>=0 && a<1) }')
    assert res == "1 1\n"


# --------------------------------------------------------------------------------------
# Compound assignment operators
# --------------------------------------------------------------------------------------

def test_compound_assignment_operators():
    """The compound assignment operators += -= *= /= %= update in place."""
    res = out('BEGIN { x=10; x+=5; x-=3; x*=2; x/=4; x%=5; print x }')
    assert res == "1\n"


# --------------------------------------------------------------------------------------
# Subtle POSIX semantics (standard AWK, but commonly implemented incorrectly)
# --------------------------------------------------------------------------------------

def test_ofmt_and_convfmt_are_distinct():
    """print uses OFMT to format a number; string conversion (concatenation) uses CONVFMT."""
    res = out('BEGIN { OFMT="%.2f"; CONVFMT="%.4f"; x=3.14159; print x; print (x "") }')
    assert res == "3.14\n3.1416\n"


def test_array_reference_autovivifies_key():
    """Merely referencing arr[key] creates that key (it becomes a member afterward)."""
    res = out('BEGIN { junk = a["x"]; print ("x" in a) }')
    assert res == "1\n"


def test_concatenation_binds_tighter_than_comparison():
    """String concatenation has higher precedence than comparison, so `1 " " 2 == "1 2"` is true."""
    res = out('BEGIN { print 1 " " 2 == "1 2" }')
    assert res == "1\n"


def test_split_of_empty_string_returns_zero():
    """Splitting an empty string yields zero fields."""
    res = out('BEGIN { print split("", a, ",") }')
    assert res == "0\n"


def test_bare_length_is_length_of_record():
    """length used with no parentheses and no argument is length($0)."""
    res = out('{ print length }', stdin="hello\n")
    assert res == "5\n"


# --------------------------------------------------------------------------------------
# Self-contained interpreter
# --------------------------------------------------------------------------------------

def test_interprets_without_an_external_awk_on_path(tmp_path):
    """The binary interprets on its own: it still works when every awk on PATH is unusable."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    for name in ("awk", "gawk", "mawk", "nawk", "busybox"):
        stub = stub_dir / name
        stub.write_text("#!/bin/sh\nexit 127\n")
        stub.chmod(0o755)
    env = {"PATH": str(stub_dir), "HOME": str(tmp_path)}
    res = out('function tot(a,   k, s) { for (k in a) s += a[k]; return s }\n'
              '$2 ~ /^[0-9]+$/ { n[$1] += $2 }\n'
              'END { printf "%s=%d %d\\n", "b", n["b"], tot(n) }',
              stdin="a 1\nb 2\na x\nb 40\n", env=env)
    assert res == "b=42 43\n"
