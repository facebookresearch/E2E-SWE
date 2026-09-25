"""Function and struct tests: parameters, closures, variadics + kwargs,
struct definitions, associated functions."""

from _helpers import run_feral


def test_function_default_and_named_arguments():
    """Function parameters may declare defaults, overridden by positional args.
    Named call-site arguments do NOT bind to declared parameters by name;
    they are collected into the declared keyword-args bundle (`.kw` here),
    from which the callee reads them out. This is Feral's dual-parameter
    design: positional slots and a single kwargs map, side-by-side."""
    src = """
let io = import('std/io');
let greet = fn(name, greeting = 'Hello', .kw) {
    let punct = kw['punctuation'] ?? '.';
    return greeting + ', ' + name + punct;
};
io.println(greet('world'));                       # both defaults used
io.println(greet('there', 'Hi'));                 # positional greeting override
io.println(greet('you', punctuation = '!'));      # punct read out of kw bundle
io.println(greet('all', 'Hey', punctuation = '?'));
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ("Hello, world.\n" "Hi, there.\n" "Hello, you!\n" "Hey, all?\n")


def test_closures_via_partial_application():
    """`feral.closure(callable, ...boundArgs)` returns a new callable that,
    when invoked with `(...moreArgs)`, calls `callable(...boundArgs, ...moreArgs)`.
    Feral closures are partial-application values (not lexical captures);
    two closures produced by the same factory hold independent bound args."""
    src = """
let io = import('std/io');
let makePrefixer = fn(prefix, sep) {
    let join = fn(pfx, sp, item) {
        return pfx + sp + item;
    };
    return feral.closure(join, prefix, sep);
};
let hi = makePrefixer('Hi', ', ');
let hello = makePrefixer('Hello', '! ');
io.println(hi('world'));
io.println(hi('there'));
io.println(hello('friend'));
io.println(hi('again'));
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "Hi, world\nHi, there\nHello! friend\nHi, again\n"


def test_variadic_and_keyword_argument_parameters():
    """A trailing `IDENT ...` parameter collects remaining positional args into
    a vector. A `STR_LITERAL` or `ATOM`-typed parameter collects unmatched
    named args into a map."""
    src = """
let io = import('std/io');
let describe = fn(first, .kw, rest...) {
    io.println('first=', first);
    io.println('rest.len=', rest.len());
    for r in rest.each() {
        io.println('rest[]=', r);
    }
    io.println('kw.color=', kw['color'] ?? 'unset');
    io.println('kw.size=', kw['size'] ?? 'unset');
};
describe(1, 2, 3, 4, color = 'red', size = 'big');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "first=1\n"
        "rest.len=3\n"
        "rest[]=2\n"
        "rest[]=3\n"
        "rest[]=4\n"
        "kw.color=red\n"
        "kw.size=big\n"
    )


def test_struct_definition_and_default_instantiation():
    """`struct(field = default)` creates a struct type. Calling the type as a
    function constructs an instance, using declared defaults where no
    argument is provided; positional and named args may both override."""
    src = """
let io = import('std/io');
let Point = struct(x = 0, y = 0, tag = 'origin');
let a = Point();
let b = Point(3);                # positional x only
let c = Point(4, 5);             # positional x, y
let d = Point(tag = 'named');    # named-arg override
io.println(a.x, ',', a.y, ',', a.tag);
io.println(b.x, ',', b.y, ',', b.tag);
io.println(c.x, ',', c.y, ',', c.tag);
io.println(d.x, ',', d.y, ',', d.tag);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ("0,0,origin\n" "3,0,origin\n" "4,5,origin\n" "0,0,named\n")


def test_struct_associated_functions_dispatch_via_dot():
    """`let name in StructTy = fn(...) { ... }` attaches an associated function
    to the struct type. Calling `instance.name(args)` implicitly passes the
    instance as `self`, allowing the function to read + mutate its fields."""
    src = """
let io = import('std/io');
let Counter = struct(value = 0);
let increment in Counter = fn(delta = 1) {
    self.value += delta;
    return self.value;
};
let describe in Counter = fn() {
    return 'value=' + self.value.str();
};
let c = Counter(10);
io.println(c.describe());
io.println(c.increment());
io.println(c.increment(5));
io.println(c.describe());
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ("value=10\n" "11\n" "16\n" "value=16\n")


def test_struct_operator_overloading_binds_binary_operators():
    """A string-literal `let` binding attaches an operator overload to a
    struct type: `let '+' in Point = fn(other) { ... }` binds the `+`
    operator, `let '==' in Point = fn(other) { ... }` binds equality.
    Inside the overload, `self` is the LHS and `other` is the RHS. The
    result value is what the overload returns."""
    src = """
let io = import('std/io');
let Point = struct(x = 0, y = 0);
let '+' in Point = fn(other) {
    return Point(self.x + other.x, self.y + other.y);
};
let '==' in Point = fn(other) {
    return self.x == other.x && self.y == other.y;
};
let p1 = Point(1, 2);
let p2 = Point(3, 4);
let p3 = p1 + p2;                              # user-defined +
io.println(p3.x, ',', p3.y);                   # 4,6
io.println(p3 == Point(4, 6));                 # true (user-defined ==)
io.println(p3 == Point(0, 0));                 # false
let p4 = Point(10, 20) + Point(1, 1) + p1;     # chained + calls
io.println(p4.x, ',', p4.y);                   # 12,23
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "4,6\ntrue\nfalse\n12,23\n"


def test_enum_produces_sequential_integer_fields():
    """`enum(.name1, .name2, ...)` is a global function returning a struct-like
    value whose atom-named fields are bound to consecutive integers starting
    at 0. Members are read with `.` syntax like a struct."""
    src = """
let io = import('std/io');
let Color = enum(.red, .green, .blue);
io.println(Color.red);         # 0
io.println(Color.green);       # 1
io.println(Color.blue);        # 2

let Priority = enum(.low, .medium, .high, .urgent);
io.println(Priority.low + Priority.urgent);   # 0 + 3 = 3
io.println(Priority.high - Priority.medium);  # 2 - 1 = 1
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "0\n1\n2\n3\n1\n"


def test_variadic_and_kwargs_in_struct_associated_function():
    """A struct-associated function may combine all parameter kinds: implicit
    `self`, regular positional, a `.kw` (or string-literal) bundle for named
    call-site args, and a trailing `IDENT ...` variadic for remaining
    positional args. Named args land in the `.kw` map; positional overflow
    lands in the variadic vector."""
    src = """
let io = import('std/io');
let Bucket = struct(base = 0);
let take in Bucket = fn(head, .kw, extras...) {
    io.println('self.base=', self.base);
    io.println('head=', head);
    io.println('kw.a=', kw['a']);
    io.println('kw.b=', kw['b']);
    io.println('extras.len=', extras.len());
    for e in extras.each() { io.println('extra=', e); }
};
let b = Bucket(base = 100);
b.take(1, a = 10, b = 20, 2, 3);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "self.base=100\n"
        "head=1\n"
        "kw.a=10\n"
        "kw.b=20\n"
        "extras.len=2\n"
        "extra=2\n"
        "extra=3\n"
    )
