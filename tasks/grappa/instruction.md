# grappa

Build `grappa`, a behavior-oriented, fluent, expressive assertion library for
Python. `grappa` lets users state expectations about Python values in a near-
natural-English DSL (e.g. `value | should.be.equal.to(expected)`,
`expect([1,2,3]).to.have.length.of(3)`) instead of writing `assert` statements
by hand. Failed assertions raise `AssertionError` with a human-readable,
templated explanation of the subject, the expectation and what differed.

The package must install cleanly as `grappa` and be usable as a
drop-in pytest assertion library.

## Dependencies

The environment is **offline** — every dependency is already installed, and you
must not install anything (there is no network).

- Runtime dependencies, already installed: `colorama` (used for colored failure
  output) and `six`. The rest of the library is pure Python (standard library
  only — e.g. `re`, `inspect`, `collections`).
- No system packages or services are required.
- The project is installed offline by a `setup.sh` that runs
  `pip install -e . --no-build-isolation` against the pre-installed
  dependencies. Provide a `setup.py` (or `pyproject.toml`) that builds with
  `setuptools` so this editable install succeeds.

## Public API

The following symbols must be importable from the top-level `grappa` package
(i.e. `from grappa import <name>`):

| Symbol     | Kind     | Purpose                                                                                                       |
|------------|----------|---------------------------------------------------------------------------------------------------------------|
| `should`   | object   | Global entry point for "should" style assertions. Callable: `should(value)`. Attribute-accessible: `should.be...` |
| `expect`   | object   | Global entry point for "expect" style assertions. Callable and attribute-accessible analogously to `should`.    |
| `Test`     | class    | Underlying assertion-builder class. `Test(subject)` returns an instance whose attribute access begins a chain.   |
| `use`      | function | Registers a plugin: a function `plugin(engine)` or an object with `register(engine)` method.                    |
| `config`   | object   | Runtime key-value config store. Supports the keys `debug`, `show_code`, `use_colors`.                           |
| `Operator` | class    | Base class for custom matcher / accessor / attribute operators.                                                 |
| `operator` | function | Decorator that registers a Python function as a new matcher keyword.                                            |
| `attribute`| function | Decorator that registers a Python function as a new attribute (chain-grammar) keyword.                          |
| `register` | function | Registers an `Operator` subclass instance/class with the global engine.                                         |

The package also exposes `__version__` and `__author__`.

## DSL semantics

### Two styles, one engine

`should` and `expect` are functionally identical entry points; they exist so
users can write idiomatic English. Both support two syntaxes:

* Pipe syntax: `value | should.<chain>(...)` — Python's `|` operator pipes the
  subject into the assertion. The right-hand side may also use `expect`
  (`value | expect.to.<chain>(...)`).
* Call syntax: `should(value).<chain>(...)` and `expect(value).to.<chain>(...)`
  — calling the entry point binds the subject explicitly.

In every case the assertion runs immediately when the matcher is invoked
(when a method is called or an accessor keyword is reached). On success the
result is silent; on failure an `AssertionError` is raised whose message
describes the failure.

### Subject-rebinding context manager

`with should(value):` (and `with expect(value):`) bind `value` as the implicit
subject for any assertion chain inside the block, so the user may omit the
leading `value |` for each call. Assertions inside the block still raise
`AssertionError` on failure, which propagates out of the `with` statement.

### The `>` chaining operator

After a matcher succeeds, certain operators rebind the assertion context's
subject to a derived value: e.g. `have.key('k')` rebinds the subject to the
value at `k`; `have.index.at(i)` rebinds to the item at `i`; `have.property('p')`
rebinds to the attribute value; `raise_error(E)` rebinds to the raised
exception's message string. The `>` operator chains a *new* assertion against
that rebound subject:

```
{'foo': 'bar'} | should.have.key('foo') > should.be.equal.to('bar')
```

The right-hand side of `>` is itself a `should`/`expect` chain. Multiple `>`
chains may follow in sequence.

### Grammar keywords

