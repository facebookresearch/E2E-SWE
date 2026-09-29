"""Hidden grading suite for the tengo task.

Drives the compiled `tengo` CLI (built by setup.sh at /app/tengo) entirely through subprocess: a
tengo source file is passed as argv[1], the interpreter runs it, and we assert on its stdout /
stderr / exit code. Each test models a distinct language behavior with EXACT expected values so the
pass fraction tracks real implementation completeness.

Scripts produce output only via the `fmt` stdlib module (print/println/printf). Most tests use
`fmt.printf` with explicit verbs so the expected stdout is fully determined. NB: tengo's
print/println join the string form of their arguments with NO separator (println only appends a
trailing newline) -- see test_print_no_separator.

Map key iteration order is non-deterministic (Go map), so map behavior is asserted via specific-key
access or single-key maps only, never multi-key string/JSON output.

Set BIN_ENV to point at the binary (defaults to /app/tengo). Local iteration:
    BIN_ENV=/tmp/tengo-gt pytest tests/test_tengo.py -q
"""

import os
import subprocess
import tempfile

BIN = os.environ.get("BIN_ENV", "/app/tengo")


def run_src(src, cwd=None):
    """Write `src` to a .tengo file and run it; return (stdout, stderr, returncode)."""
    d = cwd or tempfile.gettempdir()
    fd, path = tempfile.mkstemp(suffix=".tengo", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(src)
        proc = subprocess.run(
            [BIN, path], capture_output=True, text=True, timeout=20, cwd=cwd
        )
    finally:
        os.unlink(path)
    return proc.stdout, proc.stderr, proc.returncode


def out(src, cwd=None):
    """Run expecting success; assert exit 0 and return stdout."""
    so, se, rc = run_src(src, cwd=cwd)
    assert rc == 0, f"expected success, got rc={rc}, stderr={se!r}"
    return so


# ----------------------------------------------------------------------------- arithmetic / numbers

def test_integer_arithmetic():
    """+ - * / % on integers, with integer division truncating toward zero."""
    assert out('f:=import("fmt");f.printf("%d %d %d %d %d",7+3,7-3,7*3,7/3,7%3)') == "10 4 21 2 1"


def test_integer_division_truncates_toward_zero():
    """Integer / truncates toward zero for negative operands (not floor)."""
    assert out('f:=import("fmt");f.printf("%d %d %d",5/2,-7/2,7/-2)') == "2 -3 -3"


def test_float_arithmetic():
    """Arithmetic on floats yields floats; whole-valued floats print without a decimal under %v."""
    assert out('f:=import("fmt");f.printf("%v %v %v",1.5+2,3.0/2,2.0*3)') == "3.5 1.5 6"


def test_mixed_int_float_promotion():
    """An int combined with a float promotes the result to float."""
    assert out('f:=import("fmt");f.printf("%v %v",1+2.0,5/2.0)') == "3 2.5"


def test_operator_precedence():
    """Multiplication binds tighter than addition; parentheses override."""
    assert out('f:=import("fmt");f.printf("%d %d",2+3*4-1,(2+3)*4)') == "13 20"


def test_bitwise_operators():
    """& | ^ &^ << >> on integers."""
    assert out('f:=import("fmt");f.printf("%d %d %d %d %d %d",6&3,6|3,6^3,6&^3,1<<4,256>>2)') \
        == "2 7 5 4 16 64"


def test_unary_operators():
    """Unary minus, bitwise complement ^, and logical NOT !."""
    assert out('f:=import("fmt");f.printf("%d %d %v",-5,^0,!true)') == "-5 -1 false"


# ------------------------------------------------------------------ comparison / logical / ternary

def test_comparison_operators():
    """Ordering comparisons on ints and lexicographic ordering on strings."""
    assert out('f:=import("fmt");f.printf("%v %v %v %v",3<5,5<=5,"a"<"b",3>5)') \
        == "true true true false"


def test_logical_and_short_circuits():
    """&& does not evaluate its right operand when the left is falsy."""
    src = 'f:=import("fmt");c:=0;g:=func(){c=c+1;return true};r:=false&&g();f.printf("%v %d",r,c)'
    assert out(src) == "false 0"


def test_logical_or_short_circuits():
    """|| does not evaluate its right operand when the left is truthy."""
    src = 'f:=import("fmt");c:=0;g:=func(){c=c+1;return false};r:=true||g();f.printf("%v %d",r,c)'
    assert out(src) == "true 0"


def test_ternary_operator():
    """The ?: conditional expression selects the branch by the condition's truthiness."""
    assert out('f:=import("fmt");f.printf("%s %s",5>3?"y":"n",0?"y":"n")') == "y n"


def test_truthiness_rules():
    """0, "", empty array, empty map, and undefined are falsy; non-empty values are truthy."""
    src = 'f:=import("fmt");f.printf("%v %v %v %v %v %v",!0,!"",![],!{},!undefined,!"x")'
    assert out(src) == "true true true true true false"


# ----------------------------------------------------------------------------- strings and chars

def test_string_concatenation():
    """+ concatenates strings."""
    assert out('f:=import("fmt");f.printf("%s","foo"+"bar")') == "foobar"


def test_string_index_yields_char():
    """Indexing a string yields a char (its rune code point), convertible back to a string."""
    assert out('f:=import("fmt");s:="hello";f.printf("%d %s",int(s[1]),string(s[1]))') == "101 e"


def test_string_slicing():
    """The [lo:hi] slice operator returns the substring over the half-open range."""
    assert out('f:=import("fmt");f.printf("%s","hello world"[2:7])') == "llo w"


def test_string_is_immutable():
    """Index-assigning into a string is a runtime error with a stderr diagnostic and no stdout."""
    so, se, rc = run_src('s:="abc";s[0]=char(88)')
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_char_conversions_and_arithmetic():
    """char(int) makes a rune; char arithmetic shifts the code point; int(char) reads it."""
    assert out('f:=import("fmt");c:=char(65);f.printf("%s %d",string(c),int(c+1))') == "A 66"


# ----------------------------------------------------------------------------------------- arrays

def test_array_index_and_mutation():
    """Arrays are mutable and may hold mixed types; element assignment updates in place."""
    assert out('f:=import("fmt");a:=[1,2,3];a[1]="X";f.printf("%v",a)') == '[1, "X", 3]'


def test_array_out_of_range_index_is_undefined():
    """Indexing past the end of an array returns undefined rather than erroring."""
    assert out('f:=import("fmt");f.printf("%v",[1,2,3][10])') == "<undefined>"


def test_array_slicing_clamps_bounds():
    """Slice bounds outside the array are clamped to its extent."""
    assert out('f:=import("fmt");f.printf("%v",[1,2,3,4,5][-1:10])') == "[1, 2, 3, 4, 5]"


def test_array_concatenation():
    """+ concatenates two arrays into a new array."""
    assert out('f:=import("fmt");f.printf("%v",[1,2]+[3,4])') == "[1, 2, 3, 4]"


def test_append_builtin():
    """append adds elements; the ... spread appends each element of an array argument."""
    src = 'f:=import("fmt");f.printf("%v %v",append([1,2],3,4),append([1,2],[3,4]...))'
    assert out(src) == "[1, 2, 3, 4] [1, 2, 3, 4]"


def test_splice_builtin():
    """splice removes a count of elements at an index, inserts replacements, returns the removed."""
    src = 'f:=import("fmt");a:=[1,2,3,4,5];r:=splice(a,1,2,"x");f.printf("%v %v",a,r)'
    assert out(src) == '[1, "x", 4, 5] [2, 3]'


# ------------------------------------------------------------------------------------------- maps

def test_map_selector_and_indexer_access():
    """Map values are reachable via both .key selector and ["key"] indexer."""
    assert out('f:=import("fmt");m:={a:1,b:2};f.printf("%d %d",m.a,m["b"])') == "1 2"


def test_map_missing_key_is_undefined():
    """Accessing an absent map key returns undefined."""
    assert out('f:=import("fmt");m:={a:1};f.printf("%v",m.b)') == "<undefined>"


def test_map_add_key():
    """Assigning to a new selector adds a key to a mutable map."""
    assert out('f:=import("fmt");m:={a:1};m.b=2;f.printf("%d",m.b)') == "2"


def test_delete_builtin():
    """delete removes a key from a map; the deleted key reads as undefined and len drops."""
    src = 'f:=import("fmt");m:={a:1,b:2};delete(m,"a");f.printf("%v %d %d",m.a,m.b,len(m))'
    assert out(src) == "<undefined> 2 1"


def test_nested_data_access():
    """Selectors and indexers chain through nested arrays and maps."""
    assert out('f:=import("fmt");d:={a:[1,{b:9}]};f.printf("%d",d.a[1].b)') == "9"


def test_nil_safe_selector_chain():
    """Selecting through a missing key yields undefined rather than erroring."""
    assert out('f:=import("fmt");m:={};f.printf("%v",m.x.y.z)') == "<undefined>"


# ---------------------------------------------------------------- conversions / type predicates

def test_type_conversions():
    """string/int/float/bool/char builtins convert between value types."""
    src = 'f:=import("fmt");f.printf("%s %d %v %v %s",string(1984),int("-999"),float(-51),bool(1),string(3.5))'
    assert out(src) == "1984 -999 -51 true 3.5"


def test_conversion_failure_returns_undefined():
    """A failed conversion with no default returns undefined; a provided default is used instead."""
    assert out('f:=import("fmt");f.printf("%v %d",int("foo"),int("foo",42))') == "<undefined> 42"


def test_type_name_builtin():
    """type_name reports the value's type as a string."""
    src = 'f:=import("fmt");f.printf("%s %s %s %s %s",type_name(1),type_name(1.0),type_name("a"),type_name([1]),type_name({}))'
    assert out(src) == "int float string array map"


def test_type_predicate_builtins():
    """is_int / is_string / is_array / is_undefined / is_callable classify values."""
    src = ('f:=import("fmt");f.printf("%v %v %v %v %v",'
           'is_int(1),is_string(1),is_array([1]),is_undefined(undefined),is_callable(func(){}))')
    assert out(src) == "true false true true true"


def test_len_builtin():
    """len measures strings (bytes), arrays (elements), and maps (keys)."""
    assert out('f:=import("fmt");f.printf("%d %d %d",len("abc"),len([1,2]),len({a:1,b:2,c:3}))') \
        == "3 2 3"


def test_range_builtin():
    """range(start,stop[,step]) builds an array of ints over the half-open interval."""
    assert out('f:=import("fmt");f.printf("%v %v",range(0,5),range(0,10,2))') \
        == "[0, 1, 2, 3, 4] [0, 2, 4, 6, 8]"


def test_format_builtin():
    """format applies Go-style verbs and returns the string (sprintf without printing)."""
    assert out('f:=import("fmt");f.printf("%s",format("%d-%05.2f",7,3.14159))') == "7-03.14"


def test_print_no_separator():
    """print/println join argument string forms with no separator; println appends one newline."""
    assert out('f:=import("fmt");f.println(1,2,3)') == "123\n"


# --------------------------------------------------------------------------------- control flow

def test_if_elif_else():
    """if / else if / else selects exactly one branch."""
    assert out('f:=import("fmt");a:=0;if a<0{f.print("neg")}else if a==0{f.print("zero")}else{f.print("pos")}') \
        == "zero"


def test_if_init_statement():
    """An if condition may be preceded by a simple init statement scoped to the if."""
    assert out('f:=import("fmt");if x:=10;x>5{f.print("big")}') == "big"


def test_for_cstyle_loop():
    """The C-style for(init;cond;post) loop accumulates as expected."""
    assert out('f:=import("fmt");s:=0;for i:=0;i<5;i++{s+=i};f.printf("%d",s)') == "10"


def test_for_condition_only_loop():
    """A for loop with only a condition runs until the condition is false."""
    assert out('f:=import("fmt");i:=0;for i<3{i++};f.printf("%d",i)') == "3"


def test_for_break_and_continue():
    """break exits the loop; continue skips to the next iteration."""
    src = 'f:=import("fmt");s:=0;for i:=0;i<10;i++{if i==2{continue};if i==5{break};s+=i};f.printf("%d",s)'
    assert out(src) == "8"


def test_for_in_array_index_value():
    """for index, value in array iterates positions and elements."""
    src = 'f:=import("fmt");r:=[];for i,v in [5,6,7]{r=append(r,i*v)};f.printf("%v",r)'
    assert out(src) == "[0, 6, 14]"


def test_for_in_string_iterates_chars():
    """for-in over a string yields its chars; collected and re-stringified they reproduce it."""
    src = 'f:=import("fmt");s:="";for _,c in "abc"{s+=string(c)};f.printf("%s",s)'
    assert out(src) == "abc"


def test_for_in_single_key_map():
    """for key, value in a single-key map binds the key and value."""
    assert out('f:=import("fmt");for k,v in {x:7}{f.printf("%s=%d",k,v)}') == "x=7"


# ------------------------------------------------------------------------------------- functions

def test_closure_captures_variable():
    """A returned function closes over an outer variable."""
    assert out('f:=import("fmt");adder:=func(b){return func(x){return b+x}};f.printf("%d",adder(5)(4))') \
        == "9"


def test_recursion():
    """A function may call itself recursively."""
    assert out('f:=import("fmt");fact:=func(n){return n<=1?1:n*fact(n-1)};f.printf("%d",fact(5))') \
        == "120"


def test_variadic_function():
    """A trailing ...param collects extra arguments into an array."""
    assert out('f:=import("fmt");g:=func(a,b,...c){return [a,b,c]};f.printf("%v",g(1,2,3,4))') \
        == "[1, 2, [3, 4]]"


def test_argument_spread_in_call():
    """An array argument followed by ... is spread into positional parameters."""
    assert out('f:=import("fmt");g:=func(a,b,c){return a+b+c};f.printf("%d",g([1,2,3]...))') == "6"


def test_function_without_return_yields_undefined():
    """A function with no explicit return evaluates to undefined."""
    assert out('f:=import("fmt");g:=func(){x:=1};f.printf("%v",g())') == "<undefined>"


def test_wrong_argument_count_is_error():
    """Calling a function with the wrong number of arguments is a runtime error."""
    so, se, rc = run_src('g:=func(a,b){return a};g(1,2,3)')
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_variable_shadowing():
    """A := inside a function defines a new local that shadows an outer variable."""
    assert out('f:=import("fmt");a:=1;func(){a:=2;f.printf("%d",a)}();f.printf("%d",a)') == "21"


def test_tuple_assignment_is_rejected():
    """Tengo has no tuple assignment; `a, b = b, a` is a compile error."""
    so, se, rc = run_src('a:=1;b:=2;a,b=b,a')
    assert rc != 0
    assert so == "" and se.strip() != ""


# -------------------------------------------------------------------------- errors / immutability

def test_error_value():
    """error(x) makes an error value whose .value is x and which is_error reports true."""
    assert out('f:=import("fmt");e:=error("oops");f.printf("%v %s",is_error(e),e.value)') \
        == "true oops"


def test_immutable_array_assignment_is_error():
    """Index-assigning into an immutable array is a runtime error."""
    so, se, rc = run_src('b:=immutable([1,2,3]);b[0]=9')
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_immutable_predicate():
    """immutable() produces an immutable container that is_immutable_array recognizes."""
    assert out('f:=import("fmt");f.printf("%v",is_immutable_array(immutable([1,2])))') == "true"


def test_invalid_index_type_is_error():
    """Indexing an array with a non-int key is a runtime error."""
    so, se, rc = run_src('x:=[1,2,3];y:=x["k"]')
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_parse_error_exit_code():
    """Syntactically invalid source fails to run with a nonzero exit and a stderr diagnostic."""
    so, se, rc = run_src('a := = 5')
    assert rc != 0
    assert so == "" and se.strip() != ""


# ----------------------------------------------------------------------------- modules (import)

def test_local_module_import_function():
    """import("./mod") loads a sibling file and calls its exported function (capturing its state)."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "sum.tengo"), "w") as f:
        f.write("base := 100\nexport func(x) { return x + base }\n")
    src = 'f:=import("fmt");sum:=import("./sum");f.printf("%d",sum(5))'
    assert out(src, cwd=d) == "105"


def test_local_module_export_map():
    """A module may export a map of values and functions accessed by the importer."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "m2.tengo"), "w") as f:
        f.write("export { val: 7, twice: func(x){ return x*2 } }\n")
    src = 'f:=import("fmt");m:=import("./m2");f.printf("%d %d",m.val,m.twice(4))'
    assert out(src, cwd=d) == "7 8"


# ----------------------------------------------------------------------------------- stdlib: math

def test_math_basic_functions():
    """math.abs/ceil/floor/sqrt/pow compute the expected values."""
    src = 'm:=import("math");f:=import("fmt");f.printf("%v %v %v %v %v",m.abs(-19.84),m.ceil(4.2),m.floor(4.8),m.sqrt(16),m.pow(2,10))'
    assert out(src) == "19.84 5 4 4 1024"


def test_math_max_min_mod():
    """math.max/min take two arguments; math.mod is the floating remainder."""
    src = 'm:=import("math");f:=import("fmt");f.printf("%v %v %v",m.max(3,7),m.min(3,7),m.mod(7,3))'
    assert out(src) == "7 3 1"


# ----------------------------------------------------------------------------------- stdlib: text

def test_text_split_and_join():
    """text.split splits on a separator; text.join concatenates with one."""
    src = 't:=import("text");f:=import("fmt");f.printf("%v %s",t.split("a,b,c",","),t.join(["a","b","c"],"-"))'
    assert out(src) == '["a", "b", "c"] a-b-c'


def test_text_case_and_trim():
    """text.to_upper/to_lower change case; text.trim_space strips surrounding whitespace."""
    src = 't:=import("text");f:=import("fmt");f.printf("%s|%s|%s",t.to_upper("abc"),t.to_lower("ABC"),t.trim_space("  hi  "))'
    assert out(src) == "ABC|abc|hi"


def test_text_contains_index_prefix_suffix():
    """text.contains/index/has_prefix/has_suffix query substrings."""
    src = ('t:=import("text");f:=import("fmt");f.printf("%v %d %v %v",'
           't.contains("hello","ell"),t.index("hello","l"),t.has_prefix("foobar","foo"),t.has_suffix("foobar","bar"))')
    assert out(src) == "true 2 true true"


def test_text_replace_repeat_substr():
    """text.replace (with a count), text.repeat, and text.substr transform strings."""
    src = ('t:=import("text");f:=import("fmt");f.printf("%s|%s|%s",'
           't.replace("aaa","a","b",2),t.repeat("ab",3),t.substr("hello",1,4))')
    assert out(src) == "bba|ababab|ell"


def test_text_fields_count_title_pad():
    """text.fields splits on whitespace; count/title/pad_left behave as documented."""
    src = ('t:=import("text");f:=import("fmt");f.printf("%v %d %s %s",'
           't.fields("  a b   c "),t.count("banana","a"),t.title("hi there"),t.pad_left("42",5,"0"))')
    assert out(src) == '["a", "b", "c"] 3 Hi There 00042'


def test_text_regexp():
    """text.re_match tests a pattern; text.re_replace substitutes all matches."""
    src = 't:=import("text");f:=import("fmt");f.printf("%v %s",t.re_match("^[0-9]+$","12345"),t.re_replace("a+","aaabaa","X"))'
    assert out(src) == "true XbX"


def test_text_atoi_itoa_parse_int():
    """text.atoi/itoa convert decimal; text.parse_int reads an arbitrary base."""
    src = 't:=import("text");f:=import("fmt");f.printf("%d %s %d",t.atoi("42"),t.itoa(42),t.parse_int("ff",16,64))'
    assert out(src) == "42 42 255"


# ----------------------------------------------------------------------------------- stdlib: enum

def test_enum_map_and_filter():
    """enum.map transforms each element; enum.filter keeps elements passing a predicate."""
    src = ('e:=import("enum");f:=import("fmt");f.printf("%v %v",'
           'e.map([1,2,3],func(i,v){return v*2}),e.filter([1,2,3,4],func(i,v){return v%2==0}))')
    assert out(src) == "[2, 4, 6] [2, 4]"


def test_enum_each_find_chunk():
    """enum.each visits every element; enum.find returns the first match; enum.chunk groups."""
    src = ('e:=import("enum");f:=import("fmt");s:=0;e.each([1,2,3],func(i,v){s+=v});'
           'f.printf("%d %v %v",s,e.find([1,2,3,4],func(i,v){return v>2}),e.chunk([1,2,3,4,5],2))')
    assert out(src) == "6 3 [[1, 2], [3, 4], [5]]"


# ----------------------------------------------------------------------- stdlib: json / base64 / hex

def test_json_encode_array():
    """json.encode serializes an array deterministically (order preserved)."""
    assert out('j:=import("json");f:=import("fmt");f.printf("%s",j.encode([1,2,[3,4]]))') \
        == "[1,2,[3,4]]"


def test_json_decode_and_access():
    """json.decode parses an object whose fields are then accessed by key."""
    src = 'j:=import("json");f:=import("fmt");d:=j.decode(`{"name":"Bob","age":30}`);f.printf("%s %d",d.name,d.age)'
    assert out(src) == "Bob 30"


def test_json_number_types():
    """json.decode maps whole numbers to int and fractional numbers to float."""
    src = 'j:=import("json");f:=import("fmt");d:=j.decode("[1,2.5]");f.printf("%s %s",type_name(d[0]),type_name(d[1]))'
    assert out(src) == "int float"


def test_base64_roundtrip():
    """base64.encode/decode round-trips bytes."""
    src = 'b:=import("base64");f:=import("fmt");f.printf("%s %s",b.encode(bytes("hi")),string(b.decode("aGk=")))'
    assert out(src) == "aGk= hi"


def test_hex_encode():
    """hex.encode renders bytes as their lowercase hexadecimal string."""
    assert out('h:=import("hex");f:=import("fmt");f.printf("%s",h.encode(bytes("AB")))') == "4142"


# ------------------------------------------------------------------------- harder corners

def test_closure_counter_state():
    """A closure captures its outer variable by reference; mutations persist across calls."""
    src = 'f:=import("fmt");mk:=func(){c:=0;return func(){c++;return c}};n:=mk();f.printf("%d%d%d",n(),n(),n())'
    assert out(src) == "123"


def test_variadic_closure():
    """A returned closure may itself be variadic, collecting trailing args into an array."""
    src = 'f:=import("fmt");g:=func(a){return func(b,...c){return [a,b,c]}};f.printf("%v",g(1)(2,3,4))'
    assert out(src) == "[1, 2, [3, 4]]"


def test_precedence_shift_binds_tighter_than_add():
    """`<<` (level 5) binds tighter than `+` (level 4): 1 + 2<<3 == 1 + (2<<3) == 17."""
    assert out('f:=import("fmt");f.printf("%d",1+2<<3)') == "17"


def test_bytes_index_and_slice():
    """Indexing bytes yields the int byte value; slicing bytes yields a bytes subsequence."""
    assert out('f:=import("fmt");b:=bytes("ABCDE");f.printf("%d %s",b[1],string(b[1:4]))') == "66 BCD"


def test_splice_insert_only():
    """splice with deleteCount 0 inserts the items at the index and returns an empty array."""
    src = 'f:=import("fmt");a:=[1,2,3];r:=splice(a,1,0,"x","y");f.printf("%v %v",a,r)'
    assert out(src) == '[1, "x", "y", 2, 3] []'


def test_splice_delete_only():
    """splice with no replacement items just removes the chosen elements."""
    assert out('f:=import("fmt");a:=[1,2,3,4];r:=splice(a,1,2);f.printf("%v %v",a,r)') \
        == "[1, 4] [2, 3]"


def test_sprintf_format_verbs():
    """sprintf honors Go format verbs: %x %o %b, width %5d, precision %.3f, and %e."""
    src = 'f:=import("fmt");f.printf("%s",f.sprintf("%x|%o|%b|%5d|%.3f|%e",255,8,5,42,1.5,1000.0))'
    assert out(src) == "ff|10|101|   42|1.500|1.000000e+03"


def test_enum_find_none_and_all_any_false():
    """enum.find returns undefined when nothing matches; all/any return false appropriately."""
    src = ('e:=import("enum");f:=import("fmt");f.printf("%v %v %v",'
           'e.find([1,2],func(i,v){return v>9}),'
           'e.all([2,3],func(i,v){return v%2==0}),e.any([1,3],func(i,v){return v%2==0}))')
    assert out(src) == "<undefined> false false"


def test_immutable_map_assignment_is_error():
    """Assigning to a key of an immutable map is a runtime error."""
    so, se, rc = run_src('m:=immutable({a:1});m.a=2')
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_nested_ternary():
    """Ternary expressions chain right-associatively to form multi-way selection."""
    assert out('f:=import("fmt");x:=5;f.printf("%s",x<0?"neg":x==0?"zero":"pos")') == "pos"


def test_string_slice_omitted_bounds():
    """Omitting a slice bound defaults the low bound to 0 and the high bound to the length."""
    assert out('f:=import("fmt");f.printf("%s|%s","hello"[:3],"hello"[2:])') == "hel|llo"


def test_copy_is_deep():
    """copy is deep: mutating a nested element of the copy does not affect the original."""
    src = 'f:=import("fmt");a:=[[1,2],[3,4]];b:=copy(a);b[0][0]=9;f.printf("%v %v",a,b)'
    assert out(src) == "[[1, 2], [3, 4]] [[9, 2], [3, 4]]"


def test_for_in_bytes():
    """for-in over a bytes value yields its int byte values."""
    assert out('f:=import("fmt");s:=0;for _,x in bytes("ABC"){s+=x};f.printf("%d",s)') == "198"


def test_text_trim_cutset_and_prefix():
    """text.trim removes leading/trailing runes in a cutset; text.trim_prefix removes a prefix."""
    src = 't:=import("text");f:=import("fmt");f.printf("%s|%s",t.trim("xxhixx","x"),t.trim_prefix("foobar","foo"))'
    assert out(src) == "hi|bar"


# ------------------------------------------------------------ harder control-flow / functions

def test_nested_for_loops():
    """Nested C-style for loops accumulate over the cross product."""
    src = 'f:=import("fmt");s:=0;for i:=0;i<3;i++{for j:=0;j<3;j++{s+=i*j}};f.printf("%d",s)'
    assert out(src) == "9"


def test_for_in_array_of_maps():
    """for-in over an array of maps binds each map, whose fields are then read."""
    src = 'f:=import("fmt");data:=[{n:1},{n:2},{n:3}];s:=0;for _,m in data{s+=m.n};f.printf("%d",s)'
    assert out(src) == "6"


def test_immediately_invoked_function():
    """A function literal may be called directly at its definition site."""
    assert out('f:=import("fmt");x:=func(a){return a*a}(7);f.printf("%d",x)') == "49"


def test_nested_loop_break_innermost():
    """break exits only the innermost loop, not the outer one."""
    src = 'f:=import("fmt");c:=0;for i:=0;i<3;i++{for j:=0;j<3;j++{if j==1{break};c++}};f.printf("%d",c)'
    assert out(src) == "3"


def test_early_return_from_loop():
    """A return inside a loop exits the whole function immediately."""
    src = 'f:=import("fmt");find:=func(a,x){for i,v in a{if v==x{return i}};return -1};f.printf("%d %d",find([5,6,7],6),find([5,6,7],9))'
    assert out(src) == "1 -1"


def test_continue_in_for_in():
    """continue inside for-in skips to the next element."""
    src = 'f:=import("fmt");s:=0;for _,v in [1,2,3,4,5,6]{if v%2==0{continue};s+=v};f.printf("%d",s)'
    assert out(src) == "9"


def test_array_of_functions():
    """Functions are first-class values: an array can hold them and call them by index."""
    src = 'f:=import("fmt");ops:=[func(x){return x+1},func(x){return x*2}];f.printf("%d %d",ops[0](10),ops[1](10))'
    assert out(src) == "11 20"


def test_higher_order_function():
    """A function can be passed as an argument and invoked inside another function."""
    assert out('f:=import("fmt");apply:=func(fn,x){return fn(x)};f.printf("%d",apply(func(n){return n*n},6))') == "36"


def test_map_built_in_loop():
    """A map populated in a loop reports the expected length and key values."""
    src = 'f:=import("fmt");m:={};for i:=0;i<5;i++{m[string(i)]=i};f.printf("%d %d",len(m),m["3"])'
    assert out(src) == "5 3"
