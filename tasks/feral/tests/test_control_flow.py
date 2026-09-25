"""Control-flow tests: if/elif/else, C-style for, for-in, while, break/continue, defer."""

from _helpers import run_feral


def test_if_elif_else_chain():
    """Nested `if`/`elif`/`else` selects the first matching branch and
    executes exactly one body."""
    src = """
let io = import('std/io');
let classify = fn(n) {
    if n < 0 { return 'neg'; }
    elif n == 0 { return 'zero'; }
    elif n < 10 { return 'small'; }
    else { return 'big'; }
};
io.println(classify(-5));
io.println(classify(0));
io.println(classify(3));
io.println(classify(999));
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "neg\nzero\nsmall\nbig\n"


def test_c_style_for_loop_sum():
    """The C-style `for init; cond; step { body }` loop iterates until `cond`
    is false. Sum of 1..=10 is 55."""
    src = """
let io = import('std/io');
let sum = 0;
for let i = 1; i <= 10; ++i {
    sum += i;
}
io.println(sum);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "55\n"


def test_for_in_loop_over_vector():
    """The `for x in iterable { ... }` form desugars to a C-style loop that
    calls `.next()` on the iterator; used here to iterate a vector's
    `.each()`. Vector built with the prelude's `feral.vecNew(...)`."""
    src = """
let io = import('std/io');
let acc = 0;
let v = feral.vecNew(2, 3, 5, 7, 11);
for n in v.each() {
    acc += n;
}
io.println(acc);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "28\n"


def test_while_loop_with_break_and_continue():
    """`while cond { ... }` iterates as long as `cond`. `continue` skips
    to the next iteration, `break` exits the loop entirely."""
    src = """
let io = import('std/io');
let i = 0;
let sum_of_evens_below_20 = 0;
while i < 100 {
    ++i;
    if i >= 20 { break; }
    if i % 2 != 0 { continue; }
    sum_of_evens_below_20 += i;
}
# 2+4+6+8+10+12+14+16+18 = 90
io.println(sum_of_evens_below_20);
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "90\n"


def test_defer_runs_before_function_return():
    """Every `defer expr;` inside a function is executed on function exit, in
    reverse order (LIFO). Deferred prints must fire before the caller's
    `after` message but after the function body's `body` message."""
    src = """
let io = import('std/io');
let f = fn() {
    io.println('body-start');
    defer io.println('defer-1');
    defer io.println('defer-2');
    defer io.println('defer-3');
    io.println('body-end');
    return;
};
f();
io.println('after');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "body-start\n" "body-end\n" "defer-3\n" "defer-2\n" "defer-1\n" "after\n"
    )


def test_irange_iterator_with_bounds_and_negative_step():
    """`irange(a, b [, step])` produces an int iterator over `[a, b)` yielding
    consecutive values `step` apart. Default step is `+1`; negative step
    counts down. The iterator plugs into `for x in ...`. `irange(0, 5)`
    yields 0,1,2,3,4; `irange(10, 0, -2)` yields 10,8,6,4,2."""
    src = """
let io = import('std/io');
let sum_asc = 0;
for i in irange(0, 5) { sum_asc += i; }
io.println(sum_asc);                     # 0+1+2+3+4 = 10

let out = feral.vecNew();
for i in irange(10, 0, -2) { out.push(i); }
io.println(out.len());                   # 5 elements
for v in out.each() { io.println(v); }   # 10, 8, 6, 4, 2
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "10\n5\n10\n8\n6\n4\n2\n"


def test_inline_if_leaks_declarations_into_enclosing_scope():
    """§3 pins the semantics of `inline if`: prefixing an `if` with `inline`
    suppresses the block's scope-push, causing declarations inside it to leak
    into the enclosing scope. The contract is:

      1. `let leaked = ...` inside `inline if <true>` is visible AFTER the
         block (leak into enclosing scope).
      2. `let outer = ...` inside `inline if <true>` where `outer` already
         exists in the enclosing scope REBINDS the outer name (because the
         block shares its scope with the enclosing scope, so `let` here
         resolves against the outer bindings).
      3. Contrast: plain `if` DOES push a scope, so a same-name `let` inside
         is a fresh block-local binding; the outer name survives unchanged.
      4. Contrast: plain `if` block-local names are unreachable outside the
         block -- referencing one is an unbound-identifier error (caught here
         via the level-16 `or e { ... }` handler for a clean assertion).
    """
    src = """
let io = import('std/io');
let assert = import('std/assert');

# Contract 1: `inline if` leaks new declarations into the enclosing scope.
let cond = true;
inline if cond {
    let leaked = 'from-inline';
}
assert.eq(leaked, 'from-inline');

# Contract 2: `let` inside inline-if rebinds an enclosing-scope name.
let outer = 'orig';
inline if cond {
    let outer = 'rebound';
}
assert.eq(outer, 'rebound');

# Contract 3: plain `if` pushes a scope -> same-name `let` doesn't touch outer.
let plain = 'orig';
if cond {
    let plain = 'inner';
}
assert.eq(plain, 'orig');

# Contract 4: plain-`if` block-local names don't exist outside the block.
# Reading one raises 'variable ... does not exist'; caught cleanly with `or e`.
let probe = fn() {
    if cond {
        let block_local = 'private';
    }
    return block_local;
}() or e { return 'unbound'; };
assert.eq(probe, 'unbound');

io.println('ok');
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "ok\n"


def test_variadic_unpack_at_call_site():
    """A `vec...` argument in a call unpacks the vector into positional
    arguments. Elements land in the receiving parameters left-to-right;
    remaining elements land in a trailing variadic parameter (if any).
    Same value expanded by two call sites -- one calls a fixed-arity
    function, the other a variadic function."""
    src = """
let io = import('std/io');
let sum3 = fn(a, b, c) { return a + b + c; };
let takeHead = fn(head, rest...) {
    let acc = head;
    for r in rest.each() { acc = acc * 10 + r; }
    return acc;
};
let v = feral.vecNew(1, 2, 3);
io.println(sum3(v...));                  # 1+2+3 = 6
io.println(takeHead(v...));              # ((1)*10+2)*10+3 = 123
let big = feral.vecNew(4, 5, 6, 7);
io.println(takeHead(big...));            # (((4)*10+5)*10+6)*10+7 = 4567
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "6\n123\n4567\n"