The DSL accepts a fixed grammar of chainable keyword aliases that perform no
assertion of their own but make chains read naturally. The positive set
includes at least: `be`, `to`, `has`, `have`, `that`, `which`, `do`, `include`,
`satisfy`. The negation set inverts the next matcher and includes at least:
`not_be`, `not_to`, `to_not`, `does_not`, `do_not`, `not_have`, `not_has`,
`have_not`, `has_not`, `dont`. Any negation keyword must produce the inverse
result of the same chain with a positive keyword.

### Custom failure message

Every matcher accepts a `msg=` keyword argument. When supplied and the
assertion fails, `msg`'s string content must appear in the resulting
`AssertionError`'s textual message.

## Built-in operators

Operators are exposed as chainable attributes of `should`/`expect`. Where
multiple names are listed, each is a valid alias for the same operator.
Where a chain alias is listed, it is a no-op grammar keyword usable between
the operator keyword and its argument (e.g. `equal.to(x)`, `length.of(n)`).

### Equality

| Keywords        | Chain aliases                  | Meaning                                  |
|-----------------|--------------------------------|------------------------------------------|
| `equal`, `same` | `value`, `data`, `to`, `of`, `as` | `subject == expected`                  |

### Identity / truthiness / presence (no expected argument — accessor)

| Keywords             | Meaning                                                            |
|----------------------|--------------------------------------------------------------------|
| `true`               | `subject is True` AND `isinstance(subject, bool)`. Integers fail.  |
| `false`              | `subject is False` AND `isinstance(subject, bool)`.                |
| `none`               | `subject is None`.                                                 |
| `empty`              | `subject` is `None`, `0`, `len(subject) == 0`, or an exhausted iterator/generator; bools fail. |
| `present`, `exists`  | The opposite of `empty`.                                            |
| `callable`           | `callable(subject)` is true and subject is not `None`.              |

Negation (e.g. `not_be.true` / `not_be.false`) does NOT enforce the strict-bool
check — any non-bool subject satisfies the negated form.

### Numeric comparisons

| Keywords                                       | Chain aliases             | Meaning                       |
|------------------------------------------------|---------------------------|-------------------------------|
| `below`, `lower`, `less`                       | `of`, `to`, `number`, `than` | `subject < expected` (strict) |
| `above`, `higher`                              | (same)                    | `subject > expected` (strict) |
| `below_or_equal`, `lower_or_equal`, `most`     | (same)                    | `subject <= expected`         |
| `above_or_equal`, `higher_or_equal`, `least`   | (same)                    | `subject >= expected`         |
| `within`, `between`                            | `to`, `numbers`, `range`  | `start <= subject <= end` (inclusive). Takes two args. |

### Containers

| Keywords                                | Chain aliases                  | Meaning                                                                                          |
|-----------------------------------------|--------------------------------|--------------------------------------------------------------------------------------------------|
| `length`, `size`                        | `equal`, `to`, `of`            | `len(subject) == expected`. Subject may be any object with `__len__`, an iterator/generator (consumed to measure), or a numeric subject (its own length, enabling `length.below`/`above`/`within` numeric composition). |
| `contain`, `contains`, `includes`       | `value`, `item`, `data`        | Substring containment for strings; item-in-iterable containment for sequences/sets/dict-values. Accepts variadic items (e.g. `contain(a, b)`) — all must be present. A single `list`/`tuple`/`set` argument is treated equivalently to variadic. |
| `only`, `just`                          | (none specific)                | Same as `contain` PLUS rejects any extra item in the subject. Invoked as a chain immediately after `contain`/`contains`/`includes` — `subject \| should.contain.only(*items)` (negation `should.do_not.contain.only(*items)`) — not as a bare top-level `should.only(...)`. |
| `start_with`, `starts_with`, `startswith` | `word`, `string`, `number`, `item`, `letter`, `character` | First items / prefix match on strings, lists, tuples, iterators, and ordered mappings (e.g. `OrderedDict`). Plain unordered dicts have no defined first item and must fail. Accepts variadic items. |
| `end_with`, `ends_with`, `endswith`     | (same)                         | Last items / suffix match on the same subject types as `start_with`. Accepts variadic items.     |

`length` composes with `within`/`above`/`below`/`equal` via chained accessors
(e.g. `length.between.range(lo, hi)`). Likewise `only`/`just` compose after
`contain`/`contains`/`includes` as `contain.only(*items)` — the `only`/`just`
containment-plus-no-extras assertion runs against the subject, with `contain`
serving as the grammar prefix (there is no standalone `should.only(...)` form).

For an ordered mapping (e.g. `OrderedDict`), `start_with`/`end_with` match
against the mapping's **keys** in insertion order — the first/last item(s) are
its first/last KEY(S), not values or `(key, value)` pairs. A plain unordered
`dict` has no defined first/last item and is rejected.

### Mappings / sequences (rebind subject on success)

| Keywords                | Chain aliases             | Meaning                                                                                                             |
|-------------------------|---------------------------|---------------------------------------------------------------------------------------------------------------------|
| `key`, `keys`           | `present`, `equal`, `to`  | Subject is a `Mapping` containing the given key(s). Accepts variadic keys (e.g. `keys(a, b)`); a single `list`/`tuple`/`set` argument is treated equivalently to variadic. On success the subject is rebound to the value(s) at those keys. |
| `index`                 | `present`, `exists`, `at` | Subject is a `list`/`tuple` with a valid index — one for which `subject[index]` is defined; anything out of range fails. On success the subject is rebound to `subject[index]`. |

### Objects

| Keywords                                     | Chain aliases            | Meaning                                                                                                     |
|----------------------------------------------|--------------------------|-------------------------------------------------------------------------------------------------------------|
| `property`, `properties`, `attribute`, `attributes` | `present`, `equal`, `to` | Subject has the named attribute(s). On success the subject is rebound to the attribute value.          |
| `implements`, `implement`, `interface`       | `interface`, `methods`, `method` | Subject (class or instance) exposes the named members AS METHODS (not just bare attributes).        |

### Type assertions

| Keywords                              | Chain aliases               | Meaning                                                                                              |
|---------------------------------------|-----------------------------|------------------------------------------------------------------------------------------------------|
| `type`, `types`, `a`, `an`, `instance` | `type`, `types`, `of`, `equal`, `to` | Subject is an instance of the given type. Argument may be a type object or a string alias.    |

Recognised string type aliases include at least: `'string'`, `'int'`,
`'integer'`, `'number'`, `'object'`, `'float'`, `'bool'`, `'boolean'`,
`'complex'`, `'list'`, `'dict'`, `'dictionary'`, `'tuple'`, `'set'`, `'array'`,
`'lambda'`, `'generator'`, `'class'`, `'method'`, `'module'`, `'function'`,
`'coroutine'`, `'generatorfunction'`, `'coroutinefunction'`. Unknown alias
strings must cause the assertion to fail (not crash).

The numeric aliases map to concrete Python types: `'number'`, `'int'`, and
`'integer'` all mean exactly `int` (a `float` subject does NOT satisfy
`'number'`); `'float'` means `float`; `'complex'` means `complex`. The
remaining aliases map to the obvious built-in type of the same name (e.g.
`'string'` → `str`, `'list'` → `list`, `'dictionary'` → `dict`), with one
exception: `'array'` maps to the standard-library `array.array` type (from the
`array` module), NOT to `list` — so a plain `list` does not satisfy
`should.be.a('array')`, and only an `array.array` instance does.

### Functional predicates

| Keywords                          | Meaning                                                                                                       |
|-----------------------------------|---------------------------------------------------------------------------------------------------------------|
| `pass_test`, `pass_function`      | Argument is a Python function/method; the assertion holds iff the function returns truthy when given the subject. |

### Exception assertions

| Keywords                              | Chain aliases   | Meaning                                                                                                                                                              |
|---------------------------------------|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `raises`, `raise_error`, `raise_errors`| `to`, `that`, `instance`, `of` | Subject must be a zero-argument callable; the assertion holds iff calling it raises an exception that `isinstance` matches the given exception class. On success the subject is rebound to the exception's message string (concatenation of `args`). |

### Regular expressions

| Keywords             | Chain aliases                                | Meaning                                                              |
|----------------------|----------------------------------------------|----------------------------------------------------------------------|
| `match`, `matches`   | `value`, `string`, `expression`, `regex`, `regexp`, `to`, `word`, `phrase` | `re.search(pattern, subject, *flags)` is not `None`. Non-string subjects fail. |

### Composition

| Keywords | Meaning                                                                                                  |
|----------|----------------------------------------------------------------------------------------------------------|
| `all`    | `subject \| should.all(t1, t2, ...)` — every sub-assertion must succeed against the subject.             |
| `any`    | `subject \| should.any(t1, t2, ...)` — at least one sub-assertion must succeed against the subject.      |

## Extensibility

### `@operator` decorator

```
@operator(operators=('my_keyword', 'alias'))
def my_keyword(subject, expected):
    return subject == ...           # bool or (bool, reasons) tuple
```

Registers the decorated function as a new MATCHER keyword. All of the names
in `operators` become chainable on `should`/`expect`.

### `@attribute` decorator

```
@attribute(operators=('my_grammar_keyword',))
def my_grammar_keyword(ctx):
    ...                              # no return; may mutate ctx
```

Registers an ATTRIBUTE-kind operator: a chain keyword that performs no
assertion itself but adds DSL grammar. ATTRIBUTE operators may set
`ctx.negate = True` to behave as negation keywords.

### `register(operator_cls)`

```
class MyOperator(Operator):
    operators = ('kw1', 'kw2')
    kind = Operator.Type.MATCHER     # or ACCESSOR / ATTRIBUTE
    def match(self, subject, expected):
        return subject == ..., []    # (bool, list_of_reasons)

register(MyOperator)
```

Installs an `Operator` subclass with the global engine. The keywords are
chainable on `should`/`expect` immediately after registration.

`Operator` exposes a nested `Type` namespace with constants `MATCHER`,
`ACCESSOR`, and `ATTRIBUTE`. `Operator` subclasses implement `match()`,
which returns either a `bool` or a `(bool, reasons)` tuple where `reasons`
is a list of human-readable strings.

## Plugins

`use(plugin)` registers a plugin with the global engine. A plugin is either:

* a Python function whose single positional parameter receives the engine
  (which exposes a `register` callable), OR
* an object exposing a `register(engine)` callable (e.g. a module or class).

Anything else must raise `ValueError`.

## Configuration

`config` is a singleton key/value store. Reading or writing it goes through
ordinary attribute access:

```
from grappa import config
config.use_colors = False
```

Supported keys: `debug` (bool, default `False`), `show_code` (bool, default
`True`), `use_colors` (bool, default `True`). Reading or writing an
unsupported key must raise `ValueError`. `show_code` controls whether failure
messages include a "Where" section showing the source-code excerpt at the
failing call site.

## Error reporting

A failing assertion must raise `AssertionError`. The exception's string form
must include enough information for a user to diagnose the failure: at least
a representation of the subject, a description of what was expected, and
(when a `msg=...` argument was supplied) the user-supplied message string.

For a `length`/`size` mismatch, the message reports both the expected length
and the actual measured length of the subject (e.g. failing
`'foo' | should.have.length.of(5)` surfaces both the expected `5` and the
measured length `3`), so the actual computed length is a guaranteed part of
the rendered message.

A lookup of an unknown operator keyword (e.g.
`'foo' | should.be.totally_made_up_keyword(...)`) must raise `AttributeError`
whose message mentions the unknown keyword.

## Exceptions

The library raises only standard Python exceptions out of its public API:

* `AssertionError` — every assertion failure.
* `AttributeError` — unknown operator keyword.
* `ValueError` — invalid plugin in `use(...)`, unknown key in `config`, or `register(...)` of an `Operator` whose keyword name is already in use by another registered operator.
